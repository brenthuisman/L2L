import logging
import random
from collections import namedtuple

from deap import base, creator, tools
from deap.tools import HallOfFame

from ltl.optimizers.optimizer import Optimizer
from ltl import params_to_list, list_to_params

logger = logging.getLogger("ltl-ga")

GeneticAlgorithmParameters = namedtuple('GeneticAlgorithmParameters',
                                        ['seed', 'popsize', 'CXPB', 'MUTPB', 'NGEN', 'indpb', 'tournsize', 'matepar',
                                         'mutpar'])
GeneticAlgorithmParameters.__doc__ = """
:param seed: Random seed
:param popsize: Size of the population
:param CXPB: Crossover probability
:param MUTPB: Mutation probability
:param NGEN: Number of generations simulation should run for
:param indpb: Probability of mutation of each element in individual
:param tournsize: Size of the tournamaent used for fitness evaluation and selection
:param matepar: Paramter used for blending two values during mating
"""


class GeneticAlgorithmOptimizer(Optimizer):
    """
    Implements evolutionary algorithm

    :param  ~pypet.trajectory.Trajectory traj: Use this pypet trajectory to store the parameters of the specific runs.  The parameters should be initialized based on the values in `parameters`
    :param optimizee_create_individual: Function that creates a new individual
    :param optimizee_fitness_weights: Fitness weights. The fitness returned by the Optimizee is multiplied by these values (one for each element of the fitness vector)
    :param parameters: Instance of :class:`namedtuple` :class:`GeneticAlgorithmParameters` containing the parameters needed by the Optimizer
    """

    def __init__(self, traj, optimizee_create_individual, optimizee_fitness_weights, optimizee_individual_param_spec, parameters):

        super().__init__(traj,
                         optimizee_create_individual=optimizee_create_individual,
                         optimizee_individual_param_spec=optimizee_individual_param_spec,
                         optimizee_fitness_weights=optimizee_fitness_weights,
                         parameters=parameters)
        traj.f_add_parameter('seed', parameters.seed, comment='Seed for RNG')
        traj.f_add_parameter('popsize', parameters.popsize, comment='Population size')  # 185
        traj.f_add_parameter('CXPB', parameters.CXPB, comment='Crossover term')
        traj.f_add_parameter('MUTPB', parameters.MUTPB, comment='Mutation probability')
        traj.f_add_parameter('NGEN', parameters.NGEN, comment='Number of generations')

        traj.f_add_parameter('indpb', parameters.indpb, comment='Mutation parameter')
        traj.f_add_parameter('tournsize', parameters.tournsize, comment='Selection parameter')

        # ------- Create and register functions with DEAP ------- #
        # delay_rate, slope, std_err, max_fraction_active
        creator.create("FitnessMax", base.Fitness, weights=self.optimizee_fitness_weights)
        creator.create("Individual", list, fitness=creator.FitnessMax)

        toolbox = base.Toolbox()
        # Structure initializers
        toolbox.register("individual", tools.initIterate, creator.Individual,
                         lambda : params_to_list(optimizee_create_individual(), self.optimizee_individual_param_spec))
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)

        # Operator registering
        toolbox.register("mate", tools.cxBlend, alpha=parameters.matepar)
        toolbox.register("mutate", tools.mutGaussian, mu=0, sigma=parameters.mutpar, indpb=traj.indpb)
        toolbox.register("select", tools.selTournament, tournsize=traj.tournsize)

        # ------- Initialize Population and Trajectory -------- #
        # NOTE: The Individual object implements the list interface.
        self.pop = toolbox.population(n=traj.popsize)
        self.eval_pop_inds = [ind for ind in self.pop if not ind.fitness.valid]
        self.eval_pop = [list_to_params(ind, self.optimizee_individual_param_spec)
                         for ind in self.eval_pop_inds]
        
        self.g = 0  # the current generation
        self.toolbox = toolbox  # the DEAP toolbox
        self.hall_of_fame = HallOfFame(20)

        self._expand_trajectory(traj)

    def post_process(self, traj, fitnesses_results):
        """
        See :meth:`~ltl.optimizers.optimizer.Optimizer.post_process`
        """
        CXPB, MUTPB, NGEN = traj.CXPB, traj.MUTPB, traj.NGEN

        logger.info("  Evaluating %i individuals" % len(fitnesses_results))
        while fitnesses_results:
            result = fitnesses_results.pop()
            # Update fitness
            run_index, fitness = result  # The environment returns tuples: [(run_idx, run), ...]
            # We need to convert the current run index into an ind_idx
            # (index of individual within one generation)
            traj.v_idx = run_index
            ind_index = traj.par.ind_idx
            # Use the ind_idx to update the fitness
            individual = self.eval_pop_inds[ind_index]
            individual.fitness.values = fitness

            # Record
            traj.f_add_result('$set.$.individual', self.eval_pop[ind_index])
            traj.f_add_result('$set.$.fitness', individual.fitness.values)

        traj.v_idx = -1  # set the trajectory back to default

        logger.info("-- End of generation {} --".format(self.g))
        best_inds = tools.selBest(self.eval_pop_inds, 2)
        for best_ind in best_inds:
            print("Best individual is %s, %s" % (list_to_params(best_ind, self.optimizee_individual_param_spec), 
                                                 best_ind.fitness.values))

        self.hall_of_fame.update(self.eval_pop_inds)

        logger.info("-- Hall of fame --")
        for hof_ind in tools.selBest(self.hall_of_fame, 2):
            logger.info("HOF individual is %s, %s" % (list_to_params(hof_ind, self.optimizee_individual_param_spec),
                                                      hof_ind.fitness.values))

        # ------- Create the next generation by crossover and mutation -------- #
        if self.g < NGEN - 1:  # not necessary for the last generation
            # Select the next generation individuals
            offspring = self.toolbox.select(self.pop, len(self.pop))
            # Clone the selected individuals
            offspring = list(map(self.toolbox.clone, offspring))

            # Apply crossover and mutation on the offspring
            for child1, child2 in zip(offspring[::2], offspring[1::2]):
                if random.random() < CXPB:
                    self.toolbox.mate(child1, child2)
                    del child1.fitness.values
                    del child2.fitness.values

            for mutant in offspring:
                if random.random() < MUTPB:
                    self.toolbox.mutate(mutant)
                    del mutant.fitness.values

            if len(set(map(tuple, offspring))) < len(offspring):
                logger.info("Mutating more")
                for i, o1 in enumerate(offspring):
                    for o2 in offspring[i:]:
                        if tuple(o1) == tuple(o2):
                            if random.random() < 0.8:
                                self.toolbox.mutate(o2)

            # The population is entirely replaced by the offspring
            self.pop[:] = offspring

            self.eval_pop_inds = [ind for ind in self.pop if not ind.fitness.valid]
            self.eval_pop = [list_to_params(ind, self.optimizee_individual_param_spec)
                             for ind in self.eval_pop_inds]
            
            self.g += 1  # Update generation counter
            self._expand_trajectory(traj)

    def end(self):
        """
        See :meth:`~ltl.optimizers.optimizer.Optimizer.end`
        """
        # ------------ Finished all runs and print result --------------- #
        logger.info("-- End of (successful) evolution --")
        best_inds = tools.selBest(self.pop, 10)
        for best_ind in best_inds:
            logger.info("Best individual is %s, %s" % (best_ind, best_ind.fitness.values))

        logger.info("-- Hall of fame --")
        for hof_ind in self.hall_of_fame:
            logger.info("HOF individual is %s, %s" % (hof_ind, hof_ind.fitness.values))
