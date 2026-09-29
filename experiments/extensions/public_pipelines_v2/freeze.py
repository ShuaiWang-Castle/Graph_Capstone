"""Prospective source/config freeze after actual-source review and engineering gates."""
from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess

import networkx as nx
import numpy as np
import scipy

from .contracts import PHASES, SCHEMA, content_hash, read_json, sha256, utc_now, write_once
from .schedule import expected_ledger

NAMESPACE = Path("experiments/extensions/public_pipelines_v2")
CONFIG_PATH = NAMESPACE / "config.json"
UPSTREAM_FILES = ("experiments/candidates.py", "experiments/datasets.py", "experiments/pipeline.py",
                  "research/baselines/recursive_cheap.py", "research/baselines/sparse_criteria.py",
                  "research/baselines/almost_clique.py", "src/degree_contraction/__init__.py",
                  "src/degree_contraction/certificate.py", "src/degree_contraction/quotient.py")


def versions():
    return {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
            "networkx": nx.__version__}


def _assert(condition, message):
    if not condition:
        raise ValueError(message)


def validate_config(config):
    known = {"schema_version", "extension", "prospective_scope", "datasets", "discovery_seeds", "gamma", "arms",
             "downstream_seeds", "prefixes", "candidate_policy", "degree_policy", "recursive_policy", "rd_policy",
             "evaluator", "incumbent_policy", "schedule", "gc_policy", "retention_policy", "memory_policy", "threads",
             "phase_policy", "prerequisites", "design_paths", "data_registry", "processed_metadata", "required_review_status",
             "paths", "unexpected_failure_policy"}
    _assert(set(config) == known, "unknown/missing configuration fields")
    expected_ledger(config)
    _assert(config["schema_version"] == SCHEMA and config["extension"] == "public_pipelines_v2", "unknown schema")
    _assert(tuple(config["phase_policy"]["primary_names"]) == PHASES, "incomplete/changed primary phase policy")
    _assert(config["degree_policy"] == {"verification": "auto", "exact_max_size": 64, "dense_max_size": 64,
            "screen_tolerance": 1e-10, "center": "unchanged unweighted coordinatewise median with implicit zeros",
            "preassembly_cap": 64}, "changed degree policy")
    _assert(config["recursive_policy"] == {"max_block_size": 64, "include_round_decisions": False,
            "round_limit": None, "scope": "unchanged recursive composition of named cheap criteria; no native code"},
            "changed recursive policy")
    _assert(config["candidate_policy"] == {"resolution": "1", "minimum_size": 2, "dense_spectral_boundary": 64,
            "arpack_tolerance": 1e-7, "arpack_max_iterations": 10000, "candidate_count_cap": None,
            "complete_original_bank_identity_must_equal_v1": True}, "changed discovery policy")
    _assert(config["gc_policy"] == "normal_enabled_no_manual_collect", "changed GC policy")
    _assert(config["rd_policy"] == {"fresh_independent_recursive_prefix": True, "degree_stages_after_r": 1,
            "r_stages_after_degree": 0, "cap_after_full_bank_mapping": True, "operational_ids": "actual core CSR membership",
            "direct_original_integer_validation": True}, "changed sequential RD policy")
    _assert(config["incumbent_policy"] == {"control_kind": "discovery-incumbent control",
            "initial_partition_supplied_to_louvain": False,
            "fallback": "external original discovery allowed even when quotient-unrepresentable",
            "ties": ["discovery", "earliest downstream seed"], "comparison": "exact Fraction original-Q"}, "changed incumbent policy")
    _assert(config["retention_policy"] == "all four arm states and all raw label vectors retained through case finalization",
            "changed object retention")
    _assert(config["evaluator"] == "one Python-integer sparse exact modularity cache implementation on every arm and gamma",
            "changed evaluator")
    _assert(config["threads"] == {name: "1" for name in
            ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")}, "changed thread policy")


def validate_prerequisites(config):
    validate_config(config)
    prerequisite = config["prerequisites"]
    for name in ("original_freeze", "recovery_closeout", "collection", "selection_plan", "recovery_freeze"):
        entry = prerequisite[name]
        _assert(sha256(entry["path"]) == entry["sha256"], f"prerequisite identity mismatch: {name}")
    original = read_json(prerequisite["original_freeze"]["path"])
    for path, digest in original["runtime_source_sha256"].items():
        _assert(sha256(path) == digest, f"original frozen source changed: {path}")
    _assert(sha256(config["data_registry"]) == original["data_registry_sha256"], "data registry differs from v1")
    _assert(sha256(config["processed_metadata"]) == original["processed_metadata_sha256"], "processed metadata differs from v1")
    closeout = read_json(prerequisite["recovery_closeout"]["path"])
    _assert(closeout["status"] == "validated_descriptive_evidence_closeout_with_recorded_native_failures", "unclosed v1 evidence")
    d = closeout["denominators"]
    for key, expected in (("logical_selected_jobs", 139), ("actual_source_orchestration_attempts", 140),
                          ("selected_failed_native_arms", 2), ("formal_parent_and_recovery_failed_native_arms", 4)):
        _assert(d[key] == expected, f"v1 closeout denominator changed: {key}")
    _assert(d["parent_original_status"] == "halted_for_repair" and not d["logical_process_completion_is_native_solver_success"],
            "original failure history lost")
    for field, expected in (("required_logical_observations", 139), ("actual_source_attempts", 140),
                            ("selected_native_failed_arms", 2), ("all_formal_source_native_failed_arms", 4)):
        _assert(prerequisite[field] == expected, f"changed prerequisite policy: {field}")
    collection = read_json(prerequisite["collection"]["path"])
    _assert(collection["status"] == "complete_recovered_collection_with_recorded_native_failures"
            and collection["logical_job_count"] == 139 and collection["source_attempt_count"] == 140
            and collection["selection_plan_sha256"] == prerequisite["selection_plan"]["sha256"]
            and collection["recovery_freeze_sha256"] == prerequisite["recovery_freeze"]["sha256"],
            "recovery closeout/selection identities differ")
    for name, digest in closeout["artifact_sha256"].items():
        _assert(sha256(Path(prerequisite["recovery_closeout"]["path"]).parent / name) == digest,
                f"closeout artifact changed: {name}")
    banks = {}
    for setup in expected_ledger(config)["setups"]:
        path = Path(prerequisite["original_bank_run_dir"]) / f"{setup['dataset']}-proposal{setup['discovery_seed']}-candidates.json.gz"
        copied = collection["copied_artifacts"][path.name]
        _assert(copied["source_path"] == str(path) and copied["source_run"] == "parent" and sha256(path) == copied["sha256"],
                "archived bank bytes no longer match the closed-out original source selection")
        banks[setup["setup_key"]] = {"path": str(path), "sha256": sha256(path)}
    return {"original": original, "closeout": closeout, "archived_bank_identity": banks}


def runtime_sources():
    """Explicit recursive extension coverage plus every project-local transitive import."""
    sources = set(Path(path) for path in UPSTREAM_FILES)
    sources.add(Path("experiments/extensions/__init__.py"))
    sources.update(path for path in NAMESPACE.rglob("*.py") if not path.name.startswith("test_")
                   and "__pycache__" not in path.parts)
    # Inspect every project-local import. A new local dependency cannot be hidden
    # behind the old nonrecursive glob; standard/third-party code is version-pinned.
    pending = list(sources)
    while pending:
        path = pending.pop()
        if path.parts[0] == "src":
            module = ".".join(path.with_suffix("").parts[1:])
        else:
            module = ".".join(path.with_suffix("").parts)
        package = module.rsplit(".", 1)[0] if path.name != "__init__.py" else module.rsplit(".", 1)[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            targets = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                target = ("." * node.level) + (node.module or "")
                targets = [importlib.util.resolve_name(target, package) if node.level else target]
            for target in targets:
                if not target:
                    continue
                parts = target.split(".")
                if parts[0] not in {"degree_contraction", "experiments", "research"}:
                    continue
                base = Path("src") if parts[0] == "degree_contraction" else Path()
                candidate = base.joinpath(*parts).with_suffix(".py")
                if not candidate.is_file():
                    candidate = base.joinpath(*parts, "__init__.py")
                if candidate.is_file() and candidate not in sources:
                    sources.add(candidate)
                    pending.append(candidate)
                # Include real package initializer files up to the repo/source root.
                for index in range(1, len(parts)):
                    init = base.joinpath(*parts[:index], "__init__.py")
                    if init.is_file() and init not in sources:
                        sources.add(init)
                        pending.append(init)
    return {str(path): sha256(path) for path in sorted(sources)}


def create_freeze(config_path, review_path, validation_path, output_path):
    config = read_json(config_path)
    prerequisite = validate_prerequisites(config)
    source_map = runtime_sources()
    review = read_json(review_path)
    validation = read_json(validation_path)
    _assert(review.get("status") == config["required_review_status"] and review.get("configuration_freeze_blockers") == [],
            "independent actual-source/configuration approval is required")
    _assert(review.get("config_sha256") == sha256(config_path), "review did not approve this exact configuration")
    _assert(review.get("runtime_source_sha256") == source_map, "review did not approve these exact transitive sources")
    _assert(review.get("engineering_validation_sha256") == sha256(validation_path), "reviewed engineering record differs")
    _assert(validation.get("status") == "passed" and validation.get("engineering_only") is True,
            "completed engineering validation is required")
    _assert(validation.get("runtime_source_sha256") == source_map, "engineering validation applies to another runtime source")
    _assert(validation.get("config_sha256") == sha256(config_path), "engineering validation applies to another config")
    for path, digest in validation.get("evidence_sha256", {}).items():
        _assert(sha256(path) == digest, f"engineering evidence changed: {path}")
    for name in ("membership_and_sequential_quotient", "crossed_discovery_external_fallback",
                 "integer_arithmetic_and_loop_convention", "accounting_order_schema_and_edge_paths"):
        _assert(validation.get("fixture_groups", {}).get(name) == "passed", f"engineering fixture group incomplete: {name}")
    registry = read_json(config["data_registry"])
    data = {registry[name]["path"]: registry[name]["sha256"] for name in config["datasets"]}
    for path, digest in data.items():
        _assert(sha256(path) == digest, f"archived dataset changed: {path}")
    records = {str(config_path): sha256(config_path), str(review_path): sha256(review_path),
               str(validation_path): sha256(validation_path), config["data_registry"]: sha256(config["data_registry"]),
               config["processed_metadata"]: sha256(config["processed_metadata"]),
               **{entry["path"]: entry["sha256"] for entry in config["prerequisites"].values() if isinstance(entry, dict)},
               **{path: sha256(path) for path in config["design_paths"]}}
    ledger = expected_ledger(config)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    record = {"schema_version": SCHEMA, "status": "frozen_after_independent_actual_source_and_configuration_review",
              "created_at_utc": utc_now(), "source_commit": commit, "config_path": str(config_path),
              "config_sha256": sha256(config_path), "runtime_source_sha256": source_map,
              "original_v1_runtime_source_sha256": prerequisite["original"]["runtime_source_sha256"],
              "required_artifact_sha256": records, "archived_data_sha256": data,
              "archived_bank_identity": prerequisite["archived_bank_identity"],
              "expected_ledger": ledger, "expected_ledger_sha256": content_hash(ledger),
              "independent_review": {"path": str(review_path), "sha256": sha256(review_path), "status": review["status"]},
              "engineering_validation": {"path": str(validation_path), "sha256": sha256(validation_path)},
              "versions": versions(), "hardware": {"platform": platform.platform(), "machine": platform.machine(),
                                                       "cpu_count": os.cpu_count()},
              "performance_status_at_freeze": "no v2 public pilot or formal measurement executed",
              "scientific_novelty_or_venue_approval": False}
    write_once(output_path, record)
    return record


def validate_freeze(config_path, freeze_path, *, require_threads=True):
    freeze = read_json(freeze_path)
    config = read_json(config_path)
    validate_config(config)
    _assert(freeze.get("status") == "frozen_after_independent_actual_source_and_configuration_review", "unapproved freeze")
    _assert(freeze["config_sha256"] == sha256(config_path), "configuration changed after freeze")
    _assert(freeze["runtime_source_sha256"] == runtime_sources(), "runtime source changed after freeze")
    for field in ("required_artifact_sha256", "original_v1_runtime_source_sha256", "archived_data_sha256"):
        for path, digest in freeze[field].items():
            _assert(sha256(path) == digest, f"frozen artifact changed: {path}")
    for entry in freeze["archived_bank_identity"].values():
        _assert(sha256(entry["path"]) == entry["sha256"], "archived discovery/bank record changed")
    _assert(freeze["versions"] == versions(), "runtime/library versions differ from freeze")
    _assert(freeze["expected_ledger"] == expected_ledger(config)
            and freeze["expected_ledger_sha256"] == content_hash(freeze["expected_ledger"]), "expected execution ledger changed")
    if require_threads:
        _assert({name: os.getenv(name) for name in config["threads"]} == config["threads"], "single-thread environment not applied")
    # Verify imported local origin files, in addition to pathname byte identities.
    modules = []
    for path in freeze["runtime_source_sha256"]:
        if path.endswith(".py"):
            parts = Path(path).with_suffix("").parts
            if parts[0] == "src":
                parts = parts[1:]
            if parts[-1] == "__init__":
                parts = parts[:-1]
            modules.append(".".join(parts))
    for name in modules:
        module = importlib.import_module(name)
        origin = Path(module.__file__).resolve().relative_to(Path.cwd().resolve()).as_posix()
        _assert(origin in freeze["runtime_source_sha256"] and sha256(origin) == freeze["runtime_source_sha256"][origin],
                f"imported implementation origin differs from freeze: {name}")
    return config, freeze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--review", required=True)
    parser.add_argument("--validation", required=True)
    parser.add_argument("--output", default=str(NAMESPACE / "freeze.json"))
    args = parser.parse_args()
    record = create_freeze(args.config, args.review, args.validation, args.output)
    print(json.dumps({"path": args.output, "sha256": sha256(args.output), "counts": record["expected_ledger"]["counts"]}))


if __name__ == "__main__":
    main()
