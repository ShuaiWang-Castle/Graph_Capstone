"""Analysis-only cohort integrity checks; never import or execute an algorithm.

Read integrity fields in immutable records. Do not aggregate quality or timing.
The audit accepts NOT_RUN/failed tasks, while validating every available record.
"""
from __future__ import annotations
import argparse
import copy
import gzip
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.archival import read_bytes as archival_read_bytes


def sha(path):
    if not Path(path).exists():
        return hashlib.sha256(archival_read_bytes(path)).hexdigest()
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    path = Path(path)
    data = archival_read_bytes(path)
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def equal(errors, field, actual, expected):
    if actual != expected:
        errors.append(field + ": differs or missing")


def within_root(relative):
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("Nonportable or escaping record path")
    return ROOT / p


def m4_fields(manifest, job, raw=None, started=None, job_sha=None):
    errors = []
    backend = manifest.get("implementation", {}).get("exact_cut_backend", "original_exact")
    equal(errors, "job.source_sha256", job.get("source_sha256"), manifest["source_sha256"])
    equal(errors, "job.protocol_sha256", job.get("protocol_sha256"), manifest["protocol_sha256"])
    equal(errors, "job.backend", job.get("implementation_exact_cut_backend", "original_exact"), backend)
    if started is not None:
        equal(errors, "started.task", started.get("task"), job["task"])
        equal(errors, "started.job_sha256", started.get("job_sha256"), job_sha)
    if raw is not None:
        for name in ("task", "method", "setting", "configuration", "source_sha256", "protocol_sha256"):
            equal(errors, "raw." + name, raw.get(name), job.get(name))
        equal(errors, "raw.backend", raw.get("implementation_exact_cut_backend", "original_exact"), backend)
        entry = job["query"]
        equal(errors, "raw.seed", raw.get("seed"), int(entry["seed"]))
        expected_input = {k: v for k, v in entry.items() if k not in ("truth_vertices", "communities")}
        equal(errors, "raw.input", raw.get("input"), expected_input)
        equal(errors, "raw.command", raw.get("command"), [".venv/bin/python", "experiments/worker.py", "--job", started["job_path"]] if started and "job_path" in started else raw.get("command"))
        equal(errors, "raw.truth_in_method_path", raw.get("truth_in_method_path"), job.get("setting") == "oracle")
        if job.get("setting") != "oracle":
            equal(errors, "raw.oracle_volume", raw.get("oracle_volume"), None)
        elif not isinstance(raw.get("oracle_volume"), (int, float)) or not math.isfinite(raw["oracle_volume"]) or raw["oracle_volume"] <= 0:
            errors.append("raw.oracle_volume: explicit numeric scalar absent")
    return errors


def m6_fields(manifest, query, request, result=None, terminal=None, request_sha=None, manifest_sha=None):
    errors = []
    cfg = manifest["configuration"]
    equal(errors, "request.mode", request.get("mode"), "formal")
    equal(errors, "request.query_id", request.get("query_id"), query["query_id"])
    equal(errors, "request.query", request.get("query"), query)
    equal(errors, "request.version", request.get("implementation_version"), manifest["implementation_version"])
    equal(errors, "request.source_sha256", request.get("source_sha256"), manifest["source_sha256"])
    equal(errors, "request.method_config", request.get("method_config"), cfg["method_config"])
    equal(errors, "request.manifest_path", request.get("manifest_path"), "results/m6_prepared/manifest.json")
    equal(errors, "request.manifest_sha256", request.get("manifest_sha256"), manifest_sha)
    limits = {k: cfg[k] for k in ("query_wall_limit_seconds", "query_process_group_rss_limit_bytes", "resource_poll_seconds")}
    equal(errors, "request.resource_limits", request.get("resource_limits"), limits)
    if terminal is not None:
        equal(errors, "terminal.version", terminal.get("implementation_version"), manifest["implementation_version"])
        equal(errors, "terminal.request_sha256", terminal.get("request_sha256"), request_sha)
        equal(errors, "terminal.limits", terminal.get("limits"), limits)
        if terminal.get("status") == "completed":
            equal(errors, "terminal.returncode", terminal.get("returncode"), 0)
            if result is None:
                errors.append("terminal.completed: result absent")
    if result is not None:
        for name, expected in (("mode", "formal"), ("query_id", query["query_id"]),
                               ("implementation_version", manifest["implementation_version"]),
                               ("request_sha256", request_sha), ("input", query),
                               ("n", query["n"]), ("seed", query["seed"])):
            equal(errors, "result." + name, result.get(name), expected)
        equal(errors, "result.provenance", result.get("provenance"),
              {"method_config": cfg["method_config"], "source_sha256": manifest["source_sha256"]})
        equal(errors, "result.raw_output.config", result.get("raw_output", {}).get("config"), cfg["method_config"])
        if terminal and terminal.get("status") == "completed":
            equal(errors, "result.status", result.get("status"), "completed")
    return errors


