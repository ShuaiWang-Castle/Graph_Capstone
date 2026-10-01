"""Stdlib artificial contract fixtures; no algorithm/NumPy/plot execution."""
import ast
import copy
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventory import ROOT, canonical, digest, task_row, validate_records
from summarize import gate_g_e4, panel_summary, summarize
from plot_quality_cost import point_records


def main():
    records = []
    def check(name, condition, details=None):
        records.append({"name": name, "passed": bool(condition), "details": details})
    for path in sorted((ROOT / "experiments/m5_analysis").glob("*.py")):
        ast.parse(path.read_text())
        check("syntax:" + path.name, True)
    task = {"task_id": "q0__zr_hfd", "dataset": "contact-high-school", "method": "zr_hfd", "input_path": "data/fixture.json", "input_sha256": "input",
            "query": {"query_id": "q0", "cluster_code": "A", "seed_zero_based": 0}, "toy": False}
    cfg = {"budgets": {"wall_seconds_per_method_query": 600, "memory_bytes": 12000000000}}
    frozen = {"configuration": cfg, "tl_backend": "numba", "source_pins": {"code.py": "code"}, "dependency_versions": {"numpy": "frozen"}}
    manifest = {"frozen": frozen, "frozen_sha256": "semantic"}
    path = ROOT / "results/m5_analysis/static_fixture_manifest.json"
    request = {"task": task, "configuration": cfg, "tl_backend": "numba"}
    execution = {"actual_command": ["python", "experiments/m5/worker.py", "--request", "request.json"], "created_before_process_start": True,
        "working_directory": str(ROOT), "thread_environment_overrides": {key: "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "JULIA_NUM_THREADS")},
        "configuration_sha256": hashlib.sha256(canonical(cfg)).hexdigest(), "source_context": {"manifest_path": str(path.relative_to(ROOT)), "manifest_file_sha256": "bytes",
        "frozen_sha256": "semantic", "source_pins": frozen["source_pins"], "dependency_versions": frozen["dependency_versions"]}}
    receipt = {"task_id": task["task_id"], "formal_measurement": True, "status": "COMPLETED", "worker_status": "COMPLETED", "exit_code": 0,
        "wall_seconds": 2., "peak_sum_rss_bytes": 10000, "worker_result_sha256": "result", "wall_budget_seconds": 600, "memory_budget_bytes": 12000000000}
    worker = {"task": task, "formal_measurement": True, "status": "COMPLETED", "worker_wall_seconds": 1.5, "input_load_seconds": .1,
        "offline_metrics": {"F1": .5, "precision": .5, "recall": .5, "evaluation_only_truth": True},
        "output": {"vertices": [0], "contains_seed": True, "runtime_seconds": 1., "certificate": {"LB_R": 0., "gap": .1}}}
    def validate(r=request, e=execution, c=receipt, w=worker, t=task):
        return validate_records(t, manifest, path, r, e, c, w, "result", "bytes")
    check("valid_completed_contract", not validate())
    for name, kind, route, value in [
        ("wrong_request_task", "r", ("task", "task_id"), "wrong"),
        ("wrong_configuration", "r", ("configuration",), {}),
        ("switched_backend", "r", ("tl_backend",), "pure_python"),
        ("wrong_manifest_bytes", "e", ("source_context", "manifest_file_sha256"), "old"),
        ("wrong_semantic_source", "e", ("source_context", "frozen_sha256"), "old"),
        ("wrong_source_pins", "e", ("source_context", "source_pins"), {}),
        ("wrong_dependencies", "e", ("source_context", "dependency_versions"), {}),
        ("wrong_execution_configuration", "e", ("configuration_sha256",), "old"),
        ("wrong_worker_command", "e", ("actual_command",), ["python", "wrong.py", "--request", "r"]),
        ("missing_prestart_marker", "e", ("created_before_process_start",), False),
        ("wrong_thread_count", "e", ("thread_environment_overrides", "OPENBLAS_NUM_THREADS"), "2"),
        ("wrong_working_directory", "e", ("working_directory",), "wrong"),
        ("wrong_receipt_task", "c", ("task_id",), "wrong"),
        ("nonzero_completed_exit", "c", ("exit_code",), 1),
        ("wrong_result_hash", "c", ("worker_result_sha256",), "old"),
        ("wrong_budget", "c", ("wall_budget_seconds",), 60),
        ("wrong_worker_task", "w", ("task", "task_id"), "wrong"),
        ("toy_relabelled_formal", "w", ("formal_measurement",), False),
        ("partial_relabelled_completed", "w", ("status",), "PARTIAL_TIMEOUT"),
        ("nonfinite_F1", "w", ("offline_metrics", "F1"), float("nan")),
        ("invalid_recall", "w", ("offline_metrics", "recall"), 1.1),
        ("truth_flag_missing", "w", ("offline_metrics", "evaluation_only_truth"), False),
        ("seed_omission_primary", "w", ("output", "vertices"), [1]),
        ("nonfinite_runtime", "w", ("output", "runtime_seconds"), float("inf")),
        ("nonfinite_certificate", "w", ("output", "certificate", "LB_R"), float("nan")),
        ("incomplete_grid", "w", ("output", "metadata"), {"mass_grid_complete": False})]:
        changed = {"r": copy.deepcopy(request), "e": copy.deepcopy(execution), "c": copy.deepcopy(receipt), "w": copy.deepcopy(worker)}
        target = changed[kind]
        for field in route[:-1]:
            target = target[field]
        target[route[-1]] = value
        issues = validate(**changed)
        check("reject:" + name, bool(issues), issues)
    hfd_task = copy.deepcopy(task); hfd_task["method"] = "hfd_no_volume"; hfd_task["task_id"] = "q0__hfd_no_volume"
    hr, hc, hw = copy.deepcopy(request), copy.deepcopy(receipt), copy.deepcopy(worker)
    hr["task"] = hfd_task; hc["task_id"] = hfd_task["task_id"]; hw["task"] = hfd_task
    hw["output"].update(vertices=[1], contains_seed=False, native_author_seed_omission=True)
    check("original_HFD_seed_omission_retained", not validate(hr, execution, hc, hw, hfd_task))
    empty_rows = [task_row(task)]
    empty = summarize({"manifest": {"manifest_sha256": "fixture", "frozen_sha256": "fixture"}, "integrity_status": "PASS"}, empty_rows)
    check("zero_actual_results_NOT_RUN", empty["status"] == "NOT_RUN" and empty["G_E4"]["status"] == "NOT_RUN" and not point_records(empty))
    def rows_for(dataset, main_f1, hfd_f1, complete=True, oracle_f1=None):
        out = []
        pairs = [("zr_hfd", main_f1), ("hfd_no_volume", hfd_f1)]
        if oracle_f1 is not None:
            pairs.append(("hfd_oracle", oracle_f1))
        query = {**task["query"], "query_id": dataset + ("_complete" if complete else "_partial")}
        for method, f1 in pairs:
            row = task_row({**task, "query": query, "dataset": dataset, "method": method, "task_id": dataset + "__" + method})
            row.update(F1=f1, integrity_status="PASS", completed_budget_execution=complete, analysis_status="COMPLETED" if complete else "TIMEOUT")
            out.append(row)
        return out
    passrows = rows_for("contact-high-school", .7, .6, oracle_f1=.8)
    check("G_E4_at_least_one_full_real_dataset", gate_g_e4(passrows, "PASS")["status"] == "PASS")
    check("G_E4_partial_not_scored", gate_g_e4(rows_for("contact-high-school", 1., 0., False), "PASS")["status"] == "NOT_RUN")
    check("G_E4_integrity_required", gate_g_e4(passrows, "FAIL")["status"] == "NOT_RUN")
    failrows = rows_for("contact-high-school", .3, .5, oracle_f1=.8) + rows_for("trivago-clicks", .3, .5, oracle_f1=.8)
    check("G_E4_all_complete_real_fail", gate_g_e4(failrows, "PASS")["status"] == "FAIL")
    check("G_E4_one_fail_other_unrun", gate_g_e4(failrows[:3], "PASS")["status"] == "NOT_RUN")
    incomplete_reference = gate_g_e4(rows_for("contact-high-school", .7, .6), "PASS")
    check("G_E4_comparison_PASS_reference_incomplete", incomplete_reference["status"] == "NOT_RUN" and incomplete_reference["datasets"]["contact-high-school"]["quality_comparison_status"] == "PASS" and incomplete_reference["datasets"]["contact-high-school"]["oracle_reference_status"] == "REFERENCE_INCOMPLETE")
    failed_reference = gate_g_e4(rows_for("contact-high-school", .3, .5), "PASS")
    check("G_E4_comparison_FAIL_remains_visible", failed_reference["status"] == "NOT_RUN" and failed_reference["datasets"]["contact-high-school"]["quality_comparison_status"] == "FAIL")
    panel = panel_summary(passrows + rows_for("contact-high-school", .2, .9, False))
    check("partial_denominator_not_imputed", panel["methods"]["zr_hfd"]["planned"] == 2 and panel["methods"]["zr_hfd"]["completed_budget"] == 1 and panel["methods"]["zr_hfd"]["completed_only"]["F1"]["median"] == .7)
    check("no_numeric_or_plot_library_import", not any(name in sys.modules for name in ("numpy", "matplotlib", "scipy", "numba")))
    result = {"status": "PASS" if all(r["passed"] for r in records) else "FAIL", "checks": records,
        "scope": "Artificial static fixtures only; no actual quality, bootstrap, plot or algorithm run",
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / "experiments/m5_analysis").glob("*.py"))}}
    path = ROOT / "reviews/m5_analysis/static_contract_receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "checks": len(records), "failed": [r["name"] for r in records if not r["passed"]]}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
