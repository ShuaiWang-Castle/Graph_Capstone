"""Tiny artificial file/archive integration fixture; never runs a worker.

All fixture data are artificial, nonformal and confined to results/m5_analysis.
Only stdlib plus the stable storage reader/writer are imported.
"""
import copy
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventory import ROOT, canonical, digest, inventory, write_inventory
from experiments.archival import archive_completed_attempt


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = canonical(value)
    if path.exists():
        if path.read_bytes() != text:
            raise RuntimeError("Existing artificial fixture differs: " + str(path))
    else:
        path.write_bytes(text)


def main():
    # Preserve v001/v002 snapshots; changing analysis/storage source creates a
    # separately identified artificial fixture rather than overwriting a pin.
    run = ROOT / "results/m5_analysis/fixtures/storage_contract_v003"
    cfg = {"budgets": {"wall_seconds_per_method_query": 600, "memory_bytes": 12000000000}, "methods": ["tlhfd_no_volume"],
           "common_baseline": {"sigma": .0001}, "hfd": {"iterations": 50}}
    configuration = str((run / "config.json").relative_to(ROOT))
    save(run / "config.json", cfg)
    save(run / "input.json", {"purpose": "ARTIFICIAL_SCHEMA_FIXTURE_NOT_A_MEASUREMENT"})
    input_path = str((run / "input.json").relative_to(ROOT))
    tasks = []
    for index, status in enumerate(("COMPLETED", "TIMEOUT", "FAILED", "FAILED_INVALID_JSON")):
        query = {"query_id": "artificial" + str(index), "cluster_code": "fixture", "seed_zero_based": 0}
        tasks.append({"task_id": query["query_id"] + "__tlhfd_no_volume", "query": query, "dataset": "ARTIFICIAL_SCHEMA_FIXTURE",
            "method": "tlhfd_no_volume", "toy": True, "input_path": input_path, "input_sha256": digest(run / "input.json")})
    source = "experiments/m5_analysis/inventory.py"
    snapshot = run / "sources" / source
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes((ROOT / source).read_bytes())
    frozen = {"configuration": cfg, "configuration_file": configuration, "configuration_sha256": digest(run / "config.json"),
              "source_pins": {source: digest(snapshot)}, "dependency_versions": {}, "tl_backend": "numba", "toy": True,
              "formal_measurement": False, "tasks": tasks}
    manifest = {"frozen": frozen, "frozen_sha256": hashlib.sha256(canonical(frozen)).hexdigest(), "source_snapshot_directory": "sources"}
    save(run / "manifest.json", manifest)
    for index, task in enumerate(tasks):
        directory = run / "queries" / task["task_id"] / "attempt_000"
        request_path = directory / "request.json"
        save(request_path, {"task": task, "configuration": cfg, "tl_backend": "numba"})
        context = {"manifest_path": str((run / "manifest.json").relative_to(ROOT)), "manifest_file_sha256": digest(run / "manifest.json"),
                   "frozen_sha256": manifest["frozen_sha256"], "source_pins": frozen["source_pins"], "dependency_versions": {}}
        save(directory / "execution_request.json", {"actual_command": ["python", "experiments/m5/worker.py", "--request", str(request_path)],
            "working_directory": str(ROOT), "thread_environment_overrides": {key: "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "JULIA_NUM_THREADS")},
            "source_context": context, "configuration_sha256": hashlib.sha256(canonical(cfg)).hexdigest(), "created_before_process_start": True})
        save(directory / "process_started.json", {"purpose": "ARTIFICIAL_NO_PROCESS_STARTED"})
        worker = {"task": task, "status": "COMPLETED", "formal_measurement": False, "worker_wall_seconds": 1.5, "input_load_seconds": .1,
            "offline_metrics": {"F1": .6, "precision": .6, "recall": .6, "evaluation_only_truth": True},
            "output": {"vertices": [0], "contains_seed": True, "runtime_seconds": 1., "metadata": {"oracle": False, "mass_grid_complete": True}}}
        result_path = directory / "worker_result.json"
        if index == 3:
            result_path.write_bytes(b"{intentionally malformed artificial failed payload")
        else:
            save(result_path, worker)
        status = "COMPLETED" if index == 0 else "TIMEOUT" if index == 1 else "FAILED"
        save(directory / "receipt.json", {"task_id": task["task_id"], "status": status, "formal_measurement": False,
            "worker_status": "COMPLETED" if index != 3 else None, "exit_code": 0 if index == 0 else -9 if index == 1 else 1,
            "wall_seconds": 2., "peak_sum_rss_bytes": 1000, "wall_budget_seconds": 600, "memory_budget_bytes": 12000000000,
            "worker_result_sha256": digest(result_path), "failure_reason": None if index == 0 else "NONZERO_EXIT_CODE"})
        if index in (0, 3):
            archive_completed_attempt(directory)
    report, rows, attempts = inventory(run, verify_files=True, official=False)
    checks = [
        {"name": "all_four_artificial_attempts_inventory", "passed": len(rows) == len(attempts) == 4},
        {"name": "only_terminal_completed_in_completed_table", "passed": sum(r["completed_budget_execution"] for r in rows) == 1},
        {"name": "archived_completed_original_path_read", "passed": rows[0].get("archived") is True and rows[0]["F1"] == .6},
        {"name": "timeout_raw_COMPLETED_not_promoted", "passed": rows[1]["analysis_status"] == "TIMEOUT" and not rows[1]["completed_budget_execution"]},
        {"name": "nonzero_raw_COMPLETED_not_promoted", "passed": rows[2]["analysis_status"] == "FAILED" and not rows[2]["completed_budget_execution"]},
        {"name": "malformed_failed_bytes_retained_no_quality", "passed": rows[3]["analysis_status"] == "FAILED" and rows[3].get("F1") is None and attempts[3].get("failed_payload_retained_without_quality") is True},
        {"name": "archive_and_snapshot_integrity_PASS", "passed": report["integrity_status"] == "PASS"},
        {"name": "no_numerical_or_plot_import", "passed": not any(p in sys.modules for p in ("numpy", "scipy", "numba", "matplotlib"))},
    ]
    receipt = {"status": "PASS" if all(c["passed"] for c in checks) else "FAIL", "checks": checks,
               "scope": "Artificial nonformal file fixtures only; no algorithms, worker process, bootstrap, or figure",
               "analysis_source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / "experiments/m5_analysis").glob("*.py"))},
               "fixture_manifest_sha256": digest(run / "manifest.json"), "fixture_inventory_status": report["integrity_status"]}
    path = ROOT / "reviews/m5_analysis/storage_contract_receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "checks": len(checks), "failed": [c["name"] for c in checks if not c["passed"]]}))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
