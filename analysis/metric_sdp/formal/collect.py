"""Stdlib-only prospective 43x5 accounting; no proof replay or scientific runs.

Reported exactness is not independently verified here. Scientific credit and
paired target-qualified costs require an externally pinned independent closeout
covering the complete immutable raw inventory and every one of the 215 outcomes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics


ROOT = Path(__file__).resolve().parents[3]
BASE = "analysis/metric_sdp/formal/"
ARMS = ("U", "S", "D", "SD", "SW")
AUTHOR = "/root/experiment_supervisor"
SCHEMA = "metric-sdp-formal-descriptive-collection-v1"
AUDIT_SCHEMA = "metric-sdp-formal-independent-exactness-closeout-v1"
SOURCES = (BASE + "__init__.py", BASE + "collect.py")
CONTRACT = BASE + "fixed-contract.json"
PACKET = BASE + "prospective-analysis-manifest.json"
PILOT = "experiments/extensions/metric_sdp/"
FORMAL = "experiments/extensions/metric_sdp_formal/"
OPERATOR = FORMAL + "formal_launch_operator.py"
RUNTIME_PATHS = (
    "src/degree_contraction/__init__.py", "src/degree_contraction/certificate.py",
    "src/degree_contraction/quotient.py", "experiments/candidates.py",
    "experiments/datasets.py", "experiments/families.py", "experiments/pipeline.py",
    "experiments/extensions/__init__.py", "research/baselines/weighted_reference.py",
    *(PILOT + x for x in ("__init__.py", "rational.py", "safe_composition.py",
                          "numerical.py", "runtime.py", "freeze.py", "run_case.py",
                          "run_pilot.py")),
    *(FORMAL + x for x in ("__init__.py", "composition.py", "runtime.py",
                           "freeze.py", "run_case.py", "run_study.py")),
)
STAGES = {
    "original_graph_preparation", "common_discovery_and_bank",
    "original_discovery_incumbent", "original_input_checkpoint", "safe_composition",
    "quotient_objective_and_validation", "signed_component_presolve", "checkpoint",
    "analytic_singleton_validation", "model_canonicalization", "solver",
    "proposal_extraction", "triangle_separation", "rational_repair_and_exact_validation",
    "lift_exact_validation",
}
WORKER_NAME = re.compile(
    r"(?:input|timer-start|compute-finished|original-preparation|preprocessing|result|failure)\.json"
    r"|original-adjacency\.npz|composition-operation-\d{4}\.json"
    r"|component-\d{3}-(?:proof\.json|round-\d{3}-(?:raw\.npz|metrics\.json))")


class CollectionError(ValueError):
    pass


def require(value, message):
    if not value:
        raise CollectionError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result
    def reject(value):
        raise CollectionError("nonstandard JSON constant: " + value)
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=reject)


def relative(root, path):
    return Path(path).resolve().relative_to(root).as_posix()


def safe_path(root, path):
    require(isinstance(path, str) and path and not Path(path).is_absolute(),
            "artifact path must be relative")
    require(".." not in Path(path).parts, "artifact path traversal")
    result = root / path
    require(not result.is_symlink(), "symlink artifact")
    require(result.resolve().is_relative_to(root), "artifact escapes project")
    return result


def number(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "invalid nonnegative finite " + label)
    return value


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, "invalid integer " + label)
    return value


def exact(value, label):
    require(isinstance(value, str), "exact rational must be a string: " + label)
    try:
        answer = F(value)
    except (ValueError, ZeroDivisionError) as error:
        raise CollectionError("invalid exact rational " + label) from error
    require(str(answer) == value, "noncanonical exact rational " + label)
    return answer


def fixed_schedule(contract):
    jobs = []
    for case_index, case in enumerate(contract["cases"]):
        rotation = ARMS[case_index % 5:] + ARMS[:case_index % 5]
        for arm in rotation:
            jobs.append({"case_id": case["case_id"], "case_index": case_index,
                         "arm": arm, "backend": contract["solver"]["backend"]})
    return jobs


def source_sha256():
    base = Path(__file__).resolve().parent
    return {SOURCES[0]: sha256(base / "__init__.py"), SOURCES[1]: sha256(base / "collect.py")}


def authenticate(root, config_path, freeze_path, expected_config_sha, expected_freeze_sha):
    contract = read_json(Path(__file__).resolve().parent / "fixed-contract.json")
    require(contract["case_count"] == 43 and contract["job_count"] == 215
            and contract["primary_pair_count"] == 86 and contract["arms"] == list(ARMS),
            "collector's fixed denominator contract")
    require(expected_config_sha == contract["config_sha256"], "external config pin differs from contract")
    config, frozen = read_json(config_path), read_json(freeze_path)
    issues = []
    def check(condition, message):
        if not condition:
            issues.append(message)
    config_sha, freeze_sha = sha256(config_path), sha256(freeze_path)
    check(config_sha == expected_config_sha, "config external SHA mismatch")
    check(freeze_sha == expected_freeze_sha, "freeze external SHA mismatch")
    check(frozen.get("status") == "frozen_for_once_43x5_metric_sdp_comparison"
          and frozen.get("formal_execution_approved") is True
          and frozen.get("configuration_freeze_blockers") == [], "formal execution freeze contract")
    check(frozen.get("config_sha256") == config_sha, "freeze/config hash mismatch")
    for key in ("cases", "arms", "solver", "formal", "discovery", "checker", "watchdog",
                "threads", "checkpoint_policy", "source_version"):
        check(config.get(key) == contract[key], "fixed scientific contract mismatch: " + key)
    runtime = frozen.get("runtime_source_sha256", {})
    check(set(runtime) == set(RUNTIME_PATHS), "exact transitive 23-source inventory mismatch")
    required = frozen.get("required_artifact_sha256", {})
    for path, digest in {**runtime, **required}.items():
        try:
            check(re.fullmatch(r"[0-9a-f]{64}", digest) is not None
                  and sha256(safe_path(root, path)) == digest, "bound artifact changed: " + path)
        except (OSError, ValueError, TypeError) as error:
            issues.append("bound artifact unreadable: " + path + ": " + str(error))
    try:
        packet = read_json(safe_path(root, PACKET))
        check(required.get(PACKET) == sha256(root / PACKET), "analysis packet absent from formal freeze")
        check(packet.get("schema") == "metric-sdp-formal-prospective-analysis-manifest-v1"
              and packet.get("scientific_execution_performed") is False
              and packet.get("config_sha256") == config_sha, "prospective analysis packet contract")
        check(packet.get("collector_source_sha256") == source_sha256(), "executed collector source differs from packet")
        for path, digest in packet.get("required_artifact_sha256", {}).items():
            check(required.get(path) == digest and sha256(safe_path(root, path)) == digest,
                  "analysis packet not recursively bound: " + path)
        check(required.get(CONTRACT) == sha256(Path(__file__).resolve().parent / "fixed-contract.json"),
              "actual collector fixed contract not pinned")
        for path, digest in source_sha256().items():
            check(required.get(path) == digest, "actual collector module not pinned: " + path)
    except (OSError, ValueError, TypeError) as error:
        issues.append("analysis packet unreadable: " + str(error))
    return config, frozen, contract, config_sha, freeze_sha, issues


def inventory(root, run, jobs):
    artifacts, issues = {}, []
    expected_dirs = {f"job-{i:03d}-{j['case_id']}-{j['arm']}" for i, j in enumerate(jobs)}
    for suffix in ("-launch-started.json", "-launch-stdout.txt", "-launch-attempt.json"):
        for path in (run.with_name(run.name + suffix), run.with_name(run.name + suffix + ".partial")):
            if path.exists():
                require(path.is_file() and not path.is_symlink(), "invalid operator sidecar")
                artifacts[relative(root, path)] = sha256(path)
    if not run.exists():
        return artifacts, issues
    require(run.is_dir() and not run.is_symlink(), "run must be a real directory")
    for path in sorted(run.rglob("*")):
        require(not path.is_symlink(), "raw inventory contains a symlink")
        parts = path.relative_to(run).parts
        if path.is_dir():
            if len(parts) != 1 or parts[0] not in expected_dirs:
                issues.append("unknown raw directory: " + path.relative_to(run).as_posix())
            continue
        require(path.is_file(), "raw inventory contains a non-file")
        artifacts[relative(root, path)] = sha256(path)
        if len(parts) == 1:
            known = (parts[0] in {"study-started.json", "study-completed.json", "study-halted.json"}
                     or re.fullmatch(r"job-\d{3}(?:\.log|-closeout\.json)", parts[0]))
        else:
            known = (len(parts) == 2 and parts[0] in expected_dirs and
                     WORKER_NAME.fullmatch(parts[1].removesuffix(".partial")))
        if not known:
            issues.append("unknown raw artifact: " + path.relative_to(run).as_posix())
    return artifacts, issues


def inspect_operator(root, run, config_path, freeze_path, frozen, contract, state,
                     config_sha, freeze_sha):
    started_path = run.with_name(run.name + "-launch-started.json")
    log_path = run.with_name(run.name + "-launch-stdout.txt")
    attempt_path = run.with_name(run.name + "-launch-attempt.json")
    binding = {"state": "incomplete", "backend": contract["solver"]["backend"],
               "started_sha256": sha256(started_path) if started_path.exists() else None,
               "stdout_sha256": sha256(log_path) if log_path.exists() else None,
               "attempt_sha256": sha256(attempt_path) if attempt_path.exists() else None,
               "exit_code": None, "operator_wall_seconds": None}
    issues = []
    try:
        if not started_path.exists():
            require(not attempt_path.exists(), "operator ended without started sidecar")
            return binding, issues
        started = read_json(started_path)
        command = [".venv-sdp/bin/python", "-m", "experiments.extensions.metric_sdp_formal.run_study",
                   "--config", relative(root, config_path), "--freeze", relative(root, freeze_path),
                   "--output", relative(root, run)]
        require(started["command"] == command and started["cwd"] == ".", "operator controller command differs")
        require(started["config_sha256"] == config_sha and started["freeze_sha256"] == freeze_sha
                and started["runtime_source_sha256"] == frozen["runtime_source_sha256"], "operator source/config/freeze differs")
        require(started["operator_source_sha256"] == frozen["required_artifact_sha256"].get(OPERATOR)
                == sha256(safe_path(root, OPERATOR)), "operator wrapper is not frozen")
        require(started["environment"] == {"PYTHONPATH": "src:.", **contract["threads"]}, "operator import/thread environment differs")
        if not attempt_path.exists():
            return binding, issues
        attempt = read_json(attempt_path)
        require(all(attempt.get(k) == v for k, v in started.items()), "operator final/start record differs")
        require(log_path.is_file() and attempt["retained_stdout_stderr"] == relative(root, log_path)
                and attempt["retained_stdout_stderr_sha256"] == sha256(log_path), "operator retained stdout digest/path differs")
        require(type(attempt["exit_code"]) is int and state in {"completed", "halted"}
                and attempt["exit_code"] == (0 if state == "completed" else 2), "operator final exit/terminal controller state differs")
        binding.update(state="complete", exit_code=attempt["exit_code"],
                       operator_wall_seconds=number(attempt["operator_wall_seconds"], "operator wall"))
    except (ValueError, KeyError, TypeError, OSError) as error:
        issues.append("operator evidence: " + str(error))
    return binding, issues


def controller(run, jobs, config_sha, freeze_sha):
    issues, entries = [], []
    def attempt(path):
        try:
            return read_json(path) if path.exists() else None
        except (ValueError, OSError) as error:
            issues.append(path.name + ": " + str(error))
            return None
    started = attempt(run / "study-started.json")
    if started is not None:
        if (started.get("jobs") != jobs or started.get("planned_jobs") != 215
                or started.get("config_sha256") != config_sha or started.get("freeze_sha256") != freeze_sha):
            issues.append("controller started schedule/source mismatch")
    complete, halted = attempt(run / "study-completed.json"), attempt(run / "study-halted.json")
    if complete is not None and halted is not None:
        issues.append("both completed and halted controller records")
    terminal = complete or halted
    state = ("completed" if complete is not None else "halted" if halted is not None else
             "incomplete" if run.exists() else "not_started")
    if terminal is not None:
        entries = terminal.get("entries", terminal.get("retained_entries", []))
        if not isinstance(entries, list):
            issues.append("controller entries are not a list")
            entries = []
        summary = terminal.get("summary", {})
        if (summary.get("planned_jobs") != 215 or summary.get("dispatched_jobs") != len(entries)
                or summary.get("unexecuted_job_count") != 215 - len(entries)):
            issues.append("controller summary denominator mismatch")
        if complete is not None:
            if (len(entries) != 215 or complete.get("status") != "completed_fixed_schedule"
                    or complete.get("unexecuted_jobs") != []
                    or complete.get("formal_study_completed") is not True
                    or complete.get("config_sha256") != config_sha
                    or complete.get("freeze_sha256") != freeze_sha):
                issues.append("completed controller contract mismatch")
        elif halted.get("unexecuted_job_identities_known") is True:
            if halted.get("unexecuted_jobs") != jobs[len(entries):]:
                issues.append("halted remaining schedule mismatch")
    else:
        for index in range(215):
            value = attempt(run / f"job-{index:03d}-closeout.json")
            if value is None:
                break
            entries.append(value)
    selected = {}
    for index, entry in enumerate(entries):
        if (not isinstance(entry, dict) or index >= 215 or entry.get("index") != index
                or any(entry.get(k) != v for k, v in jobs[index].items())):
            issues.append("noncontiguous or mismatched controller entry at " + str(index))
            continue
        selected[index] = entry
        if attempt(run / f"job-{index:03d}-closeout.json") != entry:
            issues.append("terminal/root closeout byte-content mismatch at " + str(index))
    for path in run.glob("job-*-closeout.json") if run.exists() else ():
        match = re.fullmatch(r"job-(\d{3})-closeout\.json", path.name)
        if match is None or int(match[1]) not in selected:
            issues.append("extra unselected controller closeout: " + path.name)
    return state, selected, issues


def membership(value, n, q, label):
    require(isinstance(value, list) and len(value) == n and
            all(type(x) is int and 0 <= x < q for x in value)
            and set(value) == set(range(q)), "invalid " + label)
    return value


def inspect_prefix(directory, original, arm, gamma, cap):
    paths = sorted(directory.glob("composition-operation-*.json"))
    if not paths:
        return [], None
    require(original is not None and arm != "U", "operation prefix has no original checkpoint or is U")
    n = original["original_n"]
    degrees = [exact(x, "original degree") for x in original["degrees_exact"]]
    before, current_n, prior_sha, events = list(range(n)), n, None, []
    for index, path in enumerate(paths):
        require(path.name == f"composition-operation-{index:04d}.json", "noncontiguous durable operation prefix")
        event = read_json(path)
        require(event.get("kind") == "accepted_operation" and event.get("mode") == arm,
                "callback kind/mode mismatch")
        op = event["operation"]
        require(op["index"] == index and op["current_n_before"] == current_n
                and op["original_membership_before"] == before, "operation before-map/index mismatch")
        require(op["stage"] in ({"S"} if arm == "S" else {"D"} if arm == "D" else
                                {"S", "D"} if arm == "SD" else {"S", "W"}), "operation stage mismatch")
        if events and events[-1]["operation"]["stage"] != "S":
            require(op["stage"] == events[-1]["operation"]["stage"], "composition returned to S")
        block = op["block_current"]
        require(isinstance(block, list) and 2 <= len(block) <= cap and block == sorted(set(block))
                and all(type(x) is int and 0 <= x < current_n for x in block), "invalid current certified block")
        require(op["original_groups_before"] == [[u for u, c in enumerate(before) if c == v] for v in block],
                "operation groups are not actual original CSR memberships")
        q = integer(op["current_n_after"], "operation quotient size", 1)
        require(q == current_n - len(block) + 1, "operation did not perform one block quotient")
        mapping = membership(op["old_to_new_membership"], current_n, q, "current quotient map")
        require(len({mapping[v] for v in block}) == 1
                and len({mapping[v] for v in range(current_n) if v not in block}) == q - 1
                and all(mapping[v] != mapping[block[0]] for v in range(current_n) if v not in block),
                "operation merges additional incompatible groups")
        after = membership(op["original_membership_after"], n, q, "composed original membership")
        require(after == [mapping[c] for c in before], "composed original membership mismatch")
        volumes = [sum((degrees[u] for u, c in enumerate(after) if c == v), F()) for v in range(q)]
        require(list(map(str, volumes)) == op["quotient_degrees_exact"]
                and op["S_exact"] == original["S_exact"] and op["gamma_exact"] == str(gamma),
                "operation changed recorded full degrees/S/gamma")
        require(exact(op["block_volume_exact"], "block volume") ==
                sum((degrees[u] for u, c in enumerate(before) if c in block), F()), "operation block volume mismatch")
        if prior_sha is not None:
            require(op["current_graph_sha256"] == prior_sha, "operation graph hash chain mismatch")
        require(op["certificate"].get("certified") is True, "published operation is not certified")
        for source in op["original_bank_blocks"]:
            require(source in original["bank"]["blocks"] and sorted({before[v] for v in source}) == block,
                    "operation source bank mapping mismatch")
        if op["stage"] in {"D", "W"}:
            require(bool(op["original_bank_blocks"]), "D/W operation missing mapped original bank source")
        require(isinstance(event["counts_snapshot"], dict) and all(
            type(x) is int and x >= 0 for x in event["counts_snapshot"].values()), "invalid prefix counters")
        require(sum(event["counts_snapshot"].get(s + "_accepted_operations", 0) for s in ("S", "D", "W"))
                == index + 1, "prefix accepted-operation counts disagree")
        require(isinstance(event["completed_phases"], list) and all(
            p.get("fixed_point") is True for p in event["completed_phases"]), "false prior completed phase")
        events.append(event)
        before, current_n, prior_sha = after, q, op["quotient_graph_sha256"]
    return events, current_n


def inspect_job(root, run, index, job, case, entry, config, config_sha, freeze_sha):
    directory = run / f"job-{index:03d}-{job['case_id']}-{job['arm']}"
    row = {"index": index, **job, "stratum": case["stratum"],
           "family": case.get("family"), "dataset": case.get("dataset"),
           "parameters": case.get("parameters"), "original_role": case["original_role"],
           "gamma_exact": case["gamma"], "outcome_status": "unexecuted" if entry is None else entry["status"],
           "dispatched": entry is not None, "controller_target_claimed": False,
           "audited_verified_target": False, "full_compute_seconds": None,
           "process_wall_seconds": None, "monitored_peak_RSS_bytes": None,
           "limit_reason": None, "exit_code": None, "stage_seconds": None,
           "stage_order": None, "accounted_stage_seconds": None, "unassigned_compute_seconds": None,
           "callback_diagnostic_seconds": None, "reported_lower_exact": None,
           "reported_upper_exact": None, "reported_width_exact": None,
           "audited_lower_exact": None, "audited_upper_exact": None, "audited_width_exact": None,
           "original_n": None, "final_quotient_n": None, "composition_completed": False,
           "durable_prefix_operations": 0, "durable_prefix_n": None,
           "durable_prefix_exactness_approved": False,
           "stage_prefix_removed_vertices": {s: 0 for s in ("S", "D", "W")},
           "partial_files": sorted(p.name for p in directory.glob("*.partial")),
           "result_sha256": sha256(directory / "result.json") if (directory / "result.json").exists() else None,
           "failure_sha256": sha256(directory / "failure.json") if (directory / "failure.json").exists() else None,
           "integrity_issues": [], "preprocessing_sha256": None,
           "original_checkpoint_present": False, "exactness_credit_requires_independent_audit": True}
    evidence = {"original": None, "input": None, "preprocessing": None, "result": None, "events": []}
    if entry is None and directory.exists():
        row["outcome_status"] = "unclosed_attempt"
        row["integrity_issues"].append("worker artifacts exist without a controller closeout")
    try:
        if entry is not None:
            require(entry.get("credited_verified_target") in (True, False)
                    and type(entry["credited_verified_target"]) is bool, "missing boolean controller credit")
            row.update(controller_target_claimed=entry["credited_verified_target"],
                       limit_reason=entry.get("limit_reason"), exit_code=entry.get("exit_code"))
            if entry.get("process_wall_seconds_including_import_input_output") is not None:
                row["process_wall_seconds"] = number(entry["process_wall_seconds_including_import_input_output"], "process wall")
            if entry.get("monitored_peak_RSS_bytes") is not None:
                row["monitored_peak_RSS_bytes"] = integer(entry["monitored_peak_RSS_bytes"], "RSS")
            require(entry.get("result_sha256") == row["result_sha256"], "controller result hash mismatch")
            require(entry.get("failure_sha256") == row["failure_sha256"], "controller failure hash mismatch")
            require((run / f"job-{index:03d}.log").is_file(), "dispatched worker log missing")
        if (directory / "input.json").exists():
            value = read_json(directory / "input.json")
            require(value["case"] == case and value["arm"] == job["arm"] and value["backend"] == job["backend"]
                    and value["config_sha256"] == config_sha and value["freeze_sha256"] == freeze_sha,
                    "worker input/source/whole-case metadata mismatch")
            evidence["input"] = value
        if (directory / "original-preparation.json").exists():
            original = read_json(directory / "original-preparation.json")
            require(all(original[k] == v for k, v in {"case_id": case["case_id"], "arm": job["arm"],
                    "backend": job["backend"], "gamma_exact": str(F(case["gamma"])),
                    "stage": "before_any_composition"}.items()), "original preparation identity mismatch")
            n = integer(original["original_n"], "original n", 1)
            require(n <= 300 and len(original["degrees_exact"]) == n, "original full-graph size/degrees")
            d = [exact(x, "original degree") for x in original["degrees_exact"]]
            require(all(x >= 0 for x in d) and sum(d, F()) == exact(original["S_exact"], "S") > 0,
                    "recorded exact degrees/volume mismatch")
            require(original["original_csr_sha256"] == sha256(directory / "original-adjacency.npz"),
                    "actual original CSR checkpoint hash mismatch")
            bank = original["bank"]
            require(canonical_hash(bank) == original["bank_sha256"], "original bank content hash mismatch")
            require(isinstance(bank["discovery_labels"], list) and len(bank["discovery_labels"]) == n
                    and all(type(x) is int for x in bank["discovery_labels"]), "original discovery labels")
            require(all(isinstance(b, list) and len(b) >= 2 and b == sorted(set(b)) and
                        all(type(x) is int and 0 <= x < n for x in b) for b in bank["blocks"]), "original bank IDs")
            exact(original["incumbent_Q_exact"], "incumbent")
            row.update(original_n=n, original_checkpoint_present=True, durable_prefix_n=n)
            evidence["original"] = original
        events, prefix_n = inspect_prefix(directory, evidence["original"], job["arm"],
                                         F(case["gamma"]), config["checker"]["max_block_size"])
        evidence["events"] = events
        row["durable_prefix_operations"] = len(events)
        if prefix_n is not None:
            row["durable_prefix_n"] = prefix_n
        for event in events:
            op = event["operation"]
            row["stage_prefix_removed_vertices"][op["stage"]] += op["current_n_before"] - op["current_n_after"]
        if (directory / "preprocessing.json").exists():
            pre = read_json(directory / "preprocessing.json")
            original = evidence["original"]
            require(original is not None, "final preprocessing lacks durable original")
            require(all(pre[k] == original[k] for k in ("original_n", "S_exact", "original_fingerprint",
                    "bank_sha256", "bank", "incumbent_Q_exact", "original_csr_sha256")), "preprocessing original identity mismatch")
            require(all(pre[k] == v for k, v in {"case_id": case["case_id"], "arm": job["arm"],
                    "backend": job["backend"], "gamma_exact": str(F(case["gamma"]))}.items()), "preprocessing arm identity")
            q = integer(pre["quotient_n"], "final quotient n", 1)
            mapping = membership(pre["membership"], original["original_n"], q, "final original membership")
            require(pre["composition_checkpoint_files"] == [f"composition-operation-{i:04d}.json" for i in range(len(events))],
                    "final composition journal file inventory mismatch")
            comp = pre["composition"]
            if job["arm"] == "U":
                require(comp is None and not events and mapping == list(range(original["original_n"])), "U altered membership")
            else:
                require(comp["operations"] == [e["operation"] for e in events], "final trace/durable journal mismatch")
                require(all(p["fixed_point"] is True for p in comp["metadata"]["phases"]), "composition did not finish fixed points")
                require(mapping == (events[-1]["operation"]["original_membership_after"] if events else
                                     list(range(original["original_n"]))), "final quotient/prefix membership mismatch")
                callback = number(comp["metadata"]["progress_callback_seconds"], "callback diagnostic")
                require(callback == comp["metadata"]["stage_seconds"]["progress_callback"], "callback diagnostic duplicated/mismatched")
                row["callback_diagnostic_seconds"] = callback
            evidence["preprocessing"] = pre
            row.update(final_quotient_n=q, composition_completed=True,
                       preprocessing_sha256=sha256(directory / "preprocessing.json"))
        result = read_json(directory / "result.json") if row["result_sha256"] else None
        failure = read_json(directory / "failure.json") if row["failure_sha256"] else None
        require(not (result is not None and failure is not None), "both result and worker failure exist")
        if failure is not None:
            require(failure["case_id"] == case["case_id"] and failure["arm"] == job["arm"], "worker failure identity mismatch")
            if entry and entry["status"] not in {"controller_supervision_exception", "controller_record_validation_failure"}:
                require(entry.get("failure") == failure, "worker failure not retained in controller record")
        if result is not None:
            evidence["result"] = result
            require(evidence["preprocessing"] is not None and evidence["input"] is not None, "result lacks input/preprocessing")
            require(result["config_sha256"] == config_sha and result["freeze_sha256"] == freeze_sha, "result source/config/freeze identity")
            for k, v in evidence["preprocessing"].items():
                if k not in {"status", "components"}:
                    require(result.get(k) == v, "final result changed preprocessing field: " + k)
            full = number(result["full_compute_seconds"], "complete compute time")
            stages = result["stage_seconds"]
            require(isinstance(stages, dict) and set(stages) <= STAGES, "unknown/nondisjoint additive stage")
            for k, v in stages.items():
                number(v, "stage " + k)
            require(result["accounted_stage_seconds"] == sum(stages.values()), "recorded ordered stage sum mismatch")
            require(result["unassigned_compute_seconds"] == full - result["accounted_stage_seconds"]
                    and result["unassigned_compute_seconds"] >= 0, "complete compute/ledger residual mismatch")
            if job["arm"] == "U":
                require("safe_composition" not in stages, "U charged a composition stage")
            else:
                require(number(stages["safe_composition"], "composition") >= row["callback_diagnostic_seconds"],
                        "callback work not within outer composition cost")
            row.update(full_compute_seconds=full, stage_seconds=stages, stage_order=list(stages),
                       accounted_stage_seconds=result["accounted_stage_seconds"],
                       unassigned_compute_seconds=result["unassigned_compute_seconds"],
                       result_reported_status=result["status"])
            if entry is not None and entry["status"] not in {"controller_supervision_exception", "controller_record_validation_failure"}:
                require(entry["full_compute_seconds"] == full, "controller/runtime full cost mismatch")
            if result.get("lower_exact") is not None:
                lower, upper = exact(result["lower_exact"], "lower"), exact(result["upper_exact"], "upper")
                width = exact(result["width_exact"], "width")
                require(upper >= lower and width == upper - lower, "reported exact interval arithmetic")
                require(exact(result["incumbent_Q_exact"], "incumbent") <= upper, "reported upper below original feasible incumbent")
                require(sum((exact(c["lower_exact"], "component lower") for c in result["components"]), F()) == lower
                        and sum((exact(c["upper_exact"], "component upper") for c in result["components"]), F()) == upper,
                        "global/component exact interval mismatch")
                for c in result["components"]:
                    if not c["analytic"]:
                        require((directory / f"component-{c['index']:03d}-proof.json").is_file(), "bounded component proof file missing")
                row.update(reported_lower_exact=str(lower), reported_upper_exact=str(upper), reported_width_exact=str(width))
            if row["controller_target_claimed"]:
                require(result["status"] == "verified_target" and row["reported_width_exact"] is not None
                        and F(row["reported_width_exact"]) <= F(config["solver"]["width_target"])
                        and row["exit_code"] == 0 and row["limit_reason"] is None and not row["partial_files"]
                        and full <= config["formal"]["wall_seconds"]
                        and row["monitored_peak_RSS_bytes"] <= config["formal"]["rss_bytes"],
                        "controller target credit violates exact target/time/RSS/status")
                timer, finished = read_json(directory / "timer-start.json"), read_json(directory / "compute-finished.json")
                require(timer["wall_seconds"] == 300 and finished["status"] == result["status"]
                        and finished["full_compute_seconds"] == full, "target timer markers mismatch")
        else:
            require(not row["controller_target_claimed"], "credited job has no result")
    except (ValueError, KeyError, TypeError, OSError) as error:
        row["integrity_issues"].append(str(error))
    row["size_bin"] = ("unknown" if row["original_n"] is None else next(
        f"{lo}-{hi}" for lo, hi in ((1, 32), (33, 64), (65, 128), (129, 300))
        if lo <= row["original_n"] <= hi))
    row["right_censored_compute_lower_bound_seconds"] = (
        300 if row["limit_reason"] == "full_wall_limit" and (directory / "timer-start.json").exists()
        and not (directory / "compute-finished.json").exists() else None)
    return row, evidence


def cross_arm_evidence(rows, evidence):
    issues = []
    by_case = defaultdict(list)
    for row in rows:
        by_case[row["case_id"]].append(row)
    for case_id, selected in by_case.items():
        originals = [evidence[r["index"]]["original"] for r in selected if evidence[r["index"]]["original"]]
        inputs = [evidence[r["index"]]["input"]["metadata"] for r in selected if evidence[r["index"]]["input"]]
        common = ("original_n", "gamma_exact", "S_exact", "degrees_exact", "original_fingerprint",
                  "bank", "bank_sha256", "incumbent_Q_exact")
        if originals and any(any(o[k] != originals[0][k] for k in common) for o in originals[1:]):
            issues.append("cross-arm original objective/bank/incumbent mismatch: " + case_id)
        if inputs and any(v != inputs[0] for v in inputs[1:]):
            issues.append("cross-arm complete input metadata mismatch: " + case_id)
        s_prefixes = [[e["operation"] for e in evidence[r["index"]]["events"] if e["operation"]["stage"] == "S"]
                      for r in selected if r["arm"] in {"S", "SD", "SW"}]
        for a in s_prefixes:
            for b in s_prefixes:
                if a[:min(len(a), len(b))] != b[:min(len(a), len(b))]:
                    issues.append("cross-arm deterministic S prefix mismatch: " + case_id)
                    break
    return issues


def apply_audit(root, audit_path, expected_sha, raw_sha, rows, evidence, config_sha, freeze_sha, issues):
    require(not issues, "exactness credit blocked by collection integrity issues")
    require(expected_sha and sha256(audit_path) == expected_sha, "external exactness-audit SHA mismatch")
    audit = read_json(audit_path)
    require(audit.get("schema") == AUDIT_SCHEMA and audit.get("integrity_status") == "validated"
            and audit.get("scientific_credit_approved") is True and audit.get("all_215_outcomes_accounted") is True,
            "independent complete exactness/data approval absent")
    require(audit.get("reviewer_task") not in {None, "", AUTHOR}
            and audit.get("independent_of_composition_author") is True, "composition author cannot self-approve proof/data")
    require(audit.get("config_sha256") == config_sha and audit.get("freeze_sha256") == freeze_sha
            and audit.get("raw_inventory_sha256") == raw_sha
            and audit.get("collector_source_sha256") == source_sha256(), "exactness audit does not bind current data/source version")
    require(audit.get("operator_command_logs_exit_and_limits_validated") is True,
            "independent audit did not validate the operator sidecars")
    job_audits = audit.get("job_audits")
    require(isinstance(job_audits, list) and len(job_audits) == 215, "independent audit dropped an outcome")
    for row, approved in zip(rows, job_audits):
        require(all(approved.get(k) == row[k] for k in ("index", "case_id", "arm", "outcome_status",
                    "result_sha256", "failure_sha256", "durable_prefix_operations")), "audit job identity/outcome mismatch")
        checks = approved.get("checks", {})
        need = {"source_config_freeze_and_outcome_accounting"}
        if row["original_checkpoint_present"]:
            need.add("original_input_full_degrees_bank_and_incumbent")
        if row["durable_prefix_operations"]:
            need.add("all_durable_operations_current_quotient_relaxation_safe")
        if row["composition_completed"]:
            need.add("exact_full_trace_quotient_and_signed_component_presolve")
        if row["reported_lower_exact"] is not None:
            need.update({"component_exact_primal_dual_and_raw_binding", "original_lift_psd_diag_box_all_triangles",
                         "quotient_upper_transfer_all_prior_operations", "original_exact_interval_and_width"})
        if row["controller_target_claimed"]:
            need.add("complete_cost_and_hard_wall_RSS_target_eligibility")
        require(all(checks.get(name) is True for name in need), "independent audit missing required exact check at job " + str(row["index"]))
    # Apply credit only after all215 records have passed the contract, never a
    # selectively audited favorable subset. This collector does not replay proof.
    for row in rows:
        row["durable_prefix_exactness_approved"] = row["durable_prefix_operations"] > 0
        row["audited_verified_target"] = row["controller_target_claimed"]
        for name in ("lower", "upper", "width"):
            row["audited_" + name + "_exact"] = row["reported_" + name + "_exact"]
    return {"path": relative(root, audit_path), "sha256": expected_sha, "reviewer_task": audit["reviewer_task"]}


def scalar_stats(values):
    return {"n": len(values), "minimum": min(values) if values else None,
            "median": statistics.median(values) if values else None,
            "maximum": max(values) if values else None}


def ratio(a, b):
    if a is None or b is None or b == 0:
        return None
    value = a / b
    return value if math.isfinite(value) else None


def pair_rows(rows, contract):
    lookup = {(r["case_id"], r["arm"]): r for r in rows}
    answer = []
    for case in contract["cases"]:
        for arm_a, arm_b in contract["primary_comparisons"]:
            a, b = lookup[(case["case_id"], arm_a)], lookup[(case["case_id"], arm_b)]
            both = a["audited_verified_target"] and b["audited_verified_target"]
            time_ratio = ratio(a["full_compute_seconds"], b["full_compute_seconds"]) if both else None
            answer.append({"case_id": case["case_id"], "case_index": a["case_index"],
                           "comparison": arm_a + "/" + arm_b, "arm_A": arm_a, "arm_B": arm_b,
                           "stratum": case["stratum"], "family": case.get("family"),
                           "dataset": case.get("dataset"), "original_role": case["original_role"],
                           "gamma_exact": case["gamma"], "size_bin": a["size_bin"] if a["size_bin"] != "unknown" else b["size_bin"],
                           "original_n": a["original_n"] if a["original_n"] is not None else b["original_n"],
                           "status_A": a["outcome_status"], "status_B": b["outcome_status"],
                           "limit_A": a["limit_reason"], "limit_B": b["limit_reason"],
                           "A_verified_target": a["audited_verified_target"], "B_verified_target": b["audited_verified_target"],
                           "same_verified_target": bool(both),
                           "pair_outcome": ("both_target" if both else "A_only_target" if a["audited_verified_target"] else
                                            "B_only_target" if b["audited_verified_target"] else "neither_target"),
                           "conditional_full_cost_A_seconds": a["full_compute_seconds"] if both else None,
                           "conditional_full_cost_B_seconds": b["full_compute_seconds"] if both else None,
                           "time_ratio_A_over_B": time_ratio,
                           "speedup_B_over_A": ratio(b["full_compute_seconds"], a["full_compute_seconds"]) if both else None,
                           "time_outcome": "undefined" if time_ratio is None else
                           "faster" if time_ratio < 1 else "slower" if time_ratio > 1 else "equal",
                           "exact_width_target": contract["solver"]["width_target"],
                           "target_meaning": "same original-normalized interval-width tolerance, not equal primal objectives",
                           "own_D_prefix_removed_vertices": a["stage_prefix_removed_vertices"]["D"],
                           "D_stage_completed": a["composition_completed"],
                           "no_independent_trial_interpretation": True})
    return answer


def summaries(rows, pairs, credit):
    overall = {"planned_cases": 43, "planned_jobs": 215, "planned_primary_pairs": 86,
               "scientific_credit_authorized": credit, "dispatched": sum(r["dispatched"] for r in rows),
               "unexecuted": sum(r["outcome_status"] == "unexecuted" for r in rows),
               "controller_target_claimed": sum(r["controller_target_claimed"] for r in rows),
               "audited_verified_target": sum(r["audited_verified_target"] for r in rows),
               "status_counts": dict(Counter(r["outcome_status"] for r in rows)),
               "limit_counts": dict(Counter(r["limit_reason"] or "none" for r in rows)),
               "per_arm": {arm: {"planned": 43, "statuses": dict(Counter(r["outcome_status"] for r in rows if r["arm"] == arm)),
                                  "controller_target_claimed": sum(r["controller_target_claimed"] for r in rows if r["arm"] == arm),
                                  "audited_verified_target": sum(r["audited_verified_target"] for r in rows if r["arm"] == arm)} for arm in ARMS}}
    panels = defaultdict(list)
    for pair in pairs:
        labels = ["all", "stratum=" + pair["stratum"], "gamma=" + pair["gamma_exact"],
                  "size=" + pair["size_bin"], "original_role=" + pair["original_role"],
                  "family=" + (pair["family"] or "development:" + pair["dataset"])]
        for label in labels:
            panels[(pair["comparison"], label)].append(pair)
    result = []
    for (comparison, stratum), selected in sorted(panels.items()):
        eligible = [p for p in selected if p["same_verified_target"]]
        result.append({"comparison": comparison, "panel": stratum, "planned_case_denominator": len(selected),
                       "conditional_target_pair_count": len(eligible),
                       "pair_outcomes": dict(Counter(p["pair_outcome"] for p in selected)),
                       "time_outcomes_complete_denominator": dict(Counter(p["time_outcome"] for p in selected)),
                       "time_ratio_A_over_B": scalar_stats([p["time_ratio_A_over_B"] for p in eligible if p["time_ratio_A_over_B"] is not None]),
                       "speedup_B_over_A": scalar_stats([p["speedup_B_over_A"] for p in eligible if p["speedup_B_over_A"] is not None]),
                       "conditional_full_cost_A_seconds": scalar_stats([p["conditional_full_cost_A_seconds"] for p in eligible]),
                       "conditional_full_cost_B_seconds": scalar_stats([p["conditional_full_cost_B_seconds"] for p in eligible]),
                       "inference": "finite correlated inventory, descriptive conditional summaries; no IID test/CI or external-population claim"})
    return {"overall": overall, "paired_panels": result}


def collect(root, config_path, freeze_path, run_dir, *, expected_config_sha256,
            expected_freeze_sha256, exactness_audit=None, expected_exactness_audit_sha256=None):
    root, run = Path(root).resolve(), Path(run_dir).resolve()
    require(run.is_relative_to(root), "run escapes project root")
    config, frozen, contract, config_sha, freeze_sha, issues = authenticate(
        root, config_path, freeze_path, expected_config_sha256, expected_freeze_sha256)
    jobs = fixed_schedule(contract)
    artifacts, inventory_issues = inventory(root, run, jobs)
    state, selected, controller_issues = controller(run, jobs, config_sha, freeze_sha)
    issues += inventory_issues + controller_issues
    if frozen.get("planned_scientific_output") != relative(root, run):
        issues.append("run path is not the once-only frozen scientific output")
    operator, operator_issues = inspect_operator(root, run, config_path, freeze_path, frozen,
                                               contract, state, config_sha, freeze_sha)
    issues += operator_issues
    rows, evidence = [], {}
    for index, job in enumerate(jobs):
        row, details = inspect_job(root, run, index, job, contract["cases"][job["case_index"]],
                                   selected.get(index), contract, config_sha, freeze_sha)
        rows.append(row)
        evidence[index] = details
        issues += [f"job {index}: {x}" for x in row["integrity_issues"]]
    issues += cross_arm_evidence(rows, evidence)
    current_artifacts, _ = inventory(root, run, jobs)
    require(artifacts == current_artifacts, "raw inventory changed during read-only collection")
    raw_inventory = {"schema": "metric-sdp-formal-raw-inventory-v1", "run_path": relative(root, run),
                     "config_sha256": config_sha, "freeze_sha256": freeze_sha, "controller_state": state,
                     "fixed_schedule": jobs, "raw_artifact_sha256": artifacts,
                     "planned_cases": 43, "planned_jobs": 215, "operator": operator}
    raw_sha = hashlib.sha256(json_bytes(raw_inventory)).hexdigest()
    audit_binding, audit_refusal = None, None
    if exactness_audit is not None:
        try:
            require(state in {"completed", "halted"}, "independent credit requires a terminal controller")
            require(operator["state"] == "complete", "independent credit requires complete operator sidecars")
            audit_binding = apply_audit(root, Path(exactness_audit), expected_exactness_audit_sha256,
                                       raw_sha, rows, evidence, config_sha, freeze_sha, issues)
        except (ValueError, KeyError, OSError, TypeError) as error:
            audit_refusal = str(error)
    else:
        require(expected_exactness_audit_sha256 is None, "audit SHA supplied without an audit artifact")
    credit = audit_binding is not None
    pairs = pair_rows(rows, contract)
    require(len(rows) == 215 and len(pairs) == 86, "collector changed fixed row denominator")
    summary = summaries(rows, pairs, credit)
    manifest = {"schema": SCHEMA, "status": "independently_audited_descriptive_collection" if credit else "diagnostic_only",
                "collector_source_sha256": source_sha256(), "config_sha256": config_sha, "freeze_sha256": freeze_sha,
                "raw_inventory_sha256": raw_sha, "controller_state": state, "scientific_credit_authorized": credit,
                "operator_evidence": operator,
                "independent_exactness_audit": audit_binding, "audit_refusal": audit_refusal,
                "integrity_issues": issues, "fixed_counts": {"cases": 43, "jobs": 215, "primary_pairs": 86},
                "composition_authorship_disclosed": AUTHOR, "proof_replayed_by_this_collector": False,
                "timing_semantics": "complete worker compute cost; final serialization excluded; stages and callback are explanatory subsets, never summed into cost again",
                "correlation_scope": "finite39 controlled plus4 development cases; seeds/parameters are correlated; no independent-trial inference",
                "C001_or_venue_approval": False,
                "exit_code": 2 if audit_refusal is not None or issues else 0}
    return {"raw-inventory.json": raw_inventory, "job-rows.json": rows,
            "primary-pair-rows.json": pairs, "summary.json": summary, "collection-manifest.json": manifest}


def write_once(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("xb") as handle:
        handle.write(json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.link(temporary, path)
    temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--config", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--measurements-finished", action="store_true", required=True)
    parser.add_argument("--exactness-audit")
    parser.add_argument("--exactness-audit-sha256")
    args = parser.parse_args(argv)
    root, output, run = Path(args.root).resolve(), Path(args.output).resolve(), Path(args.run_dir).resolve()
    require(output.is_relative_to(root / BASE) and not output.is_relative_to(run), "collection output must be new and outside raw run")
    output.mkdir(parents=True, exist_ok=False)
    try:
        records = collect(root, args.config, args.freeze, run,
                          expected_config_sha256=args.config_sha256, expected_freeze_sha256=args.freeze_sha256,
                          exactness_audit=args.exactness_audit, expected_exactness_audit_sha256=args.exactness_audit_sha256)
        manifest = records["collection-manifest.json"]
        for name, value in records.items():
            if name != "collection-manifest.json":
                write_once(output / name, value)
        manifest["output_artifact_sha256"] = {name: sha256(output / name) for name in records if name != "collection-manifest.json"}
        write_once(output / "collection-manifest.json", manifest)
        print(json.dumps({"status": manifest["status"], "counts": manifest["fixed_counts"],
                          "scientific_credit_authorized": manifest["scientific_credit_authorized"]}))
        return manifest["exit_code"]
    except (ValueError, OSError, KeyError, TypeError) as error:
        write_once(output / "refusal.json", {"status": "collection_refused", "message": str(error),
                   "fixed_denominators": {"cases": 43, "jobs": 215, "primary_pairs": 86},
                   "scientific_credit_authorized": False, "C001_or_venue_approval": False})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
