"""Fresh-workspace eight-method smoke and unlabelled controller recovery.

This is an optional engineering stage. It never uses the original workspace,
official datasets, formal task outputs or formal performance estimates.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = "experiments/reproduction/smoke.py"
DRIVER = "experiments/reproduction/driver.py"
RUN = "results/m5/fresh_setup_smoke_v001"
BASE = "work/reproduction/smoke"
METHODS = {"zr_hfd", "zh_prov", "hfd_no_volume", "hfd_oracle",
           "tlhfd_no_volume", "tlhfd_oracle", "clique_acl_no_volume", "clique_acl_oracle"}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text() != content:
            raise ValueError("Immutable smoke evidence differs: " + str(path))
        return
    with path.open("x") as stream:
        stream.write(content)


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def contained(path):
    path = Path(path).resolve()
    if not path.is_relative_to((ROOT / BASE).resolve()):
        raise ValueError("Recovery fixture path must stay in its fresh smoke directory")
    return path


def fresh_environment():
    marker = read(ROOT / ".REPRODUCTION_WORKSPACE.json")
    if marker.get("mode") != "FRESH_CPU_REPRODUCTION" or ROOT == Path(marker["origin"]).resolve():
        raise ValueError("Smoke requires a separate marked fresh workspace")
    if ((ROOT / ".venv").is_symlink() or not Path(sys.prefix).resolve().is_relative_to(ROOT)
            or Path(sys.prefix).resolve() != (ROOT / ".venv").resolve()):
        raise ValueError("Smoke must use the fresh workspace's own virtual environment")
    lock = read(ROOT / "experiments/reproduction/lock.json")
    if marker["lock_sha256"] != sha(ROOT / "experiments/reproduction/lock.json"):
        raise ValueError("Fresh workspace lock differs from its creation marker")
    for path in (SCRIPT, DRIVER):
        if lock.get("reproduction_entry_sha256", {}).get(path) != sha(ROOT / path):
            raise ValueError("Smoke/driver source is not included in the final reproduction lock: " + path)
    sys.path.insert(0, str(ROOT))
    from experiments.reproduction.driver import frozen_sources
    frozen_sources(ROOT)
    if lock["stage_freeze_status"]["m5"] != "SOURCE_FROZEN":
        raise ValueError("M5 source freeze is required before the engineering smoke")
    versions = {}
    for line in (ROOT / "provenance/dependency_versions.txt").read_text().splitlines():
        if line.strip():
            name, version = line.split("==", 1)
            actual = importlib.metadata.version(name)
            if actual != version:
                raise ValueError("Fresh dependency version differs: " + name)
            versions[name] = actual
    receipts = sorted((ROOT / "work/reproduction/commands/python_dependencies").glob("attempt_*/receipt.json"))
    if not receipts or read(receipts[-1])["returncode"] != 0:
        raise ValueError("Fresh setup dependency-install receipt is required")
    request = read(receipts[-1].parent / "request.json")
    if request["argv"] != [str(ROOT / ".venv/bin/python"), "-m", "pip", "install",
                           "--requirement", "provenance/dependency_versions.txt"]:
        raise ValueError("Dependency installation did not use the fresh virtual environment")
    return {"marker_sha256": sha(ROOT / ".REPRODUCTION_WORKSPACE.json"),
            "lock_sha256": sha(ROOT / "experiments/reproduction/lock.json"),
            "fresh_python_prefix": str(Path(sys.prefix).resolve()),
            "python_version": sys.version, "dependency_versions": versions,
            "dependency_install_receipt": relative(receipts[-1]),
            "dependency_install_receipt_sha256": sha(receipts[-1])}


def check_archive(directory):
    """Validate the original logical members, without invoking compression."""
    directory = Path(directory)
    terminal = read(directory / "receipt.json")
    metadata = read(directory / "ARCHIVE.json")
    if terminal.get("status") != "COMPLETED" or terminal.get("formal_measurement") is not False:
        raise ValueError("Eight-method toy smoke needs a completed nonformal terminal")
    if (metadata.get("terminal_status") != terminal["status"]
            or metadata.get("terminal_receipt_sha256") != sha(directory / "receipt.json")
            or not metadata.get("all_original_bytes_preserved")
            or metadata.get("included_in_measurement_runtime") is not False):
        raise ValueError("Archive terminal/provenance identity differs")
    archive_path = directory / metadata["archive"]
    if archive_path.name != "RAW_RECORDS.zip" or sha(archive_path) != metadata["archive_sha256"]:
        raise ValueError("Archive identity differs")
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(metadata["files"]):
            raise ValueError("Archive member census differs")
        for name, expected in metadata["files"].items():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Archive member path escapes attempt")
            info = archive.getinfo(name)
            if info.file_size != expected["bytes"] or info.compress_type != expected["zip_compression_method"]:
                raise ValueError("Archive member size/codec differs")
            digest = hashlib.sha256()
            with archive.open(name) as stream:
                for block in iter(lambda: stream.read(1048576), b""):
                    digest.update(block)
            if digest.hexdigest() != expected["sha256"]:
                raise ValueError("Archive member original bytes differ: " + name)
    return metadata


def verify_eight_methods():
    sys.path.insert(0, str(ROOT))
    from experiments.archival import read_json
    run = ROOT / RUN
    manifest = read(run / "manifest.json")
    frozen = manifest["frozen"]
    canonical = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != manifest["frozen_sha256"]:
        raise ValueError("Toy manifest semantic digest differs")
    tasks = frozen["tasks"]
    if (len(tasks) != 8 or {task["method"] for task in tasks} != METHODS
            or len({task["task_id"] for task in tasks}) != 8
            or frozen["toy"] is not True or frozen["formal_measurement"] is not False
            or frozen["threads"] != 1 or frozen["tl_backend"] != "numba"):
        raise ValueError("Smoke must contain all eight frozen methods on the single toy query")
    configuration = read(ROOT / frozen["configuration_file"])
    if configuration != frozen["configuration"] or sha(ROOT / frozen["configuration_file"]) != frozen["configuration_sha256"]:
        raise ValueError("Toy method configuration changed")
    source_inventory = {}
    for name, expected in frozen["source_pins"].items():
        for path in (ROOT / name, run / "sources" / name):
            if sha(path) != expected:
                raise ValueError("Toy live/snapshot source differs: " + name)
            source_inventory[relative(path)] = expected
    records = []
    for task in tasks:
        if (task["toy"] is not True or task["dataset"] != "m5_toy_interface"
                or task["query"]["query_id"] != "m5_toy_0"
                or sha(ROOT / task["input_path"]) != task["input_sha256"]):
            raise ValueError("Toy task/input identity differs")
        attempts = sorted((run / "queries" / task["task_id"]).glob("attempt_*"))
        if not attempts:
            raise ValueError("Toy task has no raw attempt")
        attempt_records = []
        for directory in attempts:
            terminal = read(directory / "receipt.json")
            if terminal.get("status") != "COMPLETED":
                raise ValueError("Smoke retains a failed/partial task and cannot claim PASS")
            archive = check_archive(directory)
            request = read(directory / "request.json")
            execution = read(directory / "execution_request.json")
            result = read_json(directory / "worker_result.json")
            context = execution["source_context"]
            if (request != {"task": task, "configuration": configuration, "tl_backend": "numba"}
                    or context["manifest_file_sha256"] != sha(run / "manifest.json")
                    or context["source_pins"] != frozen["source_pins"]
                    or result.get("status") != "COMPLETED" or result.get("task") != task
                    or result.get("formal_measurement") is not False
                    or terminal["worker_result_sha256"] != archive["files"]["worker_result.json"]["sha256"]):
                raise ValueError("Toy request/worker/raw context differs")
            attempt_records.append({"attempt": relative(directory),
                "receipt_sha256": sha(directory / "receipt.json"),
                "request_sha256": sha(directory / "request.json"),
                "execution_request_sha256": sha(directory / "execution_request.json"),
                "archive_index_sha256": sha(directory / "ARCHIVE.json"),
                "archive_sha256": archive["archive_sha256"],
                "all_member_sha256_verified": True, "members": archive["files"],
                "status": terminal["status"], "nonformal_method_wall_seconds": terminal["wall_seconds"]})
        records.append({"task_id": task["task_id"], "method": task["method"], "attempts": attempt_records})
    return {"status": "PASS_EIGHT_NONFORMAL_TOY_METHODS", "run": RUN,
            "manifest_sha256": sha(run / "manifest.json"), "tasks": records,
            "source_and_snapshot_sha256": source_inventory,
            "formal_quality_or_cost_claim": False}


def ownership(directory, token, role):
    """Record actual identity only for this helper's freshly created processes."""
    import psutil
    directory = contained(directory)
    process = psutil.Process(os.getpid())
    record = {"pid": process.pid, "pgid": os.getpgid(process.pid),
              "create_time": process.create_time(), "cwd": process.cwd(),
              "argv": process.cmdline(), "token": token, "role": role,
              "source_sha256": sha(ROOT / SCRIPT)}
    save_new(directory / (role + ".json"), record)
    return record


