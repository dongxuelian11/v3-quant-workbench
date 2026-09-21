"""Test-only wrapper: run the real worker, measure libraries, await explicit exit."""
import os
import sys
import time
from pathlib import Path
from v3_backend.research.worker import run
from v3_backend.research.storage import read_json, write_json

directory = Path(sys.argv[1])
status = run(directory)
import numpy as np
from threadpoolctl import threadpool_info
from v3_backend.research.engines import model_estimator
model = model_estimator({'model':'lightgbm', 'hyperparameters':{'n_estimators':2, 'min_child_samples':2}})
model.fit(np.arange(80).reshape(40,2), np.arange(40))
write_json(directory/'resource-observed.json', dict(status=status, pid=os.getpid(),
    env={k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','V3_RESEARCH_THREADS')},
    lightgbmThreads=model.booster_.params['num_threads'], pools=threadpool_info()))
deadline = time.monotonic()+45
while not (directory/'release').exists() and time.monotonic()<deadline:
    time.sleep(.025)
raise SystemExit(status)
