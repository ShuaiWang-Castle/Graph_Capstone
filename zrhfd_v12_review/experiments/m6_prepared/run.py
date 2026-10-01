"""Independent serial M6 prepared exact-cut cohort; never import old measurements."""
from __future__ import annotations
import argparse
import os
import platform
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from common import (ROOT, CONFIG, MANIFEST, atomic, check_sources, dependency_fingerprint, immutable,
                    load_schedule, read, sha, single_thread_env, sources, utc)

def group_rss(root_pid):
    """Sample root process and descendants. macOS ps reports KiB RSS."""
    output = subprocess.run(["ps", "-axo", "pid=,ppid=,rss="], capture_output=True,
                            text=True, check=True).stdout
    rows = [tuple(map(int, line.split())) for line in output.splitlines() if line.strip()]
    included = {root_pid}
    while True:
        added = {pid for pid, parent, _ in rows if parent in included}
        if added.issubset(included):
            break
        included.update(added)
    return sum(rss * 1024 for pid, _, rss in rows if pid in included)

def execute_child(request, directory, limits):
    directory.mkdir(parents=True, exist_ok=True)
    request_path = directory / "request.json"
    request.update({"resource_limits": limits})
    immutable(request_path, request)
    command = ["/usr/bin/time", "-l", str(ROOT / ".venv/bin/python"),
               "experiments/m6_prepared/worker.py", "--request", str(request_path.relative_to(ROOT))]
    record = {"schema_version": 1, "status": "running", "started_at_utc": utc(),
              "actual_argv": command, "actual_cwd": str(ROOT),
              "request_sha256": sha(request_path), "limits": limits,
              "implementation_version": request["implementation_version"],
              "resource_enforcement": "wall and sampled process-group RSS; kill whole group",
              "rss_poll_seconds": limits["resource_poll_seconds"],
              "max_sampled_process_group_rss_bytes": 0}
    atomic(directory / "controller.json", record)
    began = time.perf_counter()
    peak = 0
    termination = None
    process = None
    try:
        with (directory / "stdout.log").open("x") as stdout, (directory / "stderr.log").open("x") as stderr:
            process = subprocess.Popen(command, cwd=ROOT,
                env=single_thread_env(ROOT / "results/m6_prepared/numba_cache"),
                stdout=stdout, stderr=stderr, start_new_session=True)
            while process.poll() is None:
                elapsed = time.perf_counter() - began
                rss = group_rss(process.pid)
                peak = max(peak, rss)
                if elapsed > limits["query_wall_limit_seconds"]:
                    termination = "timeout"
                elif rss > limits["query_process_group_rss_limit_bytes"]:
                    termination = "memory_limit"
                if termination:
                    os.killpg(process.pid, signal.SIGKILL)
                    break
                time.sleep(limits["resource_poll_seconds"])
            returncode = process.wait()
    except KeyboardInterrupt:
        termination = "interrupted"
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        returncode = None
    except BaseException as error:
        termination = "controller_error"
        record["controller_error"] = repr(error)
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        returncode = None
    elapsed = time.perf_counter() - began
    result_path = directory / "result.json"
    if termination:
        status = termination
    elif returncode == 0 and result_path.exists() and read(result_path)["status"] == "completed":
        status = "completed"
    else:
        status = "error"
    stderr_path = directory / "stderr.log"
    match = re.search(r"(\d+)\s+maximum resident set size", stderr_path.read_text() if stderr_path.exists() else "")
    record.update(status=status, ended_at_utc=utc(), returncode=returncode,
        parent_process_wall_seconds=elapsed, max_sampled_process_group_rss_bytes=peak,
        time_l_max_resident_set_size_bytes=int(match.group(1)) if match else None,
        last_checkpoint=read(directory / "checkpoint.json") if (directory / "checkpoint.json").exists() else None,
        result_sha256=sha(result_path) if result_path.exists() else None,
        error_sha256=sha(directory / "error.json") if (directory / "error.json").exists() else None,
        stdout_sha256=sha(directory / "stdout.log") if (directory / "stdout.log").exists() else None,
        stderr_sha256=sha(stderr_path) if stderr_path.exists() else None,
        runtime_censored=status in ("timeout", "memory_limit", "interrupted"))
    atomic(directory / "controller.json", record)
    immutable(directory / "terminal.json", record)
    print(f"{request['query_id']}: {status}; wall={elapsed:.3f}s; peak sampled group RSS={peak}", flush=True)
    if status == "interrupted":
        raise KeyboardInterrupt
    return record