def project_python_paths(root):
    """Fresh launcher plus only its own macOS Framework app executable."""
    launcher = root / ".venv/bin/python"
    if not launcher.is_file():
        raise ValueError("Fresh Python launcher is absent")
    resolved = launcher.resolve()
    allowed = {resolved}
    version = resolved.parent.parent
    if (resolved.parent.name == "bin" and version.parent.name == "Versions"
            and version.parent.parent.name == "Python.framework"):
        app = version / "Resources/Python.app/Contents/MacOS/Python"
        if app.is_file():
            allowed.add(app.resolve())
    return allowed


def role_argv_matches(actual, requested):
    return (isinstance(actual, list) and len(actual) == len(requested)
            and actual[1:] == requested[1:] and Path(actual[0]).resolve() in project_python_paths(ROOT))


def owned_process(record, allow_dead=False):
    import psutil
    if (record["source_sha256"] != sha(ROOT / SCRIPT) or record["cwd"] != str(ROOT)
            or record["token"] not in record["argv"]
            or len(record["argv"]) < 2 or record["argv"][1] != SCRIPT
            or Path(record["argv"][0]).resolve() not in project_python_paths(ROOT)
            or record["pgid"] == os.getpgrp()):
        raise ValueError("Owned fixture metadata does not identify this helper")
    if (type(record["pid"]) is not int or record["pid"] <= 0 or type(record["pgid"]) is not int
            or isinstance(record["create_time"], bool) or not isinstance(record["create_time"], (int, float))
            or not math.isfinite(record["create_time"]) or record["create_time"] <= 0):
        raise ValueError("Owned fixture process identity fields are invalid")
    try:
        process = psutil.Process(record["pid"])
        if process.status() == psutil.STATUS_ZOMBIE:
            return None
        valid = (process.create_time() == record["create_time"]
                 and process.cwd() == record["cwd"] and process.cmdline() == record["argv"]
                 and os.getpgid(record["pid"]) == record["pgid"])
    except psutil.NoSuchProcess:
        return None
    if not valid:
        if allow_dead:
            # PID reuse is no longer an owned process; never signal it.
            return None
        raise ValueError("Owned fixture process identity changed")
    return process


