"""Tiny stdlib-only smoke receipt fixtures; no processes, signals or algorithms."""
import argparse
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "experiments/reproduction/smoke.py"


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="reviews/reproduction/SMOKE_STDLIB_TINY_v003.json")
    args = parser.parse_args()
    started = time.perf_counter()
    spec = importlib.util.spec_from_file_location("smoke_fixture_target", SOURCE)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    cases = []

    def case(name, action, reject=False):
        try:
            action()
        except (ValueError, KeyError, FileNotFoundError, zipfile.BadZipFile):
            if not reject:
                raise
        else:
            if reject:
                raise AssertionError("Expected fixture rejection: " + name)
        cases.append({"case": name, "expected": "REJECT" if reject else "ACCEPT", "status": "PASS"})

    # No actual process identity access, process launch, sleep or signal is permitted.
    def forbidden(*args, **kwargs):
        raise AssertionError("A stdlib receipt fixture attempted actual process/signal work")
    smoke.subprocess.Popen = forbidden
    smoke.os.kill = forbidden
    smoke.time.sleep = forbidden
    tree = ast.parse(SOURCE.read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    case("module_has_no_numpy_graph_or_algorithm_import", lambda: (
        None if not any(name and name.startswith(("numpy", "zrhfd", "matplotlib")) for name in imports)
        else (_ for _ in ()).throw(ValueError("unexpected heavy import"))))
    with tempfile.TemporaryDirectory(prefix="fresh-smoke-stdlib-") as temporary:
        base = Path(temporary).resolve()
        smoke.ROOT = base
        original_executable = sys.executable
        framework = base / "fake_runtime/Python.framework/Versions/3.12"
        runtime_python = framework / "bin/python3.12"
        runtime_python.parent.mkdir(parents=True)
        runtime_python.write_text("# fake interpreter; never executed\n")
        app_python = framework / "Resources/Python.app/Contents/MacOS/Python"
        app_python.parent.mkdir(parents=True)
        app_python.write_text("# same-framework fake app; never executed\n")
        launcher = base / ".venv/bin/python"
        launcher.parent.mkdir(parents=True)
        launcher.symlink_to(runtime_python)
        sys.executable = str(launcher)
        def require(value):
            if not value:
                raise ValueError("Expected true artificial predicate")
        requested = [sys.executable, smoke.SCRIPT, "--internal-sleep-grandchild", "fixture", "token"]
        case("same_framework_app_argv0_accepted", lambda: require(smoke.role_argv_matches([str(app_python), *requested[1:]], requested)))
        other_python = base / "other_runtime/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python"
        other_python.parent.mkdir(parents=True)
        other_python.write_text("# other fake runtime; never executed\n")
        case("other_framework_app_argv0_refused", lambda: require(smoke.role_argv_matches([str(other_python), *requested[1:]], requested)), True)
        archive_dir = base / "attempt_000"
        archive_dir.mkdir()
        terminal = {"status": "COMPLETED", "formal_measurement": False}
        dump(archive_dir / "receipt.json", terminal)
        original = {"worker_result.json": b'{"status":"COMPLETED"}\n', "progress/event.json": b'{"toy":true}\n'}
        with zipfile.ZipFile(archive_dir / "RAW_RECORDS.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in original.items():
                archive.writestr(name, data)
        metadata = {"archive": "RAW_RECORDS.zip", "archive_sha256": smoke.sha(archive_dir / "RAW_RECORDS.zip"),
            "terminal_status": "COMPLETED", "terminal_receipt_sha256": smoke.sha(archive_dir / "receipt.json"),
            "all_original_bytes_preserved": True, "included_in_measurement_runtime": False,
            "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                            "zip_compression_method": zipfile.ZIP_DEFLATED} for name, data in original.items()}}
        dump(archive_dir / "ARCHIVE.json", metadata)
        case("valid_tiny_archive_all_members", lambda: smoke.check_archive(archive_dir))
        for name, mutate in [
            ("active_terminal_refused", lambda record: record.update(status="ACTIVE")),
            ("formal_terminal_refused", lambda record: record.update(formal_measurement=True))]:
            altered = copy.deepcopy(terminal)
            mutate(altered)
            dump(archive_dir / "receipt.json", altered)
            case(name, lambda: smoke.check_archive(archive_dir), True)
        dump(archive_dir / "receipt.json", terminal)
        for name, mutate in [
            ("changed_zip_hash_refused", lambda record: record.update(archive_sha256="0" * 64)),
            ("changed_member_hash_refused", lambda record: record["files"]["worker_result.json"].update(sha256="0" * 64)),
            ("changed_member_codec_refused", lambda record: record["files"]["worker_result.json"].update(zip_compression_method=zipfile.ZIP_STORED)),
            ("missing_member_refused", lambda record: record["files"].pop("progress/event.json"))]:
            altered = copy.deepcopy(metadata)
            mutate(altered)
            dump(archive_dir / "ARCHIVE.json", altered)
            case(name, lambda: smoke.check_archive(archive_dir), True)
        dump(archive_dir / "ARCHIVE.json", metadata)

        helper = base / smoke.SCRIPT
        helper.parent.mkdir(parents=True)
        helper.write_text("# artificial source identity, never executed\n")
        recovery = base / smoke.BASE / "controller_recovery_v001"
        plan = {"token": "artificial-token", "source_sha256": smoke.sha(helper),
                "command_key": "smoke_controller_recovery_v001", "algorithm_executed": False}
        dump(recovery / "plan.json", plan)
        records = []
        for index, role in enumerate(("controller", "child", "grandchild")):
            command = ([sys.executable, smoke.SCRIPT, "--internal-controller", smoke.relative(recovery / "interrupted_controller"), plan["token"], plan["command_key"]]
                       if role == "controller" else [sys.executable, smoke.SCRIPT,
                       "--internal-sleep-tree" if role == "child" else "--internal-sleep-grandchild",
                       smoke.relative(recovery / "interrupted_controller"), plan["token"]])
            records.append({"pid": 900000 + index, "pgid": 900000 + index, "create_time": 1.0,
                "cwd": str(base), "argv": command,
                "token": "artificial-token", "role": role, "source_sha256": smoke.sha(helper)})
        resumed = dict(records[0], pid=900004, pgid=900004, argv=[sys.executable, smoke.SCRIPT,
            "--internal-controller", smoke.relative(recovery / "resumed_controller"), plan["token"], plan["command_key"], "--quick"])
        for dirname, owned in (("interrupted_controller", records), ("resumed_controller", [resumed])):
            folder = recovery / dirname
            quick = dirname == "resumed_controller"
            dump(folder / "launch_request.json", {"argv": owned[0]["argv"], "cwd": str(base),
                "source_sha256": smoke.sha(helper), "start_new_session": True})
            dump(folder / "controller_terminal.json", {"status": "COMPLETED" if quick else "INTERRUPTED",
                "returncode": 0 if quick else 130, "token": plan["token"], "algorithm_executed": False,
                "fixture_wall_seconds": .01})
            for record in owned:
                dump(folder / (record["role"] + ".json"), record)
        dump(recovery / "interrupted_controller/signal_request.json", {"signal": "SIGINT", "target_identity": records[0],
            "only_fresh_fixture_pid_signalled": True})
        command_receipts = []
        for index, receipt in enumerate(({"interrupted": True, "returncode": -15}, {"interrupted": False, "returncode": 0})):
            path = base / "work/reproduction/commands" / plan["command_key"] / f"attempt_{index:03d}/receipt.json"
            dump(path, receipt)
            command_receipts.append(smoke.relative(path))
        files = sorted(path for path in base.rglob("*") if path.is_file() and (path.is_relative_to(recovery) or "commands" in path.parts))
        proof = {"status": "PASS_CONTROLLER_RECOVERY", "algorithm_executed": False,
            "sleep_tree_had_separate_grandchild_session": True, "interrupted_owned_processes": records,
            "resumed_owned_processes": [resumed], "command_receipts": command_receipts,
            "evidence_sha256": {smoke.relative(path): smoke.sha(path) for path in files}}
        smoke.identity_matches = lambda record, allow_dead=False: False
        case("valid_artificial_recovery_metadata", lambda: smoke.verify_recovery(proof))
        for name, mutate in [
            ("empty_owned_census_refused", lambda value: value.update(interrupted_owned_processes=[])),
            ("wrong_owned_role_refused", lambda value: value["interrupted_owned_processes"][1].update(role="controller")),
            ("missing_evidence_refused", lambda value: value["evidence_sha256"].pop(smoke.relative(recovery / "plan.json"))),
            ("reversed_attempt_order_refused", lambda value: value["command_receipts"].reverse()),
            ("quality_algorithm_claim_refused", lambda value: value.update(algorithm_executed=True))]:
            altered = copy.deepcopy(proof)
            mutate(altered)
            case(name, lambda: smoke.verify_recovery(altered), True)
        def resealed_file_case(name, file, alter_file, alter_proof=None, accept=False):
            original_value = json.loads(file.read_text())
            value = copy.deepcopy(original_value)
            alter_file(value)
            dump(file, value)
            altered = copy.deepcopy(proof)
            altered["evidence_sha256"][smoke.relative(file)] = smoke.sha(file)
            if alter_proof:
                alter_proof(altered, value)
            case(name, lambda: smoke.verify_recovery(altered), not accept)
            dump(file, original_value)
        resealed_file_case("resealed_shared_grandchild_pgid_refused", recovery / "interrupted_controller/grandchild.json",
            lambda value: value.update(pgid=records[1]["pgid"]),
            lambda value, record: value["interrupted_owned_processes"].__setitem__(2, record))
        resealed_file_case("resealed_failed_controller_terminal_refused", recovery / "interrupted_controller/controller_terminal.json",
            lambda value: value.update(status="FAILED"))
        resealed_file_case("resealed_wrong_signal_target_refused", recovery / "interrupted_controller/signal_request.json",
            lambda value: value.update(target_identity=records[1]))
        resealed_file_case("resealed_missing_role_argv_refused", recovery / "interrupted_controller/child.json",
            lambda value: value.update(argv=records[0]["argv"]),
            lambda value, record: value["interrupted_owned_processes"].__setitem__(1, record))
        resealed_file_case("resealed_invalid_controller_time_refused", recovery / "resumed_controller/controller_terminal.json",
            lambda value: value.update(fixture_wall_seconds=True))
        resealed_file_case("stored_same_framework_app_identity_accepted", recovery / "interrupted_controller/grandchild.json",
            lambda value: value.update(argv=[str(app_python), *value["argv"][1:]]),
            lambda value, record: value["interrupted_owned_processes"].__setitem__(2, record), accept=True)
        resealed_file_case("stored_other_framework_app_identity_refused", recovery / "interrupted_controller/grandchild.json",
            lambda value: value.update(argv=[str(other_python), *value["argv"][1:]]),
            lambda value, record: value["interrupted_owned_processes"].__setitem__(2, record))
        smoke.identity_matches = lambda record, allow_dead=False: True
        case("still_live_owned_process_refused", lambda: smoke.verify_recovery(proof), True)
        sys.executable = original_executable
    report = {"status": "PASS_STDLIB_TINY", "cases_passed": len(cases), "cases": cases,
        "fixture_wall_seconds": time.perf_counter() - started,
        "source_sha256": {str(SOURCE.relative_to(ROOT)): hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                          str(Path(__file__).relative_to(ROOT)): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        "process_identity_lookup_mocked_only_in_fixture": True,
        "artificial_framework_paths_and_sys_executable_only_inside_fixture": True,
        "actual_processes_signals_install_or_algorithms": "NOT_RUN",
        "fresh_eight_method_smoke": "NOT_RUN", "actual_controller_recovery": "NOT_RUN"}
    output = ROOT / args.output
    if output.exists():
        raise FileExistsError("Keep earlier fixture evidence; choose a new output path")
    dump(output, report)
    print(json.dumps({"status": report["status"], "cases_passed": len(cases), "fixture_wall_seconds": report["fixture_wall_seconds"]}))


if __name__ == "__main__":
    main()
