"""Create the pilot freeze only from the independently sealed approvals."""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

from .freeze import ROOT, environment, runtime_sources, sha256, validate
from .freeze import validate_import_origins, write_once


APPROVED_MODULE_REVIEWS = {
    "reviews/metric-sdp-rational-source-review.json":
        "71ca7c2024de4157fcbef6c8283667578883f59112b15bfff98b0d965f5f7c43",
    "reviews/metric-sdp-safe-source-review.json":
        "a2a46e5667c08111a93bbcbe99970f4492785bd79b4e988a782f28a613e644c7",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-runtime-review-sha256", required=True)
    args = parser.parse_args()
    config_path = ROOT / "experiments/extensions/metric_sdp/config.json"
    freeze_path = ROOT / "experiments/extensions/metric_sdp/pilot-freeze.json"
    review_path = ROOT / "reviews/metric-sdp-runtime-source-review.json"
    require(sha256(review_path) == args.expected_runtime_review_sha256,
            "runtime approval is not the explicitly sealed review")
    review = json.loads(review_path.read_text())
    require(review["pilot_execution_approved"] is True,
            "independent review did not approve this bounded pilot freeze")
    require(review["configuration_freeze_blockers"] == [] and
            review["required_runtime_source_changes"] == [],
            "independent runtime review retains an implementation blocker")
    require(review["formal_execution_approved"] is False,
            "this preparer grants only the fixed six U pilot calls")
    source_map = runtime_sources()
    actual_environment = environment()
    validate_import_origins(source_map)
    require(review["runtime_source_sha256"] == source_map,
            "actual17 runtime source differs from independently reviewed source")
    require(review["environment"] == actual_environment,
            "actual installed environment differs from independent review")
    require(review["config_sha256"] == sha256(config_path),
            "prospective43-case configuration differs from independent review")
    for path, digest in APPROVED_MODULE_REVIEWS.items():
        require(sha256(ROOT / path) == digest, "module approval changed: " + path)
    rational = json.loads((ROOT / next(iter(APPROVED_MODULE_REVIEWS))).read_text())
    require(rational["verdict"]["rational_module_source"] ==
            "APPROVED_FOR_SCOPED_EXACT_REPAIR_IMPLEMENTATION_USE" and
            rational["verdict"]["blocking_source_defects"] == [] and
            rational["verdict"]["required_source_changes"] == [],
            "independent rational source gate is not clear")
    safe = json.loads((ROOT / "reviews/metric-sdp-safe-source-review.json").read_text())
    require(safe["verdict"] == "approved_for_scoped_source_use" and
            safe["material_blockers"] == [] and safe["necessary_revisions"] == [],
            "independent composition source gate is not clear")
    required = dict(review["required_artifact_sha256"])
    required.update(APPROVED_MODULE_REVIEWS)
    additional = [
        "reviews/metric-sdp-runtime-source-review.json",
        review["companion_markdown"],
        "experiments/protocol.md",
        "reviews/metric-sdp-prospective-scope-review.md",
        "reviews/metric-sdp-prospective-scope-review.json",
        "experiments/extensions/metric_sdp/pilot_launch_operator.py",
        "experiments/extensions/metric_sdp/prepare_pilot_freeze.py",
    ]
    for path in additional:
        digest = sha256(ROOT / path)
        require(path not in required or required[path] == digest,
                "additional already-reviewed artifact changed: " + path)
        required[path] = digest
    for path, digest in required.items():
        require(sha256(ROOT / path) == digest,
                "bound protocol/review/test artifact changed: " + path)
    require(sha256(ROOT / review["companion_markdown"]) ==
            review["companion_markdown_sha256"], "runtime review body changed")
    require(not (ROOT / "experiments/runs/20260929-metric-sdp-pilot-v1").exists(),
            "scientific pilot output already exists")
    frozen = {
        "schema_version": 1,
        "status": "frozen_for_six_bounded_U_only_pilot_jobs",
        "frozen_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "pilot_execution_approved": True,
        "formal_execution_approved": False,
        "scientific_utility_approved": False,
        "configuration_freeze_blockers": [],
        "scope": "fixed six U-only feasibility calls; no preprocessing utility or venue judgment",
        "config_sha256": sha256(config_path),
        "runtime_source_sha256": source_map,
        "environment": actual_environment,
        "required_artifact_sha256": dict(sorted(required.items())),
        "sealed_independent_approval_sha256": {
            **APPROVED_MODULE_REVIEWS,
            "reviews/metric-sdp-runtime-source-review.json": sha256(review_path),
        },
        "historical_manuscript_context": review["historical_manuscript_context"],
        "preparation": "all reviewed17 sources, actual imports, environment and required artifacts checked before exclusive write; no graph construction or solver execution",
    }
    write_once(freeze_path, frozen)
    validate(config_path, freeze_path)
    print(json.dumps({"freeze_path": str(freeze_path.relative_to(ROOT)),
                      "freeze_sha256": sha256(freeze_path),
                      "runtime_source_count": len(source_map),
                      "required_artifact_count": len(required),
                      "status": frozen["status"]}, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