def identity_matches(record, allow_dead=False):
    return owned_process(record, allow_dead) is not None


def internal_controller(directory, token, key, quick=False):
    sys.path.insert(0, str(ROOT))
    from experiments.reproduction.driver import run_command
    ownership(directory, token, "controller")
    command = ([sys.executable, "-c", "print('unlabelled controller resume fixture')"] if quick else
               [sys.executable, SCRIPT, "--internal-sleep-tree", relative(directory), token])
    started = time.perf_counter()
    status, code = "COMPLETED", 0
    try:
        run_command(ROOT, key, command)
    except KeyboardInterrupt:
        status, code = "INTERRUPTED", 130
    except BaseException as error:
        save_new(Path(directory) / "controller_exception.json", {"phase": "run_command",
            "command_key": key, "exception": repr(error), "exception_type": type(error).__name__,
            "traceback": traceback.format_exc()})
        status, code = "FAILED", 1
    save_new(Path(directory) / "controller_terminal.json", {"status": status,
        "returncode": code, "fixture_wall_seconds": time.perf_counter() - started,
        "token": token, "algorithm_executed": False})
    return code


def internal_sleep(directory, token, grandchild=False):
    directory = contained(directory)
    ownership(directory, token, "grandchild" if grandchild else "child")
    if not grandchild:
        with (directory / "grandchild.stdout.log").open("xb") as out, (directory / "grandchild.stderr.log").open("xb") as err:
            child = subprocess.Popen([sys.executable, SCRIPT, "--internal-sleep-grandchild",
                relative(directory), token], cwd=ROOT, stdout=out, stderr=err, start_new_session=True)
            save_new(directory / "grandchild_launch.json", {"pid": child.pid, "separate_session": True})
            child.wait(timeout=60)
    else:
        time.sleep(60)


