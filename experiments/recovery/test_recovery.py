"""Lightweight recovery engineering checks; never launch native processes.

The immutable halted record is read as a fixture and copied before mutation.
All writes occur in pytest temporary directories. These checks establish no
solver correctness, performance, or global-optimality result.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from experiments import run_controls
from experiments.recovery import policy, prepare_freeze, run_case, run_remaining
from experiments.run_public import write_once


ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "experiments/runs/20260929-frozen-v1"
FAILED = PARENT / "development-davis-gamma2-full-solver-failed.json"
PREFIX = "development-davis"
GAMMA_INDEX = 2
METHOD = "full-solver"
RECOVERY_SHA = "fixture-reviewed-recovery-freeze"


def read(path):
    return json.loads(Path(path).read_text())


@pytest.fixture
def incident():
    return deepcopy(read(FAILED)["native_record"])


@pytest.fixture
def config():
    return read(ROOT / "experiments/config.json")


@pytest.fixture
def parent_completion():
    return deepcopy(read(PARENT / "run-completed.json"))


def matches(record, **scope):
    return policy.known_incident(record, prefix=scope.get("prefix", PREFIX),
                                 gamma_index=scope.get("gamma_index", GAMMA_INDEX),
                                 method=scope.get("method", METHOD))


def synchronize(record, name="unreduced"):
    """Keep both serialized aliases equal so tests reach the target guard."""
    replacement = record["paired_arms"][name]
    record["records"] = [deepcopy(replacement) if arm["case_name"].endswith(f"-{name}") else arm
                         for arm in record["records"]]


def set_arm_field(record, path, value):
    target = record["paired_arms"]["unreduced"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    synchronize(record)


def preserve(record, directory, **scope):
    return policy.recovery_preserver(run_controls.preserve_native_failure, RECOVERY_SHA)(
        directory, scope.get("prefix", PREFIX), scope.get("gamma_index", GAMMA_INDEX), record,
        method=scope.get("method", METHOD))


def schedule(config, completion, output="fixture-recovery"):
    return run_remaining.recovery_schedule(config, completion, output,
        "experiments/config.json", "experiments/freeze.json", "experiments/recovery/freeze.json")


def test_exact_two_arm_failure_is_preserved_before_marker_without_status_rewrite(incident, tmp_path):
    original_bytes = FAILED.read_bytes()
    untouched = deepcopy(incident)
    original = tmp_path / "original-policy"
    with pytest.raises(RuntimeError, match="Unexpected native full-solver failure"):
        run_controls.preserve_native_failure(original, PREFIX, GAMMA_INDEX, incident, method=METHOD)
    expected = (original / f"{PREFIX}-gamma2-full-solver-failed.json").read_bytes()
    assert expected == original_bytes

    recovered = tmp_path / "recovery-policy"
    failed = recovered / f"{PREFIX}-gamma2-full-solver-failed.json"
    marker = recovered / f"{PREFIX}-gamma2-reviewed-incident.json"
    sequence = []
    def observed_original(*args, **kwargs):
        assert not marker.exists()
        try:
            run_controls.preserve_native_failure(*args, **kwargs)
        finally:
            sequence.append((failed.exists(), marker.exists()))
    policy.recovery_preserver(observed_original, RECOVERY_SHA)(
        recovered, PREFIX, GAMMA_INDEX, incident, method=METHOD)

    assert sequence == [(True, False)]
    assert failed.read_bytes() == expected
    assert incident == untouched
    assert FAILED.read_bytes() == original_bytes
    saved = read(failed)
    assert saved["status"] == "failed"
    assert all(arm["status"] == "failed" for arm in saved["native_record"]["paired_arms"].values())
    assert all(arm["status"] == "failed" for arm in saved["native_record"]["records"])
    notice = read(marker)
    assert notice["status"] == "known_native_failure_preserved_not_solver_success"
    assert notice["native_status_retained"] == "failed"
    assert notice["failed_artifact_sha256"] == hashlib.sha256(expected).hexdigest()
    assert notice["recovery_freeze_sha256"] == RECOVERY_SHA
    assert set(notice["excluded_inferences"]) == {
        "native optimality", "native packing lower bound", "bound gap", "completed solve-time ratio"}


@pytest.mark.parametrize("path,value", [
    (("conversion", "input_sha256"), "different-input"),
    (("binary_sha256",), "different-binary"),
    (("build_provenance_sha256",), "different-build-provenance"),
    (("native", "stderr"), "different assertion\n"),
    (("native", "exit_code"), -11),
    (("timeout_seconds",), 31),
    (("native", "outer_timeout_triggered"), True),
    (("conversion", "gamma"), "1"),
    (("conversion", "volume"), 180),
    (("conversion", "budget"), 3420),
    (("full_solver_entry_called",), False),
    (("full_kapoce_solver",), False),
    (("incumbent_Q_original_exact",), "0"),
    (("incumbent", "verified_independently"), False),
    (("status",), "validation_failure"),
    (("status",), "unavailable_build"),
])
def test_changed_incident_falls_back_to_original_halt(incident, tmp_path, path, value):
    set_arm_field(incident, path, value)
    assert not matches(incident)
    with pytest.raises(RuntimeError, match="Unexpected native full-solver failure"):
        preserve(incident, tmp_path)
    assert not (tmp_path / f"{PREFIX}-gamma2-reviewed-incident.json").exists()
    assert read(tmp_path / f"{PREFIX}-gamma2-full-solver-failed.json")["native_record"] == incident


@pytest.mark.parametrize("scope", [
    {"prefix": "development-karate"}, {"gamma_index": 1}, {"method": "preprocessing"},
])
def test_exception_applies_only_to_exact_case_resolution_and_method(incident, tmp_path, scope):
    assert not matches(incident, **scope)
    with pytest.raises(RuntimeError):
        preserve(incident, tmp_path, **scope)
    assert not list(tmp_path.glob("*-reviewed-incident.json"))


@pytest.mark.parametrize("change", ["one_arm", "extra_record", "mismatched_alias"])
def test_two_complete_matching_aliases_are_required(incident, tmp_path, change):
    if change == "one_arm":
        incident["paired_arms"].pop("reduced")
        incident["records"] = [arm for arm in incident["records"] if arm["case_name"].endswith("-unreduced")]
    elif change == "extra_record":
        incident["records"].append({"case_name": "unrelated-failure", "status": "failed"})
    else:
        incident["records"][0]["native"]["stderr"] = "unmatched serialized alias"
    assert not matches(incident)
    with pytest.raises(RuntimeError):
        preserve(incident, tmp_path)
    assert not (tmp_path / f"{PREFIX}-gamma2-reviewed-incident.json").exists()


@pytest.mark.parametrize("status", ["failed", "validation_failure", "unavailable_build"])
@pytest.mark.parametrize("location", ["top_nested_list", "arm_nested_list", "record_nested_dict"])
def test_additional_nested_bad_status_is_never_exempted(incident, tmp_path, status, location):
    extra = {"diagnostics": [{"deep": {"status": status}}]}
    if location == "top_nested_list":
        incident["additional_report"] = extra
    elif location == "arm_nested_list":
        incident["paired_arms"]["unreduced"]["additional_report"] = extra
        synchronize(incident)
    else:
        incident["records"][0]["additional_report"] = extra
        name = incident["records"][0]["case_name"].rsplit("-", 1)[-1]
        incident["paired_arms"][name] = deepcopy(incident["records"][0])
    assert not matches(incident)
    with pytest.raises(RuntimeError):
        preserve(incident, tmp_path)
    assert not (tmp_path / f"{PREFIX}-gamma2-reviewed-incident.json").exists()


@pytest.mark.parametrize("existing", ["failed", "marker"])
def test_exclusive_creation_collisions_still_raise_and_keep_old_bytes(incident, tmp_path, existing):
    name = f"{PREFIX}-gamma2-full-solver-failed.json" if existing == "failed" else f"{PREFIX}-gamma2-reviewed-incident.json"
    target = tmp_path / name
    sentinel = b"immutable preexisting fixture\n"
    target.write_bytes(sentinel)
    with pytest.raises(FileExistsError):
        preserve(incident, tmp_path)
    assert target.read_bytes() == sentinel
    if existing == "failed":
        assert not (tmp_path / f"{PREFIX}-gamma2-reviewed-incident.json").exists()
    else:
        assert read(tmp_path / f"{PREFIX}-gamma2-full-solver-failed.json")["status"] == "failed"


def test_recovery_is_entire_davis_case_plus_all_72_scalers(config, parent_completion):
    original_config, original_parent = deepcopy(config), deepcopy(parent_completion)
    jobs = schedule(config, parent_completion)
    names = [name for name, _ in jobs]
    assert len(jobs) == len(set(names)) == 73
    assert names == ["development-davis", *parent_completion["not_launched_due_failure"]]
    davis = jobs[0][1]
    assert davis[:2] == ["-m", "experiments.recovery.run_case"]
    assert davis[davis.index("--stratum") + 1] == "development"
    assert davis[davis.index("--case") + 1] == "davis"
    assert "--gamma" not in davis and "--gamma-index" not in davis
    assert davis[-2:] == ["--recovery-freeze", "experiments/recovery/freeze.json"]
    assert all(name.startswith("scaling-") and command[1] == "experiments.run_scaling"
               and "--recovery-freeze" not in command for name, command in jobs[1:])
    assert config == original_config and parent_completion == original_parent


@pytest.mark.parametrize("change", [
    "parent_status", "earlier_event", "last_event", "earlier_exit", "last_exit", "last_job",
    "outcome_order", "missing_outcome", "unlaunched_order", "missing_unlaunched", "extra_unlaunched",
])
def test_changed_parent_completion_or_job_list_is_rejected(config, parent_completion, change):
    if change == "parent_status":
        parent_completion["status"] = "completed"
    elif change == "earlier_event":
        parent_completion["outcomes"][0]["event"] = "failed"
    elif change == "last_event":
        parent_completion["outcomes"][-1]["event"] = "completed"
    elif change == "earlier_exit":
        parent_completion["outcomes"][0]["exit_code"] = 1
    elif change == "last_exit":
        parent_completion["outcomes"][-1]["exit_code"] = 0
    elif change == "last_job":
        parent_completion["outcomes"][-1]["job"] = "development-karate"
    elif change == "outcome_order":
        parent_completion["outcomes"][:2] = reversed(parent_completion["outcomes"][:2])
    elif change == "missing_outcome":
        parent_completion["outcomes"].pop(0)
    elif change == "unlaunched_order":
        parent_completion["not_launched_due_failure"][:2] = reversed(parent_completion["not_launched_due_failure"][:2])
    elif change == "missing_unlaunched":
        parent_completion["not_launched_due_failure"].pop()
    else:
        parent_completion["not_launched_due_failure"].append("unexpected-job")
    with pytest.raises(ValueError, match="Parent halt"):
        schedule(config, parent_completion)


def test_changed_config_job_list_is_rejected(config, parent_completion):
    config["proposal"]["seeds"][0] = 91
    with pytest.raises(ValueError, match="Parent halt"):
        schedule(config, parent_completion)


def test_selection_uses_all_recovery_davis_resolutions_without_favorable_repeat_choice(config, parent_completion):
    selection = prepare_freeze.prospective_selection(config, parent_completion)
    rows = selection["logical_jobs"]
    assert selection["logical_job_count"] == len(rows) == 139
    assert selection["orchestration_attempt_count_if_complete"] == 140
    assert all(row["source_role"] == "parent" for row in rows[:66])
    assert rows[66]["job"] == "development-davis"
    assert all(row["source_role"] == "recovery" for row in rows[66:])
    assert selection["process_completion_is_native_solver_success"] is False


@pytest.mark.parametrize("change", ["schedule", "output"])
def test_main_rejects_changed_reviewed_schedule_or_output_before_creation(config, parent_completion, tmp_path, change):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    parent = tmp_path / "parent"
    write_once(parent / "run-completed.json", parent_completion)
    output = tmp_path / "new-run"
    recovery = {"original_config_path": str(config_path), "original_freeze_path": "fixture-base-freeze",
                "parent_run_dir": str(parent), "scheduled_jobs": ["different-reviewed-job"],
                "planned_recovery_run_dir": str(output if change == "schedule" else tmp_path / "fixed-other-output")}
    arguments = ["recovery", "--recovery-freeze", "fixture-recovery-freeze", "--run-dir", str(output)]
    with patch.object(run_remaining, "validate_recovery", return_value=(recovery, {})) as validate, \
         patch.object(run_remaining.subprocess, "run") as launch, patch("sys.argv", arguments):
        with pytest.raises(ValueError, match="Job schedule differs|Output directory differs"):
            run_remaining.main()
        validate.assert_called_once_with("fixture-recovery-freeze", parent_files=True)
        launch.assert_not_called()
    assert not output.exists()


@pytest.mark.parametrize("changed", ["parent", "selection", "engineering"])
def test_parent_and_reviewed_artifact_hashes_reject_metadata_changes(tmp_path, changed):
    base = tmp_path / "base-freeze.json"
    base.write_text("{}")
    parent = tmp_path / "parent-completion.json"
    write_once(parent, {"status": "halted_for_repair", "seconds": 1})
    selection = tmp_path / "selection-plan.json"
    write_once(selection, {"fixture_selection": 1})
    engineering = tmp_path / "engineering-validation.json"
    write_once(engineering, {"status": "passed", "fixture": 1})
    review_path = tmp_path / "review.json"
    write_once(review_path, {"status": "approved_for_recovery_configuration_freeze",
                             "overlay_runtime_source_sha256": {},
                             "selection_plan_sha256": policy.sha256(selection),
                             "engineering_validation_sha256": policy.sha256(engineering)})
    recovery_path = tmp_path / "recovery-freeze.json"
    packet = {"status": policy.STATUS, "original_config_path": "fixture-config",
              "original_freeze_path": str(base), "original_freeze_sha256": policy.sha256(base),
              "overlay_runtime_source_sha256": {}, "review_path": str(review_path),
              "review_sha256": policy.sha256(review_path), "incident_evidence_sha256": {},
              "selection_plan_path": str(selection), "selection_plan_sha256": policy.sha256(selection),
              "engineering_validation_path": str(engineering),
              "engineering_validation_sha256": policy.sha256(engineering),
              "parent_artifact_sha256": {str(parent): policy.sha256(parent)}}
    write_once(recovery_path, packet)
    with patch.object(policy, "validate_freeze", return_value={"fixture": True}):
        policy.validate_recovery(recovery_path, parent_files=True)
        target = {"parent": parent, "selection": selection, "engineering": engineering}[changed]
        target.write_text(json.dumps({"changed_metadata": changed}))
        with pytest.raises(ValueError, match="Original halted evidence changed|Reviewed recovery artifact changed"):
            policy.validate_recovery(recovery_path, parent_files=True)


@pytest.mark.parametrize("change", ["other_output", "parent_output", "missing_manifest", "wrong_manifest_status", "wrong_manifest_sha"])
def test_direct_case_rejects_wrong_output_or_manifest_before_any_write(tmp_path, change):
    parent = tmp_path / "parent"
    planned = tmp_path / "planned-recovery"
    actual = planned
    if change == "other_output":
        actual = tmp_path / "unplanned-output"
    elif change == "parent_output":
        planned = actual = parent
    recovery_freeze = tmp_path / "recovery-freeze.json"
    recovery_freeze.write_text("{}")
    if change in {"wrong_manifest_status", "wrong_manifest_sha"}:
        planned.mkdir()
        (planned / "run-manifest.json").write_text(json.dumps({
            "status": "launched" if change == "wrong_manifest_status" else "launched_recovery",
            "recovery_freeze_sha256": "different" if change == "wrong_manifest_sha" else policy.sha256(recovery_freeze)}))
    recovery = {"original_config_path": "fixture-config", "original_freeze_path": "fixture-base-freeze",
                "planned_recovery_run_dir": str(planned), "parent_run_dir": str(parent)}
    arguments = ["case", "--config", "fixture-config", "--freeze", "fixture-base-freeze",
                 "--run-dir", str(actual), "--stratum", "development", "--case", "davis",
                 "--recovery-freeze", str(recovery_freeze)]
    with patch.object(run_case, "validate_recovery", return_value=(recovery, {})), \
         patch.object(run_case, "write_once") as write, \
         patch.object(run_case.run_controls, "run_case") as execute, patch("sys.argv", arguments):
        with pytest.raises((ValueError, FileNotFoundError)):
            run_case.main()
        write.assert_not_called()
        execute.assert_not_called()
    assert not (actual / "development-davis-recovery-provenance.json").exists()
