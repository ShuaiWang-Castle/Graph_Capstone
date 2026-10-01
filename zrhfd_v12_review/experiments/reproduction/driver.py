"""Pinned, isolated CPU reproduction. Default action is read-only verification."""
from __future__ import annotations
import argparse
import ast
import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import signal
import shutil
import subprocess
import sys
import time
import tarfile
import traceback
import urllib.request
import zipfile

SOURCE = Path(__file__).resolve().parents[2]
LOCK = SOURCE / "experiments/reproduction/lock.json"
ARCHIVE = SOURCE / "experiments/reproduction/input_hash_archive.json"
MARKER = ".REPRODUCTION_WORKSPACE.json"

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def read(path):
    return json.loads(Path(path).read_text())

def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()

def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if path.exists():
        if path.read_text() != content:
            raise RuntimeError("Existing immutable record differs: " + str(path))
        return
    with path.open("x") as stream:
        stream.write(content)

def check(root, deep=False):
    lock = read(root / "experiments/reproduction/lock.json")
    missing = []
    for path, expected in lock["receipt_sha256"].items():
        file = root / path
        if not file.exists():
            missing.append(path)
        elif sha(file) != expected:
            raise RuntimeError("Pinned receipt/lock differs: " + path)
    verification = runtime_verification(root, lock)
    source_differences = [path for path, expected in verification.items()
                          if not (root / path).exists() or sha(root / path) != expected]
    if source_differences:
        raise RuntimeError("Pinned first-party sources differ: " + ", ".join(source_differences[:5]))
    reference_differences = [path for path, expected in lock.get("reference_manifest_sha256", {}).items()
                             if not (root / path).exists() or sha(root / path) != expected]
    if reference_differences:
        raise RuntimeError("Portable frozen reference manifest differs: " + reference_differences[0])
    for path, expected in lock.get("reproduction_entry_sha256", {}).items():
        if sha(root / path) != expected:
            raise RuntimeError("Reproduction entry differs from its lock: " + path)
    for path, expected in lock.get("delivery_document_sha256", {}).items():
        if sha(root / path) != expected:
            raise RuntimeError("Pinned reproduction guide differs: " + path)
    for path, expected in lock.get("stage_entry_sha256", {}).items():
        if sha(root / path) != expected:
            raise RuntimeError("Stage reproduction entry differs from its lock: " + path)
    fixed_input_checked, fixed_input_unavailable = 0, []
    for path, expected in lock.get("m5_fixed_input_sha256", {}).items():
        if not (root / path).exists():
            fixed_input_unavailable.append(path)
        else:
            fixed_input_checked += 1
            if sha(root / path) != expected:
                raise RuntimeError("Frozen M5 input bytes differ: " + path)
    original_unavailable, historical_unavailable, historical_checked = [], [], 0
    fresh_manifests = []
    for path, expected in lock.get("original_manifest_sha256", {}).items():
        if (root / MARKER).exists():
            if (root / path).exists():
                fresh_manifests.append(path)
            continue
        if not (root / path).exists():
            original_unavailable.append(path)
        elif sha(root / path) != expected:
            raise RuntimeError("Original frozen manifest differs: " + path)
    for path, expected in lock.get("historical_archive_sha256", {}).items():
        if not (root / path).exists():
            historical_unavailable.append(path)
        else:
            historical_checked += 1
            if sha(root / path) != expected:
                raise RuntimeError("Historical archived source differs: " + path)
    if not (root / MARKER).exists() and (original_unavailable or historical_unavailable):
        raise RuntimeError("Original project historical/reference files unavailable")
    versions = {}
    for requirement in (root / "provenance/dependency_versions.txt").read_text().splitlines():
        if not requirement.strip():
            continue
        name, expected = requirement.split("==", 1)
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = "NOT_INSTALLED_IN_THIS_INTERPRETER"
        versions[name] = {"expected": expected, "actual": actual}
        if actual != expected and actual != "NOT_INSTALLED_IN_THIS_INTERPRETER":
            raise RuntimeError("Dependency version differs: " + name)
    archive = read(root / "experiments/reproduction/input_hash_archive.json")
    mismatches, checked, unavailable = [], 0, 0
    for path, expected in archive["files_sha256"].items():
        file = root / path
        if not file.exists():
            unavailable += 1
        elif deep:
            checked += 1
            if sha(file) != expected:
                mismatches.append(path)
    report = {"action": "READ_ONLY_CHECK_EXISTING", "missing_lock_receipts": missing,
        "source_state": lock["source_state"], "stage_freeze_status": lock["stage_freeze_status"],
        "runtime_source_files_verified": len(verification),
        "portable_reference_manifests_verified": len(lock.get("reference_manifest_sha256", {})),
        "original_manifests_unavailable_in_fresh_workspace": original_unavailable,
        "fresh_execution_manifests_at_reference_paths": fresh_manifests,
        "fresh_execution_manifest_identity_policy": "Fresh runtime-bearing manifests are independent; portable reference copies retain original SHA-256",
        "historical_archived_files_verified": historical_checked,
        "historical_archived_files_unavailable_in_fresh_workspace": historical_unavailable,
        "historical_old_worker_bytes_required_as_current_runtime": False,
        "stage_entry_files_verified": len(lock.get("stage_entry_sha256", {})),
        "m5_fixed_inputs_verified": fixed_input_checked,
        "m5_fixed_inputs_unavailable": fixed_input_unavailable,
        "raw_archive_audit": audit_raw_archives(root, deep),
        "transparent_storage_audit": audit_transparent_storage(root, deep),
        "deep_input_hashes_checked": checked, "input_hash_mismatches": mismatches,
        "archived_input_files_unavailable": unavailable, "dependencies": versions,
        "platform": platform.platform(), "python": sys.version,
        "formal_results_modified": False}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if missing or mismatches:
        raise RuntimeError("Read-only verification failed")

