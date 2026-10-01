"""Read-only disk inventory, or an explicitly bound one-shot storage stop guard.

No measurement module is imported. Only --watch can write or send a signal.
The guard acts on one serial_workflow controller, never on its child processes.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import signal
import tempfile
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
STATE_DIRECTORY = "results/serial_workflow_v003"
WORKFLOW_SOURCE = "experiments/serial_workflow.py"
WORKFLOW_SHA256 = "181e638860b590e3044ec87f2f7a72c396147ebf71182510a982db84ff748664"
THRESHOLD_BYTES = 5 * (1024 ** 3) // 2
RESERVE_BYTES = 256 * 1024
REVIEW_DIRECTORY = "reviews/storage_guard"


class OwnershipError(ValueError):
    """The fixed controller identity is absent, terminal, or no longer owned."""


def utc():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(path):
    # These are the two small controller source/launch files, never raw results.
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise OwnershipError("Expected a JSON object: " + str(path))
    return value


def observed_process(pid):
    process = psutil.Process(pid)
    with process.oneshot():
        return {"pid": process.pid, "create_time": process.create_time(),
                "cwd": process.cwd(), "argv": process.cmdline(), "status": process.status()}


def project_python_paths(root):
    launcher = root / ".venv/bin/python"
    if not launcher.is_file():
        raise OwnershipError("Project Python launcher is absent")
    resolved = launcher.resolve()
    allowed = {resolved}
    # macOS Framework Python execs this same framework's app binary. Accept only
    # that exact sibling path, never an arbitrary system Python or PATH lookup.
    version = resolved.parent.parent
    if resolved.parent.name == "bin" and version.parent.name == "Versions" and version.parent.parent.name == "Python.framework":
        app = version / "Resources/Python.app/Contents/MacOS/Python"
        if app.is_file():
            allowed.add(app.resolve())
    return allowed


def checked_identity(identity, root, pid, created=None):
    if type(pid) is not int or pid <= 0 or identity.get("pid") != pid:
        raise OwnershipError("Controller PID differs or is invalid")
    value = identity.get("create_time")
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        raise OwnershipError("Controller creation time is invalid")
    if created is not None and value != created:
        raise OwnershipError("Controller PID was reused or creation time differs")
    if identity.get("cwd") != str(root.resolve()):
        raise OwnershipError("Controller cwd is not the exact project root")
    argv = identity.get("argv")
    if not isinstance(argv, list) or len(argv) < 2 or any(not isinstance(s, str) for s in argv):
        raise OwnershipError("Controller argv is invalid")
    if Path(argv[0]).resolve() not in project_python_paths(root):
        raise OwnershipError("Controller Python executable differs from project runtime")
    if identity.get("status") in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
        raise OwnershipError("Controller is no longer live")
    return {key: identity[key] for key in ("pid", "create_time", "cwd", "argv")}


def checked_launch(launch):
    argv = launch.get("actual_argv")
    resume = [WORKFLOW_SOURCE, "--state", STATE_DIRECTORY, "--execute"]
    valid = argv == resume
    if isinstance(argv, list) and len(argv) == 6:
        valid = (argv[0:2] == [WORKFLOW_SOURCE, "--wait-for-pid"]
                 and isinstance(argv[2], str) and argv[2].isdigit() and int(argv[2]) > 0
                 and argv[3:] == ["--state", STATE_DIRECTORY, "--execute"])
    if not valid or launch.get("serial_measurement") is not True:
        raise OwnershipError("Launch does not describe the exact owned serial workflow")
    return resume


def bind_controller(root, expected_pid=None, expected_created=None, *, observe=observed_process,
                    loader=read_json, hasher=digest, expected_source_sha=WORKFLOW_SHA256):
    """Bind once; the private injectable functions are for tiny object fixtures."""
    state_path = root / STATE_DIRECTORY / "STATE.json"
    launch_path = root / STATE_DIRECTORY / "LAUNCH.json"
    state, launch = loader(state_path), loader(launch_path)
    pid = state.get("controller_pid")
    if state.get("status") != "ACTIVE" or type(pid) is not int or pid <= 0:
        raise OwnershipError("No ACTIVE owned controller in the fixed STATE.json")
    if expected_pid is not None and pid != expected_pid:
        raise OwnershipError("STATE.json controller differs from explicitly supplied PID")
    resume_argv = checked_launch(launch)
    source_sha = hasher(root / WORKFLOW_SOURCE)
    if source_sha != expected_source_sha or launch.get("workflow_source_sha256") != expected_source_sha:
        raise OwnershipError("Frozen serial_workflow source SHA differs")
    observed = observe(pid)
    identity = checked_identity(observed, root, pid, expected_created)
    if identity["argv"][1:] not in (launch["actual_argv"], resume_argv):
        raise OwnershipError("Controller argv differs from exact launch/resume argv")
    again = loader(state_path)
    if again.get("status") != "ACTIVE" or type(again.get("controller_pid")) is not int or again.get("controller_pid") != pid:
        raise OwnershipError("Controller changed while binding")
    return {"schema_version": 1, "controller": identity,
            "process_status_at_binding": observed.get("status"),
            "state_path": STATE_DIRECTORY + "/STATE.json", "launch_path": STATE_DIRECTORY + "/LAUNCH.json",
            "launch_sha256": hasher(launch_path), "workflow_source_sha256": source_sha,
            "guard_source_sha256": digest(__file__), "threshold_bytes": THRESHOLD_BYTES,
            "meaning": "Storage emergency only; no algorithm, input, budget or quality-failure change"}


def recheck_controller(root, binding, *, observe=observed_process, loader=read_json, hasher=digest):
    controller = binding["controller"]
    state = loader(root / binding["state_path"])
    if state.get("status") != "ACTIVE" or type(state.get("controller_pid")) is not int or state.get("controller_pid") != controller["pid"]:
        raise OwnershipError("Fixed controller is no longer the ACTIVE state owner")
    if hasher(root / binding["launch_path"]) != binding["launch_sha256"]:
        raise OwnershipError("LAUNCH.json changed after binding")
    if hasher(root / WORKFLOW_SOURCE) != binding["workflow_source_sha256"]:
        raise OwnershipError("Workflow source changed after binding")
    observed = observe(controller["pid"])
    actual = checked_identity(observed, root, controller["pid"], controller["create_time"])
    if actual != controller:
        raise OwnershipError("Fixed controller cwd or full argv changed after binding")
    return {**state, "observed_controller_status": observed.get("status")}


def atomic_text(path, value):
    """Publish only after data fsync, then fsync the containing directory."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def controller_directory(root, binding):
    # PID plus creation time is the process identity. argv/cwd remain strict
    # ownership constraints but cannot create another signal slot for that PID.
    key = hashlib.sha256(canonical({name: binding["controller"][name]
                                   for name in ("pid", "create_time")})).hexdigest()
    return root / REVIEW_DIRECTORY / "controllers" / key