def audit_m4(relative):
    folder = within_root(relative)
    manifest = read(folder / "manifest.json")
    records, errors, warnings, statuses, seen = [], [], [], Counter(), set()
    for job_path in manifest["jobs"]:
        try:
            job_file = within_root(job_path)
            job = read(job_file)
            if job["task"] in seen:
                raise ValueError("Duplicate task ID in manifest")
            seen.add(job["task"])
            result = within_root(job["result_path"])
            if result.parent != folder / "raw":
                raise ValueError("Raw path points outside this cohort")
            if job_file.parent != folder / "jobs":
                raise ValueError("Job path points outside this cohort")
            raw = read(result) if result.exists() else None
            started_path = folder / "logs" / (job["task"] + ".started.json")
            started = read(started_path) if started_path.exists() else None
            if started is not None:
                started["job_path"] = job_path
            issues = m4_fields(manifest, job, raw, started, sha(job_file))
            failure_path = result.with_suffix(".failure.json")
            failure = read(failure_path) if failure_path.exists() else None
            if failure:
                equal(issues, "failure.task", failure.get("task"), job["task"])
                equal(issues, "failure.job", failure.get("job"), job_path)
                if failure.get("completion_claim") is not False:
                    issues.append("failure.completion_claim: must be false")
            if raw is not None and started is None:
                if manifest.get("implementation", {}).get("exact_cut_backend") == "prepared_region_workspace":
                    issues.append("Prepared raw record has no durable started/job-hash record")
                else:
                    warnings.append({"task": job["task"], "limitation": "Legacy original-exact record predates durable started/job-hash logging; source/protocol/job/raw consistency still checked"})
            status = failure["status"] if failure else raw.get("status", "UNKNOWN") if raw else "NOT_RUN"
            statuses[status] += 1
            if issues:
                errors.append({"task": job["task"], "issues": issues})
            if raw is not None or failure is not None:
                records.append({"task": job["task"], "status": status,
                    "job_sha256": sha(job_file), "raw_sha256": sha(result) if raw is not None else None,
                    "failure_sha256": sha(failure_path) if failure else None})
        except Exception as error:
            errors.append({"job_path": job_path, "read_error": repr(error)})
    return {"cohort": relative, "kind": "M4", "manifest_sha256": sha(folder / "manifest.json"),
        "implementation": manifest.get("implementation", {"exact_cut_backend": "original_exact"}),
        "planned": len(manifest["jobs"]), "status_counts": dict(statuses),
        "available_records": records, "errors": errors, "warnings": warnings,
        "status": "PASS" if not errors else "FAIL"}