def prepare(source_frozen):
    if not source_frozen:
        raise RuntimeError("--prepare requires --source-frozen after root's SOURCE_FROZEN message")
    if MANIFEST.exists():
        manifest = read(MANIFEST)
        check_sources(manifest)
        cfg, schedule = load_schedule()
        if manifest["schedule"] != schedule:
            raise RuntimeError("Frozen M6 schedule differs")
        print(f"Manifest unchanged: {MANIFEST.relative_to(ROOT)} sha256={sha(MANIFEST)}")
        return
    cfg, schedule = load_schedule()
    # Verify every CSR byte once, outside all formal query times.
    array_audit = {}
    for query in schedule:
        if query["case_id"] in array_audit:
            continue
        meta = read(ROOT / query["csr_path"] / "csr_metadata.json")
        hashes = {key: sha(ROOT / query["csr_path"] / filename) for key, filename in meta["files"].items()}
        if hashes != query["csr_array_sha256"]:
            raise RuntimeError("Frozen CSR array bytes differ")
        array_audit[query["case_id"]] = hashes
    manifest = {"schema_version": 1,
        "preparation_version": 1,
        "implementation_version": cfg["implementation_version"],
        "legacy_measurements_imported": False,
        "legacy_source_archive": "results/m6_prepared/legacy_m6_source_archive_v002/receipt.json",
        "created_at_utc": utc(), "source_state": "SOURCE_FROZEN",
        "config_sha256": sha(CONFIG), "source_sha256": sources(), "configuration": cfg,
        "dependency_fingerprint": dependency_fingerprint(),
        "catalog_sha256": cfg["catalog_sha256"], "schedule": schedule,
        "csr_full_hash_verification": array_audit,
        "runtime_preparation": {"python": sys.version, "platform": platform.platform(),
                                "executable": sys.executable}}
    immutable(MANIFEST, manifest)
    print(f"Frozen 9 graphs / 108 queries: {MANIFEST.relative_to(ROOT)} sha256={sha(MANIFEST)}")

def limits_from(config):
    return {key: config[key] for key in ("query_wall_limit_seconds", "query_process_group_rss_limit_bytes", "resource_poll_seconds")}

def smoke():
    cfg = read(CONFIG)
    identity = utc().replace(":", "").replace("+", "_")
    directory = ROOT / "results/m6_prepared/smoke" / identity / "attempt_000"
    request = {"schema_version": 1, "mode": "smoke", "query_id": "unlabeled_toy_smoke",
        "implementation_version": cfg["implementation_version"],
        "seed": 0, "method_config": cfg["method_config"], "source_sha256": sources(),
        "source_state": "UNFROZEN_INFRASTRUCTURE_SMOKE_ONLY"}
    result = execute_child(request, directory, limits_from(cfg))
    atomic(ROOT / "results/m6_prepared/smoke_latest.json", {"record": str(directory.relative_to(ROOT)),
        "status": result["status"], "formal_queries_executed": 0})
    if result["status"] != "completed":
        raise RuntimeError("Unlabeled infrastructure smoke failed; raw error preserved")

def run(max_queries=None, retry_failed=False):
    if not MANIFEST.exists():
        raise RuntimeError("Formal manifest absent: first prepare after root SOURCE_FROZEN")
    manifest = read(MANIFEST)
    check_sources(manifest)
    cfg, schedule = load_schedule()
    if manifest["schedule"] != schedule or manifest["config_sha256"] != sha(CONFIG):
        raise RuntimeError("M6 manifest/input/config mismatch")
    count = 0
    for query in schedule:
        base = ROOT / "results/m6_prepared/queries" / query["query_id"]
        existing = sorted(base.glob("attempt_*"))
        if existing:
            terminal_path = existing[-1] / "terminal.json"
            if terminal_path.exists():
                old = read(terminal_path)
                if old["status"] == "completed" or (old["status"] != "interrupted" and not retry_failed):
                    continue
            else:
                # A killed controller leaves its entire raw attempt intact.
                atomic(existing[-1] / "orphaned.json", {"status": "orphaned_interrupted",
                    "observed_at_utc": utc(), "reason": "No durable terminal record at resume"})
        if max_queries is not None and count >= max_queries:
            break
        directory = base / f"attempt_{len(existing):03d}"
        request = {"schema_version": 1, "mode": "formal", "query_id": query["query_id"],
            "implementation_version": cfg["implementation_version"],
            "query": query, "method_config": cfg["method_config"],
            "source_sha256": manifest["source_sha256"],
            "manifest_path": str(MANIFEST.relative_to(ROOT)), "manifest_sha256": sha(MANIFEST)}
        execute_child(request, directory, limits_from(cfg))
        count += 1
        check_sources(manifest)
    from summarize import summarize
    summarize()

if __name__ == "__main__":
    def stop_requested(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_requested)
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--prepare", action="store_true")
    choice.add_argument("--smoke", action="store_true")
    choice.add_argument("--run", action="store_true")
    choice.add_argument("--summarize", action="store_true")
    parser.add_argument("--source-frozen", action="store_true")
    parser.add_argument("--max-queries", type=int)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.source_frozen)
    elif args.smoke:
        smoke()
    elif args.run:
        run(args.max_queries, args.retry_failed)
    else:
        from summarize import summarize
        summarize()
