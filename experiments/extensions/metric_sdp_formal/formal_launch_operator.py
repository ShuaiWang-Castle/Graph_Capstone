"""Retain the exact once-only formal controller command and complete output.

No solver policy or scientific computation is supplied by this wrapper. The
independently reviewed controller owns ordering, all215 outcomes and budgets.
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
import time

from .freeze import ROOT, sha256, validate, write_once
from .prepare_formal_freeze import CONFIG, FREEZE, OUTPUT


def main():
    _, frozen = validate(ROOT / CONFIG, ROOT / FREEZE)
    base = ROOT / OUTPUT
    if base.exists():
        raise FileExistsError("the once-only formal scientific output already exists")
    if frozen["planned_scientific_output"] != OUTPUT:
        raise ValueError("formal launch path differs from the frozen output")
    command = [".venv-sdp/bin/python", "-m",
               "experiments.extensions.metric_sdp_formal.run_study",
               "--config", CONFIG, "--freeze", FREEZE, "--output", OUTPUT]
    record = {
        "schema_version": 1,
        "purpose": "once-only fixed43 inputs x five arms full-cost metric SDP study",
        "command": command, "cwd": ".",
        "environment": {name: os.environ.get(name) for name in
                        ("PYTHONPATH", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                         "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")},
        "config_sha256": sha256(ROOT / CONFIG), "freeze_sha256": sha256(ROOT / FREEZE),
        "operator_source_sha256": sha256(__file__),
        "runtime_source_sha256": frozen["runtime_source_sha256"],
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    write_once(base.with_name(base.name + "-launch-started.json"), record)
    log_path = base.with_name(base.name + "-launch-stdout.txt")
    started = time.perf_counter()
    with log_path.open("xb") as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        record["process_id"] = process.pid
        for line in process.stdout:
            log.write(line)
            log.flush()
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
        exit_code = process.wait()
    record.update(
        ended_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        operator_wall_seconds=time.perf_counter() - started,
        operator_wall_interpretation="includes all imports/input/output and all215 jobs; not a per-job endpoint",
        exit_code=exit_code, retained_stdout_stderr=str(log_path.relative_to(ROOT)),
        retained_stdout_stderr_sha256=sha256(log_path),
    )
    write_once(base.with_name(base.name + "-launch-attempt.json"), record)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