def start_controller(directory, token, key, quick=False):
    directory.mkdir(parents=True)
    command = [sys.executable, SCRIPT, "--internal-controller", relative(directory), token, key]
    if quick:
        command.append("--quick")
    save_new(directory / "launch_request.json", {"argv": command, "cwd": str(ROOT),
        "source_sha256": sha(ROOT / SCRIPT), "start_new_session": True})
    with (directory / "stdout.log").open("xb") as out, (directory / "stderr.log").open("xb") as err:
        return subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err, start_new_session=True)


def wait_records(directory, roles, process):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if all((directory / (role + ".json")).exists() for role in roles):
            records = [read(directory / (role + ".json")) for role in roles]
            if all(identity_matches(record) for record in records):
                return records
        if process.poll() is not None:
            raise RuntimeError("Fixture controller exited before owned process handshake")
        time.sleep(.05)
    raise TimeoutError("Owned process handshake exceeded 10 seconds")


def cleanup_owned(directory):
    """Exceptional cleanup is restricted to exact fixture identities."""
    import psutil
    records = [read(path) for path in directory.rglob("*.json")
               if path.name in {"controller.json", "child.json", "grandchild.json"}]
    for record in reversed(records):
        process = owned_process(record, allow_dead=True)
        if process is not None:
            try:
                process.send_signal(signal.SIGTERM)
            except (ProcessLookupError, psutil.NoSuchProcess):
                pass
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and any(identity_matches(record, allow_dead=True) for record in records):
        time.sleep(.05)
    for record in reversed(records):
        process = owned_process(record, allow_dead=True)
        if process is not None:
            try:
                process.send_signal(signal.SIGKILL)
            except (ProcessLookupError, psutil.NoSuchProcess):
                pass


