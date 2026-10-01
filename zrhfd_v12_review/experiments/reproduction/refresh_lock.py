"""Archive predecessors and refresh ordinary/M6/M5 frozen source scopes.

Only the reproduction lock and its receipts change. No measurement source,
configuration, execution manifest, raw result, or algorithm is modified.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()

def read(path):
    return json.loads(path.read_text())

def save_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if path.exists():
        if path.read_text() != content:
            raise RuntimeError("Immutable reproduction record differs: " + str(path))
        return
    with path.open("x") as stream:
        stream.write(content)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ordinary-source-frozen", action="store_true", required=True)
    parser.add_argument("--ordinary-receipt", type=Path, required=True)
    parser.add_argument("--m6-source-frozen", action="store_true", required=True)
    parser.add_argument("--m6-manifest", type=Path, required=True)
    parser.add_argument("--m5-source-frozen", action="store_true", required=True)
    parser.add_argument("--m5-manifest", type=Path, required=True)
    parser.add_argument("--storage-source-frozen", action="store_true", required=True)
    parser.add_argument("--storage-receipt", type=Path, help="Optional exact receipt; default verifies provenance/storage-wrapper-current.json")
    args = parser.parse_args()
    lock_path = ROOT / "experiments/reproduction/lock.json"
    old = read(lock_path)
    ordinary_path = ROOT / args.ordinary_receipt
    m6_path, m5_path = ROOT / args.m6_manifest, ROOT / args.m5_manifest
    ordinary, m6, m5 = read(ordinary_path), read(m6_path), read(m5_path)
    scopes = {
        "ordinary": {**ordinary["source_sha256"], **ordinary["runtime_sha256"]},
        "m6": dict(m6["source_sha256"]),
        "m5": {**m5["frozen"]["source_pins"],
               m5["frozen"]["configuration_file"]: m5["frozen"]["configuration_sha256"]},
    }
    pins = {}
    for name, scope in scopes.items():
        for path, expected in scope.items():
            if path in pins and pins[path] != expected:
                raise RuntimeError("Frozen scopes disagree on source: " + path)
            if sha(ROOT / path) != expected:
                raise RuntimeError("Current source differs from supplied frozen " + name + ": " + path)
            pins[path] = expected
    pointer_path = ROOT / "provenance/storage-wrapper-current.json"
    pointer = read(pointer_path)
    receipt_relative = Path(pointer["receipt"])
    if receipt_relative.is_absolute() or ".." in receipt_relative.parts:
        raise RuntimeError("Storage pointer must name a portable local receipt")
    storage_path = ROOT / (args.storage_receipt or receipt_relative)
    if storage_path.resolve() != (ROOT / receipt_relative).resolve():
        raise RuntimeError("Explicit storage receipt disagrees with canonical current pointer")
    if sha(storage_path) != pointer["receipt_sha256"]:
        raise RuntimeError("Canonical storage pointer receipt SHA differs")
    storage_pins = read(storage_path)["source_sha256"]
    if set(storage_pins) != {"experiments/archival.py", "experiments/run_m5_archived.py"}:
        raise RuntimeError("Storage receipt scope differs")
    for path, expected in storage_pins.items():
        if sha(ROOT / path) != expected:
            raise RuntimeError("Frozen storage wrapper source differs: " + path)
    pins.update(storage_pins)
    stage_paths = {"experiments/build.py", "experiments/run_m2.py", "experiments/summarize_m2.py",
                   "experiments/summarize_m4.py", "experiments/bootstrap_statistics.py",
                   "experiments/region_decision.py", "data/external/acquire_benson.py",
                   "experiments/plot_m4.py", "experiments/plot_m6.py", "experiments/apfs_storage.py", "experiments/run_m6_compressed.py",
                   "experiments/serial_workflow.py", "experiments/resume_workflow.py", "experiments/stage_barrier.py", "experiments/storage_guard.py"}
    for directory in ("experiments/m0_reference", "tests/m1_independent",
                      "experiments/data_generation", "experiments/baseline_integration",
                      "experiments/m5_analysis", "experiments/m6_analysis", "experiments/diagnostics"):
        stage_paths.update(str(path.relative_to(ROOT)) for path in (ROOT / directory).glob("*")
                           if path.is_file() and path.suffix in (".py", ".json"))
    stage_entry_pins = {path: sha(ROOT / path) for path in sorted(stage_paths)}
    m5_input_pins = {task["input_path"]: task["input_sha256"] for task in m5["frozen"]["tasks"]}
    for path, expected in m5_input_pins.items():
        if sha(ROOT / path) != expected:
            raise RuntimeError("Frozen M5 input differs: " + path)
    manifest_paths = {}
    for directory, expected in ordinary["manifest_sha256"].items():
        path = ROOT / directory / "manifest.json"
        if sha(path) != expected:
            raise RuntimeError("Frozen ordinary manifest differs: " + directory)
        d = read(path)
        if d["source_sha256"] != ordinary["source_sha256"]:
            raise RuntimeError("Ordinary manifest/source snapshot disagreement")
        if d["implementation"]["exact_cut_backend"] != "prepared_region_workspace":
            raise RuntimeError("Expected the explicit prepared exact-cut implementation")
        manifest_paths[str(path.relative_to(ROOT))] = expected
    if m6["source_state"] != "SOURCE_FROZEN" or m6["legacy_measurements_imported"]:
        raise RuntimeError("M6 must be frozen and start a fresh cohort")
    if len(m6["schedule"]) != 108 or not m5["frozen"]["formal_measurement"]:
        raise RuntimeError("Incomplete M6 or nonformal M5 reference manifest")
    manifest_paths[str(m6_path.relative_to(ROOT))] = sha(m6_path)
    manifest_paths[str(m5_path.relative_to(ROOT))] = sha(m5_path)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    archive = ROOT / "experiments/reproduction/snapshots" / ("before_scoped_freeze_" + timestamp.replace(":", "").replace("+", "_"))
    archive.mkdir(parents=True, exist_ok=False)
    shutil.copy2(lock_path, archive / "lock.json")
    # Portable reference manifests are audit data, not fresh execution manifests.
    # No task outputs or no-license author source are bundled here.
    reference_manifest_pins = {}
    for relative, expected in manifest_paths.items():
        target = ROOT / "experiments/reproduction/frozen_manifests" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and sha(target) != expected:
            raise RuntimeError("Reference manifest copy differs: " + relative)
        if not target.exists():
            shutil.copy2(ROOT / relative, target)
        reference_manifest_pins[str(target.relative_to(ROOT))] = expected
    historical = dict(old.get("historical_archive_sha256", {}))
    old_ordinary_path = ROOT / old["source_scopes"]["ordinary"]["receipt"]
    old_ordinary = read(old_ordinary_path)
    for relative, expected in old_ordinary["source_sha256"].items():
        historical[str((old_ordinary_path.parent / relative).relative_to(ROOT))] = expected
    historical[str(old_ordinary_path.relative_to(ROOT))] = sha(old_ordinary_path)
    old_m6_archive = ROOT / "results/m6_prepared/legacy_m6_source_archive_v002"
    old_m6 = read(old_m6_archive / "manifest.json")
    for relative, expected in old_m6["source_sha256"].items():
        historical[str((old_m6_archive / "source" / relative).relative_to(ROOT))] = expected
    for name in ("manifest.json", "receipt.json"):
        historical[str((old_m6_archive / name).relative_to(ROOT))] = sha(old_m6_archive / name)
    for path, expected in historical.items():
        if sha(ROOT / path) != expected:
            raise RuntimeError("Historical source archive differs: " + path)
    history_directories = ["provenance/workflow_v001", "provenance/workflow_v002", "provenance/resume_guard_v001",
                           "provenance/source_snapshots/m4_analysis_v001", "experiments/reproduction/snapshots/before_cohort_binding_v001"]
    history_directories.extend(str(path.relative_to(ROOT)) for path in (ROOT / "provenance").glob("storage_wrapper_v*") if path.is_dir())
    for directory in history_directories:
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and path.suffix in (".py", ".json"):
                historical[str(path.relative_to(ROOT))] = sha(path)
    new = dict(old)
    new["verification_source_sha256"] = pins
    new["stage_entry_sha256"] = stage_entry_pins
    new["stage_entry_policy"] = "Pinned reproduction/generation/check entry points at refresh; not an additional theorem or global experimental gate declaration"
    new["m5_fixed_input_sha256"] = m5_input_pins
    new["historical_archive_sha256"] = historical
    new["historical_policy"] = "Verify archived predecessor bytes, never require old worker/schedule to equal current runtime; old raw retained and never pooled with prepared cohorts"
    new["reference_manifest_sha256"] = reference_manifest_pins
    new["original_manifest_sha256"] = manifest_paths
    new["stage_freeze_status"] = {"ordinary": "SOURCE_FROZEN", "m6": "SOURCE_FROZEN", "m5": "SOURCE_FROZEN", "fixed_inputs": "SOURCE_FROZEN"}
    new["source_state"] = "SOURCE_FROZEN_SCOPED_PREPARED_REPRO_ANALYSIS_STORAGE_V002"
    new["source_scopes"] = {
        "ordinary": {"receipt": str(ordinary_path.relative_to(ROOT)), "receipt_sha256": sha(ordinary_path),
                     "manifest_sha256": ordinary["manifest_sha256"], "implementation": "formal-ordinary-v12-002", "root_signal": "SOURCE_FROZEN"},
        "m6": {"manifest": str(m6_path.relative_to(ROOT)), "manifest_sha256": sha(m6_path),
               "implementation": m6["implementation_version"], "root_signal": "SOURCE_FROZEN"},
        "m5": {"manifest": str(m5_path.relative_to(ROOT)), "manifest_sha256": sha(m5_path),
               "frozen_sha256": m5["frozen_sha256"], "root_signal": "M5 final source freeze authorized by root"},
        "storage": {"source_sha256": storage_pins, "receipt": str(storage_path.relative_to(ROOT)),
                    "receipt_sha256": sha(storage_path), "root_signal": "STORAGE_SOURCE_FROZEN",
                    "canonical_pointer": str(pointer_path.relative_to(ROOT)), "canonical_pointer_sha256": sha(pointer_path),
                    "measurement_inclusion": "archive/verification time is separate offline storage cost"},
    }
    new["receipt_sha256"] = {**old["receipt_sha256"], str(ordinary_path.relative_to(ROOT)): sha(ordinary_path),
                            str(storage_path.relative_to(ROOT)): sha(storage_path), str(pointer_path.relative_to(ROOT)): sha(pointer_path)}
    entries = set(old["reproduction_entry_sha256"])
    entries.update(str(path.relative_to(ROOT)) for path in (ROOT / "experiments/reproduction").glob("*.py"))
    entries.update(str(path.relative_to(ROOT)) for path in (ROOT / "experiments/reproduction/reference_sources").rglob("*") if path.is_file())
    new["reproduction_entry_sha256"] = {path: sha(ROOT / path) for path in sorted(entries)}
    new["delivery_document_sha256"] = {path: sha(ROOT / path) for path in ("README.md", "THIRD_PARTY_NOTICES.md")}
    new["scoped_refresh_at_utc"] = timestamp
    new["predecessor_lock_snapshot"] = str((archive / "lock.json").relative_to(ROOT))
    lock_path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
    receipt = {"timestamp_utc": timestamp, "old_lock_sha256": sha(archive / "lock.json"),
        "new_lock_sha256": sha(lock_path), "reference_manifest_sha256": reference_manifest_pins,
        "verification_source_files": len(pins), "historical_archived_files": len(historical),
        "stage_entry_files": len(stage_entry_pins), "m5_fixed_input_files": len(m5_input_pins),
        "old_lock_snapshot": str((archive / "lock.json").relative_to(ROOT)),
        "formal_measurement_sources_or_results_modified": False,
        "algorithm_or_heavy_test_executed": False}
    save_new(archive / "refresh_receipt.json", receipt)
    print(json.dumps(receipt, indent=2))

if __name__ == "__main__":
    main()