def resume_text(binding, directory):
    command = ".venv/bin/python experiments/resume_workflow.py --state " + STATE_DIRECTORY + " --execute"
    return ("# Storage emergency recovery\n\n"
            "The guard requests interruption for low disk space, not an algorithm/quality failure.\n"
            "It does not restart work or kill child processes. Preserve all partial raw and controller state.\n"
            "After freeing space, inspect the controller STATE.json and verify all owned processes have exited.\n"
            "The existing recovery launcher independently refuses live work and owns the project lease.\n\n"
            "Run from the project root only when ready to resume:\n\n"
            "```sh\n" + command + "\n```\n\n"
            "Bound controller: " + json.dumps(binding["controller"], sort_keys=True) + "\n"
            "Trigger evidence: " + str(directory / "TRIGGER.json") + "\n"
            "A recorded signal attempt never claims the controller or measurements finished.\n")


def signal_bound_controller(root, binding):
    # psutil send_signal checks PID reuse on its Process object; never use killpg,
    # os.kill, process enumeration or descendant signalling in this guard.
    state = recheck_controller(root, binding)
    if state["observed_controller_status"] == psutil.STATUS_STOPPED:
        raise OwnershipError("Controller is deliberately paused; no signal is allowed")
    identity = binding["controller"]
    process = psutil.Process(identity["pid"])
    with process.oneshot():
        actual = {"pid": process.pid, "create_time": process.create_time(),
                  "cwd": process.cwd(), "argv": process.cmdline(), "status": process.status()}
    if checked_identity(actual, root, identity["pid"], identity["create_time"]) != identity or not process.is_running() or actual["status"] == psutil.STATUS_STOPPED:
        raise OwnershipError("Controller changed immediately before signal")
    process.send_signal(signal.SIGINT)