def verify_recovery(receipt):
    if (receipt.get("status") != "PASS_CONTROLLER_RECOVERY" or receipt.get("algorithm_executed") is not False
            or receipt.get("sleep_tree_had_separate_grandchild_session") is not True):
        raise ValueError("Recovery receipt lacks the intended engineering fixture scope")
    interrupted = receipt.get("interrupted_owned_processes", [])
    resumed = receipt.get("resumed_owned_processes", [])
    if (len(interrupted) != 3 or {item.get("role") for item in interrupted} != {"controller", "child", "grandchild"}
            or len(resumed) != 1 or resumed[0].get("role") != "controller"
            or len({item.get("pid") for item in interrupted}) != 3
            or len({item.get("token") for item in interrupted + resumed}) != 1
            or not receipt.get("evidence_sha256") or len(receipt.get("command_receipts", [])) != 2):
        raise ValueError("Recovery proof lacks the full owned process and command census")
    version = receipt.get("recovery_version", 1)
    if type(version) is not int or version < 1:
        raise ValueError("Invalid recovery-only engineering version")
    base = ROOT / BASE / f"controller_recovery_v{version:03d}"
    plan = read(base / "plan.json")
    if plan["source_sha256"] != sha(ROOT / SCRIPT) or plan["token"] != interrupted[0]["token"]:
        raise ValueError("Recovery plan/source/token identity differs")
    if plan["command_key"] != f"smoke_controller_recovery_v{version:03d}" or plan["algorithm_executed"] is not False:
        raise ValueError("Recovery plan command or scope differs")
    roles = {record["role"]: record for record in interrupted}
    if any(type(record["pid"]) is not int or record["pid"] <= 0 or record["pgid"] != record["pid"]
           for record in interrupted + resumed) or roles["child"]["pgid"] == roles["grandchild"]["pgid"]:
        raise ValueError("Owned fixture process groups are not the three independent sessions")
    required = [base / "plan.json"]
    for directory, records in ((base / "interrupted_controller", interrupted), (base / "resumed_controller", resumed)):
        required.extend([directory / "launch_request.json", directory / "controller_terminal.json"])
        quick = directory.name == "resumed_controller"
        command = [sys.executable, SCRIPT, "--internal-controller", relative(directory), plan["token"], plan["command_key"]]
        if quick:
            command.append("--quick")
        launch = read(directory / "launch_request.json")
        if launch != {"argv": command, "cwd": str(ROOT), "source_sha256": sha(ROOT / SCRIPT), "start_new_session": True}:
            raise ValueError("Recovery launch identity differs")
        terminal = read(directory / "controller_terminal.json")
        if (terminal.get("status") != ("COMPLETED" if quick else "INTERRUPTED")
                or terminal.get("returncode") != (0 if quick else 130)
                or terminal.get("token") != plan["token"] or terminal.get("algorithm_executed") is not False
                or isinstance(terminal.get("fixture_wall_seconds"), bool)
                or not isinstance(terminal.get("fixture_wall_seconds"), (float, int))
                or not math.isfinite(terminal["fixture_wall_seconds"]) or terminal["fixture_wall_seconds"] < 0):
            raise ValueError("Recovery controller terminal scope/status differs")
        for record in records:
            path = directory / (record["role"] + ".json")
            if read(path) != record:
                raise ValueError("Recovery ownership record differs from its durable original")
            expected_argv = command if record["role"] == "controller" else [sys.executable, SCRIPT,
                "--internal-sleep-tree" if record["role"] == "child" else "--internal-sleep-grandchild",
                relative(directory), plan["token"]]
            if not role_argv_matches(record["argv"], expected_argv):
                raise ValueError("Recovery role/argv identity differs")
            required.append(path)
    signal_request = base / "interrupted_controller/signal_request.json"
    if read(signal_request) != {"signal": "SIGINT", "target_identity": roles["controller"], "only_fresh_fixture_pid_signalled": True}:
        raise ValueError("Recovery signal target/action differs")
    required.append(signal_request)
    expected_receipts = [ROOT / "work/reproduction/commands" / plan["command_key"] / f"attempt_{index:03d}/receipt.json"
                         for index in range(2)]
    if receipt["command_receipts"] != [relative(path) for path in expected_receipts]:
        raise ValueError("Recovery command path/attempt order differs")
    required.extend(expected_receipts)
    if any(relative(path) not in receipt["evidence_sha256"] for path in required):
        raise ValueError("Recovery evidence inventory omits ownership, plan or command receipts")
    for path, expected in receipt["evidence_sha256"].items():
        if sha(ROOT / path) != expected:
            raise ValueError("Recovery evidence changed: " + path)
    records = interrupted + resumed
    if any(identity_matches(record, allow_dead=True) for record in records):
        raise ValueError("Recovery fixture still owns live processes")
    old, new = [read(ROOT / path) for path in receipt["command_receipts"]]
    if (old["interrupted"] is not True or old["returncode"] == 0 or old.get("controller_error") is not None
            or new["interrupted"] is not False or new["returncode"] != 0 or new.get("controller_error") is not None):
        raise ValueError("Recovery command terminal sequence differs")
    return receipt


