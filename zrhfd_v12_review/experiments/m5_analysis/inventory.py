"""M5 immutable evidence inventory; no method imports or algorithm execution."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.archival import read_bytes, read_json

OFFICIAL_BYTES_SHA = "a485c3bc16b2799a8cec30d8795b2284c2718820e1254f76c88060bcbce7d98c"
OFFICIAL_SEMANTIC_SHA = "403474d726b7bfad36776b45b20a6f47299815e642992e294eed584806b4356f"
REAL = ("contact-high-school", "trivago-clicks")
METHODS = ("zr_hfd", "zh_prov", "hfd_no_volume", "hfd_oracle", "tlhfd_no_volume", "tlhfd_oracle", "clique_acl_no_volume", "clique_acl_oracle")
NUMERIC_FIELDS = ("F1", "precision", "recall", "Z_H", "Z_H_prov", "phi", "volume", "size", "components",
    "controller_wall_seconds", "worker_wall_seconds", "method_seconds", "input_load_seconds", "peak_sum_rss_bytes",
    "j_act", "j_star", "region_volume", "region_size", "touched_volume", "touched_vertices_count", "touched_over_output_volume",
    "LB_R", "gap", "native_process_count", "native_global_input_conversion_count", "native_kernel_seconds", "mass_count", "MM_steps")


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    path = Path(path)
    if not path.exists():
        return hashlib.sha256(read_bytes(path)).hexdigest()
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def project_path(relative):
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("Expected portable project-relative path")
    return ROOT / p


def eq(issues, key, actual, expected):
    if actual != expected:
        issues.append(key + ": differs or absent")


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def number(value):
    try:
        value = float(Fraction(value)) if isinstance(value, str) else float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def logical_files(directory):
    names = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file() and not p.name.endswith(".partial-archive")}
    index = directory / "ARCHIVE.json"
    if index.exists():
        names.update(read_json(index)["files"])
    return names


def storage_scope(verify_sources=False, historical_receipt=None):
    """Separate post-measurement scope; historical receipts are fixture-only.

    Original-path recovery is codec-independent. Scientific cohorts use the
    canonical current pointer; an explicitly supplied old receipt is permitted
    only by the artificial-fixture path in manifest_audit.
    """
    pointer_path = ROOT / "provenance/storage-wrapper-current.json"
    pointer = read_json(pointer_path) if historical_receipt is None else None
    name = pointer["receipt"] if pointer is not None else historical_receipt
    if not isinstance(name, str) or not re.fullmatch(r"provenance/storage_wrapper_v[0-9]{3}/receipt\.json", name):
        raise ValueError("Invalid portable storage receipt path")
    path = project_path(name)
    receipt_sha = digest(path)
    if pointer is not None and (set(pointer) != {"receipt", "receipt_sha256"} or receipt_sha != pointer["receipt_sha256"]):
        raise ValueError("Canonical storage pointer/receipt SHA mismatch")
    receipt = read_json(path)
    pins = receipt.get("source_sha256")
    if not isinstance(pins, dict) or set(pins) != {"experiments/archival.py", "experiments/run_m5_archived.py"} or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in pins.values()):
        raise ValueError("Storage receipt lacks exact source scope")
    if receipt.get("method_source_changed") is not False or receipt.get("measurement_receipt_times_unchanged") is not True:
        raise ValueError("Storage receipt does not preserve measurement scope")
    if verify_sources and pointer is not None:
        for source, expected in pins.items():
            if digest(project_path(source)) != expected:
                raise ValueError("Current storage source differs from receipt: " + source)
    return {"receipt": name, "receipt_sha256": receipt_sha, "source_sha256": pins,
            "canonical_pointer_sha256": digest(pointer_path) if pointer is not None else None,
            "historical_fixture_only": pointer is None, "current_sources_verified": verify_sources and pointer is not None}


def checked_reference_binding(run, reproduced_cohort=False, reference_binding=None, verify_files=False):
    if reproduced_cohort != (reference_binding is not None):
        raise ValueError("Fresh mode requires both --reproduced-cohort and --reference-binding")
    if not reproduced_cohort:
        return None
    from experiments.reproduction.cohort_binding import verify_reference_binding
    binding = verify_reference_binding(reference_binding, run_path=run, verify_files=verify_files)
    if binding.get("status") != "PASS" or binding.get("cohort_origin") != "FRESH_REPRODUCTION" or binding.get("reference", {}).get("manifest_sha256") != OFFICIAL_BYTES_SHA or binding.get("reference", {}).get("frozen_sha256") != OFFICIAL_SEMANTIC_SHA:
        raise ValueError("Fresh reference binding did not validate the official specification")
    if run.resolve() == ROOT / "results/m5/official_v12_001":
        raise ValueError("Fresh cohort cannot use the original official output directory")
    return binding


def validate_analysis_cohort(report, reproduced_cohort=False, reference_binding=None):
    """Recheck an inventory's cohort mode before summary or figure use."""
    origin = report.get("cohort_origin", "NONFORMAL_FIXTURE")
    if origin == "FRESH_REPRODUCTION":
        binding = checked_reference_binding(project_path(report["run"]), reproduced_cohort, reference_binding)
        if binding is None or binding["binding_receipt_sha256"] != report.get("reference_binding_sha256") or binding["fresh"]["manifest_sha256"] != report["manifest"]["manifest_sha256"] or binding["fresh"]["frozen_sha256"] != report["manifest"]["frozen_sha256"]:
            raise ValueError("Inventory differs from its fresh reference binding")
        return binding
    if reproduced_cohort or reference_binding is not None:
        raise ValueError("Reproduced flags cannot relabel an original or artificial analysis")
    if origin == "ORIGINAL_FROZEN_COHORT" and (report["manifest"]["manifest_sha256"] != OFFICIAL_BYTES_SHA or report["manifest"]["frozen_sha256"] != OFFICIAL_SEMANTIC_SHA):
        raise ValueError("Original M5 analysis differs from official pins")
    if origin not in ("ORIGINAL_FROZEN_COHORT", "NONFORMAL_FIXTURE"):
        raise ValueError("Unknown cohort origin")
    return None


