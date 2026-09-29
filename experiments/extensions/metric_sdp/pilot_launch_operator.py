"""Retain the exact one-shot operator command and its complete output.

This wrapper supplies no solver policy and performs no graph computation.
All scientific limits and job ordering belong to the reviewed run_pilot.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
import subprocess
import sys
import time

from .freeze import ROOT, sha256, validate, write_once


def main():
    config = "experiments/extensions/metric_sdp/config.json"
    frozen = "experiments/extensions/metric_sdp/pilot-freeze.json"
    output = "experiments/runs/20260929-metric-sdp-pilot-v1"
    _, freeze = validate(ROOT / config, ROOT / frozen)
    if (ROOT / output).exists():
        raise FileExistsError("the prospective pilot output already exists")
    command = [".venv-sdp/bin/python", "-m",
               "experiments.extensions.metric_sdp.run_pilot",
               "--config", config, "--freeze", frozen, "--output", output]
    record = {
        "schema_version": 1,
        "purpose": "one fixed six-job U-only feasibility pilot",
        "command": command,
        "cwd": ".",
        "environment": {name: os.environ.get(name) for name in
                        ("PYTHONPATH", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                         "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")},
        "config_sha256": sha256(ROOT / config),
        "freeze_sha256": sha256(ROOT / frozen),
        "operator_source_sha256": sha256(__file__),
        "runtime_source_sha256": freeze["runtime_source_sha256"],
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    base = ROOT / output
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
        operator_wall_interpretation="includes all six jobs, imports and output; not a per-job endpoint",
        exit_code=exit_code,
        retained_stdout_stderr=str(log_path.relative_to(ROOT)),
        retained_stdout_stderr_sha256=sha256(log_path),
    )
    write_once(base.with_name(base.name + "-launch-attempt.json"), record)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
