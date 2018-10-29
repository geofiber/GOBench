# Copyright (c) 2018 Sylvain Gubian <sylvain.gubian@pmi.com>,
# Yang Xiang <yang.xiang@pmi.com>
# Author: Sylvain Gubian, PMP S.A.
# -*- coding: utf-8 -*-

import sys
import os
import time
import logging
import copy
import multiprocessing
import inspect
import contextlib
import numpy as np
from scipy.optimize import basinhopping
from scipy.optimize import differential_evolution
from scipy.optimize import brute
from scipy.optimize import dual_annealing
from scipy.optimize import minimize
from pyswarm import pso
import cma
# nlop is a bit tricky to install, disabling by default
#import nlopt
from . import go_benchmark_functions as gbf
from .benchunit import BenchUnit
from .job import Job

logger = logging.getLogger(__name__)

DEFAULT_TOL = 1.e-6
MAX_FN_CALL = 1e6
LS_MAX_CALL = 1e4
MAX_IT = int(1e6)
if 'USE_CLUSTER' in os.environ:
    assert('NB_CORES' in os.environ)
    assert('SECTION_NUM' in os.environ)
    NB_CORES_AVAILABLES = int(os.environ['NB_CORES'])
else:
    NB_CORES_AVAILABLES = multiprocessing.cpu_count()
if NB_CORES_AVAILABLES < 1:
    NB_CORES_AVAILABLES = 1

DIMENSIONS = [5]
DIMENSIONS.extend(range(10, 110, 10))

N_DIM_FUNC_SELECTION = [
    'Ackley01', 'Exponential', 'Rastrigin', 'Rosenbrock',
    'Schwefel01',
    ]

@contextlib.contextmanager
def nostdout():
    save_stdout = sys.stdout
    save_stderr = sys.stderr
    sys.stdout = DummyFile()
    sys.stderr = DummyFile()
    yield
    sys.stdout = save_stdout
    sys.stderr = save_stderr


class OptimumFoundException(Exception):
    pass


class OptimumNotFoundException(Exception):
    pass


class Algo(object):
    def __init__(self):
        self.name = None
        # Favor context is to allow some algo
        # to run a bit more than MAX_FN_CALL to have
        # the final local search possible (this is for BF and PSO)
        # This for a fair comparison as some global optimizer use local search
        # (BH, DE, DA)
        self._favor_context = False

    @property
    def success(self):
        return self._success

    @property
    def fsuccess(self):
        return self._fsuccess

    @property
    def fcall_success(self):
        return self._fcall_success

    @property
    def nbcall(self):
        return self._nbcall

    @property
    def xsuccess(self):
        return self._xsuccess

    @property
    def duration(self):
        return self._hittime - self._starttime

    def prepare(self, fname, klass, dim=None):
        if dim:
            self._k = klass(dimensions=dim)
        else:
            self._k = klass()
        self._fname = fname
        self._xmini = None
        self._fmini = None
        self._favor_context = False
        self._maxcall = MAX_FN_CALL
        self._nbcall = 0
        self._first_hit = True
        self._starttime = time.time()
        self._fcall_success = MAX_FN_CALL
        self._xsuccess = [np.inf] * self._k.N
        self._success = False
        self._fsuccess = np.inf
        self._hittime = np.inf
        self.recording = False
        self._values = []
        self._lower = -np.inf
        self._upper = np.inf
        self._x = None
        # logger.info('Function name: {0} Dimension: {1}'.format(
        #   fname, self._k._dimensions))
        self._lower = np.array([x[0] for x in self._k.bounds])
        self._upper = np.array([x[1] for x in self._k.bounds])
        self._xinit = self._lower + np.random.rand(self._k.N) * (
                self._upper - self._lower)

    def optimize(self):
        pass

    def lsearch(self):
        pass

    def _funcwrapped(self, x, **kargs):
        ''' Function to wrap the objective function. This is needed to trace
        when the objective value is reached the first time
        It also records an array with values of the current optimum value
        if required, set recording to True)
        '''
        func = self._k.fun
        res = func(x)
        self._nbcall += 1
        if self._nbcall >= self._maxcall:
            if self._favor_context:
                self._maxcall += LS_MAX_CALL
            raise OptimumNotFoundException('NB MAX CALL reached...')
        if self.recording and self._first_hit:
            if len(self.values) > 0:
                if res < self.values[-1]:
                    self.values.append(res)
                else:
                    self.values.append(self.values[-1])
            else:
                self.values.append(res)
        if self._first_hit and res <= self._k.fglob + DEFAULT_TOL:
            self._fcall_success = self._nbcall
            self._fsuccess = res
            self._xsuccess = x
            self._success = True
            self._first_hit = False
            self._hittime = time.time()
            raise OptimumFoundException('FOUND')
        return res


class DAOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'DA'

    def optimize(self):
        Algo.optimize(self)
        dual_annealing(
            func=self._funcwrapped, x0=None,
            bounds=list(zip(self._lower, self._upper)), maxiter=MAX_IT)


class DABFGSOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'DA-BFGS'

    def optimize(self):
        Algo.optimize(self)
        opts = {
            'method': 'BFGS'
        }
        dual_annealing(
            func=self._funcwrapped, x0=None,
            bounds=list(zip(self._lower, self._upper)), maxiter=MAX_IT,
            local_search_options=opts,
        )


class PSOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'PSO'

    def optimize(self):
        with nostdout():
            xopt, fopt = pso(
                self._funcwrapped, self._lower, self._upper,
                maxiter=MAX_IT)


class PSORestartOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'PSO-R'

    def optimize(self):
        while (self._nbcall < MAX_FN_CALL):
            with nostdout():
                xopt, fopt = pso(
                    self._funcwrapped, self._lower, self._upper,
                    maxiter=MAX_IT)


class PSOLSOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'PSO-LS'

    def optimize(self):
        self._favor_context = True
        with nostdout():
            self._x, _ = pso(
                self._funcwrapped, self._lower, self._upper,
                maxiter=MAX_IT, )
        self._favor_context = False
        self.lsearch()

    def lsearch(self):
        # Call here a local search to be fair in regards to the other
        # methods.
        if self._x is None:
            logger.error('LS not possible, no returned value - FAILED')
            self._favor_context = False
            raise OptimumNotFoundException("NOT FOUND - NO LS")
        minimize(
            fun=self._funcwrapped, x0=self._x,
            bounds=zip(self._lower, self._upper))


class PSOLSRestartOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'PSO-LS-R'

    def optimize(self):
        self._favor_context = True
        while (self._nbcall < MAX_FN_CALL):
            with nostdout():
                x, v = pso(
                    self._funcwrapped, self._lower, self._upper,
                    maxiter=MAX_IT, )
            if self._xmini is None:
                self._xmini = x
            if self._fmini is None:
                self._fmini = v
            if v < self._fmini:
                self._fmini = v
                self._xmini = x

    def lsearch(self):
        # Call here a local search to be fair in regards to the other
        # methods.
        if self._xmini is None:
            logger.error('LS not possible, no returned value - FAILED')
            self._favor_context = False
            raise OptimumNotFoundException("NOT FOUND - NO LS")
        minimize(
            fun=self._funcwrapped, x0=self._xmini,
            bounds=zip(self._lower, self._upper))


class BHOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'BH'

    def optimize(self):
        mybounds = MyBounds(self._lower, self._upper)
        basinhopping(
            self._funcwrapped, self._xinit,
            minimizer_kwargs={
                'method': 'L-BFGS-B',
                'bounds': [
                    x for x in zip(self._lower, self._upper)
                    ]
                },
            accept_test=mybounds,
            niter=MAX_IT,
        )


class BHMaxiterOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'BH-MI'

    def optimize(self):
        n = len(self._lower)
        self.ls_maxiter_ratio = 6
        self.ls_maxiter_min = 100
        self.ls_maxiter_max = 1000
        self.ls_maxiter = min(max(n * self.ls_maxiter_ratio,
                                  self.ls_maxiter_min),
                              self.ls_maxiter_max)
        mybounds = MyBounds(self._lower, self._upper)
        basinhopping(
            self._funcwrapped, self._xinit,
            minimizer_kwargs={
                'method': 'L-BFGS-B',
                'bounds': [
                    x for x in zip(self._lower, self._upper)
                    ],
                'options': {'maxiter': self.ls_maxiter}
                },
            accept_test=mybounds,
            niter=MAX_IT,
        )


class BHBFGSOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'BH-BFGS'

    def optimize(self):
        mybounds = MyBounds(self._lower, self._upper)
        basinhopping(
            self._funcwrapped, self._xinit,
            minimizer_kwargs={
                'method': 'BFGS',
                },
            accept_test=mybounds,
            niter=MAX_IT,
        )


class BHRestartOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'BH-R'

    def optimize(self):
        mybounds = MyBounds(self._lower, self._upper)
        while(self._nbcall < MAX_FN_CALL):
            basinhopping(
                self._funcwrapped, self._xinit,
                minimizer_kwargs={
                    'method': 'L-BFGS-B',
                    'bounds': [
                        x for x in zip(self._lower, self._upper)
                    ]
                },
                accept_test=mybounds,
                niter=MAX_IT,
            )


class DEOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'DE'

    def optimize(self):
        differential_evolution(
            self._funcwrapped,
            [x for x in zip(self._lower, self._upper)], maxiter=MAX_IT)


class DERestartOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'DE-R'

    def optimize(self):
        while(self._nbcall < MAX_FN_CALL):
            differential_evolution(
                self._funcwrapped,
                [x for x in zip(self._lower, self._upper)],
                maxiter=MAX_IT)


class BFOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'BF'

    def optimize(self):
        brute(
            self._funcwrapped,
            [x for x in zip(self._lower, self._upper)], )


class CMAOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'CMA'
        self.es = None

    def optimize(self):
        self.es = cma.CMAEvolutionStrategy(
            self._xinit,
            0.5,
            {
                'maxiter': MAX_IT,
                'bounds': [self._lower, self._upper],
            },
        )
        with nostdout():
            res = self.es.optimize(self._funcwrapped)


class CMARestartOptimizer(Algo):
    def __init__(self):
        Algo.__init__(self)
        self.name = 'CMA-R'
        self.es = None

    def optimize(self):
        while(self._nbcall < MAX_FN_CALL):
            self.es = cma.CMAEvolutionStrategy(
                self._xinit,
                0.5,
                {
                    'maxiter': 1e6,
                    'bounds': [self._lower, self._upper],
                },
            )
            with nostdout():
                res = self.es.optimize(self._funcwrapped)


class NLOptimizer(Algo):
    def __init__(self, nlopt_algo):
        Algo.__init__(self)
        self.nlopt_algo = nlopt_algo
        self.opt = nlopt.opt(self.nlopt_algo, 2)
        self.name = self.opt.get_algorithm_name().split()[0]

    def optimize(self):
        self.opt = nlopt.opt(self.nlopt_algo, self._k.N)
        self.opt.set_min_objective(self._funcwrapped)
        self.opt.set_lower_bounds(self._lower)
        self.opt.set_upper_bounds(self._upper)
        with nostdout():
            res = self.opt.optimize(self._xinit)


METHODS_MAP = {
    'DA': DAOptimizer(),              # Dual annealing
    'BH': BHOptimizer(),              # Basinhopping
    'DE': DEOptimizer(),              # Differential evolution
    'DE-R': DERestartOptimizer(),     # Differential evolution restart
    'PSO': PSOptimizer(),             # Particule swarm
    'PSO-R': PSOptimizer(),           # Particule swarm restart
    'BF': BFOptimizer(),              # Brute force
    'CMA': CMAOptimizer(),            # Cov. matrix adaptation evolution strategy
    'CMA-R': CMARestartOptimizer(),
}


class DummyFile(object):
    def write(self, x): pass
    def flush(self): pass


class MyBounds(object):
    def __init__(self, xmax, xmin):
        self.xmax = np.array(xmax)
        self.xmin = np.array(xmin)

    def __call__(self, **kwargs):
        x = kwargs["x_new"]
        tmax = bool(np.all(x <= self.xmax))
        tmin = bool(np.all(x >= self.xmin))
        return tmax and tmin


