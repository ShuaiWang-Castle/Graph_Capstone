"""Prepare prospective selection, then freeze only an independently approved overlay."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from experiments.run_all import jobs
from experiments.run_public import sha256, validate_freeze, write_once
from experiments.recovery.policy import STATUS, known_incident
from experiments.recovery.run_remaining import recovery_schedule

PARENT = "experiments/runs/20260929-frozen-v1"
RECOVERY_RUN = "experiments/runs/20260929-v1-recovery"
COLLECTION = "analysis/collections/20260929-v1-recovery"
CONFIG = "experiments/config.json"
BASE_FREEZE = "experiments/freeze.json"
FREEZE = "experiments/recovery/freeze.json"
SELECTION = "experiments/recovery/collection-selection-plan.json"
REVIEW = "reviews/native-incident-recovery-review.json"
ENGINEERING = "experiments/recovery/engineering-validation.json"
OVERLAY = tuple(f"experiments/recovery/{name}" for name in (
    "__init__.py", "policy.py", "run_case.py", "run_remaining.py", "prepare_freeze.py"))
ANALYSIS = ("analysis/collect_recovery.py", "analysis/report.py", "analysis/test_report.py")


def prospective_selection(config, completion):
    all_jobs = list(jobs(config, RECOVERY_RUN, CONFIG, BASE_FREEZE, ["public", "controls", "scaling"]))
    recovery_schedule(config, completion, RECOVERY_RUN, CONFIG, BASE_FREEZE, FREEZE)
    return {
        "kind": "prospective_fixed_recovery_selection", "parent_run_dir": PARENT,
        "recovery_run_dir": RECOVERY_RUN, "collection_dir": COLLECTION,
        "base_config_sha256": sha256(CONFIG), "base_freeze_sha256": sha256(BASE_FREEZE),
        "primary_selection_rule": "66 complete parent jobs plus entire recovery Davis case and all72 previously unlaunched scalers; never select or average favorable repeats",
        "logical_job_count": 139, "orchestration_attempt_count_if_complete": 140,
        "logical_jobs": [{"job": name, "source_job": name,
                          "source_role": "parent" if i < 66 else "recovery",
                          "source_run_dir": PARENT if i < 66 else RECOVERY_RUN}
                         for i, (name, _) in enumerate(all_jobs)],
        "original_failed_job": "development-davis",
        "retained_nonprimary_evidence": "all original Davis partial gamma records, failed JSON, log and process outcome; independent native reproduction remains a diagnostic artifact",
        "process_completion_is_native_solver_success": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "freeze"))
    args = parser.parse_args()
    validate_freeze(CONFIG, BASE_FREEZE)
    parent = Path(PARENT)
    completion = json.loads((parent / "run-completed.json").read_text())
    if completion.get("status") != "halted_for_repair":
        raise ValueError("Original run must remain an immutable halted run")
    failed = json.loads((parent / "development-davis-gamma2-full-solver-failed.json").read_text())
    if not known_incident(failed["native_record"], prefix="development-davis", gamma_index=2, method="full-solver"):
        raise ValueError("Parent failure differs from diagnosed incident")
    selection = prospective_selection(json.loads(Path(CONFIG).read_text()), completion)
    if args.mode == "prepare":
        write_once(SELECTION, selection)
        return
    if json.loads(Path(SELECTION).read_text()) != selection:
        raise ValueError("Prospective selection changed")
    source_hashes = {path: sha256(path) for path in OVERLAY}
    review = json.loads(Path(REVIEW).read_text())
    analysis_hashes = {path: sha256(path) for path in ANALYSIS}
    if not (review.get("status") == "approved_for_recovery_configuration_freeze"
            and review.get("overlay_runtime_source_sha256") == source_hashes
            and review.get("selection_plan_sha256") == sha256(SELECTION)
            and review.get("collection_analysis_source_sha256") == analysis_hashes):
        raise ValueError("Actual overlay/selection are not independently approved")
    engineering = json.loads(Path(ENGINEERING).read_text())
    engineering_sources = source_hashes | {"experiments/recovery/test_recovery.py": sha256("experiments/recovery/test_recovery.py")}
    if engineering.get("status") != "passed" or engineering.get("source_sha256") != engineering_sources:
        raise ValueError("Passed engineering record does not match current sources")
    if review.get("engineering_validation_sha256") != sha256(ENGINEERING):
        raise ValueError("Review does not approve the passed engineering record")
    incident = Path("research/full_kapoce/incidents/davis-gamma2")
    incident_hashes = {str(p): sha256(p) for p in sorted(incident.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
    if review.get("incident_evidence_sha256") != incident_hashes:
        raise ValueError("Review does not approve actual incident evidence")
    scheduled = [item["job"] for item in selection["logical_jobs"][66:]]
    value = {
        "status": STATUS, "created_utc": datetime.now(timezone.utc).isoformat(),
        "original_config_path": CONFIG, "original_freeze_path": BASE_FREEZE,
        "original_freeze_sha256": sha256(BASE_FREEZE), "parent_run_dir": PARENT,
        "planned_recovery_run_dir": RECOVERY_RUN, "planned_collection_dir": COLLECTION,
        "overlay_runtime_source_sha256": source_hashes,
        "collection_analysis_source_sha256": analysis_hashes,
        "selection_plan_path": SELECTION, "selection_plan_sha256": sha256(SELECTION),
        "review_path": REVIEW, "review_sha256": sha256(REVIEW),
        "engineering_validation_path": ENGINEERING, "engineering_validation_sha256": sha256(ENGINEERING),
        "incident_evidence_sha256": incident_hashes,
        "parent_artifact_sha256": {str(p): sha256(p) for p in sorted(parent.rglob("*")) if p.is_file()},
        "scheduled_jobs": scheduled, "logical_job_count": 139,
        "orchestration_attempt_count_if_complete": 140,
        "native_failure_preserved": True,
        "claim_scope": "separately reviewed execution-policy recovery with recorded native failures; original v1 remains halted",
    }
    write_once(FREEZE, value)


if __name__ == "__main__":
    main()
