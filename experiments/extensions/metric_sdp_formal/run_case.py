"""Fresh-process formal worker; common input precedes the complete-cost timer."""
from __future__ import annotations

import argparse
import datetime
from pathlib import Path
import time
import traceback

from experiments.datasets import load_development
from experiments.families import load_family
from .freeze import sha256, validate, write_once
from .runtime import run_arm

ARMS = ("U", "S", "D", "SD", "SW")
CASE_COUNT = 43
JOB_COUNT = CASE_COUNT * len(ARMS)


def validate_inventory(config):
    """Read-only frozen-inventory eligibility; no graph or outcome inspection."""
    if config.get("arms") != list(ARMS):
        raise ValueError("formal arms must be the fixed five-arm order")
    cases = config.get("cases")
    if not isinstance(cases, list) or len(cases) != CASE_COUNT:
        raise ValueError("formal inventory must contain all 43 fixed cases")
    ids = [case.get("case_id") for case in cases]
    if (any(not isinstance(case_id, str) or not case_id or
            any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in case_id)
            for case_id in ids) or len(set(ids)) != CASE_COUNT):
        raise ValueError("formal case identifiers must be unique safe strings")
    for case in cases:
        if case.get("stratum") == "controlled":
            if (not isinstance(case.get("family"), str) or
                    not isinstance(case.get("parameters"), dict)):
                raise ValueError("controlled case needs its frozen family and parameters")
        elif case.get("stratum") == "development":
            if not isinstance(case.get("dataset"), str):
                raise ValueError("development case needs its frozen dataset")
        else:
            raise ValueError("unknown formal case stratum")
    if config["solver"].get("backend") not in ("direct", "indirect"):
        raise ValueError("formal backend must come from the validated solver config")
    formal = config["formal"]
    if (formal.get("jobs") != JOB_COUNT or formal.get("wall_seconds") != 300 or
            formal.get("rss_bytes") != 6 * 1024 ** 3):
        raise ValueError("formal execution requires exactly 215 jobs, 300s and 6GiB")
    return cases


def selected_case(config, case_id, arm):
    cases = validate_inventory(config)
    if arm not in ARMS:
        raise ValueError("arm is outside the fixed formal inventory")
    matches = [case for case in cases if case["case_id"] == case_id]
    if len(matches) != 1:
        raise ValueError("case is outside the fixed formal inventory")
    return matches[0]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started = None
    phase = "source_validation"
    try:
        config, frozen = validate(args.config, args.freeze)
        phase = "case_eligibility"
        case = selected_case(config, args.case, args.arm)
        backend = config["solver"]["backend"]
        config_digest = sha256(args.config)
        freeze_digest = sha256(args.freeze)
        phase = "common_input"
        if case["stratum"] == "controlled":
            graph, metadata = load_family(
                case["family"], **case["parameters"], include_oracle_blocks=False)
        else:
            graph, metadata = load_development(case["dataset"])
        write_once(output / "input.json", {
            "case": case, "metadata": metadata, "config_sha256": config_digest,
            "freeze_sha256": freeze_digest, "arm": args.arm, "backend": backend,
            "source_version": config.get("source_version"),
            "formal_freeze_status": frozen["status"],
            "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        started = time.perf_counter()
        write_once(output / "timer-start.json", {
            "perf_counter": started, "wall_seconds": config["formal"]["wall_seconds"],
        })
        phase = "complete_arm_compute"
        record, results = run_arm(
            graph, case, args.arm, backend, config, output,
            wall_seconds=config["formal"]["wall_seconds"], started_at=started)
        if (record.get("case_id") != args.case or record.get("arm") != args.arm or
                record.get("backend") != backend):
            raise ArithmeticError("runtime record identity differs from the dispatched job")
        write_once(output / "compute-finished.json", {
            "perf_counter": time.perf_counter(), "status": record["status"],
            "full_compute_seconds": record["full_compute_seconds"],
        })
        # The unchanged watchdog still monitors RSS and allows only its existing
        # bounded final-serialization window. Completion needs the final record.
        phase = "final_serialization"
        for index, result in enumerate(results):
            if result["interval"] is not None:
                write_once(output / f"component-{index:03d}-proof.json",
                           result["interval"].to_dict())
        record.update(config_sha256=config_digest, freeze_sha256=freeze_digest)
        write_once(output / "result.json", record)
        return 0
    except BaseException as error:
        record = {
            "status": "worker_exception", "phase": phase,
            "case_id": args.case, "arm": args.arm,
            "exception_type": type(error).__name__, "message": str(error),
            "traceback": traceback.format_exc(),
            "fatal_source_or_exactness": (
                phase in ("source_validation", "case_eligibility") or
                isinstance(error, (ArithmeticError, ValueError))),
            "elapsed_compute_seconds": (
                None if started is None else time.perf_counter() - started),
        }
        write_once(output / "failure.json", record)
        print(record["traceback"], flush=True)
        return 2 if record["fatal_source_or_exactness"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

