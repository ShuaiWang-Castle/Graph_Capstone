"""Sequential recovery of one whole failed case and all unlaunched v1 jobs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from experiments.run_all import jobs
from experiments.run_public import sha256, write_once
from experiments.recovery.policy import validate_recovery


def recovery_schedule(config, parent_completion, run_dir, config_path, freeze_path, recovery_path):
    all_jobs = list(jobs(config, run_dir, config_path, freeze_path, ["public", "controls", "scaling"]))
    old = parent_completion["outcomes"]
    if not (parent_completion.get("status") == "halted_for_repair"
            and len(all_jobs) == 139 and len(old) == 67
            and all(o["exit_code"] == 0 and o.get("event") == "completed" for o in old[:-1])
            and old[-1]["job"] == "development-davis" and old[-1]["exit_code"] == 1
            and old[-1].get("event") == "failed"
            and [o["job"] for o in old] == [name for name, _ in all_jobs[:67]]
            and parent_completion["not_launched_due_failure"] == [name for name, _ in all_jobs[67:]]):
        raise ValueError("Parent halt does not match the independently reviewed incident")
    remaining = all_jobs[66:]
    name, command = remaining[0]
    command = list(command)
    command[1] = "experiments.recovery.run_case"
    command.extend(["--recovery-freeze", str(recovery_path)])
    remaining[0] = name, command
    return remaining


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recovery-freeze", required=True)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    recovery, original_freeze = validate_recovery(args.recovery_freeze, parent_files=True)
    config_path, freeze_path = recovery["original_config_path"], recovery["original_freeze_path"]
    config = json.loads(Path(config_path).read_text())
    parent = Path(recovery["parent_run_dir"])
    parent_completion = json.loads((parent / "run-completed.json").read_text())
    if parent_completion["status"] != "halted_for_repair":
        raise ValueError("Original failed run must remain halted")
    run_dir = Path(args.run_dir)
    if str(run_dir) != recovery["planned_recovery_run_dir"]:
        raise ValueError("Output directory differs from fixed prospective selection")
    schedule = recovery_schedule(config, parent_completion, run_dir, config_path, freeze_path, args.recovery_freeze)
    if [name for name, _ in schedule] != recovery["scheduled_jobs"]:
        raise ValueError("Job schedule differs from reviewed recovery freeze")
    run_dir.mkdir(parents=True, exist_ok=False)
    write_once(run_dir / "run-manifest.json", {
        "status": "launched_recovery", "suites": ["controls", "scaling"],
        "config": config, "config_sha256": sha256(config_path),
        "freeze": original_freeze, "freeze_sha256": sha256(freeze_path),
        "recovery": recovery, "recovery_freeze_sha256": sha256(args.recovery_freeze),
        "scheduled_jobs": [name for name, _ in schedule],
        "parent_run_dir": str(parent), "parent_manifest_sha256": sha256(parent / "run-manifest.json"),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "execution_policy": "73 sequential isolated jobs; entire Davis primary rerun; exact paired native incident retained as failed; all other unexpected failures halt",
    })
    environment = dict(os.environ)
    environment.update(config["threads"])
    environment["PYTHONPATH"] = "src:."
    outcomes = []
    with (run_dir / "orchestration.jsonl").open("x", encoding="utf-8") as events:
        def log(record):
            events.write(json.dumps(record, ensure_ascii=False) + "\n")
            events.flush()
            os.fsync(events.fileno())
            print(json.dumps(record, ensure_ascii=False), flush=True)
        for name, command in schedule:
            validate_recovery(args.recovery_freeze)
            write_once(run_dir / f"{name}-recovery-job-provenance.json", {
                "job": name, "command": [sys.executable, *command],
                "overlay_applied_to_case_runtime": name == "development-davis",
                "base_freeze_sha256": sha256(freeze_path),
                "recovery_freeze_sha256": sha256(args.recovery_freeze),
                "overlay_runtime_source_sha256": recovery["overlay_runtime_source_sha256"],
                "review_sha256": recovery["review_sha256"],
            })
            log({"event": "started", "job": name, "utc": datetime.now(timezone.utc).isoformat()})
            started = time.perf_counter()
            with (run_dir / f"{name}.log").open("xb") as output:
                process = subprocess.run([sys.executable, *command], env=environment,
                                         stdout=output, stderr=subprocess.STDOUT)
            outcome = {"event": "completed" if process.returncode == 0 else "failed", "job": name,
                       "exit_code": process.returncode, "seconds": time.perf_counter() - started,
                       "log": f"{name}.log", "utc": datetime.now(timezone.utc).isoformat()}
            outcomes.append(outcome)
            log(outcome)
            if process.returncode:
                log({"event": "halted_for_repair", "trigger_job": name,
                     "remaining_jobs": [n for n, _ in schedule[len(outcomes):]]})
                break
    complete = len(outcomes) == len(schedule) and all(o["exit_code"] == 0 for o in outcomes)
    write_once(run_dir / "run-completed.json", {
        "status": "completed_recovery_with_recorded_native_failure" if complete else "halted_for_repair",
        "process_completion_is_native_solver_success": False,
        "outcomes": outcomes, "not_launched_due_failure": [n for n, _ in schedule[len(outcomes):]],
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    main()
