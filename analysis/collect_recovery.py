"""Exact-byte derived collection for the independently reviewed Davis recovery.

This is a provenance/selection adapter, not an experiment runner. It requires a
complete 73-job recovery and never treats the halted parent as a complete run.
All source attempts are retained; the entire Davis primary comes from recovery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from analysis.report import (AnalysisError, IncompleteSuiteError, _canonical,
    _require, expected_jobs, read_json, sha256)


COLLECTION_KIND = "derived_recovered_collection"
COLLECTION_STATUS = "complete_recovered_collection_with_recorded_native_failures"
RECOVERY_STATUS = "frozen_after_independent_incident_recovery_review"
RECOVERY_COMPLETE = "completed_recovery_with_recorded_native_failure"
REVIEW_STATUS = "approved_for_recovery_configuration_freeze"
INPUT_SHA = "572f45534f4744f3d424511d8aaec6966aec0078a2b44236f97a81c4d28e742d"
BINARY_SHA = "62d20d50a6c2812ee64b0f0564dcf01cc7fe7873ed0b1d817ba1612afec1ae86"
BUILD_SHA = "df5e857ccd7a31faed3ee0c041422dcd094c6019783a81c5f8e91aec6b99dbed"
INCIDENT_ID = "davis-gamma2-star-bound-assertion-518"
STDERR = "Assertion failed: (stars_in_bound[star] >= 0), function remove_star, file star_bound.cpp, line 518.\n"
EXCLUSIONS = ["native optimality", "native packing lower bound", "bound gap", "completed solve-time ratio"]
SELECTION_POLICY = "retain completed parent jobs; replace entire development-davis from recovery; append all originally unlaunched scaling jobs; never select partial parent Davis gamma timings"


def _relative(project: Path, path: Path | str) -> str:
    path = Path(path)
    absolute = path.resolve() if path.is_absolute() else (project / path).resolve()
    _require(absolute.is_relative_to(project), "Source/collection path must be inside the portable project root")
    return absolute.relative_to(project).as_posix()


def _events(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as error:
        raise AnalysisError(f"Unreadable source ledger {path}") from error


def _ledger(run: Path, outcomes: list[dict], *, halted: bool) -> None:
    events = _events(run / "orchestration.jsonl")
    _require(len(events) == 2*len(outcomes) + int(halted), "Source ledger length mismatch")
    for index, outcome in enumerate(outcomes):
        _require(events[2*index].get("event") == "started" and events[2*index].get("job") == outcome["job"], "Source launch/terminal identity mismatch")
        _require(events[2*index+1] == outcome, "Source ledger/completion terminal mismatch")
        _require(outcome.get("log") == outcome["job"]+".log" and (run/outcome["log"]).is_file(), "Missing actual source process log")
    if halted:
        _require(events[-1].get("event") == "halted_for_repair" and events[-1].get("trigger_job") == "development-davis", "Parent halt event is not the reviewed Davis incident")


def known_incident(record: dict) -> bool:
    """Independent stdlib-only mirror of reviewed recovery.policy allowlist."""
    if not isinstance(record, dict):
        return False
    arms, records = record.get("paired_arms", {}), record.get("records", [])
    if not isinstance(arms, dict) or set(arms) != {"unreduced", "reduced"} or not isinstance(records, list) or len(records) != 2:
        return False
    if not all(isinstance(item, dict) for item in [*records, *arms.values()]):
        return False
    if {item.get("case_name") for item in records} != {f"development-davis-gamma2-{arm}" for arm in arms}:
        return False
    if any(item != arms[item["case_name"].rsplit("-", 1)[-1]] for item in records):
        return False
    for name, arm in arms.items():
        conversion, native = arm.get("conversion", {}), arm.get("native", {})
        expected = {"input_sha256": INPUT_SHA, "gamma": "2", "volume": 178, "integer_divisor": 2,
                    "max_absolute_pair_cost": 168, "sum_absolute_pair_costs": 15172,
                    "budget": 3419, "incumbent_Q": "-106/7921"}
        if not (arm.get("status") == "failed" and arm.get("case_name") == f"development-davis-gamma2-{name}"
                and arm.get("binary_sha256") == BINARY_SHA and arm.get("build_provenance_sha256") == BUILD_SHA
                and arm.get("full_solver_entry_called") is True and arm.get("full_kapoce_solver") is True
                and arm.get("incumbent_Q_original_exact") == "-106/7921"
                and arm.get("incumbent", {}).get("verified_independently") is True and arm.get("timeout_seconds") == 30
                and all(conversion.get(key) == value for key, value in expected.items()) and len(conversion.get("degrees", [])) == 32
                and native.get("exit_code") == -6 and native.get("outer_timeout_triggered") is False
                and native.get("stderr") == STDERR and [event.get("event") for event in native.get("events", [])]
                    == ["input_accepted", "initial_bound", "full_solve_entered"]):
            return False
    permitted = {("records", 0), ("records", 1), ("paired_arms", "unreduced"), ("paired_arms", "reduced")}
    def bad_paths(value, path=()):
        if isinstance(value, dict):
            if value.get("status") in {"failed", "validation_failure", "unavailable_build", "failed_or_interrupted"}:
                yield path
            for key, item in value.items():
                yield from bad_paths(item, (*path, key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from bad_paths(item, (*path, index))
    return all(path in permitted for path in bad_paths(record))


def validate_overlay(project: Path, recovery_freeze_path: str) -> tuple[dict, dict]:
    path = project / recovery_freeze_path
    recovery = read_json(path)
    _require(recovery.get("status") == RECOVERY_STATUS, "Approved independently reviewed recovery freeze required")
    from analysis.report import _verify_frozen_packet
    original_config = read_json(project / recovery["original_config_path"])
    original = read_json(project / recovery["original_freeze_path"])
    _verify_frozen_packet(project, original_config, original,
        recovery["original_config_path"], recovery["original_freeze_path"],
        original["config_sha256"], recovery["original_freeze_sha256"])
    for field in ("overlay_runtime_source_sha256", "incident_evidence_sha256", "parent_artifact_sha256"):
        for source, expected in recovery[field].items():
            _require(sha256(project/source) == expected, f"Recovery frozen artifact changed: {source}")
    review_path = project / recovery["review_path"]
    _require(sha256(review_path) == recovery["review_sha256"], "Recovery review hash changed")
    review = read_json(review_path)
    _require(review.get("status") == REVIEW_STATUS and review.get("overlay_runtime_source_sha256") == recovery["overlay_runtime_source_sha256"], "Independent review does not approve the exact overlay sources")
    analysis_sources = recovery["collection_analysis_source_sha256"]
    _require(review.get("collection_analysis_source_sha256") == analysis_sources, "Review does not approve the actual collection/report sources")
    for source in ("analysis/collect_recovery.py", "analysis/report.py", "analysis/test_report.py"):
        _require(source in analysis_sources and sha256(project/source) == analysis_sources[source], f"Selection/report source is not independently frozen: {source}")
    for source, expected in analysis_sources.items():
        _require(sha256(project/source) == expected, f"Collection/report reviewed source changed: {source}")
    _require(sha256(project/recovery["selection_plan_path"]) == recovery["selection_plan_sha256"]
             and review.get("selection_plan_sha256") == recovery["selection_plan_sha256"], "Prospective fixed selection is not approved and hash-bound")
    _require(sha256(project/recovery["engineering_validation_path"]) == recovery["engineering_validation_sha256"]
             and review.get("engineering_validation_sha256") == recovery["engineering_validation_sha256"], "Passed recovery engineering validation is not approved and hash-bound")
    engineering = read_json(project/recovery["engineering_validation_path"])
    _require(engineering.get("status") == "passed", "Recovery engineering validation did not pass")
    for source, expected in engineering["source_sha256"].items():
        _require(sha256(project/source) == expected, f"Validated recovery source changed: {source}")
    _require(all(engineering["source_sha256"].get(source) == expected for source, expected in recovery["overlay_runtime_source_sha256"].items()), "Engineering validation omitted an actual overlay source")
    _require(review.get("incident_evidence_sha256") == recovery["incident_evidence_sha256"], "Review did not bind the actual independently reproduced incident evidence")
    return recovery, original


def _job_provenance(project: Path, run: Path, name: str, recovery: dict, base_sha: str, recovery_sha: str) -> dict:
    record = read_json(run / f"{name}-recovery-job-provenance.json")
    _require(record.get("job") == name and record.get("overlay_applied_to_case_runtime") == (name == "development-davis"), "Recovery job overlay role mismatch")
    _require(record.get("base_freeze_sha256") == base_sha and record.get("recovery_freeze_sha256") == recovery_sha
             and record.get("overlay_runtime_source_sha256") == recovery["overlay_runtime_source_sha256"]
             and record.get("review_sha256") == recovery["review_sha256"], "Recovery job provenance differs from the independently reviewed overlay")
    return record


def build_collection_plan(parent_run: str | Path, recovery_run: str | Path, *, project_root: str | Path = ".",
                          recovery_freeze_path: str = "experiments/recovery/freeze.json",
                          expected_job_count: int | None = 139) -> dict:
    """Validate source completeness and deterministic selection before copies."""
    project = Path(project_root).resolve()
    parent_text, recovery_text = _relative(project, parent_run), _relative(project, recovery_run)
    parent, recovered = project/parent_text, project/recovery_text
    complete_path = recovered/"run-completed.json"
    if not complete_path.is_file():
        raise IncompleteSuiteError("Recovery is still running/interrupted; no derived collection is permitted")
    completion = read_json(complete_path)
    if completion.get("status") != RECOVERY_COMPLETE or completion.get("not_launched_due_failure"):
        raise IncompleteSuiteError("All predeclared recovery jobs must complete before collection")
    _require(completion.get("process_completion_is_native_solver_success") is False, "Recovery process completion cannot be relabeled solver success")
    recovery, original = validate_overlay(project, recovery_freeze_path)
    recovery_sha = sha256(project/recovery_freeze_path)
    _require(original["runtime_source_sha256"].get("research/full_kapoce/build/kapoce_full") == BINARY_SHA
             and original["runtime_source_sha256"].get("research/full_kapoce/build-provenance.json") == BUILD_SHA, "Reviewed incident binary/build differ from the original frozen method")
    _require(_relative(project, recovery["parent_run_dir"]) == parent_text, "Recovery freeze selects a different parent")
    _require(_relative(project, recovery["planned_recovery_run_dir"]) == recovery_text, "Recovery run path differs from reviewed prospective selection")
    parent_manifest, parent_completion = read_json(parent/"run-manifest.json"), read_json(parent/"run-completed.json")
    recovered_manifest = read_json(recovered/"run-manifest.json")
    config = parent_manifest["config"]
    jobs = expected_jobs(config, ["public", "controls", "scaling"])
    _require(expected_job_count is None or len(jobs) == expected_job_count, "Logical recovered job denominator differs from expected suite")
    names = [job.name for job in jobs]
    _require(names.count("development-davis") == 1, "Recovery must replace exactly one whole Davis development job")
    failed_index = names.index("development-davis")
    _require(all(job.stratum == "scaling" for job in jobs[failed_index+1:]), "The reviewed recovery may append only unlaunched scaling jobs")
    old = parent_completion.get("outcomes", [])
    _require(parent_manifest.get("status") == "launched" and parent_completion.get("status") == "halted_for_repair", "The original parent must remain explicitly halted")
    _require([item.get("job") for item in old] == names[:failed_index+1] and old[-1].get("event") == "failed" and old[-1].get("exit_code") == 1
             and all(item.get("event") == "completed" and item.get("exit_code") == 0 for item in old[:-1]), "Parent attempt prefix/known failure differs from reviewed recovery")
    _require(parent_completion.get("not_launched_due_failure") == names[failed_index+1:], "Parent unlaunched denominator differs from reviewed recovery")
    scheduled = names[failed_index:]
    selection = read_json(project/recovery["selection_plan_path"])
    expected_choices = [{"job": job.name, "source_job": job.name, "source_role": "parent" if index < failed_index else "recovery",
                         "source_run_dir": parent_text if index < failed_index else recovery_text} for index, job in enumerate(jobs)]
    _require(selection.get("kind") == "prospective_fixed_recovery_selection" and selection.get("logical_jobs") == expected_choices
             and selection.get("logical_job_count") == len(jobs) == recovery["logical_job_count"]
             and selection.get("orchestration_attempt_count_if_complete") == len(jobs)+1 == recovery["orchestration_attempt_count_if_complete"]
             and selection.get("parent_run_dir") == parent_text and selection.get("recovery_run_dir") == recovery_text
             and selection.get("collection_dir") == recovery["planned_collection_dir"]
             and selection.get("base_config_sha256") == parent_manifest["config_sha256"]
             and selection.get("base_freeze_sha256") == parent_manifest["freeze_sha256"]
             and selection.get("process_completion_is_native_solver_success") is False, "Fixed prospective logical selection differs from recovered source choices")
    _require(recovery["scheduled_jobs"] == scheduled and recovered_manifest.get("scheduled_jobs") == scheduled, "Recovery schedule must replace whole Davis and all unlaunched scalers")
    _require(recovered_manifest.get("status") == "launched_recovery" and recovered_manifest.get("recovery") == recovery
             and recovered_manifest.get("recovery_freeze_sha256") == recovery_sha, "Recovery launch/freeze identity mismatch")
    _require(recovered_manifest.get("config") == config and recovered_manifest.get("config_sha256") == parent_manifest["config_sha256"]
             and recovered_manifest.get("freeze") == original == parent_manifest["freeze"]
             and recovered_manifest.get("freeze_sha256") == parent_manifest["freeze_sha256"] == recovery["original_freeze_sha256"], "Recovery modified original algorithm/configuration packet")
    _require(_relative(project, recovered_manifest["parent_run_dir"]) == parent_text
             and recovered_manifest["parent_manifest_sha256"] == sha256(parent/"run-manifest.json"), "Recovery parent manifest identity mismatch")
    outcomes = completion.get("outcomes", [])
    if [item.get("job") for item in outcomes] != scheduled:
        raise IncompleteSuiteError("Recovery terminal ledger omits or reorders a predeclared job")
    _require(all(item.get("event") == "completed" and item.get("exit_code") == 0 for item in outcomes), "Unexpected recovery process failure")
    _ledger(parent, old, halted=True)
    _ledger(recovered, outcomes, halted=False)
    files = {}
    def source_file(alias, filename):
        run = parent if alias == "parent" else recovered
        path = run/filename
        _require(path.is_file(), f"Missing selected source artifact {alias}/{filename}")
        return {"source_run": alias, "source_path": _relative(project, path), "sha256": sha256(path)}
    selected = []
    for index, job in enumerate(jobs):
        alias = "parent" if index < failed_index else "recovery"
        terminal = old[index] if alias == "parent" else outcomes[index-failed_index]
        artifact_names = [*job.required_artifacts(), terminal["log"]]
        if alias == "recovery":
            _job_provenance(project, recovered, job.name, recovery, parent_manifest["freeze_sha256"], recovery_sha)
            artifact_names.append(f"{job.name}-recovery-job-provenance.json")
        if job.name == "development-davis":
            artifact_names.extend(["development-davis-recovery-provenance.json", "development-davis-gamma2-full-solver-failed.json", "development-davis-gamma2-reviewed-incident.json"])
        for filename in artifact_names:
            _require(filename not in files, "Selected collection artifacts collide")
            files[filename] = source_file(alias, filename)
        from analysis.report import _no_failures
        run = parent if alias == "parent" else recovered
        if job.stratum != "scaling":
            _require(read_json(run/f"{job.prefix}-completed.json").get("status") == "completed", "Selected case lacks a complete case marker")
        for index in range(len(job.gamma)):
            filename = f"{job.prefix}-gamma{index}.json.gz"
            value = read_json(run/filename)
            _require(value.get("status") == "completed", "A selected logical gamma is incomplete")
            allowed = None
            if job.name == "development-davis" and index == 2:
                pair = value.get("native_full_solver", {})
                _require(known_incident(pair), "Recovery failed gamma is not the reviewed paired native incident")
                approved = {hashlib.sha256(_canonical(arm)).hexdigest() for arm in pair["paired_arms"].values()}
                allowed = lambda item: item.get("status") == "failed" and hashlib.sha256(_canonical(item)).hexdigest() in approved
            _no_failures(value, filename, allowed_failure=allowed)
        selected.append({"logical_job": job.name, "source_run": alias, "source_job": job.name,
                         "source_outcome": terminal, "artifacts": artifact_names})
    recovery_inventory = {filename for item in selected if item["source_run"] == "recovery" for filename in item["artifacts"]}
    recovery_inventory.update({"run-manifest.json", "run-completed.json", "orchestration.jsonl"})
    _require({path.name for path in recovered.iterdir()} == recovery_inventory,
             "Recovery source has missing or unexpected artifacts; unreviewed failure outputs cannot be ignored")
    parent_failure_name = "development-davis-gamma2-full-solver-failed.json"
    parent_failure = read_json(parent/parent_failure_name)
    recovered_failure = read_json(recovered/parent_failure_name)
    _require(parent_failure.get("status") == recovered_failure.get("status") == "failed"
             and known_incident(parent_failure.get("native_record")) and known_incident(recovered_failure.get("native_record")), "Native failure is not the exact independently reviewed paired incident")
    gamma = read_json(recovered/"development-davis-gamma2.json.gz")
    native = gamma.get("native_full_solver", {})
    preserved = recovered_failure["native_record"]
    timing_additions = {"shared_graph_preparation_seconds", "shared_discovery_seconds", "reduced_additional_preprocessing_seconds", "matched_pipeline_seconds", "pipeline_scope"}
    _require(known_incident(native) and {key:native.get(key) for key in preserved} == preserved
             and set(native)-set(preserved) == timing_additions, "Recovery gamma changed preserved native fields or added unapproved post-preservation fields")
    from analysis.report import _close, _time
    input_record = read_json(recovered/"development-davis-input.json.gz")
    old_input = read_json(parent/"development-davis-input.json.gz")
    graph_fields = ("graph_content_sha256", "graph_fingerprint", "dataset", "bank_sha256")
    bank_fields = ("blocks", "discovery_labels", "seed")
    _require(all(input_record.get(key) == old_input.get(key) for key in graph_fields)
             and all(input_record.get("candidate_bank", {}).get(key) == old_input.get("candidate_bank", {}).get(key) for key in bank_fields),
             "Whole Davis rerun changed original graph/refined bank/discovery partition/seed")
    bank, primary = input_record["candidate_bank"], gamma["production_independent_bank"]
    _close(native["shared_graph_preparation_seconds"], _time(input_record, "graph_preparation_seconds"), "recovery_shared_preparation")
    _close(native["shared_discovery_seconds"], _time(bank, "proposal_seconds"), "recovery_shared_discovery")
    additional = sum(_time(item, key) for item, key in ((bank, "refinement_seconds"), (primary, "checker_seconds"), (primary, "quotient_seconds"), (native, "quotient_incumbent_alignment_seconds")))
    _close(native["reduced_additional_preprocessing_seconds"], additional, "recovery_reduced_preprocessing")
    _require(set(native["matched_pipeline_seconds"]) == {"unreduced", "reduced"}
             and native["pipeline_scope"] == "prepared in-memory graph, discovery incumbent, optional refinement/certification/quotient, input conversion, complete solver, independent validation; shared raw loading and report panels excluded", "Recovery post-preservation timing scope differs from frozen runner")
    for arm, record in native["paired_arms"].items():
        expected = _time(input_record, "graph_preparation_seconds") + _time(bank, "proposal_seconds") + _time(record, "runner_wall_seconds") + _time(native, "original_incumbent_evaluation_seconds") + (additional if arm == "reduced" else 0)
        _close(native["matched_pipeline_seconds"][arm], expected, "recovery_matched_pipeline")
    marker = read_json(recovered/"development-davis-gamma2-reviewed-incident.json")
    _require(marker.get("status") == "known_native_failure_preserved_not_solver_success"
             and (marker.get("prefix"), marker.get("gamma_index"), marker.get("method")) == ("development-davis", 2, "full-solver")
             and marker.get("native_status_retained") == "failed" and marker.get("recovery_freeze_sha256") == recovery_sha
             and marker.get("failed_artifact") == parent_failure_name and marker.get("failed_artifact_sha256") == sha256(recovered/parent_failure_name)
             and marker.get("input_sha256") == INPUT_SHA and marker.get("binary_sha256") == BINARY_SHA
             and marker.get("excluded_inferences") == EXCLUSIONS
             and marker.get("retained_inference") == "independently verified feasible supplied incumbent only", "Reviewed incident marker is missing, broadened or inconsistent")
    case_provenance = read_json(recovered/"development-davis-recovery-provenance.json")
    _require(case_provenance.get("case") == "development-davis" and case_provenance.get("overlay_applied") is True
             and case_provenance.get("config_sha256") == parent_manifest["config_sha256"]
             and case_provenance.get("base_freeze_sha256") == parent_manifest["freeze_sha256"]
             and case_provenance.get("recovery_freeze_sha256") == recovery_sha
             and case_provenance.get("overlay_runtime_source_sha256") == recovery["overlay_runtime_source_sha256"]
             and case_provenance.get("review_sha256") == recovery["review_sha256"], "Whole-case recovery provenance mismatch")
    source_meta = {}
    for alias, run in (("parent", parent), ("recovery", recovered)):
        source_meta[alias] = {"path": _relative(project, run), "metadata_sha256": {
            name: sha256(run/name) for name in ("run-manifest.json", "run-completed.json", "orchestration.jsonl")}}
    source_attempts = [{"source_run": alias, "source_outcome": outcome}
                       for alias, items in (("parent", old), ("recovery", outcomes)) for outcome in items]
    return {"schema_version": "reviewed-recovery-collection-v1", "kind": COLLECTION_KIND, "status": COLLECTION_STATUS,
        "derived_ledger_is_original_run": False, "process_completion_is_native_solver_success": False,
        "selection_policy": SELECTION_POLICY, "logical_job_count": len(jobs), "source_attempt_count": len(source_attempts),
        "parent_completed_jobs_retained": failed_index, "recovery_jobs_selected": len(scheduled),
        "original_failed_attempts_retained": 1, "selected_jobs": selected, "source_attempts": source_attempts,
        "source_runs": source_meta, "copied_artifacts": dict(sorted(files.items())),
        "base_manifest": parent_manifest, "recovery_freeze_path": recovery_freeze_path,
        "planned_collection_dir": recovery["planned_collection_dir"], "selection_plan_sha256": recovery["selection_plan_sha256"],
        "recovery_freeze_sha256": recovery_sha, "recovery_freeze": recovery,
        "incident": {"id": INCIDENT_ID, "selected_failed_native_arms": 2, "all_source_failed_native_arms": 4,
            "parent_failed_artifact": source_file("parent", parent_failure_name), "selected_failed_artifact": source_file("recovery", parent_failure_name),
            "marker_artifact": source_file("recovery", "development-davis-gamma2-reviewed-incident.json"),
            "input_sha256": INPUT_SHA, "binary_sha256": BINARY_SHA,
            "allowed_native_record_sha256": {name: hashlib.sha256(_canonical(record)).hexdigest() for name, record in native["paired_arms"].items()},
            "excluded_inferences": EXCLUSIONS, "retained_inference": marker["retained_inference"]}}


def derived_ledgers(plan: dict) -> tuple[dict, dict, bytes]:
    manifest = {**plan["base_manifest"], "status": "derived_recovered_collection", "suites": ["public", "controls", "scaling"],
        "derived": True, "execution_policy": "deterministic logical selection of exact-byte source artifacts; not original process execution",
        "collection_manifest_sha256": hashlib.sha256(_canonical(plan)).hexdigest()}
    events, outcomes = [], []
    for job in plan["selected_jobs"]:
        name, source = job["logical_job"], job["source_outcome"]
        outcome = {**source, "derived": True, "source_run": job["source_run"], "logical_job": name}
        outcomes.append(outcome)
        events.extend([{"event": "started", "job": name, "derived": True, "source_run": job["source_run"], "utc": "derived logical order; see actual source ledgers"}, outcome])
    complete = {"status": COLLECTION_STATUS, "derived": True, "process_completion_is_native_solver_success": False,
                "outcomes": outcomes, "not_launched_due_failure": [], "logical_job_count": len(outcomes), "source_attempt_count": plan["source_attempt_count"]}
    ledger = "".join(json.dumps(event, ensure_ascii=False, sort_keys=True)+"\n" for event in events).encode()
    return manifest, complete, ledger


def collect_recovery(parent_run: str | Path, recovery_run: str | Path, output_dir: str | Path, *, project_root=".",
                     recovery_freeze_path="experiments/recovery/freeze.json", expected_job_count=139) -> dict:
    project = Path(project_root).resolve()
    output = project/_relative(project, output_dir)
    _require(not output.exists(), "Derived collection is immutable and must not overwrite an existing directory")
    plan = build_collection_plan(parent_run, recovery_run, project_root=project,
        recovery_freeze_path=recovery_freeze_path, expected_job_count=expected_job_count)
    _require(_relative(project, output) == plan["planned_collection_dir"], "Collection output path differs from reviewed prospective selection")
    manifest, completion, ledger = derived_ledgers(plan)
    # Validate every source hash and prepare copies before creating output.
    for item in plan["copied_artifacts"].values():
        _require(sha256(project/item["source_path"]) == item["sha256"], "Source changed during collection planning")
    output.mkdir(parents=True)
    for name, item in sorted(plan["copied_artifacts"].items()):
        raw = (project/item["source_path"]).read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == item["sha256"], "Source changed while exact-byte copying")
        with (output/name).open("xb") as stream:
            stream.write(raw)
    for name, raw in (("collection-manifest.json", _canonical(plan)), ("run-manifest.json", _canonical(manifest)),
                      ("run-completed.json", _canonical(completion)), ("orchestration.jsonl", ledger)):
        with (output/name).open("xb") as stream:
            stream.write(raw)
    return {"status": plan["status"], "collection": str(output), "logical_jobs": plan["logical_job_count"], "actual_source_attempts": plan["source_attempt_count"]}


def audit_collection(run_dir: Path, *, project_root: Path, expected_job_count=None) -> dict:
    recorded = read_json(run_dir/"collection-manifest.json")
    _require(recorded.get("kind") == COLLECTION_KIND and recorded.get("status") == COLLECTION_STATUS, "Unrecognized derived collection status")
    _require(_relative(project_root, run_dir) == recorded["planned_collection_dir"], "Derived collection directory differs from reviewed fixed path")
    sources = recorded["source_runs"]
    actual = build_collection_plan(sources["parent"]["path"], sources["recovery"]["path"], project_root=project_root,
        recovery_freeze_path=recorded["recovery_freeze_path"], expected_job_count=expected_job_count)
    _require(actual == recorded, "Derived collection selection/source/evidence manifest does not reproduce exactly")
    manifest, completion, ledger = derived_ledgers(recorded)
    _require(read_json(run_dir/"run-manifest.json") == manifest and read_json(run_dir/"run-completed.json") == completion
             and (run_dir/"orchestration.jsonl").read_bytes() == ledger, "Derived logical ledger was altered or mislabeled")
    allowed = {*recorded["copied_artifacts"], "collection-manifest.json", "run-manifest.json", "run-completed.json", "orchestration.jsonl"}
    _require({path.name for path in run_dir.iterdir()} == allowed, "Derived collection has missing or extra artifacts")
    for name, item in recorded["copied_artifacts"].items():
        _require(sha256(run_dir/name) == item["sha256"] == sha256(project_root/item["source_path"]), "Derived artifact is not an exact byte copy of its selected source")
    return recorded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-run", required=True)
    parser.add_argument("--recovery-run", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--recovery-freeze", default="experiments/recovery/freeze.json")
    parser.add_argument("--expected-jobs", type=int, default=139)
    args = parser.parse_args()
    try:
        result = collect_recovery(args.parent_run, args.recovery_run, args.output_dir,
            project_root=args.project_root, recovery_freeze_path=args.recovery_freeze, expected_job_count=args.expected_jobs)
    except AnalysisError as error:
        print(json.dumps({"status": "collection_refused", "reason": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