class Benchmarker(object):
    def __init__(self, nbruns, folder, functions=None, methods=None,
                 multidim=False):
        self.algorithms = []
        for k, v in METHODS_MAP.items():
            if methods is None or k in methods:
                self.algorithms.append(v)
        self.nbruns = nbruns
        self.folder = folder
        self.functions = functions
        self.multidim = multidim
        bench_members = inspect.getmembers(gbf, inspect.isclass)
        self.benchmark_functions = [item for item in bench_members if
                                    issubclass(item[1], gbf.Benchmark)]

    def run(self):
        jobs = {}
        index = 0
        funcs = []
        for name, klass in self.benchmark_functions:
            try:
                k = klass()
            except TypeError:
                k = klass(dimensions=2)
            if self.multidim:
                if k.change_dimensionality and name in N_DIM_FUNC_SELECTION:
                    for dim in DIMENSIONS:
                        logger.info(
                            'Appending function: {0} with dim: {1}'.format(
                                name, dim))
                        funcs.append((name, klass, dim))
            #  else:
            funcs.append((name, klass, None))
            # Removing Benchmark class that is the mother class
            funcs = [x for x in funcs if x[0] != 'Benchmark']
            # Select only the functions that are requested if any
            if self.functions is not None:
                funcs = [x for x in funcs if x[0] in self.functions]
        logger.info('Nb functions to process: {}'.format(len(funcs)))

        if 'USE_CLUSTER' in os.environ:
            start_idx = int(os.environ['SECTION_NUM']) * int(
                    os.environ['NB_CORES'])
            end_idx = start_idx + int(os.environ['NB_CORES']) - 1
            if end_idx > len(funcs):
                end_idx = len(funcs) - 1
            funcs = funcs[start_idx:(end_idx+1)]
            logger.info('Benchmarking functions: {}'.format(
                [x[0] for x in funcs]))
        for name, klass, dim in funcs:
            jobs[index] = Job(name, klass, dim)
            index += 1
        while jobs:
            running = []
            to_delete = []
            for index, job in jobs.items():
                if job.status == 'FINISHED':
                    to_delete.append(index)
                elif job.status == 'RUNNING':
                    running.append(index)
            if to_delete:
                for i in to_delete:
                    del jobs[i]
            freecores = NB_CORES_AVAILABLES - len(running)
            if freecores <= NB_CORES_AVAILABLES:
                non_running = [jobs[
                    x] for x in jobs.keys() if x not in running]
                for i in range(freecores):
                    if i < len(non_running):
                        non_running[i].start(self.bench)
            time.sleep(0.5)

    def bench(self, fname, klass, dim=None):
        '''Benchmarking function. It executes all runs for a specific
        function
        '''
        self._fname = fname
        if dim:
            self._fname = '{0}_{1}'.format(self._fname, dim)
        for algo in self.algorithms:
            bu = BenchUnit(self.nbruns, self._fname, algo.name)
            if os.path.exists(os.path.join(self.folder, bu.filename)):
                logger.info('File {} already existing, skipping...'.format(
                    bu.filename))
                continue
            else:
                bu.write(self.folder)
            for i in range(self.nbruns):
                np.random.seed(1234 + i)
                algo.prepare(fname, klass, dim)
                if i > 0 and algo.name == 'BF':
                    logger.info('BRUTE FORCE nbrun > 1, ignoring...')
                    if i == 1:
                        bu.replicate()
                    continue
                try:
                    algo.optimize()
                    s = (':-(  Func: {0} - Algo: {1} - RUN: {2} '
                         '-> FAILED after {3} calls').format(
                             self._fname, algo.name, i, algo.nbcall)
                    logger.info(s)
                    bu.update('success', i, algo.success)
                    bu.update('ncall', i, algo.fcall_success)
                    bu.update('fvalue', i, algo.fsuccess)
                    bu.update('time', i, algo.duration)
                    bu.update('ncall_max', i, algo.nbcall)
                except Exception as e:
                    if type(e) == OptimumFoundException:
                        s = (':-)  Func: {0} - Algo: {1} - RUN: {2} '
                             '-> FOUND after {3} calls').format(
                                self._fname, algo.name, i, algo.nbcall)
                        logger.info(s)
                        algo._success = True
                    elif type(e) == OptimumNotFoundException:
                        if algo._favor_context:
                            logger.info('Maximum NB CALL reached. LS...')
                            algo.lsearch()
                            self._favor_context = False
                        s = (':-(  Func: {0} - Algo: {1} - RUN: {2} '
                             '-> FAILED after {3} calls').format(
                                self._fname, algo.name, i, algo.nbcall)
                        logger.info(s)
                    else:
                        s = (':-(  Func: {0} - Algo: {1} - RUN: {2} '
                             '-> EXCEPTION RAISED after {3} '
                             'calls: {4}').format(
                                 self._fname, algo.name, i, algo.nbcall)
                        logger.info(s)
                        algo._success = False
                    bu.update('success', i, algo.success)
                    bu.update('ncall', i, algo.fcall_success)
                    bu.update('fvalue', i, algo.fsuccess)
                    bu.update('time', i, algo.duration)
                    bu.update('ncall_max', i, algo.nbcall)
            bu.write(self.folder)


def which_fglob_centered():
    '''
    Some testing function have their global minimum in bounds center, this
    make some nlopt algorithms finding the results at the first call as it goes
    first to the bounds center.
    This function retrieved the functions that have this property
    '''
    bench_members = inspect.getmembers(gbf, inspect.isclass)
    benchmark_functions = [item for item in bench_members if
                           issubclass(item[1], gbf.Benchmark)]
    funcs = []
    for name, klass in benchmark_functions:
        if name == 'Benchmark':
            continue
        try:
            k = klass()
        except TypeError:
            k = klass(dimensions=2)
        lower = np.array([x[0] for x in k._bounds])
        upper = np.array([x[1] for x in k._bounds])
        m = 0.5 * np.add(lower, upper)
        if np.all(m == k.global_optimum):
            funcs.append(name)
    return funcs
