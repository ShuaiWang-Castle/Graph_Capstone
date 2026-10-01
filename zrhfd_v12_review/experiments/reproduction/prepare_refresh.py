"""Read source text and prepare a lock-refresh inventory; never refresh the lock.

Stdlib only. No input graph, raw result, ZIP, algorithm module, or setup is read
or executed. AST inspection checks the declared entry interfaces without imports.
"""
from pathlib import Path
import argparse
import ast
import datetime
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    lock_path = root / "experiments/reproduction/lock.json"
    lock = json.loads(lock_path.read_text())
    stage_paths = {"experiments/build.py", "experiments/run_m2.py", "experiments/summarize_m2.py",
                   "experiments/summarize_m4.py", "experiments/bootstrap_statistics.py",
                   "experiments/region_decision.py", "data/external/acquire_benson.py",
                   "experiments/plot_m4.py", "experiments/plot_m6.py", "experiments/apfs_storage.py",
                   "experiments/run_m6_compressed.py", "experiments/serial_workflow.py", "experiments/resume_workflow.py", "experiments/stage_barrier.py", "experiments/storage_guard.py"}
    for directory in ("experiments/m0_reference", "tests/m1_independent", "experiments/data_generation",
                      "experiments/baseline_integration", "experiments/m5_analysis", "experiments/m6_analysis", "experiments/diagnostics"):
        stage_paths.update(str(p.relative_to(root)) for p in (root / directory).glob("*")
                           if p.is_file() and p.suffix in (".py", ".json"))
    if not {"experiments/diagnostics/gated_m4.py", "experiments/diagnostics/scope_contract.py",
            "experiments/diagnostics/solver_failure_probe.py"}.issubset(stage_paths):
        raise ValueError("Diagnostic admission/scope/failure-probe helper is missing from source table")
    reproduction_paths = set(lock["reproduction_entry_sha256"])
    reproduction_paths.update(str(p.relative_to(root)) for p in (root / "experiments/reproduction").glob("*.py"))
    reproduction_paths.update(str(p.relative_to(root)) for p in (root / "experiments/reproduction/reference_sources").rglob("*") if p.is_file())
    pointer_path = root / "provenance/storage-wrapper-current.json"
    pointer = json.loads(pointer_path.read_text())
    receipt = Path(pointer["receipt"])
    if receipt.is_absolute() or ".." in receipt.parts:
        raise ValueError("Nonportable canonical storage receipt")
    if digest(root / receipt) != pointer["receipt_sha256"]:
        raise ValueError("Canonical storage receipt SHA differs")
    storage_pins = json.loads((root / receipt).read_text())["source_sha256"]
    if set(storage_pins) != {"experiments/archival.py", "experiments/run_m5_archived.py"}:
        raise ValueError("Canonical storage scope differs")
    for name, expected in storage_pins.items():
        if digest(root / name) != expected:
            raise ValueError("Canonical storage source differs: " + name)
    groups = {"stage_entry_sha256": stage_paths, "reproduction_entry_sha256": reproduction_paths,
              "storage_outer_sha256": set(storage_pins),
              "canonical_storage_pointer_sha256": {"provenance/storage-wrapper-current.json", str(receipt)},
              "delivery_document_sha256": {"README.md", "THIRD_PARTY_NOTICES.md"}}
    observed = {key: {name: {"sha256": digest(root / name), "bytes": (root / name).stat().st_size}
                      for name in sorted(names)} for key, names in groups.items()}
    trees = {name: ast.parse((root / name).read_text(), filename=name)
             for names in groups.values() for name in names if name.endswith(".py")}
    checks = []

    def flags(name, required):
        actual = {a.value for node in ast.walk(trees[name]) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
                  for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
        if not set(required).issubset(actual):
            raise ValueError("Entry flag missing: " + name)
        checks.append({"entry": name, "check": "AST CLI flags", "required": required})

    def function(name, target, parameters):
        matches = [node for node in ast.walk(trees[name]) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target]
        if len(matches) != 1:
            raise ValueError("Function interface missing or ambiguous: " + target)
        names = [arg.arg for arg in matches[0].args.args + matches[0].args.kwonlyargs]
        if not set(parameters).issubset(names):
            raise ValueError("Function parameter missing: " + target)
        checks.append({"entry": name, "check": "AST function interface", "function": target, "required": parameters})

    for name in ("inventory", "summarize", "plot_quality_cost"):
        flags("experiments/m5_analysis/" + name + ".py", ["--reproduced-cohort", "--reference-binding"])
    function("experiments/m5_analysis/inventory.py", "inventory", ["run", "verify_files", "reproduced_cohort", "reference_binding"])
    function("experiments/m5_analysis/summarize.py", "summarize", ["report", "rows", "reproduced_cohort", "reference_binding"])
    function("experiments/m5_analysis/plot_quality_cost.py", "plot", ["input_directory", "output_directory", "reproduced_cohort", "reference_binding"])
    function("experiments/reproduction/cohort_binding.py", "verify_m4_reference_binding", ["binding_path", "run_path", "verify_files"])
    function("experiments/reproduction/cohort_binding.py", "verify_reference_binding", ["binding_path", "run_path", "verify_files"])
    flags("experiments/plot_m4.py", ["--run", "--output", "--reference-binding"])
    flags("experiments/summarize_m4.py", ["--run", "--reference-binding"])
    flags("experiments/diagnostics/run_m4.py", ["--runs", "--output", "--execute", "--query-wall-seconds", "--memory-bytes"])
    flags("experiments/diagnostics/gated_m4.py", ["--run", "--reference-binding", "--execute"])
    function("experiments/diagnostics/scope_contract.py", "load_scope", ["folder", "manifest"])
    flags("experiments/diagnostics/m4_completion_join.py", ["--run"])
    function("experiments/reproduction/smoke.py", "verify_recovery", ["receipt"])
    function("experiments/reproduction/smoke.py", "verify_eight_methods", [])
    flags("experiments/m6_analysis/audit.py", ["--run", "--output"])
    function("experiments/m6_analysis/audit.py", "verify_audit_receipt", ["receipt_path", "run_path", "verify_files"])
    flags("experiments/plot_m6.py", ["--output", "--audit-receipt"])
    source = (root / "experiments/summarize_m4.py").read_text()
    if "reproduced_binding.get('stage')=='M4_TEST_MAIN'" not in source.replace(" ", ""):
        raise ValueError("M4 G-E2 explicit test-stage guard not found")
    checks.append({"entry": "experiments/summarize_m4.py", "check": "G-E2 requires explicit M4_TEST_MAIN stage"})
    driver_calls = [node for node in ast.walk(trees["experiments/reproduction/driver.py"])
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "execute"]
    diagnostic = [node for node in driver_calls if node.args and isinstance(node.args[0], ast.Constant)
                  and node.args[0].value == "diagnostic_execute"]
    if len(diagnostic) != 1 or not isinstance(diagnostic[0].args[1], ast.Constant) or diagnostic[0].args[1].value != "experiments/diagnostics/gated_m4.py":
        raise ValueError("Fresh M4 diagnostics must execute through the scope admission helper")
    actual_args = {node.value for node in diagnostic[0].args if isinstance(node, ast.Constant)}
    if not {"--run", "--reference-binding", "work/reproduction/m4_test_cohort_binding.json", "--execute"}.issubset(actual_args):
        raise ValueError("Fresh M4 diagnostic admission lacks the explicit test cohort binding")
    if "experiments/diagnostics/scope_contract.py" not in stage_paths:
        raise ValueError("Diagnostic scope contract is not included in the lock candidate stage sources")
    checks.append({"entry": "experiments/reproduction/driver.py", "check": "diagnostic execution uses gated_m4 with explicit M4_TEST_MAIN binding; scope contract pinned"})
    return {"status": "PASS_SOURCE_TEXT_AST_ONLY_NOT_A_LOCK_REFRESH", "prepared_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "predecessor_lock_sha256": digest(lock_path), "observed_source_groups": observed, "python_AST_files": len(trees),
            "interface_checks": checks, "storage_pointer": pointer,
            "root_refresh_command": ".venv/bin/python experiments/reproduction/refresh_lock.py --ordinary-source-frozen --ordinary-receipt provenance/source_snapshots/formal_ordinary_v12_002/receipt.json --m6-source-frozen --m6-manifest results/m6_prepared/manifest.json --m5-source-frozen --m5-manifest results/m5/official_v12_001/manifest.json --storage-source-frozen",
            "frozen_measurement_scopes": lock["source_scopes"],
            "measurement_manifests_or_lock_modified": False, "algorithm_or_dependency_imported": False,
            "graphs_raw_ZIPs_read": False, "setup_or_refresh_executed": False,
            "limitations": ["Static interface compatibility only; no CLI imports, runtime analysis or fresh rebuild", "Actual fresh setup/eight-method smoke/controller signals and full-cohort audit are separately evidenced; this source inventory does not execute them"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="reviews/reproduction/FINAL_REFRESH_AST_v001.json")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT / "reviews/reproduction"):
        parser.error("Inventory writes restricted to reviews/reproduction")
    value = inventory(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2); stream.write("\n")
    print(json.dumps({"status": value["status"], "python_AST_files": value["python_AST_files"], "interface_checks": len(value["interface_checks"]), "output": str(output.relative_to(ROOT))}))


if __name__ == "__main__":
    main()
