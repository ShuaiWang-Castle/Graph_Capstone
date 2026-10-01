"""Bind a fresh M5 cohort to the immutable official plan without relabelling raw.

Only stdlib verification runs here. Creating a binding always hashes all source
snapshots, live sources, planned inputs and referenced real-data raw inputs.
The original analysis remains byte/semantic strict; this is an explicit mode.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

OFFICIAL_BYTES_SHA = "a485c3bc16b2799a8cec30d8795b2284c2718820e1254f76c88060bcbce7d98c"
OFFICIAL_SEMANTIC_SHA = "403474d726b7bfad36776b45b20a6f47299815e642992e294eed584806b4356f"
REFERENCE = "experiments/reproduction/frozen_manifests/results/m5/official_v12_001/manifest.json"
MARKER = ".REPRODUCTION_WORKSPACE.json"
RUNTIME_PATHS = {"work/bin/mincut128", "provenance/environment.json"}
BUILD_ENTRY_SHA = "b4413a28f24df497471d27f90ec6aaf114ded2e3f49a6565db7f1a575ab3803d"
ROOT = Path(__file__).resolve().parents[2]
M4_CATALOG_SHA = "c7e97bfbb7bea8fa7708b3e9061309f170cd345ac40116f67b4a97891a7481d4"
M4_MANIFEST_SHA = "caaf1ed4f65d2d51b1269856d1f944a59941e401a00cf99757775736b515150f"
M4_REFERENCE = "experiments/reproduction/frozen_manifests/results/m4/test_main_v12_002/manifest.json"
M4_CATALOG = "data/test/calibrated_lfr/catalog.json"
M4_REFERENCE_CATALOG = "experiments/reproduction/reference_sources/" + M4_CATALOG
M4_REFERENCE_FREEZE = "experiments/reproduction/reference_sources/data/test/calibrated_lfr/GENERATION_FREEZE.json"
M4_JOB_TEMPLATES = "experiments/reproduction/reference_sources/m4_test_job_templates.json"
M4_JOB_TEMPLATES_SHA = "95aec67f10ea971a58070d850da77b1d0eb8b13cbd35584122293d83efe74c5e"
M4_DEV_MANIFEST_SHA = "ae8e1b57d465673c1ac14112e3e9ec13a1ba2b5166b0872d82c7a5d28ae8df3e"
M4_DEV_REFERENCE = "experiments/reproduction/frozen_manifests/results/m4/dev_main_v12_002/manifest.json"
M4_DEV_CATALOG = "data/dev/catalog_v12.json"
M4_DEV_CATALOG_SHA = "b32813d56dc5093c67dce7287879c53ee0c6a60a9a647af69889a5a59bbe8e22"
M4_DEV_REFERENCE_CATALOG = "experiments/reproduction/reference_sources/" + M4_DEV_CATALOG


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def portable(root, path):
    path = Path(path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Expected portable relative path: " + str(path))
    target = root / path
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes the reproduction workspace: " + str(path))
    return target


def relative(root, path):
    path = Path(path)
    if not path.is_absolute():
        path = portable(root, path)
    return path.resolve().relative_to(root.resolve()).as_posix()


def same(actual, expected, label):
    # Canonical JSON also prevents bool/int equality from weakening a field.
    if isinstance(actual, set):
        actual = sorted(actual)
    if isinstance(expected, set):
        expected = sorted(expected)
    if isinstance(actual, Path):
        actual = str(actual)
    if isinstance(expected, Path):
        expected = str(expected)
    if canonical(actual) != canonical(expected):
        raise ValueError(label + " differs from the frozen reference")


def _relation(reference, fresh, count=11480, source_count=35):
    """Pure plan comparison; private count arguments serve stdlib fixtures only."""
    a, b = reference["frozen"], fresh["frozen"]
    for item in (reference, fresh):
        same(item["frozen_sha256"], hashlib.sha256(canonical(item["frozen"])).hexdigest(), "semantic hash")
        same(item["source_snapshot_directory"], "sources", "source snapshot directory")
    same(len(a["tasks"]), count, "reference task count")
    same(len(a["source_pins"]), source_count, "reference source count")
    same(set(a), set(b), "frozen field set")
    for key in a:
        if key != "source_pins":
            same(b[key], a[key], "frozen." + key)
    same(set(a["source_pins"]), set(b["source_pins"]), "source path set")
    changed = {}
    for name, expected in a["source_pins"].items():
        if b["source_pins"][name] != expected:
            if name not in RUNTIME_PATHS:
                raise ValueError("Algorithm/author source changed: " + name)
            changed[name] = {"reference_sha256": expected, "fresh_sha256": b["source_pins"][name]}
    tasks = b["tasks"]
    if len({t["task_id"] for t in tasks}) != len(tasks):
        raise ValueError("Duplicate task IDs")
    same(b["toy"], False, "formal toy flag")
    same(b["formal_measurement"], True, "formal flag")
    same(b["serial_execution"], True, "serial execution")
    same(b["threads"], 1, "threads")
    same(b["tl_backend"], "numba", "TL backend")
    # Timestamp/host descriptions can differ; all structural execution fields stay exact.
    same(set(reference), set(fresh), "manifest top-level field set")
    for name in set(reference) - {"created_utc", "host_metadata", "frozen", "frozen_sha256"}:
        same(fresh[name], reference[name], "manifest." + name)
    for manifest in (reference, fresh):
        same(manifest["host_metadata"]["python"], manifest["frozen"]["python_version"], "host Python identity")
        same(manifest["host_metadata"]["dependencies"], manifest["frozen"]["dependency_versions"], "host dependency identity")
    return {"task_plan_sha256": hashlib.sha256(canonical(tasks)).hexdigest(),
            "specification_sha256": hashlib.sha256(canonical({k: v for k, v in b.items() if k != "source_pins"})).hexdigest(),
            "runtime_source_identity_differences": changed}


def _hash_files(root, run, reference, fresh, changed):
    files = {}
    def check(name, expected=None):
        path = portable(root, name)
        actual = digest(path)
        if expected is not None:
            same(actual, expected, "file " + str(name))
        files[str(name)] = actual
        return path

    frozen = fresh["frozen"]
    snapshot = relative(root, run / "sources")
    for name, expected in frozen["source_pins"].items():
        check(name, expected)
        check(snapshot + "/" + name, expected)
    cfg = check(frozen["configuration_file"], frozen["configuration_sha256"])
    same(read(cfg), frozen["configuration"], "configuration JSON")
    inputs = {}
    for task in frozen["tasks"]:
        if task["input_path"] in inputs:
            same(task["input_sha256"], inputs[task["input_path"]], "shared input SHA")
        inputs[task["input_path"]] = task["input_sha256"]
    for name, expected in sorted(inputs.items()):
        path = check(name, expected)
        for dataset in read(path).get("datasets", []):
            for record in dataset.get("raw_files", {}).values():
                check(record["path"], record["sha256"])
    lock = read(check("experiments/reproduction/lock.json"))
    storage = lock["source_scopes"]["storage"]
    storage_receipt = read(check(storage["receipt"], storage["receipt_sha256"]))
    same(storage_receipt["source_sha256"], storage["source_sha256"], "separate frozen storage wrapper scope")
    if "canonical_pointer" in storage:
        pointer = read(check(storage["canonical_pointer"], storage["canonical_pointer_sha256"]))
        same(pointer, {"receipt": storage["receipt"], "receipt_sha256": storage["receipt_sha256"]}, "canonical storage pointer")
    for name, expected in storage["source_sha256"].items():
        check(name, expected)
    dependencies = read_versions(check("provenance/dependency_versions.txt"))
    for name, version in frozen["dependency_versions"].items():
        same(dependencies.get(name), version, "dependency lock " + name)
    # A new binary identity is permitted only with a recorded successful build of
    # the same frozen C++ source and the locked build entry, not an arbitrary file.
    if "work/bin/mincut128" in changed:
        identity = read(check("work/reproduction/build_identity.json"))
        same(identity["mincut_binary_sha256"], frozen["source_pins"]["work/bin/mincut128"], "build identity binary")
        same(identity["mincut_source_sha256"], reference["frozen"]["source_pins"]["zrhfd/mincut128.cpp"], "build identity source")
        expected_build = BUILD_ENTRY_SHA
        same(lock["stage_entry_sha256"]["experiments/build.py"], expected_build, "locked native build entry")
        check("experiments/build.py", expected_build)
        record = read(check("provenance/mincut-build.json"))
        same(record["returncode"], 0, "native build return code")
        same(record["source_sha256"], identity["mincut_source_sha256"], "native build source")
        same(record["binary_sha256"], identity["mincut_binary_sha256"], "native build binary")
        same(record["command"], ["clang++", "-O3", "-std=c++17", str(root / "zrhfd/mincut128.cpp"), "-o", str(root / "work/bin/mincut128")], "native compile command")
    if "provenance/environment.json" in changed:
        original_name = "experiments/reproduction/reference_sources/provenance/environment.json"
        original = read(check(original_name, reference["frozen"]["source_pins"]["provenance/environment.json"]))
        current = read(root / "provenance/environment.json")
        same({k: v for k, v in current.items() if k not in {"recorded_utc", "platform"}},
             {k: v for k, v in original.items() if k not in {"recorded_utc", "platform"}}, "runtime environment non-identity fields")
        same(current["python"], frozen["python_version"], "runtime environment Python")
    return files


def read_versions(path):
    return dict(line.strip().split("==", 1) for line in path.read_text().splitlines() if line.strip())


def _workspace(root, run):
    root = Path(root).resolve()
    if not (root / MARKER).is_file() or read(root / MARKER).get("mode") != "FRESH_CPU_REPRODUCTION":
        raise ValueError("Binding requires a marked fresh reproduction workspace")
    run = portable(root, relative(root, run))
    if not run.resolve().is_relative_to(root / "results/m5") or run == root / "results/m5/official_v12_001":
        raise ValueError("Fresh binding must use a separate M5 output cohort")
    return root, run


def _audit(root, run, verify_files):
    reference_path, fresh_path = root / REFERENCE, run / "manifest.json"
    same(digest(reference_path), OFFICIAL_BYTES_SHA, "official reference bytes hash")
    reference, fresh = read(reference_path), read(fresh_path)
    same(reference["frozen_sha256"], OFFICIAL_SEMANTIC_SHA, "official reference semantic hash")
    relation = _relation(reference, fresh)
    storage_scope = read(root / "experiments/reproduction/lock.json")["source_scopes"]["storage"]
    files = _hash_files(root, run, reference, fresh, relation["runtime_source_identity_differences"]) if verify_files else None
    return {"schema_version": 1, "status": "PASS", "cohort_origin": "FRESH_REPRODUCTION",
        "binding_validator_sha256": digest(__file__),
        "reference": {"manifest_path": REFERENCE, "manifest_sha256": OFFICIAL_BYTES_SHA,
                      "frozen_sha256": OFFICIAL_SEMANTIC_SHA, "task_plan_sha256": relation["task_plan_sha256"]},
        "fresh": {"manifest_path": relative(root, fresh_path), "manifest_sha256": digest(fresh_path),
                  "frozen_sha256": fresh["frozen_sha256"]},
        "specification_sha256": relation["specification_sha256"],
        "post_measurement_storage_scope": storage_scope,
        "runtime_source_identity_differences": relation["runtime_source_identity_differences"],
        "manifest_identity_differences": {key: {"reference": reference[key], "fresh": fresh[key]}
                                         for key in ("created_utc", "host_metadata") if reference[key] != fresh[key]},
        "planned_tasks": len(fresh["frozen"]["tasks"]), "source_snapshot_count": len(fresh["frozen"]["source_pins"]),
        "validated_files_sha256": files,
        "verification_policy": "All tasks/config/budgets/threads/dependency versions exact; algorithm and author source bytes exact; only recorded native binary and environment identity exceptions",
        "completion_or_quality_claim": False, "original_official_raw_modified": False}


def create_reference_binding(root, run_path, binding_path):
    root, run = _workspace(root, run_path)
    target = portable(root, relative(root, binding_path))
    if not target.resolve().is_relative_to(root / "work/reproduction"):
        raise ValueError("Binding receipt must stay in fresh work/reproduction")
    if target.exists():
        return verify_reference_binding(target, run, verify_files=True)
    receipt = _audit(root, run, True)
    receipt["created_utc"] = datetime.now(timezone.utc).isoformat()
    receipt["all_source_snapshots_and_inputs_verified_at_creation"] = True
    receipt["binding_payload_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return receipt


def verify_reference_binding(binding_path, run_path=None, verify_files=False):
    binding_path = Path(binding_path).resolve()
    root = next((parent for parent in binding_path.parents if (parent / MARKER).exists()), None)
    if root is None:
        raise ValueError("Binding is outside a marked fresh workspace")
    receipt = read(binding_path)
    recorded_payload_sha = receipt.get("binding_payload_sha256")
    same(recorded_payload_sha, hashlib.sha256(canonical({k: v for k, v in receipt.items() if k != "binding_payload_sha256"})).hexdigest(), "binding payload hash")
    manifest_path = portable(root, receipt["fresh"]["manifest_path"])
    if run_path is None:
        run_path = manifest_path.parent
    root, run = _workspace(root, run_path)
    same(manifest_path, run / "manifest.json", "binding cohort path")
    same(receipt.get("all_source_snapshots_and_inputs_verified_at_creation"), True, "binding creation audit")
    if not isinstance(receipt.get("validated_files_sha256"), dict) or not receipt["validated_files_sha256"]:
        raise ValueError("Binding lacks full file validation inventory")
    actual = _audit(root, run, verify_files)
    for key, value in actual.items():
        if key != "validated_files_sha256" or verify_files:
            same(receipt.get(key), value, "binding." + key)
    # Validate every recorded portable path even during metadata-only inventory.
    for name in receipt["validated_files_sha256"]:
        portable(root, name)
    return {**receipt, "files_reverified_now": verify_files, "binding_receipt_sha256": digest(binding_path)}


def _m4_relation(reference, fresh, catalog_reference, catalog_fresh, task_count=5184, case_count=36, query_count=432):
    same(set(reference), set(fresh), "M4 manifest fields")
    for key in reference:
        if key not in {"created_utc", "catalog_sha256", "runtime_sha256"}:
            same(fresh[key], reference[key], "M4 manifest." + key)
    same(reference["phase"], "main", "M4 phase")
    same(len(reference["jobs"]), task_count, "M4 complete task count")
    same(set(fresh["runtime_sha256"]), {"work/bin/mincut128"}, "M4 runtime path set")
    same(set(catalog_reference), set(catalog_fresh), "M4 catalog field set")
    for key in catalog_reference:
        if key != "generation_freeze_sha256":
            same(catalog_fresh[key], catalog_reference[key], "M4 catalog." + key)
    same(len(catalog_fresh["cases"]), case_count, "M4 graph count")
    same(sum(case["query_count"] for case in catalog_fresh["cases"]), query_count, "M4 query census")


def _m4_audit(root, run, verify_files):
    fresh = read(run / "manifest.json")
    if len(fresh["jobs"]) == 4032:
        stage, task_count, case_count, query_count = "M4_DEV_MAIN", 4032, 28, 336
        reference_name, manifest_sha = M4_DEV_REFERENCE, M4_DEV_MANIFEST_SHA
        reference_catalog, catalog_name, catalog_sha = M4_DEV_REFERENCE_CATALOG, M4_DEV_CATALOG, M4_DEV_CATALOG_SHA
    elif len(fresh["jobs"]) == 5184:
        stage, task_count, case_count, query_count = "M4_TEST_MAIN", 5184, 36, 432
        reference_name, manifest_sha = M4_REFERENCE, M4_MANIFEST_SHA
        reference_catalog, catalog_name, catalog_sha = M4_REFERENCE_CATALOG, M4_CATALOG, M4_CATALOG_SHA
    else:
        raise ValueError("M4 requires a complete frozen dev or test task plan")
    reference_path = root / reference_name
    same(digest(reference_path), manifest_sha, "M4 reference manifest bytes")
    same(digest(root / reference_catalog), catalog_sha, "M4 reference catalog bytes")
    reference = read(reference_path)
    same(reference["catalog_sha256"], catalog_sha, "M4 reference manifest catalog identity")
    same(len(reference["source_sha256"]), 27, "M4 reference source count")
    old, catalog = read(root / reference_catalog), read(root / catalog_name)
    _m4_relation(reference, fresh, old, catalog, task_count, case_count, query_count)
    prefix = relative(root, run) + "/jobs/"
    if len(set(fresh["jobs"])) != len(fresh["jobs"]) or any(not name.startswith(prefix) for name in fresh["jobs"]):
        raise ValueError("M4 task paths do not bind to this full fresh cohort")
    same(digest(root / M4_JOB_TEMPLATES), M4_JOB_TEMPLATES_SHA, "M4 frozen job template bytes")
    templates = read(root / M4_JOB_TEMPLATES)
    same(templates["reference_manifest_sha256"], M4_MANIFEST_SHA, "M4 template reference manifest")
    same(digest(root / M4_REFERENCE), M4_MANIFEST_SHA, "M4 template source manifest bytes")
    template_manifest = read(root / M4_REFERENCE)
    for key in ("source_sha256", "protocol_sha256", "resources", "implementation"):
        same(reference[key], template_manifest[key], "M4 common configuration template source " + key)
    same(len(templates["templates"]), 12, "M4 method/config template count")
    if len({t["label"] for t in templates["templates"]}) != 12:
        raise ValueError("M4 duplicate job template labels")
    same(fresh["catalog_sha256"], digest(root / catalog_name), "M4 actual fresh catalog SHA")
    original_freeze = read(root / M4_REFERENCE_FREEZE)
    if stage == "M4_TEST_MAIN":
        same(digest(root / M4_REFERENCE_FREEZE), old["generation_freeze_sha256"], "M4 original generator freeze SHA")
        freeze_path = "data/test/calibrated_lfr/GENERATION_FREEZE.json"
        freeze = read(root / freeze_path)
        same(digest(root / freeze_path), catalog["generation_freeze_sha256"], "M4 actual generator freeze SHA")
        same(set(freeze), set(original_freeze), "M4 generator freeze field set")
        for key in original_freeze:
            if key != "generator_binary_sha256":
                same(freeze[key], original_freeze[key], "M4 generator." + key)
    else:
        # The small original test freeze anchors the shared generation Config.
        # Dev's deterministic catalog has no runtime metadata exception.
        same(digest(root / M4_REFERENCE_CATALOG), M4_CATALOG_SHA, "M4 shared generator reference catalog")
        same(digest(root / M4_REFERENCE_FREEZE), read(root / M4_REFERENCE_CATALOG)["generation_freeze_sha256"], "M4 shared original freeze")
        freeze_path = "data/dev/sbm_v12/GENERATION_FREEZE.json"
        freeze = read(root / freeze_path)
        same(freeze, {"config_sha256": original_freeze["config_sha256"],
                     "sbm": read(root / "experiments/data_generation/generation_config.json")["sbm"],
                     "numpy": read_versions(root / "provenance/dependency_versions.txt")["numpy"]}, "M4 dev generator freeze")
    same(digest(root / "experiments/data_generation/generation_config.json"), original_freeze["config_sha256"], "M4 generator configuration bytes")
    same(read(root / "experiments/data_generation/generation_config.json")["lfr"], original_freeze["lfr"], "M4 generator parameters")
    same(digest(root / "provenance/generators/lfr_native.json"), original_freeze["generator_provenance_sha256"], "M4 generator provenance")
    files = {}
    def check(name, expected=None):
        path = portable(root, name)
        actual = digest(path)
        if expected is not None:
            same(actual, expected, "M4 file " + name)
        files[name] = actual
        return path
    query_plan = []
    expected_jobs = {}
    for case in catalog["cases"]:
        for kind in ("graph", "truth", "queries"):
            name, expected = case[kind + "_path"], case[kind + "_sha256"]
            if verify_files:
                check(name, expected)
            else:
                portable(root, name)
        # Tiny fixed queries are read even in metadata mode to bind actual seeds.
        queries = read(root / case["queries_path"])["queries"]
        same(len(queries), case["query_count"], "M4 graph query count")
        for index, query in enumerate(queries):
            query_plan.append({"case_id": case["case_id"], "query_index": index,
                "seed": query["seed"], "community_index": query["community_index"],
                "graph_sha256": case["graph_sha256"], "truth_sha256": case["truth_sha256"],
                "queries_sha256": case["queries_sha256"]})
        if verify_files:
            communities = read(root / case["truth_path"])["communities"]
            for index, query in enumerate(queries):
                entry = {**case, "query_index": index, "seed": query["seed"],
                    "community_index": query["community_index"], "truth_vertices": communities[query["community_index"]],
                    "communities": communities}
                if query["seed"] not in entry["truth_vertices"]:
                    raise ValueError("M4 planned query seed is outside its fixed truth community")
                for template in templates["templates"]:
                    task = case["case_id"] + "_q%02d_" % index + template["label"]
                    config = dict(template["configuration"])
                    run_name = relative(root, run)
                    if template["method"] != "zrhfd":
                        config["artifact_directory"] = run_name + "/artifacts/" + task
                    expected_jobs[run_name + "/jobs/" + task + ".json"] = {
                        "task": task, "method": template["method"], "setting": template["setting"], "configuration": config,
                        "query": entry, "implementation_exact_cut_backend": template["implementation_exact_cut_backend"],
                        "result_path": run_name + "/raw/" + task + ".json.gz", "source_sha256": fresh["source_sha256"],
                        "protocol_sha256": fresh["protocol_sha256"], "measurement_role": template["measurement_role"]}
    same(len(query_plan), query_count, "M4 actual query count")
    changed = ({"generator_binary_sha256": {"reference": original_freeze["generator_binary_sha256"], "fresh": freeze["generator_binary_sha256"]}}
               if stage == "M4_TEST_MAIN" else {})
    if verify_files:
        for name, expected in fresh["source_sha256"].items():
            check(name, expected)
        check("experiments/protocol_v12.yaml", fresh["protocol_sha256"])
        check("provenance/dependency_versions.txt", fresh["dependency_versions_sha256"])
        for name in (reference_name, reference_catalog, M4_REFERENCE_CATALOG, M4_REFERENCE_FREEZE, catalog_name,
                     M4_JOB_TEMPLATES, freeze_path, "experiments/data_generation/generation_config.json", "provenance/generators/lfr_native.json"):
            check(name)
        same(set(expected_jobs), set(fresh["jobs"]), "M4 complete job/query/method census")
        for name in fresh["jobs"]:
            same(read(check(name)), expected_jobs[name], "M4 full job specification " + name)
        if stage == "M4_TEST_MAIN":
            lfr = read(root / "provenance/generators/lfr_native.json")
            binary = freeze["lfr"]["generator_binary"]
            for name, expected in lfr["files_sha256"].items():
                if name != binary:
                    check(name, expected)
            check(binary, freeze["generator_binary_sha256"])
        check("work/bin/mincut128", fresh["runtime_sha256"]["work/bin/mincut128"])
        lock = read(check("experiments/reproduction/lock.json"))
        generator_changed = stage == "M4_TEST_MAIN" and freeze["generator_binary_sha256"] != original_freeze["generator_binary_sha256"]
        if fresh["runtime_sha256"] != reference["runtime_sha256"] or generator_changed:
            identity = read(check("work/reproduction/build_identity.json"))
            same(identity["mincut_binary_sha256"], fresh["runtime_sha256"]["work/bin/mincut128"], "M4 mincut build identity")
            same(identity["mincut_source_sha256"], fresh["source_sha256"]["zrhfd/mincut128.cpp"], "M4 mincut source identity")
            same(lock["stage_entry_sha256"]["experiments/build.py"], BUILD_ENTRY_SHA, "M4 locked build entry")
            check("experiments/build.py", BUILD_ENTRY_SHA)
            record = read(check("provenance/mincut-build.json"))
            same(record["returncode"], 0, "M4 mincut build status")
            same(record["binary_sha256"], identity["mincut_binary_sha256"], "M4 mincut build receipt")
            same(record["source_sha256"], identity["mincut_source_sha256"], "M4 mincut build CPP")
            same(record["command"], ["clang++", "-O3", "-std=c++17", str(root / "zrhfd/mincut128.cpp"), "-o", str(root / "work/bin/mincut128")], "M4 mincut compile command")
            if stage == "M4_TEST_MAIN":
                same(identity["lfr_binary_sha256"], freeze["generator_binary_sha256"], "M4 LFR build identity")
                attempts = sorted((root / "work/reproduction/commands/lfr_build").glob("attempt_*"))
                if not attempts:
                    raise ValueError("M4 fresh LFR binary lacks a successful build receipt")
                latest = attempts[-1]
                command = read(check(relative(root, latest / "request.json")))
                result = read(check(relative(root, latest / "receipt.json")))
                same(result["returncode"], 0, "M4 LFR build status")
                same(command["cwd"], str(root), "M4 LFR build cwd")
                same(command["argv"][1:], ["-O3", "-funroll-loops", str(root / "external/generators/lfr_native/unweighted_undirected/Sources/benchm.cpp"), "-o", str(root / binary)], "M4 LFR compile flags/source")
    return {"schema_version": 1, "status": "PASS", "cohort_origin": "FRESH_REPRODUCTION", "stage": stage,
        "binding_validator_sha256": digest(__file__),
        "reference": {"manifest_path": reference_name, "manifest_sha256": manifest_sha,
                      "catalog_path": reference_catalog, "catalog_sha256": catalog_sha},
        "fresh": {"manifest_path": relative(root, run / "manifest.json"), "manifest_sha256": digest(run / "manifest.json"),
                  "catalog_path": catalog_name, "catalog_sha256": digest(root / catalog_name)},
        "planned_queries": query_count, "planned_tasks": task_count,
        "query_plan_sha256": hashlib.sha256(canonical(query_plan)).hexdigest(),
        "job_configuration_templates_sha256": M4_JOB_TEMPLATES_SHA,
        "job_file_count_verified_at_creation": task_count,
        "permitted_job_path_construction": templates["allowed_path_construction"],
        "allowed_generation_identity_differences": changed,
        "runtime_identity": {"reference": reference["runtime_sha256"], "fresh": fresh["runtime_sha256"]},
        "validated_files_sha256": files if verify_files else None,
        "completion_or_quality_claim": False, "original_official_raw_modified": False,
        "fresh_catalog_or_generator_provenance_overwritten": False}


def create_m4_reference_binding(root, run_path, binding_path):
    root = Path(root).resolve()
    if not (root / MARKER).exists() or read(root / MARKER).get("mode") != "FRESH_CPU_REPRODUCTION":
        raise ValueError("M4 binding requires a marked fresh workspace")
    run, target = portable(root, relative(root, run_path)), portable(root, relative(root, binding_path))
    if not run.resolve().is_relative_to(root / "results/m4") or not target.resolve().is_relative_to(root / "work/reproduction"):
        raise ValueError("M4 binding paths outside fresh output directories")
    if target.exists():
        return verify_m4_reference_binding(target, run, verify_files=True)
    receipt = _m4_audit(root, run, True)
    receipt["created_utc"] = datetime.now(timezone.utc).isoformat()
    receipt["all_frozen_sources_and_inputs_verified_at_creation"] = True
    receipt["binding_payload_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return receipt


def verify_m4_reference_binding(binding_path, run_path=None, verify_files=False):
    path = Path(binding_path).resolve()
    root = next((parent for parent in path.parents if (parent / MARKER).exists()), None)
    if root is None:
        raise ValueError("M4 binding is outside a marked fresh workspace")
    same(read(root / MARKER).get("mode"), "FRESH_CPU_REPRODUCTION", "M4 fresh workspace mode")
    receipt = read(path)
    same(receipt.get("binding_payload_sha256"), hashlib.sha256(canonical({k: v for k, v in receipt.items() if k != "binding_payload_sha256"})).hexdigest(), "M4 binding payload")
    run = portable(root, relative(root, run_path)) if run_path is not None else portable(root, receipt["fresh"]["manifest_path"]).parent
    same(run / "manifest.json", portable(root, receipt["fresh"]["manifest_path"]), "M4 binding run path")
    same(receipt.get("all_frozen_sources_and_inputs_verified_at_creation"), True, "M4 creation file audit")
    if not receipt.get("validated_files_sha256"):
        raise ValueError("M4 binding lacks validated file inventory")
    if not set(read(run / "manifest.json")["jobs"]).issubset(receipt["validated_files_sha256"]):
        raise ValueError("M4 binding lacks full actual job file inventory")
    actual = _m4_audit(root, run, verify_files)
    for key, value in actual.items():
        if key != "validated_files_sha256" or verify_files:
            same(receipt.get(key), value, "M4 binding." + key)
    for name in receipt["validated_files_sha256"]:
        portable(root, name)
    return {**receipt, "files_reverified_now": verify_files, "binding_receipt_sha256": digest(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", default="work/reproduction/m5_cohort_binding.json")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify-files", action="store_true")
    parser.add_argument("--stage", choices=["m5", "m4-test", "m4-dev"], default="m5")
    args = parser.parse_args()
    path = portable(ROOT, args.output)
    if args.stage in ("m4-test", "m4-dev"):
        receipt = verify_m4_reference_binding(path, args.run, args.verify_files) if args.check else create_m4_reference_binding(ROOT, args.run, path)
        same(receipt["stage"], "M4_TEST_MAIN" if args.stage == "m4-test" else "M4_DEV_MAIN", "explicit M4 stage")
    else:
        receipt = verify_reference_binding(path, args.run, args.verify_files) if args.check else create_reference_binding(ROOT, args.run, path)
    print(json.dumps({k: receipt[k] for k in ("status", "cohort_origin", "planned_tasks", "reference", "fresh")}, indent=2))


if __name__ == "__main__":
    main()