def trigger_stop(root, binding, directory, disk, *, recheck=recheck_controller,
                 sender=signal_bound_controller, writer=atomic_json, text_writer=atomic_text,
                 exists=lambda path: path.exists(), release=lambda path: path.unlink(missing_ok=True)):
    """Persist intent/recovery before exactly one send; every side effect is injectable."""
    marker = directory / "SIGNAL_ATTEMPT.json"
    trigger = directory / "TRIGGER.json"
    if exists(trigger) or exists(marker):
        return {"status": "ALREADY_TRIGGERED", "signal_attempts_this_invocation": 0}
    if disk["free"] >= THRESHOLD_BYTES:
        return {"status": "ABOVE_THRESHOLD", "signal_attempts_this_invocation": 0}
    state = recheck(root, binding)
    if state.get("observed_controller_status") == psutil.STATUS_STOPPED:
        raise OwnershipError("Controller is deliberately paused; do not interrupt it")
    release(directory / ".receipt-reserve")
    receipt = {"schema_version": 1, "status": "STORAGE_EMERGENCY_INTENT_PERSISTED", "created_utc": utc(),
               "binding": binding, "disk": disk, "threshold_bytes": THRESHOLD_BYTES,
               "planned_signal": "SIGINT", "signal_attempts": 0, "algorithm_failure_claim": False,
               "automatic_restart": False, "other_jobs_affected_by_guard": False}
    writer(trigger, receipt)
    text_writer(directory / "RESUME.md", resume_text(binding, directory))
    # An identity change or failed evidence write must never result in a signal.
    try:
        state = recheck(root, binding)
        if state.get("observed_controller_status") == psutil.STATUS_STOPPED:
            raise OwnershipError("Controller paused after evidence; no signal")
    except (OwnershipError, psutil.Error, OSError) as error:
        outcome = {"status": "OWNERSHIP_CHANGED_NO_SIGNAL", "signal_attempts": 0, "error": repr(error), "at_utc": utc()}
        writer(directory / "OUTCOME.json", outcome)
        return outcome
    # Persistent marker provides at-most-once across guard invocations. A crash
    # after this write is intentionally ambiguous; do not resend automatically.
    writer(marker, {"status": "ONE_SIGINT_ATTEMPT_COMMITTED", "at_utc": utc(),
                    "controller": binding["controller"], "state_before_signal": state,
                    "completion_claim": False})
    try:
        sender(root, binding)
        outcome = {"status": "SIGINT_SENT", "signal_attempts": 1, "controller_stopped_claim": False, "at_utc": utc()}
    except (OwnershipError, psutil.Error, OSError) as error:
        outcome = {"status": "SIGNAL_NOT_CONFIRMED", "signal_attempts": 1, "error": repr(error), "at_utc": utc()}
    writer(directory / "OUTCOME.json", outcome)
    return outcome


def disk_snapshot(root):
    usage = shutil.disk_usage(root)
    return {"path": str(root), "total": usage.total, "used": usage.used, "free": usage.free,
            "free_GiB": usage.free / (1024 ** 3)}


def inventory(root=ROOT, expected_pid=None, expected_created=None):
    result = {"read_only": True, "disk": disk_snapshot(root), "threshold_bytes": THRESHOLD_BYTES,
              "state_path": STATE_DIRECTORY + "/STATE.json", "signal_sent": False}
    try:
        binding = bind_controller(root, expected_pid, expected_created)
        directory = controller_directory(root, binding)
        result.update(status="BOUND_ACTIVE_CONTROLLER", binding=binding,
                      controller_process_status=binding["process_status_at_binding"],
                      previous_trigger=bool((directory / "TRIGGER.json").exists()))
        command = [str(root / ".venv/bin/python"), "experiments/storage_guard.py", "--watch",
                   "--expected-pid", str(binding["controller"]["pid"]),
                   "--expected-create-time", repr(binding["controller"]["create_time"])]
        result["watch_command"] = shlex.join(command)
    except (OwnershipError, psutil.Error, OSError, ValueError, KeyError) as error:
        result.update(status="NO_VERIFIED_ACTIVE_CONTROLLER", error=repr(error))
    return result