def audit_m6(relative):
    folder = within_root(relative)
    manifest_path = folder / "manifest.json"
    manifest = read(manifest_path)
    records, errors, statuses, seen = [], [], Counter(), set()
    for query in manifest["schedule"]:
        query_id = query["query_id"]
        if query_id in seen:
            errors.append({"query_id": query_id, "issues": ["Duplicate query ID"]})
        seen.add(query_id)
        attempts = sorted((folder / "queries" / query_id).glob("attempt_*"))
        if not attempts:
            statuses["NOT_RUN"] += 1
        for directory in attempts:
            try:
                request_path = directory / "request.json"
                request = read(request_path)
                result_path, terminal_path = directory / "result.json", directory / "terminal.json"
                result = read(result_path) if result_path.exists() else None
                terminal = read(terminal_path) if terminal_path.exists() else None
                issues = m6_fields(manifest, query, request, result, terminal, sha(request_path), sha(manifest_path))
                if terminal is not None:
                    equal(issues, "terminal.result_sha256", terminal.get("result_sha256"), sha(result_path) if result else None)
                for name in ("method_result.json", "workspace_summary.json", "error.json"):
                    path = directory / name
                    if path.exists():
                        sidecar = read(path)
                        equal(issues, name + ".version", sidecar.get("implementation_version"), manifest["implementation_version"])
                        if name == "method_result.json":
                            equal(issues, name + ".query_id", sidecar.get("query_id"), query_id)
                            equal(issues, name + ".raw_output.config", sidecar.get("raw_output", {}).get("config"), manifest["configuration"]["method_config"])
                status = terminal.get("status", "UNKNOWN") if terminal else "interrupted_unfinished"
                if directory == attempts[-1]:
                    statuses[status] += 1
                record = {"query_id": query_id, "attempt": str(directory.relative_to(ROOT)),
                    "status": status, "request_sha256": sha(request_path),
                    "result_sha256": sha(result_path) if result else None}
                records.append(record)
                if issues:
                    errors.append({"attempt": record["attempt"], "issues": issues})
            except Exception as error:
                errors.append({"attempt": str(directory.relative_to(ROOT)), "read_error": repr(error)})
    return {"cohort": relative, "kind": "M6", "manifest_sha256": sha(manifest_path),
        "implementation_version": manifest["implementation_version"], "planned": len(manifest["schedule"]),
        "status_counts": dict(statuses), "available_records": records,
        "errors": errors, "status": "PASS" if not errors else "FAIL"}


def fixtures():
    """Static dictionaries only; deliberate cohort copying, no subprocesses."""
    source = {"core.py": "frozen"}
    manifest4 = {"source_sha256": source, "protocol_sha256": "protocol2", "implementation": {"exact_cut_backend": "prepared_region_workspace"}}
    job = {"task": "q0_main", "method": "zrhfd", "setting": "no_volume", "configuration": {"sigma": .0001},
           "source_sha256": source, "protocol_sha256": "protocol2", "implementation_exact_cut_backend": "prepared_region_workspace",
           "query": {"seed": 0, "graph_path": "data/g.json", "truth_vertices": [0], "communities": [[0]]}}
    raw = {**{k: v for k, v in job.items() if k != "query"}, "seed": 0,
           "input": {"seed": 0, "graph_path": "data/g.json"}, "truth_in_method_path": False, "oracle_volume": None}
    cfg = {"method_config": {"sigma": .0001}, "query_wall_limit_seconds": 600,
           "query_process_group_rss_limit_bytes": 12000000000, "resource_poll_seconds": 1.0}
    manifest6 = {"configuration": cfg, "implementation_version": "prepared", "source_sha256": source}
    query = {"query_id": "q0", "seed": 0, "n": 5, "offline_only": {"truth_path": "data/truth.json"}}
    request = {"mode": "formal", "query_id": "q0", "query": query, "implementation_version": "prepared",
               "source_sha256": source, "method_config": cfg["method_config"],
               "manifest_path": "results/m6_prepared/manifest.json", "manifest_sha256": "manifest2",
               "resource_limits": {k: v for k, v in cfg.items() if k != "method_config"}}
    result = {"mode": "formal", "query_id": "q0", "implementation_version": "prepared", "request_sha256": "request2",
              "input": query, "n": 5, "seed": 0, "status": "completed",
              "provenance": {"method_config": cfg["method_config"], "source_sha256": source},
              "raw_output": {"config": cfg["method_config"]}}
    out = []
    def record(name, errors, must_reject):
        out.append({"name": name, "expected": "REJECT" if must_reject else "ACCEPT",
                    "issues": errors, "passed": bool(errors) == must_reject})
    record("M4_same_cohort", m4_fields(manifest4, job, raw), False)
    for name, field, value in [("M4_old_source", "source_sha256", {"core.py": "old"}),
                               ("M4_old_protocol", "protocol_sha256", "protocol1"),
                               ("M4_old_backend", "implementation_exact_cut_backend", "original_exact"),
                               ("M4_wrong_seed", "seed", 1),
                               ("M4_wrong_config", "configuration", {"sigma": .001}),
                               ("M4_truth_leak_marker", "truth_in_method_path", True)]:
        changed = copy.deepcopy(raw); changed[field] = value
        record(name, m4_fields(manifest4, job, changed), True)
    record("M6_same_cohort", m6_fields(manifest6, query, request, result, request_sha="request2", manifest_sha="manifest2"), False)
    for name, field, value in [("M6_old_version", "implementation_version", "old"),
                               ("M6_wrong_query", "query_id", "q1"),
                               ("M6_wrong_request", "request_sha256", "request1"),
                               ("M6_wrong_seed", "seed", 1),
                               ("M6_old_source", "provenance", {"method_config": cfg["method_config"], "source_sha256": {"core.py": "old"}}),
                               ("M6_changed_config", "raw_output", {"config": {"sigma": .001}})]:
        changed = copy.deepcopy(result); changed[field] = value
        record(name, m6_fields(manifest6, query, request, changed, request_sha="request2", manifest_sha="manifest2"), True)
    changed = copy.deepcopy(request); changed["manifest_sha256"] = "old_manifest"
    record("M6_old_manifest", m6_fields(manifest6, query, changed, result, request_sha="request2", manifest_sha="manifest2"), True)
    return out


