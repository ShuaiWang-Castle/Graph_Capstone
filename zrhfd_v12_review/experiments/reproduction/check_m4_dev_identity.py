"""Sub-second stdlib-only M4 stage identity mock; no file/graph/method audit."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.reproduction import cohort_binding as b


def main():
    root = Path("/mock-fresh-project")
    run = root / "results/m4/dev_main_v12_002"
    cases = [{"case_id": "case%d" % i, "query_count": 12, "split": "dev",
        "graph_path": "data/dev/g%d.json" % i, "graph_sha256": "g%d" % i,
        "truth_path": "data/dev/t%d.json" % i, "truth_sha256": "t%d" % i,
        "queries_path": "data/dev/q%d.json" % i, "queries_sha256": "q%d" % i} for i in range(28)]
    labels = ["main"] + ["method%d" % i for i in range(11)]
    jobs = ["results/m4/dev_main_v12_002/jobs/" + c["case_id"] + "_q%02d_" % q + label + ".json"
            for c in cases for q in range(12) for label in labels]
    source = {"mock_source%d.py" % i: "sha%d" % i for i in range(27)}
    reference = {"phase": "main", "jobs": jobs, "source_sha256": source, "catalog_sha256": b.M4_DEV_CATALOG_SHA,
        "runtime_sha256": {"work/bin/mincut128": "old-binary"}, "created_utc": "old", "protocol_sha256": "protocol",
        "resources": {"memory_limit_bytes": 12000000000}, "implementation": {"exact_cut_backend": "prepared_region_workspace"}}
    fresh = copy.deepcopy(reference);fresh["created_utc"] = "fresh"
    fresh["runtime_sha256"]["work/bin/mincut128"] = "fresh-binary"
    config = {"lfr": {"mean_degree": 20}, "sbm": {"graph_rng_seed": 20261001}}
    freeze = {"config_sha256": "config", "generator_provenance_sha256": "provenance", "lfr": config["lfr"]}
    catalog = {"protocol": "fixed dev", "cases": cases}
    templates = {"reference_manifest_sha256": b.M4_MANIFEST_SHA, "templates": [{"label": label} for label in labels],
        "allowed_path_construction": {"result_path": "<fresh_run>/raw/<task>.json.gz"}}
    objects = {
        "results/m4/dev_main_v12_002/manifest.json": fresh, b.M4_DEV_REFERENCE: reference,
        b.M4_DEV_REFERENCE_CATALOG: catalog, b.M4_DEV_CATALOG: catalog,
        b.M4_REFERENCE: reference, b.M4_REFERENCE_CATALOG: {"generation_freeze_sha256": "freeze"},
        b.M4_REFERENCE_FREEZE: freeze, b.M4_JOB_TEMPLATES: templates,
        "experiments/data_generation/generation_config.json": config,
        "data/dev/sbm_v12/GENERATION_FREEZE.json": {"config_sha256": "config", "sbm": config["sbm"], "numpy": "mock"}}
    for case in cases:
        objects[case["queries_path"]] = {"queries": [{"seed": q, "community_index": q // 2} for q in range(12)]}
    digests = {b.M4_DEV_REFERENCE: b.M4_DEV_MANIFEST_SHA, b.M4_DEV_REFERENCE_CATALOG: b.M4_DEV_CATALOG_SHA,
        b.M4_DEV_CATALOG: b.M4_DEV_CATALOG_SHA, b.M4_REFERENCE: b.M4_MANIFEST_SHA,
        b.M4_REFERENCE_CATALOG: b.M4_CATALOG_SHA, b.M4_REFERENCE_FREEZE: "freeze", b.M4_JOB_TEMPLATES: b.M4_JOB_TEMPLATES_SHA,
        "experiments/data_generation/generation_config.json": "config", "provenance/generators/lfr_native.json": "provenance"}
    def read_mock(path):
        return copy.deepcopy(objects[Path(path).relative_to(root).as_posix()])
    def digest_mock(path):
        try:return digests.get(Path(path).relative_to(root).as_posix(), "mock-sha")
        except ValueError:return "mock-validator"
    checks = []
    with patch.object(b, "read", read_mock), patch.object(b, "digest", digest_mock), patch.object(b, "read_versions", lambda path: {"numpy": "mock"}):
        result = b._m4_audit(root, run, False)
        checks.extend([result["stage"] == "M4_DEV_MAIN", result["cohort_origin"] == "FRESH_REPRODUCTION",
                       result["planned_queries"] == 336, result["planned_tasks"] == 4032,
                       result["completion_or_quality_claim"] is False, result["validated_files_sha256"] is None,
                       result["stage"] != "M4_TEST_MAIN"])
        for key, mutate in [("resources", lambda value: value["resources"].update(memory_limit_bytes=12884901888)),
                            ("source", lambda value: value["source_sha256"].update({"mock_source0.py": "other"}))]:
            bad = copy.deepcopy(fresh);mutate(bad)
            objects["results/m4/dev_main_v12_002/manifest.json"] = bad
            try:b._m4_audit(root, run, False)
            except ValueError:checks.append(True)
            else:checks.append(False)
        objects["results/m4/dev_main_v12_002/manifest.json"] = fresh
    if not all(checks):raise AssertionError("Dev identity fixture failed")
    record = {"status": "PASS_STDLIB_STAGE_IDENTITY_MOCK", "checks": len(checks), "utc": datetime.now(timezone.utc).isoformat(),
        "actual_graphs_or_raw_read": False, "algorithms_numpy_or_matplotlib_imported": False,
        "full_dev_job_and_files_mock": "NOT_RUN; queued full fixture waits CPU window",
        "mock_reference_read_and_digest_only_inside_fixture": True,
        "real_fresh_rebuild": "NOT_RUN", "source_sha256": {"cohort_binding.py": b.digest(b.__file__), "check_m4_dev_identity.py": b.digest(__file__)}}
    output = ROOT / "reviews/reproduction/M4_DEV_IDENTITY_STDLIB_v001.json"
    with output.open("x") as stream:json.dump(record, stream, indent=2);stream.write("\n")
    print(json.dumps({"status": record["status"], "checks": len(checks), "full_files": "NOT_RUN"}))


if __name__ == "__main__":
    main()