@contextmanager
def watcher_lease(root):
    review = root / REVIEW_DIRECTORY
    review.mkdir(parents=True, exist_ok=True)
    with (review / "watch.lock").open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise OwnershipError("Another storage guard holds this project's watch lease") from error
        yield


def watch(root, pid, created, interval=1.):
    with watcher_lease(root):
        binding = bind_controller(root, pid, created)
        if binding["process_status_at_binding"] == psutil.STATUS_STOPPED:
            raise OwnershipError("Controller is paused; watch only after its owner releases the barrier")
        directory = controller_directory(root, binding)
        directory.mkdir(parents=True, exist_ok=True)
        if (directory / "TRIGGER.json").exists() or (directory / "SIGNAL_ATTEMPT.json").exists():
            return {"status": "ALREADY_TRIGGERED", "evidence_directory": str(directory), "signal_attempts_this_invocation": 0}
        atomic_json(directory / "BINDING.json", binding)
        reserve = directory / ".receipt-reserve"
        if not reserve.exists():
            with reserve.open("xb") as stream:
                stream.write(b"\0" * RESERVE_BYTES)
                stream.flush()
                os.fsync(stream.fileno())
        try:
            while True:
                try:
                    state = recheck_controller(root, binding)
                    if state["observed_controller_status"] == psutil.STATUS_STOPPED:
                        raise OwnershipError("Controller deliberately paused; no signal or restart")
                except (OwnershipError, psutil.Error, OSError) as error:
                    outcome = {"status": "OWNERSHIP_ENDED_NO_SIGNAL", "error": repr(error), "signal_attempts": 0, "at_utc": utc()}
                    reserve.unlink(missing_ok=True)
                    atomic_json(directory / "WATCH_END.json", outcome)
                    return outcome
                disk = disk_snapshot(root)
                if disk["free"] < THRESHOLD_BYTES:
                    result = trigger_stop(root, binding, directory, disk)
                    return {**result, "evidence_directory": str(directory), "resume_file": str(directory / "RESUME.md")}
                time.sleep(interval)
        finally:
            reserve.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="Explicitly monitor the one supplied controller identity")
    parser.add_argument("--expected-pid", type=int)
    parser.add_argument("--expected-create-time", type=float)
    parser.add_argument("--interval-seconds", type=float, default=1.)
    args = parser.parse_args()
    if (args.expected_pid is None) != (args.expected_create_time is None):
        parser.error("PID and creation time must be supplied together")
    if args.watch and args.expected_pid is None:
        parser.error("--watch requires explicit --expected-pid and --expected-create-time")
    if args.expected_pid is not None and (args.expected_pid <= 0 or not math.isfinite(args.expected_create_time) or args.expected_create_time <= 0):
        parser.error("Expected identity values must be positive and finite")
    if not math.isfinite(args.interval_seconds) or not .1 <= args.interval_seconds <= 30:
        parser.error("Poll interval must be between .1 and 30 seconds")
    try:
        result = watch(ROOT, args.expected_pid, args.expected_create_time, args.interval_seconds) if args.watch else inventory(ROOT, args.expected_pid, args.expected_create_time)
    except (OwnershipError, psutil.Error, OSError, ValueError) as error:
        result = {"status": "GUARD_FAILED_CLOSED", "error": repr(error), "automatic_restart": False,
                  "meaning": "No retry signal; inspect persisted trigger/attempt evidence before recovery"}
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["status"] in ("BOUND_ACTIVE_CONTROLLER", "SIGINT_SENT", "ALREADY_TRIGGERED", "OWNERSHIP_ENDED_NO_SIGNAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