def audit_raw_archives(root, deep):
    """Read indexes/ZIP inventory by default; stream original byte hashes if deep."""
    archives, members, bytes_expanded, bytes_compressed, offline_seconds = 0, 0, 0, 0, 0.0
    for index in sorted((root / "results/m5").rglob("ARCHIVE.json")):
        metadata = read(index)
        if not metadata["all_original_bytes_preserved"] or metadata["included_in_measurement_runtime"]:
            raise RuntimeError("Raw archive provenance policy differs: " + str(index))
        if "terminal_receipt_sha256" in metadata and sha(index.parent / "receipt.json") != metadata["terminal_receipt_sha256"]:
            raise RuntimeError("Archive terminal receipt identity differs: " + str(index))
        archive_path = index.parent / metadata["archive"]
        with zipfile.ZipFile(archive_path) as archive:
            if set(archive.namelist()) != set(metadata["files"]):
                raise RuntimeError("Raw archive inventory differs: " + str(index))
            for name, record in metadata["files"].items():
                if archive.getinfo(name).file_size != record["bytes"]:
                    raise RuntimeError("Raw archive uncompressed size differs: " + name)
                if deep:
                    digest = hashlib.sha256()
                    with archive.open(name) as stream:
                        for block in iter(lambda: stream.read(1048576), b""):
                            digest.update(block)
                    if digest.hexdigest() != record["sha256"]:
                        raise RuntimeError("Raw archive member SHA-256 differs: " + name)
        if deep and sha(archive_path) != metadata["archive_sha256"]:
            raise RuntimeError("Raw archive ZIP SHA-256 differs: " + str(index))
        archives += 1
        members += len(metadata["files"])
        bytes_expanded += metadata["expanded_bytes"]
        bytes_compressed += metadata["archive_bytes"]
        offline_seconds += metadata["offline_archive_and_verification_seconds"]
    return {"archives": archives, "original_members": members,
            "original_bytes": bytes_expanded, "stored_zip_bytes": bytes_compressed,
            "offline_archive_and_verification_seconds": offline_seconds,
            "included_in_algorithm_measurement": False,
            "inventory_and_sizes_checked": True, "all_member_byte_hashes_checked": deep,
            "original_path_reader": "experiments.archival.read_bytes/read_json"}

def audit_transparent_storage(root, deep):
    """Read terminal-only APFS receipts; never invoke filesystem compression."""
    receipts = files = logical = allocated_before = allocated_after = 0
    seconds = 0.0
    for index in sorted((root / "results/m6_prepared").rglob("TRANSPARENT_STORAGE.json")):
        metadata = read(index)
        if (not metadata["all_original_paths_and_bytes_unchanged"] or not metadata["filesystem_compression_only"]
                or metadata["included_in_measurement_runtime"]):
            raise RuntimeError("Transparent storage policy differs: " + str(index))
        terminal = read(index.parent / "terminal.json")
        if terminal["status"] != metadata["terminal_status"] or terminal["status"] in ("STARTED", "running"):
            raise RuntimeError("Transparent storage lacks matching durable terminal: " + str(index))
        names = [record["path"] for record in metadata["files"]]
        if len(names) != len(set(names)):
            raise RuntimeError("Duplicate transparent storage original paths")
        for record in metadata["files"]:
            relative = Path(record["path"])
            path = index.parent / relative
            if relative.is_absolute() or ".." in relative.parts or not path.resolve().is_relative_to(index.parent.resolve()):
                raise RuntimeError("Transparent storage path escapes original attempt")
            if path.stat().st_size != record["logical_bytes"] or (deep and sha(path) != record["sha256"]):
                raise RuntimeError("Transparent storage original bytes differ: " + str(path))
            files += 1
            logical += record["logical_bytes"]
        receipts += 1
        allocated_before += metadata["allocated_before_bytes"]
        allocated_after += metadata["allocated_after_bytes"]
        seconds += metadata["offline_storage_seconds"]
    return {"terminal_receipts": receipts, "original_paths": files, "logical_bytes": logical,
            "receipt_allocated_before_bytes": allocated_before, "receipt_allocated_after_bytes": allocated_after,
            "offline_storage_seconds": seconds, "included_in_algorithm_measurement": False,
            "terminal_and_logical_sizes_checked": True, "all_original_byte_hashes_checked": deep,
            "filesystem_compression_invoked": False,
            "allocation_scope": "Historical receipt host; filesystem allocation may differ after copying"}

