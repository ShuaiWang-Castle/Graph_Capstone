"""Exclusive formal freeze from sealed independent source and pilot evidence.

This preparer creates no graph, solver call or scientific outcome. The stored
configuration remains a prospective document; this separate record grants only
the fixed once-only 43x5 execution, not utility or manuscript-quality approval.
"""
from __future__ import annotations

import argparse
import datetime
import json

from .freeze import (
    ROOT, environment, runtime_sources, sha256, validate, validate_configuration,
    validate_import_origins, write_once,
)


CONFIG = "experiments/extensions/metric_sdp_formal/config.json"
FREEZE = "experiments/extensions/metric_sdp_formal/formal-freeze.json"
REVIEW = "reviews/metric-sdp-formal-source-review.json"
ANALYSIS = "analysis/metric_sdp/formal/prospective-analysis-manifest.json"
OUTPUT = "experiments/runs/20260929-metric-sdp-formal-v1"
DEPENDENCY_APPROVALS = {
    "reviews/metric-sdp-rational-source-review.json":
        "71ca7c2024de4157fcbef6c8283667578883f59112b15bfff98b0d965f5f7c43",
    "reviews/metric-sdp-safe-source-review.json":
        "a2a46e5667c08111a93bbcbe99970f4492785bd79b4e988a782f28a613e644c7",
    "reviews/metric-sdp-runtime-source-review.json":
        "96739c9b410ca005fca02e5377f76fb0e07baf5827b65072cb5a0bb98b75d89b",
    "reviews/metric-sdp-pilot-closeout.json":
        "4724d5223f65e54786b5cd8567f852637f3776726a9e6bc186c88b85af947324",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-formal-review-sha256", required=True)
    parser.add_argument("--expected-analysis-manifest-sha256", required=True)
    args = parser.parse_args(argv)
    require(sha256(ROOT / REVIEW) == args.expected_formal_review_sha256,
            "formal source approval is not the explicitly sealed independent review")
    review = json.loads((ROOT / REVIEW).read_text())
    require(review["status"] == "approved_for_once_43x5_metric_sdp_configuration_freeze"
            and review["formal_execution_approved"] is True,
            "independent review did not approve this fixed215 execution")
    require(review["scientific_utility_approved"] is False,
            "source gate must not claim preprocessing utility")
    require(review["configuration_freeze_blockers"] == [] and
            review["required_runtime_source_changes"] == [],
            "independent source review retains an implementation blocker")
    config = json.loads((ROOT / CONFIG).read_text())
    validate_configuration(config)
    source_map, actual_environment = runtime_sources(), environment()
    validate_import_origins(source_map)
    require(len(source_map) == 23 and review["runtime_source_sha256"] == source_map,
            "actual23 transitive sources differ from independent review")
    require(review["environment"] == actual_environment,
            "installed numerical environment differs from independent review")
    require(review["config_sha256"] == sha256(ROOT / CONFIG),
            "full43/five-arm configuration differs from independent review")
    require(sha256(ROOT / ANALYSIS) == args.expected_analysis_manifest_sha256,
            "analysis methods are not the explicitly sealed prospective packet")
    analysis = json.loads((ROOT / ANALYSIS).read_text())
    require(analysis["config_sha256"] == sha256(ROOT / CONFIG),
            "prospective analysis methods bind a different configuration")
    required = dict(review["required_artifact_sha256"])
    for mapping in (DEPENDENCY_APPROVALS, analysis["required_artifact_sha256"]):
        for path, digest in mapping.items():
            require(path not in required or required[path] == digest,
                    "two gate packets bind different bytes: " + path)
            required[path] = digest
    for path in (
        REVIEW, review["companion_markdown"], ANALYSIS, CONFIG,
        "experiments/extensions/metric_sdp_formal/prepare_formal_freeze.py",
        "experiments/extensions/metric_sdp_formal/formal_launch_operator.py",
        config["pilot_provenance"]["freeze_path"],
        config["pilot_provenance"]["decision_path"],
        config["pilot_provenance"]["independent_closeout_path"],
    ):
        digest = sha256(ROOT / path)
        require(path not in required or required[path] == digest,
                "additional already-reviewed artifact changed: " + path)
        required[path] = digest
    pilot = json.loads((ROOT / config["pilot_provenance"]["freeze_path"]).read_text())
    for path, digest in pilot["required_artifact_sha256"].items():
        require(path not in required or required[path] == digest,
                "formal/pilot required evidence differs: " + path)
        required[path] = digest
    for path, digest in required.items():
        require(sha256(ROOT / path) == digest,
                "required immutable protocol/evidence changed: " + path)
    require(sha256(ROOT / review["companion_markdown"]) ==
            review["companion_markdown_sha256"], "independent review body changed")
    base = ROOT / OUTPUT
    require(not base.exists(), "formal scientific output already exists")
    for suffix in ("-launch-started.json", "-launch-stdout.txt", "-launch-attempt.json"):
        require(not base.with_name(base.name + suffix).exists(),
                "formal launch sidecar already exists")
    frozen = {
        "schema_version": 1,
        "status": "frozen_for_once_43x5_metric_sdp_comparison",
        "frozen_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "formal_execution_approved": True, "scientific_utility_approved": False,
        "configuration_freeze_blockers": [],
        "scope": "fixed43 whole inputs x five arms, selected common direct backend, one serial attempt each; no automatic C001/venue judgment",
        "config_sha256": sha256(ROOT / CONFIG),
        "runtime_source_sha256": source_map,
        "environment": actual_environment,
        "required_artifact_sha256": dict(sorted(required.items())),
        "sealed_independent_approval_sha256": {**DEPENDENCY_APPROVALS,
                                               REVIEW: sha256(ROOT / REVIEW)},
        "prospective_analysis_manifest_sha256": sha256(ROOT / ANALYSIS),
        "planned_scientific_output": OUTPUT,
        "preparation": "actual23 source/import/environment/config/evidence identity checked before exclusive write; no scientific input generation or solver execution",
    }
    write_once(ROOT / FREEZE, frozen)
    validate(ROOT / CONFIG, ROOT / FREEZE)
    print(json.dumps({"freeze_path": FREEZE, "freeze_sha256": sha256(ROOT / FREEZE),
                      "runtime_source_count": len(source_map),
                      "required_artifact_count": len(required), "status": frozen["status"]}, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
