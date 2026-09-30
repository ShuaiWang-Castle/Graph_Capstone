#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "${1:-}" != "--new-reproduction" ]]; then
  printf '%s\n' 'Use: bash REPRODUCE.sh --new-reproduction [--all-development]' 'This creates a separate reproduction round. Current-round resume: RESUME.md.' 'Default: all nine initial baseline arms. --all-development adds existing Ego controls, C1 three-seed controls, and author harness cross-check.'
  exit 2
fi
if [[ "${2:-}" != "" && "${2:-}" != "--all-development" ]]; then
  printf '%s\n' 'Unsupported option'; exit 2
fi
REPLAY_ALL="${2:-}"
PYTHON="${PYTHON:-python3.12}"
REPLAY_DIR="$($PYTHON - <<'PY'
from pathlib import Path
from datetime import datetime,timezone
import shutil,os
root=Path.cwd();dest=root/'replays'/('replay_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+str(os.getpid()));dest.mkdir(parents=True)
for folder in ['adapters','candidates','lab','tools','tests','configs','provenance']:
 shutil.copytree(root/folder,dest/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
for f in ['START_HERE.sh','README_ZH.md','GOAL_MODE_PROMPT_ZH.md']:
 shutil.copy2(root/f,dest/f)
print(dest)
PY
)"
printf 'New reproduction workspace: %s\n' "$REPLAY_DIR"
cd "$REPLAY_DIR"
"$PYTHON" -m venv .venv
.venv/bin/python tools/session.py start
.venv/bin/python -m pip install -r provenance/dependency_versions.txt
.venv/bin/python -m pip check
.venv/bin/python tools/restore_locked_sources.py
# Force a fresh build even when the archived source tree contains old binaries.
make -B -j1 -C external/lfr/unweighted_undirected
make -B -j1 -C external/snap/examples/bigclam
cmake -S external/highway_native_reference/benchmark/highway/highway_cpp -B external/highway_native_reference/benchmark/highway/highway_cpp/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_DISABLE_FIND_PACKAGE_OpenMP=TRUE
cmake --build external/highway_native_reference/benchmark/highway/highway_cpp/build --config Release -j1
.venv/bin/python -m unittest discover -s tests -v
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
# Native adapter smokes are actual method runs, separate from unit tests and
# recovery benchmarks. Keep their failures/records for the new environment.
.venv/bin/python tools/lab.py make-smoke --output work/smoke
.venv/bin/python tools/prepare_plan.py --catalog work/smoke/catalog.json --method-configs configs/methods.json --alg-seed 73 --output work/plans/native_smokes/jobs.json
.venv/bin/python tools/run_jobs.py --plan work/plans/native_smokes/jobs.json --run-root work/native_smokes
.venv/bin/python tools/summarize.py --catalog work/smoke/catalog.json --plan work/plans/native_smokes/jobs.json --run-root work/native_smokes --output analysis/native_smokes
.venv/bin/python tools/generate_lfr.py --binary external/lfr/unweighted_undirected/benchmark
run_phase() {
  local phase_name="$1" method_config="$2" alg_seed="$3"
  .venv/bin/python tools/prepare_plan.py --catalog work/dev_lfr/catalog.json --method-configs "$method_config" --alg-seed "$alg_seed" --output "work/plans/$phase_name/jobs.json"
  .venv/bin/python tools/run_jobs.py --plan "work/plans/$phase_name/jobs.json" --run-root "work/$phase_name"
  .venv/bin/python tools/summarize.py --catalog work/dev_lfr/catalog.json --plan "work/plans/$phase_name/jobs.json" --run-root "work/$phase_name" --output "analysis/$phase_name" --plot
  .venv/bin/python tools/summarize_extended.py --catalog work/dev_lfr/catalog.json --plan "work/plans/$phase_name/jobs.json" --run-root "work/$phase_name" --analysis "analysis/$phase_name"
}
run_phase initial_baselines configs/methods.json 73
if [[ "$REPLAY_ALL" == "--all-development" ]]; then
  run_phase existing_ego_controls configs/ego_existing_controls_v1.json 73
  for alg_seed in 73 74 75; do
    run_phase "pairdot_dev_s$alg_seed" configs/nocd_pairdot_controls_v1.json "$alg_seed"
  done
  run_phase author_refcheck configs/nocd_author_refcheck_v1.json 73
fi
printf '%s\n' 'Reproduction terminal records saved. A fresh environment run is a new measurement, not a copy of archived times.' 'This script does not select an algorithm or use confirmation feedback to tune anything.'
