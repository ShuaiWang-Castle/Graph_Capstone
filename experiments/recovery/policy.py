"""Narrow fail-stop exception for the independently reproduced Davis incident.

This classifies no solver result as successful and repairs no algorithm. All
native assertions stay enabled. Every other unexpected failure still halts.
"""
from __future__ import annotations

import json
from pathlib import Path

from experiments.run_public import sha256, validate_freeze, write_once

INPUT_SHA = "572f45534f4744f3d424511d8aaec6966aec0078a2b44236f97a81c4d28e742d"
BINARY_SHA = "62d20d50a6c2812ee64b0f0564dcf01cc7fe7873ed0b1d817ba1612afec1ae86"
BUILD_SHA = "df5e857ccd7a31faed3ee0c041422dcd094c6019783a81c5f8e91aec6b99dbed"
STDERR = "Assertion failed: (stars_in_bound[star] >= 0), function remove_star, file star_bound.cpp, line 518.\n"
STATUS = "frozen_after_independent_incident_recovery_review"
BAD = {"failed", "validation_failure", "unavailable_build"}


def known_incident(record, *, prefix, gamma_index, method):
    """Exact paired allowlist. A lone matching failure is never sufficient."""
    if (prefix, gamma_index, method) != ("development-davis", 2, "full-solver"):
        return False
    if not isinstance(record, dict):
        return False
    arms = record.get("paired_arms", {})
    records = record.get("records", [])
    if (not isinstance(arms, dict) or not isinstance(records, list)
            or set(arms) != {"unreduced", "reduced"} or len(records) != 2
            or not all(isinstance(r, dict) for r in [*records, *arms.values()])):
        return False
    if {r.get("case_name") for r in records} != {
        "development-davis-gamma2-unreduced", "development-davis-gamma2-reduced"
    }:
        return False
    if any(r != arms[name] for name, r in
           ((r["case_name"].rsplit("-", 1)[-1], r) for r in records)):
        return False
    for name, arm in arms.items():
        conversion, native = arm.get("conversion", {}), arm.get("native", {})
        if not (
            arm.get("status") == "failed"
            and arm.get("case_name") == f"development-davis-gamma2-{name}"
            and arm.get("binary_sha256") == BINARY_SHA
            and arm.get("build_provenance_sha256") == BUILD_SHA
            and arm.get("full_solver_entry_called") is True
            and arm.get("full_kapoce_solver") is True
            and arm.get("incumbent_Q_original_exact") == "-106/7921"
            and arm.get("incumbent", {}).get("verified_independently") is True
            and arm.get("timeout_seconds") == 30
            and conversion.get("input_sha256") == INPUT_SHA
            and conversion.get("gamma") == "2"
            and conversion.get("volume") == 178
            and len(conversion.get("degrees", [])) == 32
            and conversion.get("integer_divisor") == 2
            and conversion.get("max_absolute_pair_cost") == 168
            and conversion.get("sum_absolute_pair_costs") == 15172
            and conversion.get("budget") == 3419
            and conversion.get("incumbent_Q") == "-106/7921"
            and native.get("exit_code") == -6
            and native.get("outer_timeout_triggered") is False
            and native.get("stderr") == STDERR
            and [event.get("event") for event in native.get("events", [])]
                == ["input_accepted", "initial_bound", "full_solve_entered"]
        ):
            return False
    permitted = {("records", 0), ("records", 1),
                 ("paired_arms", "unreduced"), ("paired_arms", "reduced")}
    def bad_paths(value, path=()):
        if isinstance(value, dict):
            if value.get("status") in BAD:
                yield path
            for key, item in value.items():
                yield from bad_paths(item, (*path, key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from bad_paths(item, (*path, index))
    return all(path in permitted for path in bad_paths(record))


def validate_recovery(freeze_path, *, parent_files=False):
    freeze_path = Path(freeze_path)
    value = json.loads(freeze_path.read_text())
    if value.get("status") != STATUS:
        raise ValueError("Independent incident recovery freeze is required")
    original = validate_freeze(value["original_config_path"], value["original_freeze_path"])
    if sha256(value["original_freeze_path"]) != value["original_freeze_sha256"]:
        raise ValueError("Original frozen packet identity changed")
    for path, expected in value["overlay_runtime_source_sha256"].items():
        if sha256(path) != expected:
            raise ValueError(f"Recovery overlay changed after freeze: {path}")
    review_path = value["review_path"]
    if sha256(review_path) != value["review_sha256"]:
        raise ValueError("Independent recovery review changed")
    review = json.loads(Path(review_path).read_text())
    if (review.get("status") != "approved_for_recovery_configuration_freeze"
            or review.get("overlay_runtime_source_sha256") != value["overlay_runtime_source_sha256"]):
        raise ValueError("Review does not approve the actual overlay")
    for path_key, sha_key in (("selection_plan_path", "selection_plan_sha256"),
                              ("engineering_validation_path", "engineering_validation_sha256")):
        if sha256(value[path_key]) != value[sha_key]:
            raise ValueError(f"Reviewed recovery artifact changed: {value[path_key]}")
    if review.get("selection_plan_sha256") != value["selection_plan_sha256"]:
        raise ValueError("Review does not approve the frozen primary selection")
    if review.get("engineering_validation_sha256") != value["engineering_validation_sha256"]:
        raise ValueError("Review does not approve the frozen engineering record")
    for path, expected in value["incident_evidence_sha256"].items():
        if sha256(path) != expected:
            raise ValueError(f"Incident evidence changed: {path}")
    if parent_files:
        for path, expected in value["parent_artifact_sha256"].items():
            if sha256(path) != expected:
                raise ValueError(f"Original halted evidence changed: {path}")
    return value, original


def recovery_preserver(original_preserver, recovery_freeze_sha):
    def preserve(run_dir, prefix, gamma_index, record, *, method):
        if not known_incident(record, prefix=prefix, gamma_index=gamma_index, method=method):
            return original_preserver(run_dir, prefix, gamma_index, record, method=method)
        failed_path = Path(run_dir) / f"{prefix}-gamma{gamma_index}-{method}-failed.json"
        try:
            original_preserver(run_dir, prefix, gamma_index, record, method=method)
        except RuntimeError:
            if not failed_path.exists():
                raise
            marker = {
                "status": "known_native_failure_preserved_not_solver_success",
                "prefix": prefix, "gamma_index": gamma_index, "method": method,
                "native_status_retained": "failed", "recovery_freeze_sha256": recovery_freeze_sha,
                "failed_artifact": failed_path.name, "failed_artifact_sha256": sha256(failed_path),
                "input_sha256": INPUT_SHA, "binary_sha256": BINARY_SHA,
                "excluded_inferences": ["native optimality", "native packing lower bound", "bound gap", "completed solve-time ratio"],
                "retained_inference": "independently verified feasible supplied incumbent only",
            }
            write_once(Path(run_dir) / f"{prefix}-gamma{gamma_index}-reviewed-incident.json", marker)
        else:
            raise ArithmeticError("Known failed native record unexpectedly bypassed original halt")
    return preserve
