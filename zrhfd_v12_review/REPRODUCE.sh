#!/bin/sh
# Read-only by default; installation and execution require a separate workspace.
set -eu
REPRO_SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPRO_PYTHON=${REPRO_PYTHON:-python3.12}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export NUMBA_NUM_THREADS=1 JULIA_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
export BLIS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0
exec "$REPRO_PYTHON" "$REPRO_SCRIPT_DIR/experiments/reproduction/driver.py" "$@"
