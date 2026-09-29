"""Once-only serial 43x5 formal controller; no outcome-dependent dispatch."""
from __future__ import annotations

import argparse
from collections import Counter
import datetime
import json
import math
from pathlib import Path
import sys
import traceback

from experiments.extensions.metric_sdp.run_pilot import supervise
from .freeze import sha256, validate, write_once
from .run_case import ARMS, JOB_COUNT, validate_inventory


def formal_schedule(config):
    cases = validate_inventory(config)
    jobs = []
    for case_index, case in enumerate(cases):
        offset = case_index % len(ARMS)
        rotation = ARMS[offset:] + ARMS[:offset]
        for arm in rotation:
            jobs.append({
                "case_id": case["case_id"], "case_index": case_index,
                "arm": arm, "backend": config["solver"]["backend"],
            })
    return jobs


def watchdog_overlay(config):
    """Operational limits override the retained historical pilot metadata."""
    return {"pilot": config["formal"], "watchdog": config["watchdog"]}


def _optional_json(path):
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("worker marker must contain a JSON object: " + str(path))
    return value


def _safe_hash(path):
    try:
        return sha256(path) if Path(path).exists() else None
    except OSError:
        return None


def _error(error):
    return {
        "exception_type": type(error).__name__, "message": str(error),
        "traceback": traceback.format_exc(),
    }


def closeout(job, index, monitoring, job_dir, config, digests):
    """Only a serialized runtime result within both budgets is creditable."""
    result_path, failure_path = job_dir / "result.json", job_dir / "failure.json"
    result = _optional_json(result_path)
    failure = _optional_json(failure_path)
    if failure is not None and any(
            failure.get(key) != job[key] for key in ("case_id", "arm")):
        raise ArithmeticError("serialized worker failure has a different job identity")
    if result is not None:
        expected = {
            "case_id": job["case_id"], "arm": job["arm"], "backend": job["backend"],
            "config_sha256": digests["config"], "freeze_sha256": digests["freeze"],
        }
        if any(result.get(key) != value for key, value in expected.items()):
            raise ArithmeticError("serialized worker result has a different job/source identity")
        seconds = result.get("full_compute_seconds")
        if (not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or
                not math.isfinite(seconds) or seconds < 0):
            raise ArithmeticError("serialized worker compute time is invalid")
    else:
        seconds = None
    credited = (
        monitoring["exit_code"] == 0 and monitoring["limit_reason"] is None and
        failure is None and result is not None and result.get("status") == "verified_target" and
        seconds <= config["formal"]["wall_seconds"] and
        monitoring["monitored_peak_RSS_bytes"] <= config["formal"]["rss_bytes"])
    entry = {
        **job, "index": index, **monitoring,
        "status": ((result or {}).get("status") or monitoring["limit_reason"] or
                   (failure or {}).get("status") or "missing_final_result"),
        "credited_verified_target": credited, "full_compute_seconds": seconds,
        "result_sha256": _safe_hash(result_path),
        "failure_sha256": _safe_hash(failure_path), "failure": failure,
    }
    fatal = (
        bool((failure or {}).get("fatal_source_or_exactness")) or
        monitoring["exit_code"] == 2)
    return entry, fatal


def summary(jobs, entries, unexecuted):
    credited = sum(bool(entry["credited_verified_target"]) for entry in entries)
    return {
        "planned_jobs": JOB_COUNT, "scheduled_jobs": len(jobs),
        "dispatched_jobs": len(entries), "unexecuted_job_count": JOB_COUNT - len(entries),
        "detailed_schedule_known": len(jobs) == JOB_COUNT,
        "credited_verified_target_jobs": credited,
        "all_jobs_credited_verified_target": credited == JOB_COUNT,
        "status_counts": dict(Counter(entry["status"] for entry in entries)),
        "per_arm": {
            arm: {
                "planned": JOB_COUNT // len(ARMS),
                "dispatched": sum(entry["arm"] == arm for entry in entries),
                "credited_verified_target": sum(
                    entry["arm"] == arm and entry["credited_verified_target"]
                    for entry in entries),
                "unexecuted": JOB_COUNT // len(ARMS) - sum(
                    entry["arm"] == arm for entry in entries),
            } for arm in ARMS
        },
        "runtime_ratios_computed": False,
        "scientific_judgment": "none; completion is an execution/accounting record",
    }