def controller_recovery(version=1):
    if type(version) is not int or version < 1:
        raise ValueError("Invalid recovery-only engineering version")
    base = ROOT / BASE / f"controller_recovery_v{version:03d}"
    receipt_path = base / "receipt.json"
    if receipt_path.exists():
        return verify_recovery(read(receipt_path))
    base.mkdir(parents=True, exist_ok=True)
    plan = base / "plan.json"
    if not plan.exists():
        save_new(plan, {"token": str(uuid.uuid4()), "source_sha256": sha(ROOT / SCRIPT),
            "command_key": f"smoke_controller_recovery_v{version:03d}", "algorithm_executed": False})
    specification = read(plan)
    if specification["source_sha256"] != sha(ROOT / SCRIPT):
        raise ValueError("Partial recovery fixture was created by different source; retain it and stop")
    key, token = specification["command_key"], specification["token"]
    attempts = ROOT / "work/reproduction/commands" / key
    interrupted = sorted(path for path in attempts.glob("attempt_*/receipt.json") if read(path).get("interrupted"))
    started = time.perf_counter()
    first = base / "interrupted_controller"
    try:
        if not interrupted:
            if first.exists():
                raise ValueError("Incomplete fixture handshake retained; inspect it before an explicit fresh fixture")
            process = start_controller(first, token, key)
            owned = wait_records(first, ("controller", "child", "grandchild"), process)
            controller = owned[0]
            if controller["pid"] != process.pid or not identity_matches(controller):
                raise ValueError("Fixture controller handshake differs from its launched PID")
            if owned[1]["pgid"] == owned[2]["pgid"]:
                raise ValueError("Fixture grandchild must have an independent session")
            save_new(first / "signal_request.json", {"signal": "SIGINT", "target_identity": controller,
                "only_fresh_fixture_pid_signalled": True})
            process.send_signal(signal.SIGINT)
            if process.wait(timeout=10) != 130:
                raise RuntimeError("Fixture controller did not retain its interrupted terminal")
            interrupted = sorted(path for path in attempts.glob("attempt_*/receipt.json") if read(path).get("interrupted"))
        owned = [read(first / (role + ".json")) for role in ("controller", "child", "grandchild")]
        if len(interrupted) != 1 or any(identity_matches(record, allow_dead=True) for record in owned):
            raise ValueError("Interrupted fixture descendants remain live or terminal census differs")
        old_sha = sha(interrupted[0])
        resumed = base / "resumed_controller"
        if not resumed.exists():
            process = start_controller(resumed, token, key, quick=True)
            if process.wait(timeout=10) != 0:
                raise RuntimeError("Fresh controller failed to resume the same command key")
        if read(resumed / "controller_terminal.json")["status"] != "COMPLETED":
            raise ValueError("Resumed controller lacks a durable completed terminal")
        resume_owned = [read(resumed / "controller.json")]
        receipts = sorted(attempts.glob("attempt_*/receipt.json"))
        if len(receipts) != 2 or sha(interrupted[0]) != old_sha:
            raise ValueError("Resume overwrote an old terminal or added unexpected attempts")
        evidence = {relative(path): sha(path) for path in sorted(base.rglob("*")) if path.is_file()}
        evidence.update({relative(path): sha(path) for path in sorted(attempts.rglob("*")) if path.is_file()})
        result = {"status": "PASS_CONTROLLER_RECOVERY", "recovery_version": version, "algorithm_executed": False,
            "sleep_tree_had_separate_grandchild_session": True,
            "interrupted_owned_processes": owned, "resumed_owned_processes": resume_owned,
            "command_receipts": [relative(path) for path in receipts],
            "evidence_sha256": evidence, "fixture_wall_seconds": time.perf_counter() - started,
            "scope": "run_command interruption, descendant cleanup, immutable receipt and same-key new attempt; no algorithm convergence claim"}
        verify_recovery(result)
        save_new(receipt_path, result)
        return result
    except BaseException:
        cleanup_owned(base)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--internal-controller", nargs=3, metavar=("DIRECTORY", "TOKEN", "KEY"))
    parser.add_argument("--internal-sleep-tree", nargs=2, metavar=("DIRECTORY", "TOKEN"))
    parser.add_argument("--internal-sleep-grandchild", nargs=2, metavar=("DIRECTORY", "TOKEN"))
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--recovery-only", action="store_true")
    parser.add_argument("--recovery-version", type=int, default=1)
    args = parser.parse_args()
    fresh = fresh_environment()
    if args.internal_controller:
        directory, token, key = args.internal_controller
        return internal_controller(contained(ROOT / directory), token, key, args.quick)
    if args.internal_sleep_tree or args.internal_sleep_grandchild:
        directory, token = args.internal_sleep_tree or args.internal_sleep_grandchild
        internal_sleep(contained(ROOT / directory), token, bool(args.internal_sleep_grandchild))
        return 0
    if args.quick:
        parser.error("--quick is restricted to the internal controller fixture role")
    if args.recovery_version < 1:
        parser.error("--recovery-version must be positive")
    if not args.recovery_only and args.recovery_version != 1:
        parser.error("An engineering recovery version is restricted to --recovery-only")
    if args.recovery_only:
        source_start = {SCRIPT: sha(ROOT / SCRIPT), DRIVER: sha(ROOT / DRIVER)}
        recovery = controller_recovery(args.recovery_version)
        for path, expected in source_start.items():
            if sha(ROOT / path) != expected:
                raise ValueError("Recovery source changed during execution")
        output = ROOT / BASE / f"recovery_only_v{args.recovery_version:03d}.json"
        save_new(output, {"status": "PASS_RECOVERY_ONLY", "fresh_environment": fresh,
            "source_sha256": source_start, "controller_recovery": recovery,
            "setup_repeated": False, "eight_methods_repeated": False,
            "formal_measurements": False, "original_frozen_cohort_pass_claim": False})
        print(json.dumps({"status": "PASS_RECOVERY_ONLY", "receipt": relative(output),
            "setup_repeated": False, "eight_methods_repeated": False}), flush=True)
        return 0
    sys.path.insert(0, str(ROOT))
    from experiments.reproduction.driver import run_command
    source_start = {SCRIPT: sha(ROOT / SCRIPT), DRIVER: sha(ROOT / DRIVER)}
    started = time.perf_counter()
    run_command(ROOT, "smoke_eight_methods", [sys.executable, "experiments/run_m5_archived.py",
        "--run", RUN, "--toy", "--tl-backend", "numba", "--execute"])
    methods = verify_eight_methods()
    recovery = controller_recovery()
    for path, expected in source_start.items():
        if sha(ROOT / path) != expected:
            raise ValueError("Smoke source changed during execution")
    output = ROOT / BASE / "receipt.json"
    receipt = {"status": "PASS_FRESH_SETUP_SMOKE", "cohort_origin": "FRESH_REPRODUCTION",
        "fresh_environment": fresh, "source_sha256": source_start,
        "eight_method_smoke": methods, "controller_recovery": recovery,
        "original_project_modified": False, "formal_measurements": False,
        "timing_scope": "nonformal engineering stage wall including toy work, storage verification and controller recovery",
        "stage_wall_seconds": time.perf_counter() - started}
    if output.exists():
        previous = read(output)
        if (previous["fresh_environment"] != fresh or previous["source_sha256"] != source_start
                or previous["eight_method_smoke"] != methods or previous["controller_recovery"] != recovery):
            raise ValueError("Existing smoke receipt differs; original proof retained")
    else:
        save_new(output, receipt)
    print(json.dumps({"status": "PASS_FRESH_SETUP_SMOKE", "receipt": relative(output),
        "formal_measurements": False, "all_eight_methods_completed": True,
        "controller_recovery_verified": True}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
