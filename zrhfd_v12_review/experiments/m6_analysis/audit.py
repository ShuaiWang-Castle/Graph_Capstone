"""Independent offline audit of all108 prepared M6 identities and raw outcomes.

Only stdlib is imported. CSR access uses readonly .npy mmap; no production
Graph, evaluation helper, diffusion, cut solver, NumPy, or plot code is called.
This runs after measurement, writes derived evidence, and never edits raw data.
"""
from pathlib import Path
from collections import Counter
from fractions import Fraction
import argparse
import ast
import csv
import datetime
import hashlib
import json
import math
import mmap
import os
import importlib.metadata
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN = "results/m6_prepared"
DEFAULT_RECEIPT = "results/m6_analysis/prepared_audit/receipt.json"
VERSION = "M6_prepared_exact_cut_v001"
TERMINAL = {"completed", "timeout", "memory_limit", "interrupted", "controller_error", "error"}
SOURCES = {"zrhfd/__init__.py", "zrhfd/graph.py", "zrhfd/storage.py", "zrhfd/diffusion.py",
           "zrhfd/sweep.py", "zrhfd/mincut.py", "zrhfd/certificate.py", "zrhfd/pipeline.py",
           "work/bin/mincut128", "zrhfd/mincut128.cpp", "zrhfd/experimental_cut_workspace.py",
           "experiments/m6_prepared/config.json", "experiments/m6_prepared/common.py",
           "experiments/m6_prepared/run.py", "experiments/m6_prepared/worker.py",
           "experiments/m6_prepared/summarize.py"}
CONFIG = "experiments/m6_prepared/config.json"


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def same(actual, expected, label):
    if actual != expected:
        raise ValueError(label + " differs")