def _halt(output, reason, jobs, entries, first_unexecuted, detail):
    remaining = jobs[first_unexecuted:]
    identities_known = len(jobs) == JOB_COUNT
    write_once(output / "study-halted.json", {
        "status": "halted_source_version", "reason": reason, "detail": detail,
        "retained_entries": entries,
        "unexecuted_jobs": remaining if identities_known else None,
        "unexecuted_job_identities_known": identities_known,
        "summary": summary(jobs, entries, remaining),
        "formal_study_completed": False, "C001_or_venue_judgment": False,
    })
    return 2


def _unvalidated_schedule(config_path):
    # Only reconstruct the denominator; never load input or dispatch from it.
    try:
        return formal_schedule(json.loads(Path(config_path).read_text()))
    except Exception:
        return []


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        config, frozen = validate(args.config, args.freeze)
        jobs = formal_schedule(config)
        digests = {"config": sha256(args.config), "freeze": sha256(args.freeze)}
    except Exception as error:
        jobs = _unvalidated_schedule(args.config)
        detail = {**_error(error), "schedule_from_unvalidated_config": True,
                  "fixed_unexecuted_denominator": JOB_COUNT,
                  "config_sha256": _safe_hash(args.config),
                  "freeze_sha256": _safe_hash(args.freeze)}
        return _halt(output, "initial_source_or_contract_validation_failure",
                     jobs, [], 0, detail)
    write_once(output / "study-started.json", {
        "jobs": jobs, "planned_jobs": JOB_COUNT, "formal": config["formal"],
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "config_sha256": digests["config"], "freeze_sha256": digests["freeze"],
        "source_version": config.get("source_version"),
        "formal_freeze_status": frozen["status"],
        "scientific_scope": "fixed once-only formal comparison; no automatic C001/venue decision",
    })
    entries = []
    for index, job in enumerate(jobs):
        try:
            current, _ = validate(args.config, args.freeze)
            if (current != config or sha256(args.config) != digests["config"] or
                    sha256(args.freeze) != digests["freeze"]):
                raise ValueError("formal source/config freeze identity changed during the study")
        except Exception as error:
            return _halt(output, "pre_dispatch_source_validation_failure",
                         jobs, entries, index, {**_error(error), "failed_dispatch": job})
        job_dir = output / f"job-{index:03d}-{job['case_id']}-{job['arm']}"
        command = [
            sys.executable, "-m", "experiments.extensions.metric_sdp_formal.run_case",
            "--config", str(Path(args.config).resolve()),
            "--freeze", str(Path(args.freeze).resolve()),
            "--case", job["case_id"], "--arm", job["arm"], "--output", str(job_dir),
        ]
        print(json.dumps({"event": "formal_job_start", "index": index, **job}), flush=True)
        try:
            with (output / f"job-{index:03d}.log").open("xb") as log:
                monitoring = supervise(command, job_dir, watchdog_overlay(config), log)
        except Exception as error:
            entry = {
                **job, "index": index, "status": "controller_supervision_exception",
                "credited_verified_target": False, "full_compute_seconds": None,
                "failure": _error(error), "dispatch_state": "attempted_not_creditable",
            }
            entries.append(entry)
            write_once(output / f"job-{index:03d}-closeout.json", entry)
            return _halt(output, "controller_supervision_failure", jobs, entries,
                         index + 1, {"current_worker_state_requires_operational_check": True})
        try:
            entry, fatal = closeout(job, index, monitoring, job_dir, config, digests)
        except Exception as error:
            entry = {
                **job, "index": index, **monitoring,
                "status": "controller_record_validation_failure",
                "credited_verified_target": False, "full_compute_seconds": None,
                "result_sha256": _safe_hash(job_dir / "result.json"),
                "failure_sha256": _safe_hash(job_dir / "failure.json"),
                "failure": {**_error(error), "fatal_source_or_exactness": True},
            }
            fatal = True
        entries.append(entry)
        write_once(output / f"job-{index:03d}-closeout.json", entry)
        print(json.dumps({"event": "formal_job_closeout", **entry}), flush=True)
        if fatal:
            return _halt(output, "source_or_exactness_failure", jobs, entries,
                         index + 1, {"failed_job": job})
    write_once(output / "study-completed.json", {
        "status": "completed_fixed_schedule", "entries": entries,
        "unexecuted_jobs": [], "summary": summary(jobs, entries, []),
        "formal_study_completed": True, "C001_or_venue_judgment": False,
        "config_sha256": digests["config"], "freeze_sha256": digests["freeze"],
    })
    print(json.dumps({"event": "formal_study_finished",
                      "summary": summary(jobs, entries, [])}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