def manifest_audit(run, verify_files=False, official=True, reproduced_cohort=False, reference_binding=None, historical_storage_receipt=None):
    manifest_path = run / "manifest.json"
    manifest = read_json(manifest_path)
    frozen = manifest["frozen"]
    issues = []
    semantic = hashlib.sha256(canonical(frozen)).hexdigest()
    eq(issues, "manifest.frozen_sha256", manifest.get("frozen_sha256"), semantic)
    binding = checked_reference_binding(run, reproduced_cohort, reference_binding, verify_files)
    if not official and (binding is not None or frozen.get("toy") is not True or frozen.get("formal_measurement") is not False or not run.resolve().is_relative_to(ROOT / "results/m5_analysis/fixtures")):
        raise ValueError("official=False is restricted to explicit artificial nonformal fixture directories")
    if historical_storage_receipt is not None and official:
        raise ValueError("Scientific cohorts require the canonical current storage scope")
    if official and binding is None:
        eq(issues, "official_manifest_bytes_sha256", digest(manifest_path), OFFICIAL_BYTES_SHA)
        eq(issues, "official_manifest_semantic_sha256", semantic, OFFICIAL_SEMANTIC_SHA)
        eq(issues, "official_planned_tasks", len(frozen["tasks"]), 11480)
        eq(issues, "official_source_count", len(frozen["source_pins"]), 35)
        eq(issues, "official_methods", frozen["configuration"]["methods"], list(METHODS))
        eq(issues, "official_toy", frozen.get("toy"), False)
    if binding is not None:
        eq(issues, "fresh_manifest_bytes_sha256", digest(manifest_path), binding["fresh"]["manifest_sha256"])
        eq(issues, "fresh_manifest_semantic_sha256", semantic, binding["fresh"]["frozen_sha256"])
        eq(issues, "reference_planned_tasks", len(frozen["tasks"]), 11480)
        eq(issues, "reference_source_count", len(frozen["source_pins"]), 35)
        eq(issues, "reference_methods", frozen["configuration"]["methods"], list(METHODS))
        eq(issues, "reference_toy", frozen.get("toy"), False)
    task_ids = [t["task_id"] for t in frozen["tasks"]]
    if len(task_ids) != len(set(task_ids)):
        issues.append("manifest contains duplicate task IDs")
    hashes = {}
    storage = storage_scope(verify_files, historical_storage_receipt)
    if binding is not None:
        expected_storage = binding["post_measurement_storage_scope"]
        eq(issues, "binding.storage_receipt", storage["receipt"], expected_storage["receipt"])
        eq(issues, "binding.storage_receipt_sha256", storage["receipt_sha256"], expected_storage["receipt_sha256"])
        eq(issues, "binding.storage_source_sha256", storage["source_sha256"], expected_storage["source_sha256"])
    if verify_files:
        for name, expected in frozen["source_pins"].items():
            path = run / manifest["source_snapshot_directory"] / name
            actual = digest(path)
            eq(issues, "source_snapshot:" + name, actual, expected)
            hashes[str(path.relative_to(ROOT))] = actual
        cfg_path = project_path(frozen["configuration_file"])
        eq(issues, "configuration_file_sha256", digest(cfg_path), frozen["configuration_sha256"])
        eq(issues, "configuration_file_contents", read_json(cfg_path), frozen["configuration"])
        for name, expected in sorted({t["input_path"]: t["input_sha256"] for t in frozen["tasks"]}.items()):
            path = project_path(name)
            actual = digest(path)
            eq(issues, "input:" + name, actual, expected)
            hashes[name] = actual
            data = read_json(path)
            for dataset in data.get("datasets", []):
                for item in dataset.get("raw_files", {}).values():
                    raw = project_path(item["path"])
                    actual_raw = digest(raw)
                    eq(issues, "raw_input:" + item["path"], actual_raw, item["sha256"])
                    hashes[item["path"]] = actual_raw
    return manifest, {"manifest_sha256": digest(manifest_path), "frozen_sha256": semantic,
        "source_snapshot_count": len(frozen["source_pins"]), "source_input_file_hashes_verified": verify_files,
        "storage_receipt": storage["receipt"], "storage_receipt_sha256": storage["receipt_sha256"], "storage_source_sha256": storage["source_sha256"],
        "storage_scope": storage, "cohort_origin": "FRESH_REPRODUCTION" if binding else "ORIGINAL_FROZEN_COHORT" if official else "NONFORMAL_FIXTURE",
        "reference_binding": binding,
        "verified_files": hashes, "issues": issues, "status": "FAIL" if issues else "PASS" if verify_files else "METADATA_ONLY"}