def archived_storage_fixtures():
    """Resolve root-created storage fixtures; do not run the archiver."""
    records = []
    base = ROOT / "results/storage_fixtures/verified_archival_v001"
    for status in ("COMPLETED", "FAILED", "TIMEOUT"):
        directory = base / status
        metadata = read(directory / "ARCHIVE.json")
        issues = []
        equal(issues, "archive_sha256", sha(directory / metadata["archive"]), metadata["archive_sha256"])
        for name, expected in metadata["files"].items():
            original_path = directory / name
            data = archival_read_bytes(original_path)
            equal(issues, name + ".sha256", hashlib.sha256(data).hexdigest(), expected["sha256"])
            equal(issues, name + ".bytes", len(data), expected["bytes"])
            if name.endswith(".json"):
                equal(issues, name + ".json_reader", read(original_path), json.loads(data))
        records.append({"terminal_status": status, "index_sha256": sha(directory / "ARCHIVE.json"),
            "members": len(metadata["files"]), "status": "PASS" if not issues else "FAIL", "issues": issues})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m4", action="append", default=[], help="Relative M4 run directory")
    parser.add_argument("--m6", help="Relative prepared M6 run directory")
    parser.add_argument("--fixtures", action="store_true")
    parser.add_argument("--archived-storage-fixtures", action="store_true")
    parser.add_argument("--output", required=True, help="Receipt path within reviews/prepared_backend_adoption")
    args = parser.parse_args()
    output = within_root(args.output)
    if not output.is_relative_to(ROOT / "reviews/prepared_backend_adoption"):
        parser.error("Receipt writes are restricted to reviews/prepared_backend_adoption")
    result = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "audit_source_sha256": sha(__file__),
              "archival_reader_source_sha256": sha(ROOT / "experiments/archival.py"),
              "scope": "Integrity only; no algorithm, quality aggregation, timing analysis, or current-source substitution", "cohorts": []}
    if args.fixtures:
        result["fixtures"] = fixtures()
    if args.archived_storage_fixtures:
        result["archived_storage_fixtures"] = archived_storage_fixtures()
    result["cohorts"].extend(audit_m4(path) for path in args.m4)
    if args.m6:
        result["cohorts"].append(audit_m6(args.m6))
    result["status"] = "PASS" if all(c["status"] == "PASS" for c in result["cohorts"]) and all(f["passed"] for f in result.get("fixtures", [])) and all(f["status"] == "PASS" for f in result.get("archived_storage_fixtures", [])) else "FAIL"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "cohorts": [{k: c[k] for k in ("cohort", "status", "planned", "status_counts")} for c in result["cohorts"]], "fixtures": len(result.get("fixtures", [])), "errors": sum(len(c["errors"]) for c in result["cohorts"])}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