def runtime_verification(root, lock):
    """Accept recorded fresh build/catalog identities only in an isolated clone."""
    verification = dict(lock["verification_source_sha256"])
    if not (root / MARKER).exists():
        return verification
    build_receipt = root / "work/reproduction/build_identity.json"
    if build_receipt.exists():
        verification["work/bin/mincut128"] = read(build_receipt)["mincut_binary_sha256"]
    rebinding_path = root / "work/reproduction/m6_catalog_rebinding.json"
    if rebinding_path.exists():
        receipt = read(rebinding_path)
        path = receipt["configuration_path"]
        if verification[path] != receipt["original_configuration_sha256"]:
            raise RuntimeError("Fresh catalog receipt original Config pin differs")
        if sha(root / path) == receipt["original_configuration_sha256"]:
            # A durable plan may precede the atomic Config replacement. Leave
            # this original pin in place so the next stage safely resumes it.
            return verification
        current = read(root / path)
        original = read(root / receipt["original_configuration_snapshot"])
        reference = root / "experiments/reproduction/frozen_manifests" / lock["source_scopes"]["m6"]["manifest"]
        if original != read(reference)["configuration"]:
            raise RuntimeError("Fresh catalog original Config differs from frozen reference")
        if {k: v for k, v in current.items() if k != "catalog_sha256"} != {k: v for k, v in original.items() if k != "catalog_sha256"}:
            raise RuntimeError("Fresh catalog rebinding changed a non-catalog Config field")
        if current["catalog_sha256"] != receipt["regenerated_catalog_sha256"]:
            raise RuntimeError("Fresh catalog rebinding receipt differs")
        verification[path] = receipt["regenerated_configuration_sha256"]
    return verification

def clone_workspace(destination):
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise RuntimeError("--fresh destination must not exist; use --workspace to resume")
    if destination.is_relative_to(SOURCE) or SOURCE.is_relative_to(destination):
        raise RuntimeError("Fresh workspace must be separate from the original project")
    destination.mkdir(parents=True)
    # Code/config/receipts only. Author code with unverified redistribution
    # permission, runtimes, raw measurements and large graphs are not bundled.
    directories = ("zrhfd", "tests", "experiments", "provenance", "inputs", "reviews")
    for directory in directories:
        base = SOURCE / directory
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(SOURCE)
            if directory == "reviews" and path.suffix not in (".py", ".md"):
                continue
            if directory in ("provenance", "experiments") or directory == "reviews":
                if path.suffix not in (".py", ".cpp", ".jl", ".json", ".yaml", ".md", ".txt", ".toml") and "LICENSE" not in path.name:
                    continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    for path in ("REPRODUCE.sh", "README.md", "THIRD_PARTY_NOTICES.md", "EXPERIMENT_PROTOCOL_ZH.md",
                 "data/dev/lfr_reference_queries.json", "data/external/m5_queries.json",
                 "external/runtime/hfd-environment/Project.toml", "external/runtime/hfd-environment/Manifest.toml"):
        file = SOURCE / path
        if file.exists():
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
    for file in (SOURCE / "data/external").glob("*.py"):
        target = destination / file.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
    # LFR source is redistributable under its retained MIT license. Compile in
    # the fresh workspace; do not copy the original architecture-specific binary.
    generator = SOURCE / "external/generators/lfr_native"
    for file in generator.rglob("*"):
        if file.is_file() and file.name != "benchmark":
            target = destination / file.relative_to(SOURCE)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
    # Historical first-party snapshots are small audit records, not runnable
    # current workers or original measurements. Preserve their recorded bytes.
    for relative, expected in read(LOCK).get("historical_archive_sha256", {}).items():
        source = SOURCE / relative
        if sha(source) != expected:
            raise RuntimeError("Historical archive changed before clone: " + relative)
        target = destination / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    save_new(destination / MARKER, {"created_at_utc": utc(), "origin": str(SOURCE),
        "lock_sha256": sha(LOCK), "input_hash_archive_sha256": sha(ARCHIVE),
        "mode": "FRESH_CPU_REPRODUCTION", "large_graphs_included": False,
        "author_HFD_pnorm_source_included": False, "original_raw_results_included": False})
    # Small immutable reference metadata is audit-only. Fresh generators keep
    # their own catalogs/freezes; explicit binding validates identity exceptions.
    input_archive = read(ARCHIVE)["files_sha256"]
    m5_reference = read(SOURCE / "experiments/reproduction/frozen_manifests/results/m5/official_v12_001/manifest.json")
    dev_reference = read(SOURCE / "experiments/reproduction/frozen_manifests/results/m4/dev_main_v12_002/manifest.json")
    references = {"data/dev/catalog_v12.json": dev_reference["catalog_sha256"],
                  "data/test/calibrated_lfr/catalog.json": input_archive["data/test/calibrated_lfr/catalog.json"],
                  "data/test/calibrated_lfr/GENERATION_FREEZE.json": input_archive["data/test/calibrated_lfr/GENERATION_FREEZE.json"],
                  "provenance/environment.json": m5_reference["frozen"]["source_pins"]["provenance/environment.json"]}
    for name, expected in references.items():
        if sha(SOURCE / name) != expected:
            raise RuntimeError("Immutable reference metadata changed: " + name)
        target = destination / "experiments/reproduction/reference_sources" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / name, target)
    return destination

def isolated(path):
    path = path.expanduser().resolve()
    if path == SOURCE or not (path / MARKER).exists():
        raise RuntimeError("Setup/stages require --fresh or a marked --workspace; original project is protected")
    marker = read(path / MARKER)
    if marker["lock_sha256"] != sha(path / "experiments/reproduction/lock.json"):
        raise RuntimeError("Marked workspace reproduction lock changed")
    frozen_sources(path)
    return path

