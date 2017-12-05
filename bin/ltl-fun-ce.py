from __future__ import with_statement
from __future__ import absolute_import
import logging.config
import os

from pypet import Environment
import sys
from io import open
sys.path.append('.')

from ltl.optimizees.functions import tools as function_tools
from ltl.optimizees.functions.benchmarked_functions import BenchmarkedFunctions
from ltl.optimizees.functions.optimizee import FunctionGeneratorOptimizee
from ltl.optimizers.crossentropy.distribution import NoisyGaussian
from ltl.optimizers.crossentropy import CrossEntropyOptimizer, CrossEntropyParameters
from ltl.paths import Paths
from ltl.recorder import Recorder

import numpy as np
from ltl.logging_tools import create_shared_logger_data, configure_loggers

logger = logging.getLogger(u'bin.ltl-fun-ce')


def main():
    name = u'LTL-FUN-CE'
    try:
        with open(u'bin/path.conf') as f:
            root_dir_path = f.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(
            u"You have not set the root path to store your results."
            u" Write the path to a path.conf text file in the bin directory"
            u" before running the simulation"
        )
    paths = Paths(name, dict(run_no=u'test'), root_dir_path=root_dir_path)

    print u"All output logs can be found in directory ", paths.logs_path

    traj_file = os.path.join(paths.output_dir_path, u'data.h5')

    # Create an environment that handles running our simulation
    # This initializes a PyPet environment
    env = Environment(trajectory=name, filename=traj_file, file_title=u'{} data'.format(name),
                      comment=u'{} data'.format(name),
                      add_time=True,
                      # freeze_input=True,
                      # multiproc=True,
                      # use_scoop=True,
                      # wrap_mode=pypetconstants.WRAP_MODE_LOCAL,
                      automatic_storing=True,
                      log_stdout=False,  # Sends stdout to logs
                      )
    create_shared_logger_data(logger_names=['bin', 'optimizers'],
                              log_levels=['INFO', 'INFO'],
                              log_to_consoles=[True, True],
                              sim_name=name,
                              log_directory=paths.logs_path)
    configure_loggers()

    # Get the trajectory from the environment
    traj = env.trajectory

    ## Benchmark function
    function_id = 14
    bench_functs = BenchmarkedFunctions()
    (benchmark_name, benchmark_function), benchmark_parameters = \
        bench_functs.get_function_by_index(function_id, noise=True)

    optimizee_seed = 100
    random_state = np.random.RandomState(seed=optimizee_seed)
    function_tools.plot(benchmark_function, random_state)

    ## Innerloop simulator
    optimizee = FunctionGeneratorOptimizee(traj, benchmark_function, seed=101)

    ## Outerloop optimizer initialization
    parameters = CrossEntropyParameters(pop_size=10, rho=0.9, smoothing=0.0, temp_decay=0, n_iteration=1000,
                                        distribution=NoisyGaussian(noise_magnitude=1., noise_decay=0.99),
                                        stop_criterion=np.inf, seed=102)
    optimizer = CrossEntropyOptimizer(traj, optimizee_create_individual=optimizee.create_individual,
                                      optimizee_fitness_weights=(-0.1,),
                                      parameters=parameters,
                                      optimizee_bounding_func=optimizee.bounding_func)

    # Add post processing
    env.add_postprocessing(optimizer.post_process)

    # Add Recorder
    recorder = Recorder(trajectory=traj,
                        optimizee_name=benchmark_name, optimizee_parameters=benchmark_parameters,
                        optimizer_name=optimizer.__class__.__name__,
                        optimizer_parameters=optimizer.get_params())
    recorder.start()

    # Run the simulation with all parameter combinations
    env.run(optimizee.simulate)

    ## Outerloop optimizer end
    optimizer.end(traj)
    recorder.end()

    # Finally disable logging and close all log-files
    env.disable_logging()


if __name__ == u'__main__':
    main()
