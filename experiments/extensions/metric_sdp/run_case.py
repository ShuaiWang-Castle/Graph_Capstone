"""Fresh-process U-only pilot worker; numerical time starts after common input."""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import time
import traceback

from experiments.datasets import load_development
from experiments.families import load_family
from .freeze import sha256, validate, write_once
from .runtime import run_arm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--backend", choices=("direct", "indirect"), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started = None
    try:
        config, frozen = validate(args.config, args.freeze)
        if args.case not in config["pilot"]["sentinels"]:
            raise ValueError("case is not in the fixed pilot sentinel list")
        case = next(c for c in config["cases"] if c["case_id"] == args.case)
        if case["stratum"] == "controlled":
            graph, metadata = load_family(case["family"], **case["parameters"],
                                          include_oracle_blocks=False)
        else:
            graph, metadata = load_development(case["dataset"])
        write_once(output / "input.json",
                   {"case": case, "metadata": metadata, "config_sha256": sha256(args.config),
                    "freeze_sha256": sha256(args.freeze), "arm": "U",
                    "backend": args.backend, "utc": datetime.datetime.now(
                        datetime.timezone.utc).isoformat()})
        started = time.perf_counter()
        write_once(output / "timer-start.json",
                   {"perf_counter": started, "wall_seconds": config["pilot"]["wall_seconds"]})
        record, results = run_arm(
            graph, case, "U", args.backend, config, output,
            wall_seconds=config["pilot"]["wall_seconds"], started_at=started)
        # A compute marker ends only the numerical watchdog, not RSS/log/output
        # monitoring. Final serialized proof is necessary for credited completion.
        write_once(output / "compute-finished.json",
                   {"perf_counter": time.perf_counter(), "status": record["status"],
                    "full_compute_seconds": record["full_compute_seconds"]})
        for i, result in enumerate(results):
            if result["interval"] is not None:
                write_once(output / f"component-{i:03d}-proof.json",
                           result["interval"].to_dict())
        record.update(config_sha256=sha256(args.config), freeze_sha256=sha256(args.freeze))
        write_once(output / "result.json", record)
        return 0
    except BaseException as error:
        record = {"status": "worker_exception", "exception_type": type(error).__name__,
                  "message": str(error), "traceback": traceback.format_exc(),
                  "fatal_source_or_exactness": isinstance(error, (ArithmeticError, ValueError)),
                  "elapsed_compute_seconds": None if started is None else
                  time.perf_counter() - started}
        write_once(output / "failure.json", record)
        print(record["traceback"], flush=True)
        return 2 if record["fatal_source_or_exactness"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