def validate_records(task, manifest, manifest_path, request, execution, receipt, worker=None, worker_sha=None, manifest_sha=None):
    """Pure static contract checker, also exercised by artificial fixtures."""
    f = manifest["frozen"]
    c = f["configuration"]
    issues = []
    eq(issues, "request.task", request.get("task"), task)
    eq(issues, "request.configuration", request.get("configuration"), c)
    eq(issues, "request.tl_backend", request.get("tl_backend"), f["tl_backend"])
    context = execution.get("source_context", {})
    eq(issues, "execution.context.manifest_path", context.get("manifest_path"), str(manifest_path.relative_to(ROOT)))
    eq(issues, "execution.context.manifest_file_sha256", context.get("manifest_file_sha256"), manifest_sha or digest(manifest_path))
    eq(issues, "execution.context.frozen_sha256", context.get("frozen_sha256"), manifest["frozen_sha256"])
    eq(issues, "execution.context.source_pins", context.get("source_pins"), f["source_pins"])
    eq(issues, "execution.context.dependencies", context.get("dependency_versions"), f["dependency_versions"])
    eq(issues, "execution.configuration_sha256", execution.get("configuration_sha256"), hashlib.sha256(canonical(c)).hexdigest())
    eq(issues, "execution.created_before_process_start", execution.get("created_before_process_start"), True)
    expected_threads = {key: "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "JULIA_NUM_THREADS")}
    eq(issues, "execution.thread_environment_overrides", execution.get("thread_environment_overrides"), expected_threads)
    eq(issues, "execution.working_directory", execution.get("working_directory"), str(ROOT))
    command = execution.get("actual_command", [])
    if len(command) != 4 or command[1:3] != ["experiments/m5/worker.py", "--request"]:
        issues.append("execution.actual_command: not the frozen worker interface")
    eq(issues, "receipt.task_id", receipt.get("task_id"), task["task_id"])
    eq(issues, "receipt.formal_measurement", receipt.get("formal_measurement"), not task["toy"])
    if receipt.get("status") not in ("COMPLETED", "FAILED", "PARTIAL_TIMEOUT", "PARTIAL_UPDATE_BUDGET", "TIMEOUT", "MEMORY_LIMIT", "INTERRUPTED", "ABANDONED_PREVIOUS_RUN"):
        issues.append("receipt.status: unknown terminal status")
    if "wall_budget_seconds" in receipt:
        eq(issues, "receipt.wall_budget", receipt["wall_budget_seconds"], c["budgets"]["wall_seconds_per_method_query"])
        eq(issues, "receipt.memory_budget", receipt.get("memory_budget_bytes"), c["budgets"]["memory_bytes"])
    if worker is not None:
        eq(issues, "receipt.worker_result_sha256", receipt.get("worker_result_sha256"), worker_sha)
        eq(issues, "worker.task", worker.get("task"), task)
        eq(issues, "worker.formal_measurement", worker.get("formal_measurement"), not task["toy"])
        if receipt.get("status") == "COMPLETED":
            eq(issues, "receipt.exit_code", receipt.get("exit_code"), 0)
            eq(issues, "worker.status", worker.get("status"), "COMPLETED")
            eq(issues, "receipt.worker_status", receipt.get("worker_status"), "COMPLETED")
            if not finite(receipt.get("wall_seconds")) or receipt["wall_seconds"] < 0:
                issues.append("receipt.wall_seconds: invalid completed time")
            if not finite(receipt.get("peak_sum_rss_bytes")) or receipt["peak_sum_rss_bytes"] < 0:
                issues.append("receipt.peak_sum_rss_bytes: invalid completed memory")
            metrics = worker.get("offline_metrics", {})
            for key in ("F1", "precision", "recall"):
                v = metrics.get(key)
                if not finite(v) or not 0 <= v <= 1:
                    issues.append("worker.metrics." + key + ": invalid completed value")
            eq(issues, "worker.metrics.evaluation_only_truth", metrics.get("evaluation_only_truth"), True)
            output = worker.get("output", {})
            vertices = output.get("vertices")
            if not isinstance(vertices, list) or any(type(v) is not int for v in vertices) or len(vertices) != len(set(vertices)):
                issues.append("worker.output.vertices: invalid")
            seed = task["query"]["seed_zero_based"]
            if isinstance(vertices, list):
                eq(issues, "worker.contains_seed", output.get("contains_seed"), seed in vertices)
                if task["method"].startswith("hfd_"):
                    eq(issues, "worker.native_author_seed_omission", output.get("native_author_seed_omission"), seed not in vertices)
                elif seed not in vertices:
                    issues.append("worker.seed: declared seeded method omitted seed")
            for key in ("worker_wall_seconds", "input_load_seconds"):
                if not finite(worker.get(key)) or worker[key] < 0:
                    issues.append("worker." + key + ": invalid completed time")
            if not finite(output.get("runtime_seconds")) or output["runtime_seconds"] < 0:
                issues.append("worker.output.runtime_seconds: invalid completed time")
            metadata = output.get("metadata", {})
            if task["method"] in ("zr_hfd", "zh_prov"):
                for key in ("LB_R", "gap"):
                    if not finite(output.get("certificate", {}).get(key)):
                        issues.append("worker.certificate." + key + ": invalid completed value")
            if task["method"] not in ("zr_hfd", "zh_prov") and "oracle" in metadata:
                eq(issues, "worker.metadata.oracle", metadata["oracle"], task["method"].endswith("_oracle"))
            if metadata.get("mass_grid_complete") is False or str(metadata.get("status", "")).startswith("PARTIAL"):
                issues.append("worker.metadata: incomplete grid labelled completed")
    elif receipt.get("status") == "COMPLETED":
        issues.append("Completed receipt without worker result")
    return issues


def task_row(task):
    query = task["query"]
    dataset = task["dataset"]
    mu = re.search(r"_mu(\d+)_seed", dataset)
    return {"task_id": task["task_id"], "dataset": dataset,
        "dataset_family": dataset if dataset in REAL else "HSBM", "cross_edge_fraction": int(mu[1]) / 100 if mu else None,
        "query_id": query["query_id"], "cluster_code": query["cluster_code"],
        "seed": query["seed_zero_based"], "method": task["method"], "oracle_setting": task["method"].endswith("_oracle"),
        "input_path": task["input_path"], "input_sha256": task["input_sha256"],
        "analysis_status": "NOT_RUN", "terminal_status": "NOT_RUN", "integrity_status": "NOT_APPLICABLE",
        "completed_budget_execution": False, "convergence_claim": False, "attempt_count": 0}


def extract_fields(row, worker, receipt):
    out = worker.get("output") or worker.get("partial_output") or {}
    metrics = worker.get("offline_metrics") or {}
    stats = out.get("stats") or {}
    cert = out.get("certificate") or {}
    meta = out.get("metadata") or {}
    costs = out.get("execution_cost_definition") or {}
    vertices = out.get("vertices")
    row.update({"F1": metrics.get("F1"), "precision": metrics.get("precision"), "recall": metrics.get("recall"),
        "Z_H_exact": metrics.get("Z_H_exact"), "Z_H_prov_exact": metrics.get("Z_H_prov_exact"),
        "Z_H": number(metrics.get("Z_H_exact", stats.get("Z_H"))), "Z_H_prov": number(metrics.get("Z_H_prov_exact", stats.get("Z_H_prov"))),
        "phi": metrics.get("hypergraph_conductance"), "volume_exact": metrics.get("volume_exact", stats.get("volume_exact")),
        "volume": number(metrics.get("volume_exact", stats.get("volume"))), "size": metrics.get("size", stats.get("size")),
        "components": metrics.get("components", out.get("components")), "truth_size": metrics.get("truth_size"), "truth_volume": metrics.get("truth_volume"),
        "controller_wall_seconds": receipt.get("wall_seconds"), "worker_wall_seconds": worker.get("worker_wall_seconds"),
        "method_seconds": out.get("runtime_seconds"), "input_load_seconds": worker.get("input_load_seconds"),
        "peak_sum_rss_bytes": receipt.get("peak_sum_rss_bytes"), "j_act": out.get("j_act"), "j_star": out.get("j_star"),
        "region_volume": out.get("region_volume"), "region_size": len(out["region_vertices"]) if isinstance(out.get("region_vertices"), list) else None,
        "touched_volume": out.get("touched_volume"), "touched_vertices_count": len(out["touched_vertices"]) if isinstance(out.get("touched_vertices"), list) else None,
        "touched_definition": meta.get("touched_definition", "diffusion support union region; not total implementation I/O" if row["method"] in ("zr_hfd", "zh_prov") else "UNKNOWN"),
        "LB_R": cert.get("LB_R"), "LB_R_upper": cert.get("LB_R_upper"), "LB_R_lower_exact": cert.get("LB_R_lower_exact"),
        "gap": cert.get("gap"), "gap_exact": cert.get("gap_using_rational_lower_exact"), "certificate_status": cert.get("certificate_status"),
        "LB_R_target_precision_met": cert.get("LB_R_target_precision_met"), "LB_R_width_exact": cert.get("LB_R_width_exact"),
        "hull_vertices_count": len(cert["hull_vertices"]) if isinstance(cert.get("hull_vertices"), list) else None,
        "hull_best_Z_exact": cert.get("hull_best_Z_exact"), "certificate_mincut_calls": cert.get("mincut_calls"),
        "native_process_count": costs.get("native_process_count"), "native_global_input_conversion_count": costs.get("native_global_input_conversion_count"),
        "native_kernel_seconds": costs.get("native_kernel_seconds_total", meta.get("kernel_seconds_total")),
        "global_topology_loaded": costs.get("global_topology_loaded", True), "native_global_diffusion_scans": costs.get("global_native_diffusion_scans"),
        "mass_count": len(out.get("mass_sequence", meta.get("mass_grid", []))), "MM_steps": len(out.get("mm_trace", [])),
        "stop_reason": out.get("stop_reason", meta.get("stop")), "numeric_solver_status": out.get("numeric_solver_status", meta.get("objective")),
        "contains_seed": out.get("contains_seed"), "native_author_seed_omission": out.get("native_author_seed_omission"),
        "update_count": meta.get("update_count"), "mass_grid_complete": meta.get("mass_grid_complete"),
        "trial_count": len(meta.get("trials", [])), "selection": meta.get("selection"), "scope_gate": out.get("scope_gate", worker.get("scope"))})
    if row["method"].startswith("hfd_") and meta.get("execution"):
        row["native_process_count"] = 1
        row["native_global_input_conversion_count"] = 1
        row["native_global_diffusion_scans"] = True
    row["touched_over_output_volume"] = row["touched_volume"] / row["volume"] if row["touched_volume"] is not None and row["volume"] and row["volume"] > 0 else None
    if isinstance(vertices, list):
        row["output_vertices_sha256"] = hashlib.sha256(canonical(vertices)).hexdigest()
    return row


def inspect_attempt(directory, task, manifest, run, verify_archives=False, manifest_sha=None, storage_source_sha256=None):
    issues = []
    names = logical_files(directory)
    hashes = {}
    if "ARCHIVE.json" in names:
        index = read_json(directory / "ARCHIVE.json")
        expected_storage = storage_source_sha256 or storage_scope()["source_sha256"]
        eq(issues, "archive.storage_source_sha256", index.get("storage_source_sha256"), expected_storage)
        if verify_archives:
            from experiments.archival import verify_archive
            verify_archive(directory, index, cleanup_expanded=False)
        hashes.update({name: item["sha256"] for name, item in index["files"].items()})
    for name in ("request.json", "execution_request.json", "receipt.json", "process_started.json"):
        if name in names:
            hashes[name] = digest(directory / name)
    info = {"attempt": str(directory.relative_to(ROOT)), "task_id": task["task_id"],
        "logical_file_count": len(names), "archive_present": "ARCHIVE.json" in names,
        "archive_members_verified": verify_archives if "ARCHIVE.json" in names else None,
        "status": "UNFINISHED", "integrity_issues": issues, "file_sha256": hashes}
    request = read_json(directory / "request.json")
    eq(issues, "request.task", request.get("task"), task)
    eq(issues, "request.configuration", request.get("configuration"), manifest["frozen"]["configuration"])
    eq(issues, "request.tl_backend", request.get("tl_backend"), manifest["frozen"]["tl_backend"])
    if "receipt.json" not in names:
        info["logical_file_names"] = sorted(names)
        info["integrity_status"] = "FAIL" if issues else "PASS_AVAILABLE_UNFINISHED"
        return info, None, None
    receipt = read_json(directory / "receipt.json")
    info["status"] = receipt["status"]
    worker = None
    file_inventory = {}
    archive_index = read_json(directory / "ARCHIVE.json") if "ARCHIVE.json" in names else {}
    for name in sorted(names):
        archived = archive_index.get("files", {}).get(name)
        path = directory / name
        if archived:
            file_inventory[name] = {**archived, "storage": "ARCHIVE_MEMBER"}
        else:
            file_inventory[name] = {"bytes": path.stat().st_size, "storage": "PLAIN"}
            if verify_archives or name in hashes:
                actual = hashes.get(name) or digest(path)
                hashes[name] = actual
                file_inventory[name]["sha256"] = actual
    info["logical_file_inventory"] = file_inventory
    if "worker_result.json" in names:
        worker_sha = hashes.get("worker_result.json") or digest(directory / "worker_result.json")
        hashes["worker_result.json"] = worker_sha
        eq(issues, "receipt.worker_result_sha256", receipt.get("worker_result_sha256"), worker_sha)
        # Always resolve this original path through the stable archive reader.
        try:
            worker = read_json(directory / "worker_result.json")
            if not isinstance(worker, dict):
                raise ValueError("Worker payload is not a dictionary")
        except (ValueError, UnicodeDecodeError) as error:
            worker = None
            info["worker_payload_parse_error"] = repr(error)
            if receipt.get("status") == "COMPLETED":
                issues.append("Completed receipt with malformed worker payload")
            else:
                info["failed_payload_retained_without_quality"] = True
    else:
        worker_sha = None
    if receipt.get("status") == "ABANDONED_PREVIOUS_RUN":
        eq(issues, "abandoned.task_id", receipt.get("task_id"), task["task_id"])
        info["abandoned_incomplete_execution_context"] = True
    else:
        execution = read_json(directory / "execution_request.json")
        issues.extend(validate_records(task, manifest, run / "manifest.json", request, execution, receipt, worker, worker_sha, manifest_sha))
        command = execution.get("actual_command", [])
        if len(command) == 4:
            eq(issues, "execution.request_path", str(Path(command[3]).resolve()), str((directory / "request.json").resolve()))
        if "process_started.json" not in names and receipt.get("failure_reason") != "PROCESS_START_FAILED":
            issues.append("Terminal execution lacks process_started record")
    # Native command/stream hashes can be validated even when the method failed.
    native = []
    driver_pin = manifest["frozen"]["source_pins"].get("zrhfd/baselines/native_driver.jl")
    for name in sorted(n for n in names if n.startswith("native_logs/") and n.endswith("/execution.json")):
        record = read_json(directory / name)
        eq(issues, name + ":driver_sha256", record.get("driver_sha256"), driver_pin)
        command = record.get("actual_command", [])
        if len(command) != 17 or Path(command[4]).name != "native_driver.jl" or command[5] != "hfd_hyper":
            issues.append(name + ": unexpected author invocation")
        else:
            eq(issues, name + ":julia_path", command[0], str(ROOT / "external/runtime/julia-1.10.10/bin/julia"))
            eq(issues, name + ":startup", command[1], "--startup-file=no")
            eq(issues, name + ":threads", command[2], "--threads=1")
            eq(issues, name + ":environment", command[3], "--project=" + str(ROOT / "external/runtime/hfd-environment"))
            eq(issues, name + ":driver_path", command[4], str(ROOT / "zrhfd/baselines/native_driver.jl"))
            eq(issues, name + ":author_path", command[6], str(ROOT / "external/hfd"))
            eq(issues, name + ":seed", command[9], str(task["query"]["seed_zero_based"]))
            eq(issues, name + ":sigma", number(command[10]), manifest["frozen"]["configuration"]["common_baseline"]["sigma"])
            c = manifest["frozen"]["configuration"]
            iterations = c["zr"]["native_iterations"] if task["method"] in ("zr_hfd", "zh_prov") else c["hfd"]["iterations"]
            eq(issues, name + ":iterations", number(command[11]), iterations)
            eq(issues, name + ":p", command[12], "2")
            eq(issues, name + ":rngseed", command[14], "73")
        source_files = record.get("sources", {}).get("files", {})
        eq(issues, name + ":author_file_inventory", set(source_files), {"ucHFD.jl", "utils.jl", "struct.jl"})
        for filename, native_hash in source_files.items():
            eq(issues, name + ":source:" + filename, native_hash, manifest["frozen"]["source_pins"].get("external/hfd/" + filename))
        if not record.get("input_edge_csv_sha256"):
            issues.append(name + ": missing conversion input hash")
        for stream in ("stdout", "stderr"):
            relative = record.get(stream + "_path")
            if not relative:
                issues.append(name + ": missing " + stream + " path")
                continue
            path = project_path(relative)
            if not path.is_relative_to(directory):
                issues.append(name + ": stream path leaves attempt")
                continue
            local = str(path.relative_to(directory))
            if local not in names:
                issues.append(name + ": missing logical " + stream)
            elif record.get(stream + "_sha256"):
                actual = hashes.get(local) or digest(path)
                hashes[local] = actual
                eq(issues, name + ":" + stream + "_sha256", actual, record[stream + "_sha256"])
        native.append({"path": name, "status": record.get("status"), "driver_sha256": record.get("driver_sha256"),
            "input_edge_csv_sha256": record.get("input_edge_csv_sha256"), "subprocess_wall_seconds": record.get("subprocess_wall_seconds")})
    info["native_invocations"] = native
    info["integrity_status"] = "FAIL" if issues else "PASS"
    return info, worker, receipt


def inventory(run, verify_files=False, official=True, reproduced_cohort=False, reference_binding=None, historical_storage_receipt=None):
    manifest, audit = manifest_audit(run, verify_files, official, reproduced_cohort, reference_binding, historical_storage_receipt)
    planned, attempts, errors = [], [], []
    task_ids = {t["task_id"] for t in manifest["frozen"]["tasks"]}
    query_root = run / "queries"
    extra = sorted(p.name for p in query_root.iterdir() if p.is_dir() and p.name not in task_ids) if query_root.exists() else []
    if extra:
        errors.append({"unplanned_task_directories": extra})
    for task in manifest["frozen"]["tasks"]:
        row = task_row(task)
        directories = sorted((query_root / task["task_id"]).glob("attempt_*"))
        row["attempt_count"] = len(directories)
        for directory in directories:
            try:
                info, worker, receipt = inspect_attempt(directory, task, manifest, run, verify_files, audit["manifest_sha256"], audit["storage_source_sha256"])
                attempts.append(info)
                if info["integrity_issues"]:
                    errors.append({"attempt": info["attempt"], "issues": info["integrity_issues"]})
                if directory == directories[-1]:
                    row.update(attempt=info["attempt"], terminal_status=info["status"], integrity_status=info["integrity_status"],
                        worker_result_sha256=info["file_sha256"].get("worker_result.json"), archived=info["archive_present"],
                        analysis_status="INTEGRITY_FAIL" if info["integrity_issues"] else info["status"],
                        completed_budget_execution=bool(receipt and receipt["status"] == "COMPLETED" and not info["integrity_issues"]))
                    if receipt:
                        row.update(failure_reason=receipt.get("failure_reason"), exit_code=receipt.get("exit_code"),
                            controller_wall_seconds=receipt.get("wall_seconds"), peak_sum_rss_bytes=receipt.get("peak_sum_rss_bytes"),
                            partial_progress_events=receipt.get("partial_progress_events"))
                    if worker:
                        extract_fields(row, worker, receipt or {})
            except Exception as error:
                try:
                    raw_terminal = read_json(directory / "receipt.json").get("status", "UNKNOWN")
                except Exception:
                    raw_terminal = "UNPARSEABLE_OR_ABSENT"
                info = {"attempt": str(directory.relative_to(ROOT)), "task_id": task["task_id"], "status": "INTEGRITY_FAIL",
                    "terminal_status_original": raw_terminal, "integrity_issues": [repr(error)], "integrity_status": "FAIL"}
                attempts.append(info); errors.append(info)
                if directory == directories[-1]:
                    row.update(attempt=info["attempt"], analysis_status="INTEGRITY_FAIL", integrity_status="FAIL", terminal_status=raw_terminal)
        planned.append(row)
    counts = Counter(r["analysis_status"] for r in planned)
    binding = audit.get("reference_binding")
    report = {"schema_version": 1, "created_utc": utc(), "run": str(run.relative_to(ROOT)),
        "cohort_origin": audit["cohort_origin"], "reference_binding_sha256": binding["binding_receipt_sha256"] if binding else None,
        "manifest": audit, "planned_tasks": len(planned), "observed_attempts": len(attempts),
        "status_counts": dict(counts), "integrity_errors": errors,
        "integrity_status": "FAIL" if audit["issues"] or errors else audit["status"],
        "source_sha256": {"experiments/m5_analysis/inventory.py": digest(__file__), "experiments/archival.py": digest(ROOT / "experiments/archival.py")},
        "selected_attempt_policy": "Latest attempt per frozen task; every previous attempt remains in attempt_inventory.json",
        "quality_policy": "Only COMPLETED terminal + valid completed worker; budget completion is not convergence",
        "metadata_only_limitation": None if verify_files else "No source/input/archive-byte verification; not approved for final quality/cost claims"}
    return report, planned, attempts


def csv_write(path, rows, fields=None):
    fields = fields or sorted({key for row in rows for key in row})
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def write_inventory(output, report, rows, attempts):
    if report.get("cohort_origin") == "FRESH_REPRODUCTION" and output.resolve() == ROOT / "results/m5_analysis/official_v12_001":
        raise ValueError("Fresh inventory cannot overwrite original official analysis")
    output.mkdir(parents=True, exist_ok=True)
    csv_write(output / "query_results.csv", rows, sorted({key for row in rows for key in row} | set(NUMERIC_FIELDS)))
    csv_write(output / "attempt_inventory.csv", [{k: v for k, v in a.items() if k not in ("native_invocations", "logical_file_inventory", "logical_file_names")} for a in attempts], ["task_id", "attempt", "status", "terminal_status_original", "integrity_status", "archive_present", "archive_members_verified", "logical_file_count", "integrity_issues", "file_sha256", "abandoned_incomplete_execution_context", "worker_payload_parse_error", "failed_payload_retained_without_quality"])
    (output / "attempt_inventory.json").write_text(json.dumps(attempts, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    (output / "query_results.json").write_text(json.dumps(rows, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n")
    report["artifact_sha256"] = {name: digest(output / name) for name in ("query_results.csv", "query_results.json", "attempt_inventory.csv", "attempt_inventory.json")}
    (output / "inventory.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="results/m5/official_v12_001")
    parser.add_argument("--output", default="results/m5_analysis/official_v12_001")
    parser.add_argument("--verify-files", action="store_true", help="Hash immutable snapshots/config/input and verify archived bytes; run in offline analysis window")
    parser.add_argument("--reproduced-cohort", action="store_true", help="Explicit fresh reference-bound cohort; original official mode stays strict")
    parser.add_argument("--reference-binding", help="Verified fresh binding receipt, paired with --reproduced-cohort")
    args = parser.parse_args()
    run, output = project_path(args.run), project_path(args.output)
    if not output.is_relative_to(ROOT / "results/m5_analysis"):
        parser.error("Analysis writes must stay in results/m5_analysis")
    if args.reproduced_cohort != bool(args.reference_binding):
        parser.error("Both --reproduced-cohort and --reference-binding are required for fresh mode")
    if args.reproduced_cohort and output.resolve() == ROOT / "results/m5_analysis/official_v12_001":
        parser.error("Fresh analysis cannot overwrite the original official directory")
    report, rows, attempts = inventory(run, args.verify_files, official=True, reproduced_cohort=args.reproduced_cohort,
                                     reference_binding=project_path(args.reference_binding) if args.reference_binding else None)
    write_inventory(output, report, rows, attempts)
    print(json.dumps({"planned": len(rows), "attempts": len(attempts), "status_counts": report["status_counts"], "integrity": report["integrity_status"]}))
    return 1 if report["integrity_status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
