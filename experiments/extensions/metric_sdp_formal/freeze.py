"""Separate gate for the once-only 43x5 formal study after the sealed pilot."""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..metric_sdp.freeze import ROOT, environment, sha256, write_once
from ..metric_sdp.freeze import runtime_sources as pilot_runtime_sources
from ..metric_sdp.freeze import validate_import_origins

NAMESPACE = Path("experiments/extensions/metric_sdp_formal")
FORMAL_RUNTIME = tuple(str(NAMESPACE / name) for name in
                       ("__init__.py", "composition.py", "runtime.py", "freeze.py",
                        "run_case.py", "run_study.py"))


def runtime_sources():
    sources = pilot_runtime_sources()
    sources.update({path: sha256(ROOT / path) for path in FORMAL_RUNTIME})
    return sources


def validate_configuration(config):
    """Enforce the prospective inventory/policies, not outcome-based eligibility."""
    original_path = ROOT / config["original_configuration"]["path"]
    if sha256(original_path) != config["original_configuration"]["sha256"]:
        raise ValueError("original reviewed configuration changed")
    original = json.loads(original_path.read_text())
    for key in ("protocol", "original_config", "original_config_sha256",
                "case_selection", "cases", "arms", "discovery", "checker",
                "pilot", "formal", "watchdog", "threads", "failure_policy",
                "output_policy"):
        if config[key] != original[key]:
            raise ValueError("prospective whole-study policy changed: " + key)
    expected_solver = dict(original["solver"])
    expected_solver["backend"] = config["pilot_provenance"]["selected_backend"]
    if config["solver"] != expected_solver:
        raise ValueError("common numerical policy changed beyond selected backend")
    ids = [case["case_id"] for case in config["cases"]]
    if len(ids) != 43 or len(set(ids)) != 43 or config["arms"] != ["U", "S", "D", "SD", "SW"]:
        raise ValueError("full43 input/five-arm denominator required")
    if (config["formal"]["jobs"] != 215 or config["formal"]["wall_seconds"] != 300
            or config["formal"]["rss_bytes"] != 6 * 1024 ** 3):
        raise ValueError("fixed215 job/budget contract required")
    provenance = config["pilot_provenance"]
    for label in ("freeze", "decision", "independent_closeout"):
        if sha256(ROOT / provenance[label + "_path"]) != provenance[label + "_sha256"]:
            raise ValueError("sealed pilot provenance changed: " + label)
    decision = json.loads((ROOT / provenance["decision_path"]).read_text())
    closeout = json.loads((ROOT / provenance["independent_closeout_path"]).read_text())
    backend = config["solver"]["backend"]
    if (decision["status"] != "feasibility_pass" or backend not in ("direct", "indirect")
            or decision["selected_backend"] != backend
            or closeout["integrity_status"] != "validated"
            or closeout["pilot_feasibility_outcome"] != "pass"
            or closeout["selected_backend"] != backend
            or not closeout["n240_eligibility"][backend]):
        raise ValueError("full original-size pilot feasibility and independent closeout required")


def validate(config_path, freeze_path):
    config_path, freeze_path = Path(config_path), Path(freeze_path)
    config = json.loads(config_path.read_text())
    frozen = json.loads(freeze_path.read_text())
    if (frozen["status"] != "frozen_for_once_43x5_metric_sdp_comparison"
            or frozen["formal_execution_approved"] is not True
            or frozen["configuration_freeze_blockers"] != []):
        raise ValueError("this source version has no formal-study execution approval")
    if frozen["config_sha256"] != sha256(config_path):
        raise ValueError("formal configuration changed after freeze")
    sources = runtime_sources()
    if frozen["runtime_source_sha256"] != sources:
        raise ValueError("transitive formal/pilot source changed after freeze")
    validate_import_origins(sources)
    if frozen["environment"] != environment():
        raise ValueError("runtime environment changed after formal freeze")
    for path, digest in frozen["required_artifact_sha256"].items():
        if sha256(ROOT / path) != digest:
            raise ValueError("required formal/pilot evidence changed: " + path)
    if any(os.getenv(name) != value for name, value in config["threads"].items()):
        raise ValueError("fixed numerical thread settings required before imports")
    validate_configuration(config)
    return config, frozen
