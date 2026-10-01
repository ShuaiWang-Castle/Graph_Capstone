"""One command to generate/audit M3 inputs; preserves completed frozen inputs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
def main():
    env=os.environ.copy()
    env.update(OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1",PYTHONDONTWRITEBYTECODE="1")
    for name in ["generate_sbm.py","generate_calibrated_lfr.py","audit_inputs.py"]:
        subprocess.run([sys.executable,str(ROOT/"experiments/data_generation"/name)],cwd=ROOT,env=env,check=True)
    records={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for base in [ROOT/"data/dev/sbm_v12",ROOT/"data/test/calibrated_lfr",ROOT/"provenance/generators",ROOT/"external/generators/lfr_native"] for p in sorted(base.rglob("*")) if p.is_file()}
    (ROOT/"results/data_generation/checksums.json").write_text(json.dumps(records,indent=1))
if __name__=="__main__":main()
