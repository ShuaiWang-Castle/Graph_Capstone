"""Six fixed pilot jobs with process RSS/compute watchdog and retained failures."""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import psutil

from .freeze import ROOT, sha256, validate
from .run_case import write_once


def pilot_schedule(config):
    jobs = []
    for index, case_id in enumerate(config["pilot"]["sentinels"]):
        backends = config["pilot"]["backends"]
        if index % 2:
            backends = list(reversed(backends))
        for backend in backends:
            jobs.append({"case_id": case_id, "backend": backend, "arm": "U"})
    return jobs


def supervise(command, job_dir, config, log):
    process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log,
                               start_new_session=True)
    launched = time.perf_counter()
    peak = 0
    limit_reason = None
    while process.poll() is None:
        now = time.perf_counter()
        try:
            child = psutil.Process(process.pid)
            rss = child.memory_info().rss
            rss += sum(p.memory_info().rss for p in child.children(recursive=True)
                       if p.is_running())
            peak = max(peak, rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            rss = 0
        if rss > config["pilot"]["rss_bytes"]:
            limit_reason = "rss_limit"
        elif (job_dir / "timer-start.json").exists():
            timer = json.loads((job_dir / "timer-start.json").read_text())
            if not (job_dir / "compute-finished.json").exists():
                if now - timer["perf_counter"] >= config["pilot"]["wall_seconds"]:
                    limit_reason = "full_wall_limit"
            elif now - json.loads((job_dir / "compute-finished.json").read_text())[
                    "perf_counter"] > 60:
                limit_reason = "final_serialization_limit"
        elif now - launched > config["watchdog"]["initialization_limit_seconds"]:
            limit_reason = "initialization_limit"
        if limit_reason:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=config["watchdog"]["terminate_then_kill_seconds"])
            except subprocess.TimeoutExpired:
                pass
            # A leader can exit before a descendant; terminate the entire
            # isolated group even in that case before dispatching the next job.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            break
        time.sleep(config["watchdog"]["sampling_seconds"])
    return {"exit_code": process.returncode, "monitored_peak_RSS_bytes": peak,
            "monitored_peak_RSS_GiB": peak / (1024 ** 3),
            "limit_reason": limit_reason,
            "process_wall_seconds_including_import_input_output": time.perf_counter() - launched}


def select_backend(entries, config):
    sentinels = config["pilot"]["sentinels"]
    large = sentinels[-1]
    summaries = {}
    for backend in config["pilot"]["backends"]:
        rows = [r for r in entries if r["backend"] == backend]
        success = {r["case_id"] for r in rows if r["credited_verified_target"]}
        penalty = sum(r["full_compute_seconds"] if r["credited_verified_target"]
                      else config["pilot"]["wall_seconds"] for r in rows)
        summaries[backend] = {"eligible": large in success,
                              "completed_sentinels": len(success),
                              "selection_cost_with_unresolved_penalty": penalty}
    eligible = [b for b in config["pilot"]["backends"] if summaries[b]["eligible"]]
    if not eligible:
        return None, summaries
    winner = min(eligible, key=lambda b: (
        -summaries[b]["completed_sentinels"],
        summaries[b]["selection_cost_with_unresolved_penalty"],
        0 if b == "direct" else 1))
    return winner, summaries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="experiments/extensions/metric_sdp/config.json")
    parser.add_argument("--freeze", default="experiments/extensions/metric_sdp/pilot-freeze.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config, frozen = validate(args.config, args.freeze)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    jobs = pilot_schedule(config)
    write_once(output / "pilot-started.json",
               {"jobs": jobs, "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "config_sha256": sha256(args.config), "freeze_sha256": sha256(args.freeze),
                "scientific_scope": "exploratory U-only feasibility, not utility comparison"})
    entries = []
    for index, job in enumerate(jobs):
        # Every dispatch verifies the same source, config, environment and reviews.
        validate(args.config, args.freeze)
        job_dir = output / f"job-{index:03d}-{job['case_id']}-{job['backend']}"
        command = [sys.executable, "-m", "experiments.extensions.metric_sdp.run_case",
                   "--config", str(Path(args.config).resolve()),
                   "--freeze", str(Path(args.freeze).resolve()),
                   "--case", job["case_id"], "--backend", job["backend"],
                   "--output", str(job_dir)]
        print(json.dumps({"event": "pilot_job_start", "index": index, **job}), flush=True)
        with (output / f"job-{index:03d}.log").open("xb") as log:
            monitoring = supervise(command, job_dir, config, log)
        result_path = job_dir / "result.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        failure_path = job_dir / "failure.json"
        failure = json.loads(failure_path.read_text()) if failure_path.exists() else {}
        credited = (monitoring["exit_code"] == 0 and monitoring["limit_reason"] is None
                    and result.get("status") == "verified_target"
                    and result["full_compute_seconds"] <= config["pilot"]["wall_seconds"]
                    and monitoring["monitored_peak_RSS_bytes"] <= config["pilot"]["rss_bytes"])
        entry = {**job, "index": index, **monitoring,
                 "status": result.get("status", monitoring["limit_reason"] or
                                      failure.get("status", "missing_final_result")),
                 "credited_verified_target": credited,
                 "full_compute_seconds": result.get("full_compute_seconds"),
                 "result_sha256": sha256(result_path) if result_path.exists() else None,
                 "failure": failure or None}
        entries.append(entry)
        write_once(output / f"job-{index:03d}-closeout.json", entry)
        print(json.dumps({"event": "pilot_job_closeout", **entry}), flush=True)
        if failure.get("fatal_source_or_exactness") or monitoring["exit_code"] == 2:
            write_once(output / "pilot-halted.json", {"reason": "source_or_exactness_failure",
                                                     "retained_entries": entries,
                                                     "unexecuted_jobs": jobs[index + 1:]})
            return 2
    backend, summaries = select_backend(entries, config)
    write_once(output / "pilot-decision.json",
               {"status": "feasibility_pass" if backend else "feasibility_fail_stop_version",
                "selected_backend": backend, "backend_summaries": summaries,
                "entries": entries, "formal_execution_approved": False,
                "scientific_scope": "no preprocessing utility result or C001 closure"})
    print(json.dumps({"event": "pilot_finished", "selected_backend": backend,
                      "backend_summaries": summaries}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