def portable(root, name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Nonportable input path: " + str(name))
    result = (root / path).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Input path escapes workspace")
    return result


class NpyArray:
    """Readonly one-dimensional numeric NPY v1/v2/v3; no array dependency."""
    def __init__(self, path):
        self.stream = Path(path).open("rb")
        try:
            same(self.stream.read(6), b"\x93NUMPY", "NPY magic")
            version = self.stream.read(2)
            if version not in (b"\x01\x00", b"\x02\x00", b"\x03\x00"):
                raise ValueError("Unsupported NPY version")
            fmt = "<H" if version[0] == 1 else "<I"
            length = struct.unpack(fmt, self.stream.read(struct.calcsize(fmt)))[0]
            header = ast.literal_eval(self.stream.read(length).decode("utf-8" if version[0] == 3 else "latin1").strip())
            if header["fortran_order"] or len(header["shape"]) != 1:
                raise ValueError("Require one-dimensional C-order NPY")
            self.length = int(header["shape"][0]); self.dtype = header["descr"]
            allowed = {"<i4": "<i", "<i8": "<q", "<f8": "<d", ">i4": ">i", ">i8": ">q", ">f8": ">d"}
            if self.dtype not in allowed:
                raise ValueError("Unsupported CSR numeric dtype: " + self.dtype)
            self.unpack = struct.Struct(allowed[self.dtype]); self.offset = self.stream.tell()
            if self.offset + self.length * self.unpack.size != Path(path).stat().st_size:
                raise ValueError("NPY array byte length differs")
            self.mapping = mmap.mmap(self.stream.fileno(), 0, access=mmap.ACCESS_READ)
        except BaseException:
            self.stream.close(); raise

    def __len__(self):
        return self.length

    def __getitem__(self, index):
        if not isinstance(index, int) or not 0 <= index < self.length:
            raise IndexError(index)
        return self.unpack.unpack_from(self.mapping, self.offset + index * self.unpack.size)[0]

    def close(self):
        self.mapping.close(); self.stream.close()


def vertices(value, n, label):
    if not isinstance(value, list) or any(type(v) is not int or not 0 <= v < n for v in value) or len(set(value)) != len(value):
        raise ValueError("Invalid vertex collection: " + label)
    return set(value)


def quality(selected, truth):
    overlap = len(selected & truth)
    return {"precision": overlap / len(selected) if selected else 0.0,
            "recall": overlap / len(truth), "F1": 2 * overlap / (len(selected) + len(truth)),
            "symmetric_difference": len(selected ^ truth)}


def set_stats(nodes, ptr, indices, weights, degree, total):
    # Frozen scale graphs have unit integral weights; use independent integer
    # sums and Fraction rather than production float array reductions.
    volume = 0; cut = 0
    for u in nodes:
        d = degree[u]
        if not math.isfinite(d) or d != int(d):
            raise ValueError("Scale degree is not finite integral")
        volume += int(d)
        for j in range(ptr[u], ptr[u + 1]):
            v, w = indices[j], weights[j]
            if not 0 <= v < len(degree) or w != 1.0:
                raise ValueError("Scale CSR is not the frozen unweighted graph")
            if v not in nodes:
                cut += 1
    z = Fraction(cut * total + volume * volume, total * volume) if volume else None
    denom = min(volume, total - volume)
    return {"volume": volume, "cut": cut, "Z": float(z) if z is not None else None,
            "Z_exact": str(z) if z is not None else None, "phi": cut / denom if denom > 0 else None,
            "phi_v": cut / volume if volume else None, "size": len(nodes)}


def independent_offline(query, output, truth, arrays, total):
    n = query["n"]
    groups = [vertices(group, n, "truth") for group in truth]
    ci = query["offline_only"]["community_index"]
    if not 0 <= ci < len(groups) or not groups[ci] or query["seed"] not in groups[ci]:
        raise ValueError("Fixed query seed/target identity differs")
    if any(not group for group in groups):
        raise ValueError("Empty truth community")
    C = groups[ci]
    R, S, H, T = [vertices(value, n, label) for value, label in (
        (output["region_vertices"], "region"), (output["vertices"], "output"),
        (output["certificate"]["hull_best"], "hull"), (output["touched_vertices"], "touched"))]
    if not S.issubset(R) or not H.issubset(R) or not R.issubset(T) or query["seed"] not in S or query["seed"] not in H:
        raise ValueError("Returned set/hull/region/seed inclusion differs")
    stats = set_stats(C, total=total, **arrays)
    target = stats["volume"]
    intersections = [{"community_index": j, "size": len(group), "region_intersection_size": len(R & group),
                      "region_covered_fraction": len(R & group) / len(group)} for j, group in enumerate(groups)]
    rho = max((r["region_covered_fraction"] for r in intersections if r["community_index"] != ci), default=0.0)
    degree = arrays["degree"]
    outside = sum(int(degree[u]) for u in R - C)
    touched = sum(int(degree[u]) for u in T)
    region = sum(int(degree[u]) for u in R)
    output_stats = set_stats(S, total=total, **arrays)
    same(output["stats"], output_stats, "Independent output graph statistics")
    same(output["touched_volume"], touched, "Independent touched volume")
    same(output["region_volume"], region, "Independent region volume")
    return {"quality": quality(S, C), "hull_best_quality": quality(H, C), "truth_stats": stats,
            "community_index": ci, "target_size": len(C), "target_volume": target,
            "target_size_outlier_from_native_requested_bounds": not 100 <= len(C) <= 200,
            "covered": C.issubset(R), "rho_hat": rho, "region_missing_truth_vertices": sorted(C - R),
            "region_outside_truth_vertices": sorted(R - C), "region_outside_truth_volume": float(outside),
            "region_outside_truth_volume_ratio": outside / target, "truth_community_region_intersections": intersections,
            "failure_class": None if S == C else "H1" if not C.issubset(R) else "H2",
            "touched_over_output_volume": touched / output_stats["volume"]}


def projected_row(query, config, attempts, directory=None, terminal=None, result=None):
    """Independent explicit raw-to-CSV schema, preserving every absent outcome."""
    row = {"query_id": query["query_id"], "case_id": query["case_id"], "implementation_version": config["implementation_version"],
           "n": query["n"], "generation_seed": query["generation_seed"], "seed": query["seed"],
           "status": "NOT_RUN", "attempt_count": attempts}
    if directory is not None:
        row["raw_directory"] = directory
        if terminal is None:
            row["status"] = "interrupted_unfinished"
        else:
            row.update({key: terminal.get(key) for key in ("status", "parent_process_wall_seconds",
                "max_sampled_process_group_rss_bytes", "time_l_max_resident_set_size_bytes", "runtime_censored")})
            row["last_checkpoint_stage"] = (terminal.get("last_checkpoint") or {}).get("event", {}).get("stage")
    if row["status"] == "completed":
        if result is None:
            raise ValueError("Completed projection requires raw result")
        output, offline = result["raw_output"], result["offline_only"]
        row.update(result["timing"])
        row.update({"touched_volume": output["touched_volume"], "output_volume": output["stats"]["volume"],
            "output_size": output["stats"]["size"], "method_status": output["status"], "j_act": output["j_act"],
            "j_star": output["j_star"], "region_volume": output["region_volume"],
            "certificate_status": output["certificate"]["certificate_status"], "gap": output["certificate"]["gap"],
            "progress_io_seconds": result["progress_io"]["seconds"], "touched_over_output_volume": offline["touched_over_output_volume"],
            "target_volume": offline["target_volume"], "target_size": offline["target_size"],
            "target_size_outlier": offline["target_size_outlier_from_native_requested_bounds"], "covered": offline["covered"],
            "rho_hat": offline["rho_hat"], "region_outside_truth_volume_ratio": offline["region_outside_truth_volume_ratio"],
            "failure_class": offline["failure_class"], "F1": offline["quality"]["F1"], "hull_best_F1": offline["hull_best_quality"]["F1"]})
    return row


def compare_csv(rows, expected):
    same(len(rows), len(expected), "CSV planned rows")
    if len({r["query_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate CSV query identity")
    fields = sorted({key for row in expected for key in row})
    mapping = {r["query_id"]: r for r in rows}
    same(set(mapping), {r["query_id"] for r in expected}, "CSV full query identity set")
    for target in expected:
        row = mapping[target["query_id"]]
        same(set(row), set(fields), "CSV schema")
        for field in fields:
            value = target.get(field)
            same(row[field], "" if value is None else str(value), "CSV/raw field " + target["query_id"] + "." + field)


def audit(root, run_path):
    root = Path(root).resolve(); run = Path(run_path).resolve()
    if not run.is_relative_to(root / "results"):
        raise ValueError("M6 audit run must be inside workspace results")
    files = {}
    def check(path, expected=None):
        path = Path(path)
        name = str(path.relative_to(root))
        actual = sha(path)
        if expected is not None:
            same(actual, expected, "File " + name)
        if name in files:
            same(actual, files[name], "File changed during offline audit " + name)
        files[name] = actual
        return actual
    auditor_path = portable(root, "experiments/m6_analysis/audit.py")
    same(Path(__file__).resolve(), auditor_path, "Executed auditor canonical source path")
    auditor_source_sha = check(auditor_path)
    manifest_sha = check(run / "manifest.json"); manifest = read(run / "manifest.json")
    summary_sha = check(run / "summary.json"); summary = read(run / "summary.json")
    csv_sha = check(run / "query_summary.csv")
    config = read(root / CONFIG); check(root / CONFIG, manifest["config_sha256"])
    same(manifest["configuration"], config, "Configuration snapshot")
    same(manifest["implementation_version"], VERSION, "Implementation version")
    same(config["implementation_version"], VERSION, "Current implementation")
    same(manifest["source_state"], "SOURCE_FROZEN", "Source freeze")
    same(manifest["legacy_measurements_imported"], False, "Legacy import")
    same(summary["legacy_measurements_imported"], False, "Summary legacy import")
    same(set(manifest["source_sha256"]), SOURCES, "All16 source paths")
    for name, expected in manifest["source_sha256"].items():
        check(portable(root, name), expected)
    dependency = {"python_binary_sha256": sha(Path(sys.executable).resolve()), "python_version": sys.version, "packages": {}}
    for name in ("numpy", "scipy", "numba", "llvmlite"):
        distribution = importlib.metadata.distribution(name)
        record = next((p for p in distribution.files or [] if str(p).endswith(".dist-info/RECORD")), None)
        dependency["packages"][name] = {"version": distribution.version,
            "distribution_record_sha256": sha(distribution.locate_file(record)) if record else None}
    same(dependency, manifest["dependency_fingerprint"], "Actual dependency distribution fingerprint without importing packages")
    same(config["query_wall_limit_seconds"], 600, "Frozen wall budget")
    same(config["query_process_group_rss_limit_bytes"], 12000000000, "Frozen RSS budget")
    limits = {key: config[key] for key in ("query_wall_limit_seconds", "query_process_group_rss_limit_bytes", "resource_poll_seconds")}
    schedule = manifest["schedule"]
    same(len(schedule), 108, "Planned108 queries")
    if len({q["query_id"] for q in schedule}) != 108:
        raise ValueError("Repeated planned query")
    same(Counter(q["n"] for q in schedule), Counter({10000: 36, 100000: 36, 1000000: 36}), "Scale census")
    same(sorted(Counter(q["case_id"] for q in schedule).values()), [12] * 9, "Nine fixed input query counts")
    query_directories = {p.name for p in (run / "queries").glob("*") if p.is_dir()}
    if not query_directories.issubset({q["query_id"] for q in schedule}):
        raise ValueError("Unplanned query directory in this cohort")
    catalog = read(portable(root, config["catalog"])); check(portable(root, config["catalog"]), config["catalog_sha256"])
    same(manifest["catalog_sha256"], config["catalog_sha256"], "Catalog identity")
    cases = {case["case_id"]: case for case in catalog["cases"]}
    same(set(cases), {q["case_id"] for q in schedule}, "Fixed case identity set")
    arrays_by_case = {}; truth_by_case = {}; total_by_case = {}
    planned_rows = []; attempt_records = []; completed_quality = []
    try:
        for case_id in sorted(cases):
            case = cases[case_id]; same(case["status"], "CALIBRATED", "Input calibration status")
            truth_path = portable(root, case["truth_path"]); query_path = portable(root, case["queries_path"])
            check(truth_path, case["truth_sha256"]); check(query_path, case["queries_sha256"])
            truth = read(truth_path)["communities"]; truth_by_case[case_id] = truth
            metadata_path = portable(root, case["csr_path"]) / "csr_metadata.json"
            check(metadata_path, case["csr_metadata_sha256"]); metadata = read(metadata_path)
            same(metadata["n"], case["n"], "CSR input n"); same(metadata["integer_weights"], True, "CSR integral graph")
            same(set(metadata["files"]), {"indptr", "indices", "weights", "degree"}, "CSR arrays")
            same(metadata["sha256"], manifest["csr_full_hash_verification"][case_id], "Prepared input full hash audit")
            arrays = {}
            arrays_by_case[case_id] = arrays
            for key, name in metadata["files"].items():
                file_path = portable(root, str(metadata_path.parent.relative_to(root) / name))
                check(file_path, metadata["sha256"][key]); arrays[key if key != "indptr" else "ptr"] = NpyArray(file_path)
            same(len(arrays["degree"]), case["n"], "Degree count")
            same(len(arrays["ptr"]), case["n"] + 1, "CSR pointer count")
            same(arrays["ptr"][0], 0, "CSR start")
            same(arrays["ptr"][case["n"]], len(arrays["indices"]), "CSR end")
            same(len(arrays["weights"]), len(arrays["indices"]), "Arc weight count")
            same(arrays["indices"].dtype, "<i4", "Frozen readonly neighbor signature")
            same(arrays["ptr"].dtype, "<i8", "Frozen readonly offset signature")
            total_by_case[case_id] = int(metadata["total_volume"])
            fixed_queries = read(query_path)["queries"]
            same(len(fixed_queries), 12, "Actual fixed input query count")
            selected = [q for q in schedule if q["case_id"] == case_id]
            same([q["query_index"] for q in selected], list(range(12)), "Fixed query index order")
            for q, actual in zip(selected, fixed_queries):
                same(q, {"query_id": case_id + "_q%02d" % q["query_index"], "case_id": case_id, "n": case["n"],
                    "generation_seed": case["generation_seed"], "query_index": q["query_index"], "seed": actual["seed"],
                    "csr_path": case["csr_path"], "csr_metadata_sha256": case["csr_metadata_sha256"],
                    "csr_array_sha256": metadata["sha256"], "native_network_sha256": metadata["source_network_sha256"],
                    "native_community_sha256": metadata["source_community_sha256"], "offline_only": {
                        "community_index": actual["community_index"], "truth_path": case["truth_path"], "truth_sha256": case["truth_sha256"],
                        "queries_path": case["queries_path"], "queries_sha256": case["queries_sha256"]}}, "Entire fixed schedule query")
        for q in schedule:
            base = run / "queries" / q["query_id"]
            attempts = sorted(base.glob("attempt_*")); latest_terminal = latest_result = None
            for index, directory in enumerate(attempts):
                same(directory.name, "attempt_%03d" % index, "Contiguous immutable attempts")
                request_path = directory / "request.json"
                request_sha = check(request_path); request = read(request_path)
                same(request, {"schema_version": 1, "mode": "formal", "query_id": q["query_id"], "implementation_version": VERSION,
                    "query": q, "method_config": config["method_config"], "source_sha256": manifest["source_sha256"],
                    "manifest_path": str((run / "manifest.json").relative_to(root)), "manifest_sha256": manifest_sha,
                    "resource_limits": limits}, "Full request specification")
                terminal_path = directory / "terminal.json"
                terminal = read(terminal_path) if terminal_path.exists() else None
                result = None
                hashes = {"request.json": request_sha}
                if terminal is not None:
                    if terminal["status"] not in TERMINAL:
                        raise ValueError("Unknown terminal status")
                    hashes["terminal.json"] = check(terminal_path)
                    same(terminal["request_sha256"], request_sha, "Terminal request SHA")
                    same(terminal["limits"], limits, "Terminal budgets")
                    same(terminal["implementation_version"], VERSION, "Terminal implementation")
                    same(terminal["actual_cwd"], str(root), "Terminal cwd")
                    same(terminal["actual_argv"], ["/usr/bin/time", "-l", str(root / ".venv/bin/python"),
                        "experiments/m6_prepared/worker.py", "--request", str(request_path.relative_to(root))], "Actual worker command")
                    same(terminal["runtime_censored"], terminal["status"] in {"timeout", "memory_limit", "interrupted"}, "Censored status")
                    same(read(directory / "controller.json"), terminal, "Durable controller/terminal record")
                    for name, field in (("result.json", "result_sha256"), ("error.json", "error_sha256"),
                                        ("stdout.log", "stdout_sha256"), ("stderr.log", "stderr_sha256")):
                        path = directory / name
                        actual = check(path) if path.exists() else None
                        same(actual, terminal.get(field), "Terminal artifact SHA " + name)
                    if (directory / "checkpoint.json").exists():
                        same(read(directory / "checkpoint.json"), terminal["last_checkpoint"], "Final checkpoint snapshot")
                    if terminal["status"] == "completed":
                        if index != len(attempts) - 1:
                            raise ValueError("Frozen controller cannot retry a completed query")
                        same(terminal["returncode"], 0, "Completed process returncode")
                        result = read(directory / "result.json")
                        same(result["status"], "completed", "Raw completed status")
                        same(result["mode"], "formal", "Raw formal mode")
                        same(result["query_id"], q["query_id"], "Raw query identity")
                        same(result["n"], q["n"], "Raw graph size")
                        same(result["seed"], q["seed"], "Raw seed")
                        same(result["implementation_version"], VERSION, "Raw implementation")
                        same(result["request_sha256"], request_sha, "Raw request hash")
                        same(result["input"], q, "Raw full input context")
                        same(result["provenance"], {"method_config": config["method_config"], "source_sha256": manifest["source_sha256"]}, "Raw source/config context")
                        same(result["raw_output"]["config"], config["method_config"], "Raw method configuration")
                        same(result["readonly_csr_signatures_match_warmup"], True, "Readonly signature match")
                        same(result["signature_added_during_method"], False, "No timed new signature")
                        for field, value in result["timing"].items():
                            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                                raise ValueError("Invalid actual timing telemetry: " + field)
                        recomputed = independent_offline(q, result["raw_output"], truth_by_case[q["case_id"]], arrays_by_case[q["case_id"]], total_by_case[q["case_id"]])
                        same(result["offline_only"], recomputed, "All independent offline truth/cover/quality fields")
                        completed_quality.append({"query_id": q["query_id"], "attempt": str(directory.relative_to(root)),
                            "F1": recomputed["quality"]["F1"], "hull_F1": recomputed["hull_best_quality"]["F1"],
                            "C_subset_R": recomputed["covered"], "failure_class": recomputed["failure_class"]})
                # Inventory all original logical files, including prior/failed/
                # partial progress. A partial result never receives quality.
                for path in sorted(directory.rglob("*")):
                    if path.is_file():
                        if path.is_symlink():
                            raise ValueError("Attempt file symlink is not immutable raw")
                        hashes[str(path.relative_to(directory))] = check(path)
                attempt_records.append({"query_id": q["query_id"], "directory": str(directory.relative_to(root)),
                    "status": terminal["status"] if terminal else "interrupted_unfinished",
                    "artifact_sha256": hashes, "quality_recomputed": terminal is not None and terminal["status"] == "completed"})
                if index == len(attempts) - 1:
                    latest_terminal, latest_result = terminal, result
            planned_rows.append(projected_row(q, config, len(attempts), str(attempts[-1].relative_to(root)) if attempts else None, latest_terminal, latest_result))
        actual_rows = list(csv.DictReader((run / "query_summary.csv").open()))
        compare_csv(actual_rows, planned_rows)
        counts = dict(Counter(r["status"] for r in planned_rows))
        same(summary["manifest_sha256"], manifest_sha, "Summary manifest SHA")
        same(summary["implementation_version"], VERSION, "Summary implementation")
        same(summary["scheduled_queries"], 108, "Summary all-query denominator")
        same(summary["completed_queries"], counts.get("completed", 0), "Summary completed count")
        same(summary["all_queries_completed"], counts.get("completed", 0) == 108, "Summary completion claim")
        same(summary["status_counts"], counts, "Summary status counts")
        same(summary["status_counts_by_n"], {str(n): dict(Counter(r["status"] for r in planned_rows if r["n"] == n)) for n in (10000, 100000, 1000000)}, "Summary scale denominators")
        # Recheck current derived inputs and all files to expose mutation while
        # auditing. This is offline cost; it never changes a method clock.
        for name, expected in files.items():
            same(sha(portable(root, name)), expected, "Bytes stable during audit " + name)
        return {"schema_version": 1, "status": "PASS", "cohort_origin": "FRESH_REPRODUCTION" if (root / ".REPRODUCTION_WORKSPACE.json").exists() else "ORIGINAL_FROZEN_COHORT",
            "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "run_path": str(run.relative_to(root)),
            "implementation_version": VERSION, "manifest_sha256": manifest_sha, "config_sha256": manifest["config_sha256"],
            "summary_sha256": summary_sha, "query_csv_sha256": csv_sha, "source_sha256": manifest["source_sha256"],
            "scheduled_queries": 108, "completed_queries": counts.get("completed", 0), "all_queries_completed": counts.get("completed", 0) == 108,
            "status_counts": counts, "attempt_records": attempt_records, "completed_quality_checks": completed_quality,
            "query_records": planned_rows, "dependency_fingerprint": dependency,
            "validated_files_sha256": files, "auditor_source_sha256": auditor_source_sha, "quality_for_noncompleted": "NONE; all planned rows preserved",
            "independent_checks": ["108 fixed identities and all immutable attempts", "All16 frozen source bytes; configuration; fixed CSR/truth/query bytes", "Full request/command/budget/terminal/result SHA and context", "Every CSV cell matches raw telemetry projection", "Independent integer CSR stats, full truth cover, F1/hull-F1, rho and H1/H2"],
            "algorithm_or_numpy_imported": False, "measurement_sources_inputs_raw_or_timers_modified": False,
            "limitations": ["A PASS integrity audit does not establish G-E3 or uncensored full-cohort performance", "Statistical fit estimates are not re-fitted by this audit", "Readonly snapshot verification requires quiescent artifacts; rerun summary if current CSV is stale"]}
    finally:
        for arrays in arrays_by_case.values():
            for array in arrays.values():
                array.close()


def verify_audit_receipt(receipt_path, run_path=None, verify_files=False):
    path = Path(receipt_path).resolve(); receipt = read(path)
    if receipt.get("status") != "PASS" or receipt.get("schema_version") != 1:
        raise ValueError("Missing valid PASS M6 audit receipt")
    supplied_hash = receipt.get("receipt_payload_sha256")
    same(supplied_hash, object_sha({k: v for k, v in receipt.items() if k != "receipt_payload_sha256"}), "Audit receipt payload")
    candidates = [p for p in path.parents if (p / CONFIG).exists()]
    if len(candidates) != 1:
        raise ValueError("Audit receipt must resolve to one workspace root")
    root = candidates[0]
    run = portable(root, receipt["run_path"])
    if run_path is not None:
        same(Path(run_path).resolve(), run, "Audit target run")
    same(receipt["implementation_version"], VERSION, "Audit implementation")
    same(receipt["cohort_origin"], "FRESH_REPRODUCTION" if (root / ".REPRODUCTION_WORKSPACE.json").exists() else "ORIGINAL_FROZEN_COHORT", "Audit origin identity")
    same(receipt["scheduled_queries"], 108, "Audit denominator")
    if receipt.get("algorithm_or_numpy_imported") is not False or receipt.get("measurement_sources_inputs_raw_or_timers_modified") is not False:
        raise ValueError("Receipt does not declare independent readonly audit scope")
    if not receipt.get("validated_files_sha256") or len(receipt.get("query_records", [])) != 108:
        raise ValueError("Empty audit file/full-query inventory")
    records = receipt["query_records"]
    if len({r["query_id"] for r in records}) != 108:
        raise ValueError("Audit full query inventory repeats identities")
    same(dict(Counter(r["status"] for r in records)), receipt["status_counts"], "Audit query/status census")
    same(receipt["completed_queries"], sum(r["status"] == "completed" for r in records), "Audit query completion census")
    same(receipt["all_queries_completed"], receipt["completed_queries"] == 108, "Audit full completion claim")
    manifest, config = read(run / "manifest.json"), read(root / CONFIG)
    same(set(receipt["source_sha256"]), SOURCES, "Receipt all16 source paths")
    same(receipt["source_sha256"], manifest["source_sha256"], "Receipt/manifest source identity")
    same(config, manifest["configuration"], "Receipt current configuration snapshot")
    same(manifest["config_sha256"], receipt["config_sha256"], "Receipt manifest configuration SHA")
    same(manifest["implementation_version"], VERSION, "Receipt manifest version")
    same(manifest["source_state"], "SOURCE_FROZEN", "Receipt source freeze")
    same(manifest["legacy_measurements_imported"], False, "Receipt legacy import")
    same(receipt["dependency_fingerprint"], manifest["dependency_fingerprint"], "Receipt dependency fingerprint")
    scheduled = {q["query_id"]: q for q in manifest["schedule"]}
    same(len(manifest["schedule"]), 108, "Receipt planned schedule count")
    same(Counter(q["n"] for q in manifest["schedule"]), Counter({10000: 36, 100000: 36, 1000000: 36}), "Receipt scale census")
    same(sorted(Counter(q["case_id"] for q in manifest["schedule"]).values()), [12] * 9, "Receipt nine fixed cases")
    same(set(scheduled), {r["query_id"] for r in records}, "Receipt whole-query identities")
    for row in records:
        q = scheduled[row["query_id"]]
        for field in ("case_id", "n", "generation_seed", "seed"):
            same(row[field], q[field], "Receipt fixed query field " + field)
        if row["status"] not in TERMINAL | {"NOT_RUN", "interrupted_unfinished"}:
            raise ValueError("Unknown audit query status")
        if row["status"] != "completed" and any(field in row for field in (
                "F1", "hull_best_F1", "covered", "rho_hat", "failure_class", "target_size", "target_volume",
                "target_size_outlier", "region_outside_truth_volume_ratio", "touched_over_output_volume")):
            raise ValueError("Noncompleted audit row contains completed-only quality/cover metrics")
    compare_csv(list(csv.DictReader((run / "query_summary.csv").open())), records)
    same(len(receipt["completed_quality_checks"]), receipt["completed_queries"], "Receipt completed independent quality census")
    completed = {r["query_id"]: r for r in records if r["status"] == "completed"}
    checked = {r["query_id"]: r for r in receipt["completed_quality_checks"]}
    same(len(checked), len(receipt["completed_quality_checks"]), "Unique completed quality identities")
    same(set(checked), set(completed), "Completed quality/query identity set")
    for key, row in completed.items():
        value = checked[key]
        same(value, {"query_id": key, "attempt": row["raw_directory"], "F1": row["F1"],
            "hull_F1": row["hull_best_F1"], "C_subset_R": row["covered"], "failure_class": row["failure_class"]}, "Completed independent quality/attempt binding")
        for field in ("F1", "hull_F1"):
            if type(value[field]) not in (int, float) or not math.isfinite(value[field]) or not 0 <= value[field] <= 1:
                raise ValueError("Invalid independently audited completed quality")
        if type(value["C_subset_R"]) is not bool:
            raise ValueError("Completed cover claim must be boolean")
        same(value["failure_class"], None if value["F1"] == 1 else "H2" if value["C_subset_R"] else "H1", "Completed H1/H2/quality consistency")
    attempts_by_query = {}
    for attempt in receipt["attempt_records"]:
        key = attempt["query_id"]
        if key not in scheduled or attempt["status"] not in TERMINAL | {"interrupted_unfinished"}:
            raise ValueError("Unknown receipt attempt identity/status")
        attempts_by_query.setdefault(key, []).append(attempt)
        hashes = attempt["artifact_sha256"]
        if "request.json" not in hashes or (attempt["status"] == "completed" and not {"terminal.json", "result.json"}.issubset(hashes)):
            raise ValueError("Missing audited request/terminal/result identity")
        for name, digest in hashes.items():
            path = portable(root, attempt["directory"] + "/" + name)
            relative = str(path.relative_to(root))
            same(receipt["validated_files_sha256"].get(relative), digest, "Attempt/fullfile identity")
    for row in records:
        group = attempts_by_query.get(row["query_id"], [])
        same(row["attempt_count"], len(group), "Receipt row/all-attempt census")
        for index, attempt in enumerate(group):
            expected = str(run.relative_to(root)) + "/queries/" + row["query_id"] + "/attempt_%03d" % index
            same(attempt["directory"], expected, "Contiguous receipt attempt path")
        if group:
            same(row["status"], group[-1]["status"], "Receipt latest-attempt outcome")
            same(row["raw_directory"], group[-1]["directory"], "Receipt latest-attempt path")
        else:
            same(row["status"], "NOT_RUN", "Absent attempt status")
    check = {str((run / "manifest.json").relative_to(root)): receipt["manifest_sha256"], CONFIG: receipt["config_sha256"],
             str((run / "summary.json").relative_to(root)): receipt["summary_sha256"],
             str((run / "query_summary.csv").relative_to(root)): receipt["query_csv_sha256"],
             "experiments/m6_analysis/audit.py": receipt["auditor_source_sha256"]}
    check.update(receipt["source_sha256"])
    for name, expected in check.items():
        if name != "experiments/m6_analysis/audit.py":
            same(receipt["validated_files_sha256"].get(name), expected, "Receipt validated-file identity " + name)
    if verify_files:
        check.update(receipt["validated_files_sha256"])
    for name, expected in check.items():
        same(sha(portable(root, name)), expected, "Current audit-bound bytes " + name)
    summary = read(run / "summary.json")
    same(receipt["completed_queries"], summary["completed_queries"], "Audit/summary completion count")
    same(receipt["status_counts"], summary["status_counts"], "Audit/summary statuses")
    return {key: receipt[key] for key in ("status", "cohort_origin", "implementation_version", "manifest_sha256", "summary_sha256", "query_csv_sha256", "scheduled_queries", "completed_queries", "all_queries_completed", "status_counts")} | {"audit_receipt_sha256": sha(path), "files_reverified_now": bool(verify_files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=DEFAULT_RUN)
    parser.add_argument("--output", default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not (output.is_relative_to(ROOT / "results/m6_analysis") or output.is_relative_to(ROOT / "reviews/m6_analysis")):
        parser.error("Audit evidence writes restricted to derived M6 audit scopes")
    if output.exists():
        # A previous bounded/resumed cohort may have a stale derived receipt.
        # Preserve its exact bytes by content hash before updating the canonical
        # derived view; original measurements are never overwritten.
        try:
            verification = verify_audit_receipt(output, run_path=ROOT / args.run, verify_files=True)
            print(json.dumps(verification)); return
        except (ValueError, FileNotFoundError, KeyError, json.JSONDecodeError):
            old_sha = sha(output)
            history = output.parent / "history" / (old_sha + ".json")
            history.parent.mkdir(parents=True, exist_ok=True)
            if history.exists():
                same(sha(history), old_sha, "Preserved previous audit receipt")
            else:
                with history.open("xb") as stream:
                    stream.write(output.read_bytes())
    value = audit(ROOT, ROOT / args.run)
    value["receipt_payload_sha256"] = object_sha(value)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2); stream.write("\n")
    os.replace(temporary, output)
    print(json.dumps({"status": value["status"], "scheduled_queries": 108, "completed_queries": value["completed_queries"], "receipt": str(output.relative_to(ROOT))}))


if __name__ == "__main__":
    main()
