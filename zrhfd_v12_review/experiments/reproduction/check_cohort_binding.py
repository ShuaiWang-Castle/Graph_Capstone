"""Tiny stdlib-only binding adversarial fixtures; no algorithms or original data.

The official identity constants are patched only inside isolated mock fixtures.
The production public interface has no reference/count override.
"""
from __future__ import annotations
import copy
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.reproduction import cohort_binding as binding


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else binding.canonical(value) + b"\n")
    return binding.digest(path)


def seal(manifest):
    manifest["frozen_sha256"] = hashlib.sha256(binding.canonical(manifest["frozen"])).hexdigest()
    return manifest


def m5_fixture(root):
    write(root, binding.MARKER, {"mode": "FRESH_CPU_REPRODUCTION"})
    sources = {"zrhfd/mock%d.py" % i: write(root, "zrhfd/mock%d.py" % i, b"mock source\n") for i in range(32)}
    for name, value in [("zrhfd/mincut128.cpp", b"mock C++\n"), ("work/bin/mincut128", b"mock binary\n"),
                        ("provenance/environment.json", {"python": "3.12.13", "recorded_utc": "old", "platform": "old", "cpu_threads_env": 1})]:
        sources[name] = write(root, name, value)
    write(root, "experiments/reproduction/reference_sources/provenance/environment.json", (root / "provenance/environment.json").read_bytes())
    raw_sha = write(root, "data/external/raw.txt", b"mock data\n")
    input_sha = write(root, "data/external/m5_queries.json", {"datasets": [{"raw_files": {"mock": {"path": "data/external/raw.txt", "sha256": raw_sha}}}]})
    cfg = {"methods": ["zr_hfd", "zh_prov", "hfd_no_volume", "hfd_oracle", "tlhfd_no_volume", "tlhfd_oracle", "clique_acl_no_volume", "clique_acl_oracle"], "budgets": {"memory_bytes": 12000000000, "wall_seconds_per_method_query": 600}}
    cfg_name = "experiments/m5/config_v12_001.json"
    cfg_sha = write(root, cfg_name, cfg)
    tasks = [{"task_id": "q%d__zr_hfd" % i, "method": "zr_hfd", "dataset": "mock", "input_path": "data/external/m5_queries.json", "input_sha256": input_sha,
              "query": {"query_id": "q%d" % i, "seed_zero_based": i % 12}, "toy": False} for i in range(11480)]
    manifest = seal({"frozen": {"schema_version": 1, "configuration": cfg, "configuration_file": cfg_name, "configuration_sha256": cfg_sha,
        "source_pins": sources, "dependency_versions": {"numpy": "mock"}, "python_version": "3.12.13", "tl_backend": "numba", "tasks": tasks,
        "toy": False, "formal_measurement": True, "threads": 1, "serial_execution": True},
        "created_utc": "old", "host_metadata": {"python": "3.12.13", "dependencies": {"numpy": "mock"}, "platform": "old", "cpu_count": 1},
        "initial_status": "PREPARED_FROZEN_RUN", "execution_status_source": "immutable receipts", "source_snapshot_directory": "sources"})
    reference_sha = write(root, binding.REFERENCE, manifest)
    build_sha = write(root, "experiments/build.py", b"mock build entry\n")
    storage_pins = {name: write(root, name, b"mock storage source\n") for name in ("experiments/archival.py", "experiments/run_m5_archived.py")}
    storage_name = "provenance/storage_wrapper_mock/receipt.json"
    storage_sha = write(root, storage_name, {"source_sha256": storage_pins})
    pointer_name = "provenance/storage-wrapper-current.json"
    pointer_sha = write(root, pointer_name, {"receipt": storage_name, "receipt_sha256": storage_sha})
    write(root, "experiments/reproduction/lock.json", {"stage_entry_sha256": {"experiments/build.py": build_sha},
        "source_scopes": {"storage": {"receipt": storage_name, "receipt_sha256": storage_sha, "source_sha256": storage_pins,
            "canonical_pointer": pointer_name, "canonical_pointer_sha256": pointer_sha}}})
    write(root, "provenance/dependency_versions.txt", b"numpy==mock\n")
    fresh = copy.deepcopy(manifest)
    fresh["created_utc"] = "fresh"
    fresh["host_metadata"]["platform"] = "fresh"
    run = root / "results/m5/reproduction"
    write(root, "results/m5/reproduction/manifest.json", fresh)
    for name in sources:
        write(root, "results/m5/reproduction/sources/" + name, (root / name).read_bytes())
    return manifest, fresh, run, reference_sha, build_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="reviews/reproduction/COHORT_BINDING_STDLIB_v006.json")
    args = parser.parse_args()
    cases = []
    def outcome(name, action, reject=False):
        try:
            action()
        except (ValueError, KeyError, FileNotFoundError) as error:
            if not reject:
                raise
            cases.append({"case": name, "expected": "REJECT", "status": "PASS", "rejection": str(error)})
        else:
            if reject:
                raise AssertionError("Fixture accepted: " + name)
            cases.append({"case": name, "expected": "ACCEPT", "status": "PASS"})
    with tempfile.TemporaryDirectory(prefix="cohort-binding-stdlib-") as temporary:
        root = Path(temporary).resolve()
        original, fresh, run, reference_sha, build_sha = m5_fixture(root)
        with patch.object(binding, "OFFICIAL_BYTES_SHA", reference_sha), patch.object(binding, "OFFICIAL_SEMANTIC_SHA", original["frozen_sha256"]), patch.object(binding, "BUILD_ENTRY_SHA", build_sha):
            target = root / "work/reproduction/m5_binding.json"
            outcome("full_creation", lambda: binding.create_reference_binding(root, run, target))
            outcome("metadata_and_full_reverification", lambda: (binding.verify_reference_binding(target, run), binding.verify_reference_binding(target, run, True)))
            outcome("binding_wrong_output_cohort", lambda: binding.verify_reference_binding(target, root / "results/m5/other", False), True)
            outcome("original_official_path_refused", lambda: binding.create_reference_binding(root, "results/m5/official_v12_001", "work/reproduction/bad.json"), True)
            outcome("reference_byte_tamper", lambda: binding.same("0" * 64, reference_sha, "official bytes"), True)
            for name, mutate in [
                ("query_seed_change", lambda m: m["frozen"]["tasks"][0]["query"].update(seed_zero_based=999)),
                ("task_order_change", lambda m: m["frozen"]["tasks"].reverse()),
                ("task_subset", lambda m: m["frozen"]["tasks"].pop()),
                ("method_change", lambda m: m["frozen"]["tasks"][0].update(method="new_method")),
                ("budget_change", lambda m: m["frozen"]["configuration"]["budgets"].update(memory_bytes=12884901888)),
                ("threads_change", lambda m: m["frozen"].update(threads=2)),
                ("dependency_version_change", lambda m: m["frozen"]["dependency_versions"].update(numpy="other")),
                ("algorithm_source_pin_change", lambda m: m["frozen"]["source_pins"].update({"zrhfd/mock0.py": "0" * 64})),
                ("false_semantic_hash", lambda m: m.update(frozen_sha256="0" * 64))]:
                mutated = copy.deepcopy(fresh)
                mutate(mutated)
                if name != "false_semantic_hash":
                    seal(mutated)
                outcome(name, lambda m=mutated: binding._relation(original, m), True)
            for name, path in [("snapshot_bytes_change", run / "sources/zrhfd/mock0.py"), ("input_bytes_change", root / "data/external/m5_queries.json"), ("real_raw_input_bytes_change", root / "data/external/raw.txt"),
                               ("canonical_storage_pointer_change", root / "provenance/storage-wrapper-current.json")]:
                previous = path.read_bytes()
                path.write_bytes(previous + b"tampered")
                outcome(name, lambda: binding.verify_reference_binding(target, run, True), True)
                path.write_bytes(previous)
            # Recorded rebuild identity is allowed, with the source/entry/flags fixed.
            new = copy.deepcopy(fresh)
            new_sha = write(root, "work/bin/mincut128", b"fresh mock binary\n")
            write(root, "results/m5/reproduction/sources/work/bin/mincut128", b"fresh mock binary\n")
            new["frozen"]["source_pins"]["work/bin/mincut128"] = new_sha
            seal(new)
            write(root, "results/m5/reproduction/manifest.json", new)
            outcome("changed_binary_without_build_evidence", lambda: binding.create_reference_binding(root, run, "work/reproduction/new_binding.json"), True)
            cpp = original["frozen"]["source_pins"]["zrhfd/mincut128.cpp"]
            write(root, "work/reproduction/build_identity.json", {"mincut_binary_sha256": new_sha, "mincut_source_sha256": cpp})
            write(root, "provenance/mincut-build.json", {"returncode": 0, "source_sha256": cpp, "binary_sha256": new_sha,
                  "command": ["clang++", "-O3", "-std=c++17", str(root / "zrhfd/mincut128.cpp"), "-o", str(root / "work/bin/mincut128")]})
            outcome("same_CPP_recorded_fresh_binary", lambda: binding.create_reference_binding(root, run, "work/reproduction/new_binding.json"))
            environment = binding.read(root / "provenance/environment.json")
            environment.update(recorded_utc="fresh", platform="fresh")
            env_sha = write(root, "provenance/environment.json", environment)
            write(root, "results/m5/reproduction/sources/provenance/environment.json", environment)
            new["frozen"]["source_pins"]["provenance/environment.json"] = env_sha
            seal(new);write(root, "results/m5/reproduction/manifest.json", new)
            outcome("environment_time_platform_identity", lambda: binding.create_reference_binding(root, run, "work/reproduction/env_binding.json"))
            environment["cpu_threads_env"] = 2
            env_sha = write(root, "provenance/environment.json", environment)
            write(root, "results/m5/reproduction/sources/provenance/environment.json", environment)
            new["frozen"]["source_pins"]["provenance/environment.json"] = env_sha
            seal(new);write(root, "results/m5/reproduction/manifest.json", new)
            outcome("environment_threads_change", lambda: binding.create_reference_binding(root, run, "work/reproduction/bad_env_binding.json"), True)
            outcome("relative_path_escape", lambda: binding.portable(root, "../outside"), True)
            unmarked = root / "unmarked";unmarked.mkdir()
            outcome("unmarked_workspace_refused", lambda: binding.create_reference_binding(unmarked, "results/m5/reproduction", "work/reproduction/binding.json"), True)
        # M4 pure identity relation, with real 36/432/5184 census sizes.
        old_catalog = {"generation_freeze_sha256": "old", "cases": [{"case_id": "c%d" % i, "query_count": 12, "graph_sha256": "g", "truth_sha256": "t", "queries_sha256": "q"} for i in range(36)]}
        new_catalog = copy.deepcopy(old_catalog);new_catalog["generation_freeze_sha256"] = "fresh"
        old_m = {"phase": "main", "jobs": ["results/m4/test_main_v12_002/jobs/t%d.json" % i for i in range(5184)],
            "source_sha256": {"zrhfd/mock.py": "s"}, "catalog_sha256": "old", "runtime_sha256": {"work/bin/mincut128": "old"},
            "created_utc": "old", "resources": {"memory_limit_bytes": 12000000000}}
        new_m = copy.deepcopy(old_m);new_m.update(created_utc="fresh", catalog_sha256="fresh", runtime_sha256={"work/bin/mincut128": "fresh"})
        outcome("m4_generator_and_runtime_identity_only", lambda: binding._m4_relation(old_m, new_m, old_catalog, new_catalog))
        for name, mutate in [("m4_graph_hash_change", lambda c: c["cases"][0].update(graph_sha256="other")),
                             ("m4_query_count_change", lambda c: c["cases"][0].update(query_count=11)),
                             ("m4_selection_statistic_change", lambda c: c["cases"][0].update(selected_attempt=1))]:
            mutated = copy.deepcopy(new_catalog);mutate(mutated)
            outcome(name, lambda c=mutated: binding._m4_relation(old_m, new_m, old_catalog, c), True)
        mutated = copy.deepcopy(new_m);mutated["resources"]["memory_limit_bytes"] = 12884901888
        outcome("m4_budget_change", lambda: binding._m4_relation(old_m, mutated, old_catalog, new_catalog), True)
    result = {"status": "PASS_STDLIB_MOCK", "created_utc": datetime.now(timezone.utc).isoformat(), "cases": cases,
        "cases_passed": len(cases), "fixture_identity_constants_patched_only_inside_mock": True,
        "production_reference_identity_override_available": False,
        "original_inputs_or_raw_hashed": False, "CPU_algorithms_executed": False,
        "real_fresh_full_rebuild_test": "NOT_RUN", "m4_full_files_fixture": "NOT_RUN; pure relation only",
        "source_sha256": {"experiments/reproduction/cohort_binding.py": binding.digest(binding.__file__), "experiments/reproduction/check_cohort_binding.py": binding.digest(__file__)}}
    path = (ROOT / args.output).resolve()
    if not path.is_relative_to(ROOT / "reviews/reproduction"):
        raise ValueError("Fixture receipts must stay in reviews/reproduction")
    if path.exists():
        raise RuntimeError("Immutable fixture record already exists; choose a new version")
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "cases_passed": len(cases), "real_fresh_full_rebuild_test": "NOT_RUN"}))


if __name__ == "__main__":
    main()
