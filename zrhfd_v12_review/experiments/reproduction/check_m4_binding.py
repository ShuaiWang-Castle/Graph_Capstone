"""Full tiny M4 binding files fixture; no generation, methods, or original raw."""
import copy
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.reproduction import cohort_binding as b
from experiments.reproduction.check_cohort_binding import write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="reviews/reproduction/M4_BINDING_STDLIB_v006.json")
    args = parser.parse_args()
    cases = []
    def record(name, fn, reject=False):
        try:
            fn()
        except (ValueError, FileNotFoundError, KeyError) as error:
            if not reject:
                raise
            cases.append({"case": name, "status": "PASS", "expected": "REJECT", "rejection": str(error)})
        else:
            if reject:
                raise AssertionError(name)
            cases.append({"case": name, "status": "PASS", "expected": "ACCEPT"})
    with tempfile.TemporaryDirectory(prefix="m4-binding-stdlib-") as temp:
        root = Path(temp).resolve()
        write(root, b.MARKER, {"mode": "FRESH_CPU_REPRODUCTION"})
        binary = "external/generators/lfr_native/unweighted_undirected/benchmark"
        old_binary_sha = write(root, binary, b"original generator binary\n")
        generator_cpp = "external/generators/lfr_native/unweighted_undirected/Sources/benchm.cpp"
        cpp_sha = write(root, generator_cpp, b"mock generator C++\n")
        generator = {"files_sha256": {binary: old_binary_sha, generator_cpp: cpp_sha}}
        gp_sha = write(root, "provenance/generators/lfr_native.json", generator)
        config = {"lfr": {"generator_binary": binary, "mean_degree": 20, "max_degree": 100, "max_attempts": 8, "tolerance": .025},
                  "sbm": {"K_values": [4, 8], "graph_rng_seed": 20261001}}
        cfg_sha = write(root, "experiments/data_generation/generation_config.json", config)
        freeze = {"config_sha256": cfg_sha, "generator_binary_sha256": old_binary_sha, "generator_provenance_sha256": gp_sha, "lfr": config["lfr"]}
        old_freeze_sha = write(root, b.M4_REFERENCE_FREEZE, freeze)
        rows = []
        for i in range(36):
            case = {"case_id": "case%d" % i, "query_count": 12, "split": "test"}
            for kind, data in [("graph", {"n": 12, "edges": [[v, (v + 1) % 12] for v in range(12)]}),
                               ("truth", {"communities": [[v, v + 1] for v in range(0, 12, 2)]}),
                               ("queries", {"queries": [{"seed": v, "community_index": v // 2} for v in range(12)]})]:
                name = "data/test/calibrated_lfr/%s/case%d.%s.json" % (kind, i, kind)
                case[kind + "_path"] = name
                case[kind + "_sha256"] = write(root, name, data)
            rows.append(case)
        old_catalog = {"schema_version": 1, "generation_freeze_sha256": old_freeze_sha, "cases": rows}
        old_catalog_sha = write(root, b.M4_REFERENCE_CATALOG, old_catalog)
        sources = {"zrhfd/mock%d.py" % i: write(root, "zrhfd/mock%d.py" % i, b"same frozen source\n") for i in range(25)}
        sources["zrhfd/mincut128.cpp"] = write(root, "zrhfd/mincut128.cpp", b"same mincut C++\n")
        sources["experiments/protocol_v12.yaml"] = write(root, "experiments/protocol_v12.yaml", b"mock identical protocol\n")
        runtime_sha = write(root, "work/bin/mincut128", b"same mincut binary\n")
        deps_sha = write(root, "provenance/dependency_versions.txt", b"numpy==mock\n")
        run_name = "results/m4/test_main_v12_002"
        templates = [{"label": "main" if i == 0 else "mock%d" % i, "method": "zrhfd" if i == 0 else "mock%d" % i,
            "setting": "no_volume", "configuration": {"budget_seconds": 600}, "implementation_exact_cut_backend": "prepared_region_workspace",
            "measurement_role": "formal_cpu_serial"} for i in range(12)]
        jobs = [run_name + "/jobs/" + case["case_id"] + "_q%02d_" % qi + template["label"] + ".json"
                for case in rows for qi in range(12) for template in templates]
        manifest = {"created_utc": "reference", "phase": "main", "jobs": jobs,
            "source_sha256": sources, "catalog_sha256": old_catalog_sha, "protocol_sha256": sources["experiments/protocol_v12.yaml"],
            "dependency_versions_sha256": deps_sha, "runtime_sha256": {"work/bin/mincut128": runtime_sha},
            "resources": {"memory_limit_bytes": 12000000000, "local_method_query_seconds": 600}, "implementation": {"exact_cut_backend": "prepared_region_workspace"}}
        reference_sha = write(root, b.M4_REFERENCE, manifest)
        templates_sha = write(root, b.M4_JOB_TEMPLATES, {"reference_manifest_sha256": reference_sha, "templates": templates,
            "allowed_path_construction": {"result_path": "<fresh_run>/raw/<task>.json.gz", "baseline_artifact_directory": "<fresh_run>/artifacts/<task>"}})
        fresh_catalog = copy.deepcopy(old_catalog)
        new_binary_sha = write(root, binary, b"fresh generator binary\n")
        freeze["generator_binary_sha256"] = new_binary_sha
        fresh_catalog["generation_freeze_sha256"] = write(root, "data/test/calibrated_lfr/GENERATION_FREEZE.json", freeze)
        new_catalog_sha = write(root, b.M4_CATALOG, fresh_catalog)
        fresh = copy.deepcopy(manifest);fresh.update(created_utc="fresh", catalog_sha256=new_catalog_sha)
        run = root / "results/m4/test_main_v12_002"
        write(root, "results/m4/test_main_v12_002/manifest.json", fresh)
        for case in rows:
            communities = b.read(root / case["truth_path"])["communities"]
            for qi, query in enumerate(b.read(root / case["queries_path"])["queries"]):
                entry = {**case, "query_index": qi, "seed": query["seed"], "community_index": query["community_index"],
                    "truth_vertices": communities[query["community_index"]], "communities": communities}
                for template in templates:
                    task = case["case_id"] + "_q%02d_" % qi + template["label"]
                    cfg = dict(template["configuration"])
                    if template["method"] != "zrhfd":cfg["artifact_directory"] = run_name + "/artifacts/" + task
                    write(root, run_name + "/jobs/" + task + ".json", {"task": task, "method": template["method"], "setting": template["setting"],
                        "configuration": cfg, "query": entry, "implementation_exact_cut_backend": template["implementation_exact_cut_backend"],
                        "result_path": run_name + "/raw/" + task + ".json.gz", "source_sha256": sources,
                        "protocol_sha256": sources["experiments/protocol_v12.yaml"], "measurement_role": template["measurement_role"]})
        build_sha = write(root, "experiments/build.py", b"same locked build entry\n")
        write(root, "experiments/reproduction/lock.json", {"stage_entry_sha256": {"experiments/build.py": build_sha}})
        write(root, "work/reproduction/build_identity.json", {"mincut_binary_sha256": runtime_sha, "mincut_source_sha256": sources["zrhfd/mincut128.cpp"], "lfr_binary_sha256": new_binary_sha})
        write(root, "provenance/mincut-build.json", {"returncode": 0, "binary_sha256": runtime_sha, "source_sha256": sources["zrhfd/mincut128.cpp"],
              "command": ["clang++", "-O3", "-std=c++17", str(root / "zrhfd/mincut128.cpp"), "-o", str(root / "work/bin/mincut128")]})
        write(root, "work/reproduction/commands/lfr_build/attempt_000/request.json", {"cwd": str(root), "argv": ["clang++", "-O3", "-funroll-loops", str(root / generator_cpp), "-o", str(root / binary)]})
        write(root, "work/reproduction/commands/lfr_build/attempt_000/receipt.json", {"returncode": 0})
        with patch.object(b, "M4_MANIFEST_SHA", reference_sha), patch.object(b, "M4_CATALOG_SHA", old_catalog_sha), patch.object(b, "BUILD_ENTRY_SHA", build_sha), patch.object(b, "M4_JOB_TEMPLATES_SHA", templates_sha):
            target = root / "work/reproduction/m4_binding.json"
            record("fresh_freeze_catalog_real_file_validation", lambda: b.create_m4_reference_binding(root, run, target))
            record("metadata_reverification", lambda: b.verify_m4_reference_binding(target, run, False))
            record("full_file_reverification", lambda: b.verify_m4_reference_binding(target, run, True))
            record("other_run_path", lambda: b.verify_m4_reference_binding(target, root / "results/m4/other", True), True)
            for name, path in [("changed_graph_bytes", root / rows[0]["graph_path"]), ("changed_truth_bytes", root / rows[0]["truth_path"]),
                               ("changed_query_bytes", root / rows[0]["queries_path"]), ("changed_generator_CPP", root / generator_cpp),
                               ("changed_protocol", root / "experiments/protocol_v12.yaml")]:
                before = path.read_bytes();path.write_bytes(before + b"tampered")
                record(name, lambda: b.verify_m4_reference_binding(target, run, True), True)
                path.write_bytes(before)
            bad_config = copy.deepcopy(config);bad_config["lfr"]["max_attempts"] = 3
            write(root, "experiments/data_generation/generation_config.json", bad_config)
            record("changed_generator_parameters", lambda: b.verify_m4_reference_binding(target, run, True), True)
            write(root, "experiments/data_generation/generation_config.json", config)
            job_path = root / jobs[0]
            original_job = job_path.read_bytes()
            for name, mutation in [("changed_actual_job_seed", lambda j: j["query"].update(seed=999)),
                    ("changed_actual_job_truth", lambda j: j["query"].update(truth_vertices=[999])),
                    ("changed_actual_job_budget", lambda j: j["configuration"].update(budget_seconds=900)),
                    ("changed_actual_job_method", lambda j: j.update(method="other")),
                    ("changed_actual_job_setting", lambda j: j.update(setting="oracle")),
                    ("changed_actual_job_backend", lambda j: j.update(implementation_exact_cut_backend="other")),
                    ("changed_actual_job_result_path", lambda j: j.update(result_path="results/other/raw.json"))]:
                mutated = json.loads(original_job);mutation(mutated);job_path.write_bytes(b.canonical(mutated) + b"\n")
                record(name, lambda: b.verify_m4_reference_binding(target, run, True), True)
                job_path.write_bytes(original_job)
            bad_receipt = b.read(target);bad_receipt["validated_files_sha256"] = {}
            bad_receipt["binding_payload_sha256"] = b.hashlib.sha256(b.canonical({k: v for k, v in bad_receipt.items() if k != "binding_payload_sha256"})).hexdigest()
            write(root, "work/reproduction/empty_binding.json", bad_receipt)
            record("empty_self_sealed_binding_refused", lambda: b.verify_m4_reference_binding(root / "work/reproduction/empty_binding.json", run, False), True)
            # Neither public creation nor verification rewrites the fresh provenance.
            record("fresh_catalog_and_freeze_preserved", lambda: (b.same(b.digest(root / b.M4_CATALOG), new_catalog_sha, "fresh catalog"), b.same(b.digest(root / "data/test/calibrated_lfr/GENERATION_FREEZE.json"), fresh_catalog["generation_freeze_sha256"], "fresh freeze")))
            dev_rows = copy.deepcopy(rows[:28])
            for case in dev_rows:
                case["split"] = "dev"
                for kind in ("graph", "truth", "queries"):
                    previous = root / case[kind + "_path"]
                    name = "data/dev/mock/" + case["case_id"] + "." + kind + ".json"
                    case[kind + "_sha256"] = write(root, name, previous.read_bytes())
                    case[kind + "_path"] = name
            dev_catalog = {"protocol": "mock frozen dev", "cases": dev_rows}
            dev_catalog_sha = write(root, b.M4_DEV_REFERENCE_CATALOG, dev_catalog)
            write(root, b.M4_DEV_CATALOG, dev_catalog)
            write(root, "data/dev/sbm_v12/GENERATION_FREEZE.json", {"config_sha256": cfg_sha, "sbm": config["sbm"], "numpy": "mock"})
            dev_run_name = "results/m4/dev_main_v12_002"
            dev_jobs = []
            for case in dev_rows:
                communities = b.read(root / case["truth_path"])["communities"]
                for qi, query in enumerate(b.read(root / case["queries_path"])["queries"]):
                    entry = {**case, "query_index": qi, "seed": query["seed"], "community_index": query["community_index"],
                        "truth_vertices": communities[query["community_index"]], "communities": communities}
                    for template in templates:
                        task = case["case_id"] + "_q%02d_" % qi + template["label"]
                        cfg = dict(template["configuration"])
                        if template["method"] != "zrhfd":cfg["artifact_directory"] = dev_run_name + "/artifacts/" + task
                        name = dev_run_name + "/jobs/" + task + ".json";dev_jobs.append(name)
                        write(root, name, {"task": task, "method": template["method"], "setting": template["setting"],
                            "configuration": cfg, "query": entry, "implementation_exact_cut_backend": template["implementation_exact_cut_backend"],
                            "result_path": dev_run_name + "/raw/" + task + ".json.gz", "source_sha256": sources,
                            "protocol_sha256": sources["experiments/protocol_v12.yaml"], "measurement_role": template["measurement_role"]})
            dev_reference = copy.deepcopy(manifest);dev_reference.update(jobs=dev_jobs, catalog_sha256=dev_catalog_sha)
            dev_ref_sha = write(root, b.M4_DEV_REFERENCE, dev_reference)
            dev_fresh = copy.deepcopy(dev_reference);dev_fresh["created_utc"] = "fresh dev"
            write(root, dev_run_name + "/manifest.json", dev_fresh)
            dev_run, dev_target = root / dev_run_name, root / "work/reproduction/m4_dev_binding.json"
            with patch.object(b, "M4_DEV_MANIFEST_SHA", dev_ref_sha), patch.object(b, "M4_DEV_CATALOG_SHA", dev_catalog_sha):
                record("dev_full_4032_job_creation", lambda: b.create_m4_reference_binding(root, dev_run, dev_target))
                record("dev_full_reverification", lambda: b.verify_m4_reference_binding(dev_target, dev_run, True))
                record("dev_metadata_identity_and_stage", lambda: b.same(b.verify_m4_reference_binding(dev_target, dev_run, False)["stage"], "M4_DEV_MAIN", "dev stage"))
                record("dev_binding_cannot_identify_test", lambda: b.verify_m4_reference_binding(dev_target, run, False), True)
                dev_job = root / dev_jobs[0];before = dev_job.read_bytes();mutated = json.loads(before);mutated["configuration"]["budget_seconds"] = 900
                dev_job.write_bytes(b.canonical(mutated) + b"\n")
                record("dev_actual_job_budget_change", lambda: b.verify_m4_reference_binding(dev_target, dev_run, True), True)
                dev_job.write_bytes(before)
    result = {"status": "PASS_STDLIB_MOCK_FULL_FILES", "created_utc": datetime.now(timezone.utc).isoformat(), "cases": cases,
        "cases_passed": len(cases), "mock_census": {"test": {"graphs": 36, "queries": 432, "tasks": 5184}, "dev": {"graphs": 28, "queries": 336, "tasks": 4032}, "sources": 27},
        "fixture_identity_constants_patched_only_inside_mock": True, "original_inputs_or_raw_hashed": False,
        "CPU_algorithms_executed": False, "real_fresh_full_rebuild_test": "NOT_RUN",
        "source_sha256": {"experiments/reproduction/cohort_binding.py": b.digest(b.__file__), "experiments/reproduction/check_m4_binding.py": b.digest(__file__)}}
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT / "reviews/reproduction"):
        raise ValueError("Fixture receipts must stay in reviews/reproduction")
    if output.exists():
        raise RuntimeError("Immutable mock receipt already exists")
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "cases_passed": len(cases)}))


if __name__ == "__main__":
    main()
