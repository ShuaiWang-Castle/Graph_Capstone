"""Sequential orchestration with immutable process logs and explicit exits.

Timing comparisons run one child at a time. No failed or unavailable case is
replaced, retried under changed parameters, or omitted from the launch ledger.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from experiments.run_public import sha256, validate_freeze, write_once


def jobs(config, run_dir, config_path, freeze_path, suites):
    common = ["--config", config_path, "--freeze", freeze_path, "--run-dir", str(run_dir)]
    if "public" in suites:
        for seed in config["proposal"]["seeds"]:
            for dataset in config["public_datasets"]:
                name = f"public-{dataset}-proposal{seed}"
                yield name, ["-m", "experiments.run_public", *common,
                             "--dataset", dataset, "--proposal-seed", str(seed)]
    if "controls" in suites:
        for case in config["controlled_cases"]:
            yield case["case_id"], ["-m", "experiments.run_controls", *common, "--stratum", "controlled", "--case", case["case_id"]]
        for dataset in config["development_datasets"]:
            yield f"development-{dataset}", ["-m", "experiments.run_controls", *common, "--stratum", "development", "--case", dataset]
    if "scaling" in suites:
        for case in config["controlled_cases"]:
            if case["family"] != "profile_scaling":
                continue
            for measurement, repetitions in (("timing", config["scaling"]["replicate_count"]),
                                              ("memory", config["scaling"]["memory_replicate_count"])):
                for replicate in range(repetitions):
                    methods = config["scaling"]["methods"]
                    methods = methods[replicate % len(methods):] + methods[:replicate % len(methods)]
                    for method in methods:
                        name = f"scaling-{case['case_id']}-{method}-{measurement}-{replicate}"
                        yield name, ["-m", "experiments.run_scaling", *common, "--case-id", case["case_id"],
                            "--method", method, "--replicate", str(replicate), "--measurement", measurement]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="experiments/config.json")
    parser.add_argument("--freeze", default="experiments/freeze.json")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--suites", nargs="+", choices=("public", "controls", "scaling"), default=["public", "controls", "scaling"])
    args = parser.parse_args()
    freeze = validate_freeze(args.config, args.freeze)
    config = json.loads(Path(args.config).read_text())
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    write_once(run_dir / "run-manifest.json", {"status": "launched", "suites": args.suites,
        "config": config, "config_sha256": sha256(args.config), "freeze": freeze,
        "freeze_sha256": sha256(args.freeze), "started_utc": datetime.now(timezone.utc).isoformat(),
        "execution_policy": "sequential isolated child processes; all configured jobs logged"})
    environment = dict(os.environ)
    environment.update(config["threads"])
    environment["PYTHONPATH"] = "src:."
    outcomes = []
    all_jobs = list(jobs(config, run_dir, args.config, args.freeze, args.suites))
    with (run_dir / "orchestration.jsonl").open("x", encoding="utf-8") as events:
        def log(record):
            events.write(json.dumps(record, ensure_ascii=False) + "\n")
            events.flush()
            os.fsync(events.fileno())
            print(json.dumps(record, ensure_ascii=False), flush=True)
        for name, command in all_jobs:
            validate_freeze(args.config, args.freeze)
            log({"event": "started", "job": name, "utc": datetime.now(timezone.utc).isoformat()})
            started = time.perf_counter()
            with (run_dir / f"{name}.log").open("xb") as output:
                process = subprocess.run([sys.executable, *command], env=environment, stdout=output, stderr=subprocess.STDOUT)
            outcome = {"event": "completed" if process.returncode == 0 else "failed",
                       "job": name, "exit_code": process.returncode,
                       "seconds": time.perf_counter() - started, "log": f"{name}.log",
                       "utc": datetime.now(timezone.utc).isoformat()}
            outcomes.append(outcome)
            log(outcome)
            if process.returncode:
                log({"event": "halted_for_repair", "trigger_job": name,
                     "remaining_jobs": [job for job, _ in all_jobs[len(outcomes):]]})
                break
    write_once(run_dir / "run-completed.json", {"status": "completed" if all(o["exit_code"] == 0 for o in outcomes) else "halted_for_repair",
        "outcomes": outcomes, "not_launched_due_failure": [job for job, _ in all_jobs[len(outcomes):]],
        "completed_utc": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    main()