def frozen_sources(root):
    lock = read(root / "experiments/reproduction/lock.json")
    # Fresh builds get their own binary identity and manifests. Check frozen
    # source semantics before setup, without imposing the original host binary.
    mismatches = [path for path, expected in runtime_verification(root, lock).items()
                  if not path.startswith("external/") and Path(path).suffix in (".py", ".cpp", ".jl", ".yaml", ".json", ".txt")
                  and (not (root / path).exists() or sha(root / path) != expected)]
    mismatches.extend(path for path, expected in lock.get("stage_entry_sha256", {}).items()
                      if not (root / path).exists() or sha(root / path) != expected)
    mismatches.extend(path for path, expected in lock.get("reproduction_entry_sha256", {}).items()
                      if not (root / path).exists() or sha(root / path) != expected)
    if mismatches:
        raise RuntimeError("Fresh workspace source pin differs: " + ", ".join(mismatches[:5]))

def run_command(root, key, argv, resumable=True, partial_output=None, rerun_success=False):
    base = root / "work/reproduction/commands" / key
    attempts = sorted(base.glob("attempt_*"))
    if attempts and (attempts[-1] / "receipt.json").exists():
        old = read(attempts[-1] / "receipt.json")
        if old.get("status") == "FAILED_CLEANUP_NOT_VERIFIED":
            raise RuntimeError("Manual owned-process verification required before resume; see " + str(attempts[-1] / "RESUME.json"))
        if old["returncode"] == 0 and not rerun_success:
            return
    if attempts and not resumable and partial_output and (root / partial_output).exists():
        retained = root / "work/reproduction/abandoned_outputs" / f"{key}_{len(attempts):03d}"
        retained.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root / partial_output), str(retained))
    directory = base / f"attempt_{len(attempts):03d}"
    directory.mkdir(parents=True)
    env = dict(os.environ, NUMBA_CACHE_DIR=str(root / "work/reproduction/numba_cache"),
               JULIA_DEPOT_PATH=str(root / "external/runtime/julia-depot"),
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               NUMBA_NUM_THREADS="1", JULIA_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1",
               BLIS_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1", PIP_NO_CACHE_DIR="1")
    save_new(directory / "request.json", {"argv": argv, "cwd": str(root), "started_at_utc": utc(),
        "actual_entry_source_sha256": ({argv[1]: sha(root / argv[1])}
            if len(argv) > 1 and argv[1].endswith(".py") and (root / argv[1]).is_file() else {}),
        "environment_overrides": {k: env.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS", "JULIA_NUM_THREADS", "NUMBA_CACHE_DIR", "JULIA_DEPOT_PATH", "PIP_NO_CACHE_DIR")}})
    print("RUN", key, " ".join(argv), flush=True)
    interrupted, process, failure, failure_tb = False, None, None, None
    owned_root = None
    phase, controller_error = "opening_logs", None
    try:
        with (directory / "stdout.log").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
            phase = "process_start"
            process = subprocess.Popen(argv, cwd=root, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            phase = "process_identity"
            try:
                import psutil
            except ModuleNotFoundError as error:
                if error.name != "psutil":
                    raise
                # Bootstrap commands precede the fresh dependency installation.
                # Without a held identity, interruption refuses tree signalling.
                save_new(directory / "process_identity.json", {"pid": process.pid,
                    "status": "UNAVAILABLE_BEFORE_PSUTIL_INSTALL", "tree_signalling_allowed": False})
            else:
                try:
                    owner = psutil.Process(process.pid)
                    owned_root = {"process": owner, "create_time": owner.create_time(), "psutil": psutil}
                    save_new(directory / "process_identity.json", {"pid": process.pid,
                        "create_time": owned_root["create_time"], "status": "HELD_BEFORE_WAIT"})
                except psutil.NoSuchProcess:
                    if process.poll() is None:
                        raise
                    save_new(directory / "process_identity.json", {"pid": process.pid,
                        "status": "EXITED_BEFORE_IDENTITY_CAPTURE", "returncode": process.returncode})
            phase = "process_wait"
            try:
                process.wait()
            except KeyboardInterrupt:
                interrupted = True
                phase = "terminate_tree"
                terminate_tree(process, directory / "termination_trace.jsonl", owned_root=owned_root)
    except BaseException as error:
        failure, failure_tb = error, error.__traceback__
        controller_error = {"phase": phase, "exception_type": type(error).__name__,
            "exception": repr(error), "traceback": traceback.format_exc(),
            "process_pid": process.pid if process is not None else None,
            "process_returncode": process.returncode if process is not None else None,
            "termination_trace": "termination_trace.jsonl" if (directory / "termination_trace.jsonl").exists() else None,
            "completion_claim": False}
        if interrupted and phase == "terminate_tree":
            controller_error["status"] = "FAILED_CLEANUP_NOT_VERIFIED"
            save_new(directory / "RESUME.json", {"status": "FAILED_CLEANUP_NOT_VERIFIED",
                "manual_owned_process_verification_required": True, "automatic_retry_allowed": False,
                "pid": process.pid, "requested_argv": argv, "descendants_exit_claim": False,
                "held_root_identity_available": owned_root is not None,
                "exception_type": type(error).__name__, "exception": repr(error),
                "reason": "Owned-tree cleanup raised an exception; descendant exit is not verified",
                "instruction": "Verify the requested command and descendants manually; retain this failed attempt. No automatic resume is permitted."})
        save_new(directory / "controller_error.json", controller_error)
    save_new(directory / "receipt.json", {"returncode": process.returncode if process is not None else None, "finished_at_utc": utc(),
        "interrupted": interrupted,
        **({"status": "FAILED_CLEANUP_NOT_VERIFIED"} if controller_error and controller_error.get("status") == "FAILED_CLEANUP_NOT_VERIFIED" else {}),
        "stdout_sha256": sha(directory / "stdout.log") if (directory / "stdout.log").exists() else None,
        "stderr_sha256": sha(directory / "stderr.log") if (directory / "stderr.log").exists() else None,
        "controller_error": controller_error,
        "termination_trace_sha256": sha(directory / "termination_trace.jsonl") if (directory / "termination_trace.jsonl").exists() else None})
    if failure is not None:
        raise failure.with_traceback(failure_tb)
    if interrupted:
        raise KeyboardInterrupt
    if process.returncode:
        raise RuntimeError(f"Command {key} failed; full raw logs retained in {directory}")

def terminate_tree(process, trace_path=None, owned_root=None):
    """Signal only held descendants; never reuse a stale process group."""
    def event(phase, **detail):
        if trace_path is not None:
            with Path(trace_path).open("a") as stream:
                stream.write(json.dumps({"phase": phase, "utc": utc(), **detail}, sort_keys=True) + "\n")
                stream.flush()
    def action(phase, callback, **detail):
        event(phase, event="started", **detail)
        try:
            result = callback()
        except BaseException as error:
            event(phase, event="error", exception=repr(error), traceback=traceback.format_exc(), **detail)
            raise
        event(phase, event="finished", **detail)
        return result
    root_returncode = action("poll_owned_child_before_capture", process.poll, pid=process.pid)
    if root_returncode is not None:
        event("owned_tree_skip", reason="owned_root_already_exited", pid=process.pid, returncode=root_returncode)
        return
    if owned_root is None:
        event("owned_tree_refused", reason="no_held_root_identity", pid=process.pid)
        raise RuntimeError("Cannot signal a process tree without its retained launch identity")
    psutil, owner = owned_root["psutil"], owned_root["process"]
    if owner.pid != process.pid or not owner.is_running() or owner.create_time() != owned_root["create_time"]:
        event("owned_tree_skip", reason="owned_root_gone_or_reused", pid=process.pid)
        return
    descendants = action("capture_owned_descendants", lambda: owner.children(recursive=True), pid=owner.pid)
    held = [(owner, owned_root["create_time"])]
    for child in descendants:
        try:
            held.append((child, child.create_time()))
        except psutil.NoSuchProcess:
            event("owned_descendant_skip", reason="gone_during_capture", pid=child.pid)
    event("held_owned_descendants", identities=[{"pid": child.pid, "create_time": created} for child, created in held])
    def signal_owned(child, created, sig):
        phase = "send_signal_" + signal.Signals(sig).name
        detail = {"pid": child.pid, "create_time": created}
        try:
            if child.pid == process.pid and process.returncode is not None:
                event(phase, event="skipped", reason="owned_root_reaped", **detail)
                return
            if not child.is_running() or child.create_time() != created:
                event(phase, event="skipped", reason="gone_or_reused", **detail)
                return
            status = child.status()
            if status in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                event(phase, event="skipped", reason=status, **detail)
                return
            # Process.send_signal performs psutil's PID-reuse check again.
            action(phase, lambda: child.send_signal(sig), **detail)
        except psutil.NoSuchProcess:
            event(phase, event="skipped", reason="gone_during_signal", **detail)
    for child, created in held:
        signal_owned(child, created, signal.SIGTERM)
    action("termination_grace", lambda: time.sleep(.5))
    action("poll_owned_child_after_grace", process.poll, pid=process.pid)
    for child, created in held:
        signal_owned(child, created, signal.SIGKILL)
    action("wait_owned_child", process.wait, pid=process.pid)

def retain_incomplete_scheduler_logs(root, output):
    """Retry interrupted, unterminated jobs while keeping every previous artifact."""
    folder = root / output
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        return
    for jobpath in read(manifest_path)["jobs"]:
        job = read(root / jobpath)
        result = root / job["result_path"]
        if result.exists() or result.with_suffix(".failure.json").exists():
            continue
        files = [folder / "logs" / (job["task"] + suffix) for suffix in (".stdout.log", ".stderr.log")]
        files.extend([Path(str(result) + ".checkpoint.json"), folder / "artifacts" / job["task"]])
        files = [file for file in files if file.exists()]
        if not files:
            continue
        base = root / "work/reproduction/abandoned_outputs" / job["task"]
        target = base / f"attempt_{len(list(base.glob('attempt_*'))):03d}"
        target.mkdir(parents=True)
        save_new(target / "receipt.json", {"status": "INTERRUPTED_UNTERMINATED_JOB", "task": job["task"],
            "original_paths": [str(p.relative_to(root)) for p in files], "timing_unknown": True,
            "completion_claim": False, "retained_at_utc": utc()})
        for file in files:
            shutil.move(str(file), str(target / file.name))

def download(root, url, target, expected):
    target = root / target
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha(target) != expected:
            raise RuntimeError("Existing downloaded bytes differ: " + str(target))
        return
    partial = target.with_name(target.name + ".partial")
    if partial.exists():
        partial.rename(partial.with_name(partial.name + ".retained_" + str(len(list(partial.parent.glob(partial.name + ".retained_*"))))))
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("xb") as stream:
        shutil.copyfileobj(response, stream)
    if sha(partial) != expected:
        raise RuntimeError("Downloaded SHA-256 differs; partial bytes retained")
    partial.rename(target)

def setup(root, python):
    lock = read(root / "experiments/reproduction/lock.json")
    if sys.platform != "darwin" or platform.machine() not in ("arm64", "aarch64"):
        raise RuntimeError("Setup archive is pinned for macOS arm64 only; Linux setup has not been validated")
    run_command(root, "venv", [python, "-m", "venv", ".venv"])
    py = str(root / ".venv/bin/python")
    actual_python = subprocess.check_output([py, "-c", "import platform; print(platform.python_version())"], text=True).strip()
    if actual_python != lock["python_version"]:
        raise RuntimeError("Python version differs from pinned reference: " + actual_python)
    run_command(root, "python_dependencies", [py, "-m", "pip", "install", "--requirement", "provenance/dependency_versions.txt"])
    for name, repository in lock["repositories"].items():
        target = root / repository["path"]
        run_command(root, f"fetch_{name}_init", ["git", "init", repository["path"]])
        run_command(root, f"fetch_{name}_remote", ["git", "-C", repository["path"], "remote", "add", "origin", repository["url"]])
        run_command(root, f"fetch_{name}_commit", ["git", "-C", repository["path"], "fetch", "--depth", "1", "origin", repository["commit"]])
        run_command(root, f"fetch_{name}_checkout", ["git", "-C", repository["path"], "checkout", "--detach", repository["commit"]])
        actual = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
        if actual != repository["commit"]:
            raise RuntimeError("Author repository commit differs: " + name)
        for path, expected in repository["tracked_worktree_file_sha256"].items():
            if sha(target / path) != expected:
                raise RuntimeError("Author source hash differs: " + name + "/" + path)
    for paper in lock["papers"].values():
        arxiv = paper.get("verified_arxiv_version", paper["arxiv_version"])
        download(root, "https://arxiv.org/pdf/" + arxiv, paper["path"], paper["sha256"])
    julia = lock["julia"]
    download(root, julia["url"], julia["archive_path"], julia["sha256"])
    if not (root / julia["binary_paths"][0]).exists():
        with tarfile.open(root / julia["archive_path"]) as archive:
            archive.extractall(root / "external/runtime", filter="data")
    run_command(root, "julia_packages", [str(root / julia["binary_paths"][0]), "--startup-file=no",
        "--project=external/runtime/hfd-environment", "-e", "using Pkg; Pkg.instantiate(); using Combinatorics; @assert pkgversion(Combinatorics)==v\"1.0.2\""])
    for path, expected in lock["julia_dependencies"]["files_sha256"].items():
        # The package cache directory slug is platform-independent for this tree.
        if sha(root / path) != expected:
            raise RuntimeError("Pinned task-local Julia package/environment differs: " + path)
    run_command(root, "mincut_build", [py, "experiments/build.py"])
    generator = root / "external/generators/lfr_native/unweighted_undirected"
    compiler = os.environ.get("CXX", "clang++")
    run_command(root, "lfr_build", [compiler, "-O3", "-funroll-loops", str(generator / "Sources/benchm.cpp"), "-o", str(generator / "benchmark")])
    save_new(root / "work/reproduction/build_identity.json", {"platform": platform.platform(),
        "python": subprocess.check_output([py, "-V"], text=True).strip(),
        "mincut_source_sha256": sha(root / "zrhfd/mincut128.cpp"), "mincut_binary_sha256": sha(root / "work/bin/mincut128"),
        "lfr_binary_sha256": sha(generator / "benchmark"), "lfr_reference_binary_sha256": lock["lfr_reference_binary_sha256"],
        "binary_byte_identity_not_assumed": True, "created_at_utc": utc()})

def compare_inputs(root, prefix):
    archive = read(root / "experiments/reproduction/input_hash_archive.json")
    paths = {p: expected for p, expected in archive["files_sha256"].items()
             if p.startswith(prefix) and (p.endswith((".graph.json", ".truth.json", ".queries.json", "truth.json", "queries.json", ".npy")))}
    mismatches = [p for p, expected in paths.items() if not (root / p).exists() or sha(root / p) != expected]
    target = root / "work/reproduction/input_comparisons" / (prefix.replace("/", "_") + ".json")
    save_new(target, {"input_prefix": prefix, "files": len(paths), "mismatches": mismatches,
        "status": "PASS" if not mismatches else "INPUT_REGENERATION_DIFFERS", "quality_was_not_inspected": True})
    if mismatches:
        raise RuntimeError("Regenerated input differs; preserve raw output and stop affected quality stage: " + ", ".join(mismatches[:5]))

def stage(root, name, maximum):
    lock = read(root / "experiments/reproduction/lock.json")
    if name in ("m5", "smoke") and lock["stage_freeze_status"]["m5"] != "SOURCE_FROZEN":
        raise RuntimeError("NOT_FROZEN_M5: root hypergraph engineering is still active; refresh only after M5SOURCE_FROZEN")
    py = str(root / ".venv/bin/python")
    def execute(key, script, *args, **kwargs):
        run_command(root, name + "_" + key, [py, script, *args], **kwargs)
    if name == "smoke":
        execute("fresh_setup", "experiments/reproduction/smoke.py", rerun_success=True)
    elif name == "m0":
        execute("same12", "experiments/m0_reference/materialize_same12.py")
        for script in ("checks_g2", "checks_g3b"):
            execute(script, "experiments/m0_reference/run_supplied.py", script,
                    resumable=False, partial_output=f"results/m0_reference/{script}")
        execute("legacy", "experiments/m0_reference/run_legacy_reconstruction.py", resumable=False,
                partial_output="results/m0_reference/legacy_reconstruction")
        execute("summary", "experiments/m0_reference/summarize.py")
    elif name == "m1":
        execute("checks", "tests/m1_independent/run_all.py", resumable=False,
                partial_output="results/m1_independent")
    elif name == "m2":
        execute("queries", "experiments/run_m2.py", "--output", "results/m2/run_v12_001")
        execute("summary", "experiments/summarize_m2.py")
    elif name == "m3":
        execute("inputs", "experiments/data_generation/run_all.py")
        compare_inputs(root, "data/dev/sbm_v12/")
        compare_inputs(root, "data/test/calibrated_lfr/")
        execute("baseline_smoke", "experiments/baseline_integration/run_smoke.py")
    elif name in ("m4", "m4-region", "m4-ablations"):
        if name != "m4":
            phase = "region" if name == "m4-region" else "ablations"
            output = "results/m4/dev_region_v12_002" if phase == "region" else "results/m4/dev_ablations_v12_002"
            args = ["--phase", phase, "--split", "dev", "--output", output]
            if maximum is not None:
                args.extend(["--max-tasks", str(maximum)])
            retain_incomplete_scheduler_logs(root, output)
            execute("queries", "experiments/schedule.py", *args, rerun_success=True)
            if phase == "region" and maximum is None:
                execute("decision", "experiments/region_decision.py")
            return
        for split in ("dev", "test"):
            output = f"results/m4/{split}_main_v12_002"
            args = ["--phase", "main", "--split", split, "--output", output]
            if maximum is not None:
                args.extend(["--max-tasks", str(maximum)])
            binding = f"work/reproduction/m4_{split}_cohort_binding.json"
            execute(split + "_prepare", "experiments/schedule.py", "--phase", "main", "--split", split, "--output", output, "--prepare-only", rerun_success=True)
            execute(split + "_binding", "experiments/reproduction/cohort_binding.py", "--stage", "m4-" + split, "--run", output, "--output", binding, rerun_success=True)
            retain_incomplete_scheduler_logs(root, output)
            execute(split, "experiments/schedule.py", *args, rerun_success=True)
            summary_args = ["--run", output, "--reference-binding", binding]
            execute(split + "_summary", "experiments/summarize_m4.py", *summary_args, rerun_success=True)
            execute(split + "_plot", "experiments/plot_m4.py", "--run", output, "--output", f"figures/m4/{split}_main_reproduction", "--reference-binding", binding, rerun_success=True)
        if maximum is None:
            diagnostic_run = "results/diagnostics/m4_main_reproduction_v001"
            upstream = ["results/m4/dev_main_v12_002", "results/m4/test_main_v12_002"]
            diagnostic_args = ["--runs", *upstream, "--output", diagnostic_run,
                               "--query-wall-seconds", "600", "--memory-bytes", "12000000000"]
            # This runner's default action prepares/inventories; it has no --prepare flag.
            execute("diagnostic_prepare", "experiments/diagnostics/run_m4.py", *diagnostic_args, rerun_success=True)
            # Keep the entire frozen plan; this outer helper admits test
            # diagnostics only after verifying this fresh test cohort's G-E2.
            execute("diagnostic_execute", "experiments/diagnostics/gated_m4.py", "--run", diagnostic_run,
                    "--reference-binding", "work/reproduction/m4_test_cohort_binding.json",
                    "--execute", rerun_success=True)
            execute("diagnostic_summary", "experiments/diagnostics/summarize_m4.py", "--run", diagnostic_run, rerun_success=True)
            execute("diagnostic_crosslist", "experiments/diagnostics/m4_completion_join.py", "--run", diagnostic_run, rerun_success=True)
        else:
            print("M4 offline diagnostics omitted for a bounded measurement prefix; no complete-diagnostics claim", flush=True)
    elif name == "m5":
        for dataset in read(root / "provenance/baselines/benson-download.json")["datasets"].values():
            download(root, dataset["url"], dataset["path"], dataset["sha256"])
        execute("official_data", "data/external/acquire_benson.py")
        run = "results/m5/reproduction"
        binding = "work/reproduction/m5_cohort_binding.json"
        execute("prepare", "experiments/m5/run_serial.py", "--run", run, "--tl-backend", "numba", rerun_success=True)
        execute("binding", "experiments/reproduction/cohort_binding.py", "--run", run, "--output", binding, rerun_success=True)
        args = ["--run", run, "--execute", "--tl-backend", "numba"]
        if maximum is not None:
            args.extend(["--max-jobs", str(maximum)])
        execute("queries", "experiments/run_m5_archived.py", *args, rerun_success=True)
        analysis = "results/m5_analysis/reproduction"
        mode = ["--reproduced-cohort", "--reference-binding", binding]
        execute("inventory", "experiments/m5_analysis/inventory.py", "--run", run, "--output", analysis, "--verify-files", *mode, rerun_success=True)
        execute("summary", "experiments/m5_analysis/summarize.py", "--input", analysis, *mode,
                *(["--bootstrap"] if maximum is None else []), rerun_success=True)
        execute("plot", "experiments/m5_analysis/plot_quality_cost.py", "--input", analysis, "--output", "figures/m5/reproduction", *mode, rerun_success=True)
    elif name == "m6":
        execute("inputs", "experiments/data_generation/scale_generate.py")
        compare_inputs(root, "data/scale/")
        # Runtime-bearing catalog/metadata hashes necessarily change on a fresh
        # generation. Rebind only after every graph/truth/query byte is equal.
        config_path = root / "experiments/m6_prepared/config.json"
        config = read(config_path)
        catalog_hash = sha(root / config["catalog"])
        if config["catalog_sha256"] != catalog_hash:
            original = config["catalog_sha256"]
            original_config_hash = sha(config_path)
            snapshot = "work/reproduction/m6_original_configuration.json"
            save_new(root / snapshot, config)
            config["catalog_sha256"] = catalog_hash
            config_text = json.dumps(config, indent=2) + "\n"
            save_new(root / "work/reproduction/m6_catalog_rebinding.json", {
                "configuration_path": str(config_path.relative_to(root)),
                "original_configuration_sha256": original_config_hash,
                "regenerated_configuration_sha256": hashlib.sha256(config_text.encode()).hexdigest(),
                "original_configuration_snapshot": snapshot,
                "original_catalog_sha256": original, "regenerated_catalog_sha256": catalog_hash,
                "reason": "Fresh generation timestamps/runtime metadata differ; arrays/truth/queries already matched archived bytes",
                "main_method_changed": False, "original_project_modified": False})
            temporary = config_path.with_name(config_path.name + ".reproduction.tmp")
            temporary.write_text(config_text)
            os.replace(temporary, config_path)
        execute("prepare", "experiments/m6_prepared/run.py", "--prepare", "--source-frozen")
        args = ["--run"]
        if maximum is not None:
            args.extend(["--max-queries", str(maximum)])
        controller = "experiments/run_m6_compressed.py" if sys.platform == "darwin" else "experiments/m6_prepared/run.py"
        execute("queries", controller, *args, rerun_success=True)
        execute("summary", "experiments/m6_prepared/summarize.py", rerun_success=True)
        audit_receipt = "results/m6_analysis/prepared_audit/receipt.json"
        execute("offline_audit", "experiments/m6_analysis/audit.py", "--run", "results/m6_prepared", "--output", audit_receipt, rerun_success=True)
        execute("plot", "experiments/plot_m6.py", "--audit-receipt", audit_receipt, rerun_success=True)
    else:
        raise ValueError(name)

def main():
    def stop_requested(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_requested)
    parser = argparse.ArgumentParser(description=__doc__)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--fresh", type=Path)
    destination.add_argument("--workspace", type=Path)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--stages", default="")
    parser.add_argument("--check-existing", action="store_true")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--python", default="python3.12")
    parser.add_argument("--max-tasks", type=int)
    args = parser.parse_args()
    stages = [name for name in args.stages.split(",") if name]
    if any(name not in {"smoke", "m0", "m1", "m2", "m3", "m4", "m4-region", "m4-ablations", "m5", "m6"} for name in stages):
        parser.error("Stages are smoke,m0,m1,m2,m3,m4,m4-region,m4-ablations,m5,m6")
    if args.plan:
        print(json.dumps({"stages": stages, "setup": args.setup, "fresh": str(args.fresh) if args.fresh else None,
            "platform_tested": "macOS arm64", "formal_original_results_modified": False,
            "source_state": read(LOCK)["source_state"], "stage_freeze_status": read(LOCK)["stage_freeze_status"],
            "lock_sha256": sha(LOCK), "input_hash_archive_sha256": sha(ARCHIVE)}, indent=2))
        return
    if not args.fresh and not args.workspace:
        if args.setup or stages:
            parser.error("Actual setup/execution requires --fresh DIR or --workspace DIR")
        check(SOURCE, args.deep)
        return
    root = clone_workspace(args.fresh) if args.fresh else isolated(args.workspace)
    frozen_sources(root)
    serial_lock = root / "work/reproduction/serial.lock"
    serial_lock.parent.mkdir(parents=True, exist_ok=True)
    if serial_lock.exists():
        try:
            os.kill(int(serial_lock.read_text()), 0)
        except ProcessLookupError:
            serial_lock.rename(serial_lock.with_name("abandoned_serial_lock_" + utc().replace(":", "")))
        else:
            raise RuntimeError("Another reproduction command owns this workspace")
    with serial_lock.open("x") as stream:
        stream.write(str(os.getpid()))
    try:
        if args.setup:
            setup(root, args.python)
        for name in stages:
            stage(root, name, args.max_tasks)
        if args.check_existing:
            check(root, args.deep)
    finally:
        serial_lock.unlink()

if __name__ == "__main__":
    main()
