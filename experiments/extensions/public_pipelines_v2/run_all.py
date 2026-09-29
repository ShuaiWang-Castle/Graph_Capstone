"""Single-process immutable full v2 execution; requires reviewed source freeze."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import gc
import json
import os
from pathlib import Path
import time
import traceback

from experiments.datasets import load_snap

from .contracts import SCHEMA, PhaseLedger, content_hash, read_json, sha256, utc_now, write_once
from .freeze import CONFIG_PATH, NAMESPACE, validate_freeze
from .run_case import run_case
from .schedule import enumerate_cases
from .stages import build_fixed_bank, graph_counts, prepare_original


@contextmanager
def measurement_lock():
    """Cross-run controller mutex, separate from immutable measurement evidence."""
    path = NAMESPACE / "measurement.lock"
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another public-pipeline measurement process is active") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def timed_write(path, value):
    serialization_start = time.perf_counter()
    # write_once includes deterministic JSON encoding, compression and I/O;
    # this outer duration is explicitly outside all constructed compute totals.
    digest = write_once(path, value)
    return {"path": str(path), "sha256": digest,
            "serialization_compression_io_seconds": time.perf_counter() - serialization_start}


def prepare_setup(case, config, freeze, identity, run_dir, *, progress=None):
    progress = {} if progress is None else progress
    setup_started = time.perf_counter()
    key = case.setup_key
    start_identity = {"schema_version": SCHEMA, "setup_key": key, "dataset": case.dataset,
                      "discovery_seed": case.discovery_seed, **identity, "started_at_utc": utc_now()}
    timed_write(run_dir / f"{key}-setup-started.json", start_identity)
    loading_started = time.perf_counter()
    graph, metadata = load_snap(case.dataset)
    archived = freeze["archived_bank_identity"][key]
    archived_record = read_json(archived["path"])
    expected_metadata = read_json(config["processed_metadata"])[case.dataset]
    loading_seconds = time.perf_counter() - loading_started
    ledger = PhaseLedger()
    partial = {**start_identity, "status": "started", "dataset_metadata": metadata,
               "primary_phase_records": ledger.records}
    progress["raw_setup_record"] = partial
    progress["phase"] = "common_original_prepare"
    with ledger.measure("common_original_prepare"):
        context = prepare_original(graph, metadata, expected_metadata=expected_metadata)
        # Full source counts and exact original cache identity are common input work.
        original = {"graph_counts": graph_counts(context.objective), "degrees_exact": list(context.objective.degrees),
                    "S_exact": context.objective.total, "objective_content_sha256": context.objective.content_sha256,
                    "original_vertex_order": list(context.vertex_order), "largest_component_original_vertices": list(context.largest_component),
                    "sorted_original_ID_sha256": metadata["original_sorted_node_labels_sha256"]}
        partial["original"] = original
    progress["phase"] = "candidate_discovery_and_fixed_bank_validation"
    bank = build_fixed_bank(context, case.discovery_seed, ledger, archived_record=archived_record, progress=partial)
    for record in ledger.records:
        record["interval_domain"] = key
    record = {**start_identity, "status": "completed", "completed_at_utc": utc_now(),
              "dataset_metadata": metadata, "original": original, "fixed_bank": bank.source_record,
              "archived_v1_bank_reference": archived, "primary_phase_records": ledger.records,
              "loading_archive_decoding_seconds": loading_seconds,
              "physical_setup_elapsed_seconds": time.perf_counter() - setup_started,
              "phase_attribution": {"fixed_bank_refinement_seconds": ledger.sum(("fixed_bank_refinement",)),
                                    "common_discovery_seconds": ledger.sum(("common_discovery",)),
                                    "source_call_diagnostics": bank.source_record["candidate_call_diagnostics"],
                                    "bank_validation_charged_to_U": False}}
    path = run_dir / f"{key}-setup.json.gz"
    io = timed_write(path, record)
    timed_write(run_dir / f"{key}-setup-completed.json", {**start_identity, "status": "completed", "record": io})
    # This identity is the hash of the immutable setup bytes, added to the
    # in-memory case view only; no self-referential artifact hash is stored.
    record["identity"] = {"path": str(path), "sha256": io["sha256"], "setup_key": key}
    return context, bank, record


def execute(config_path, freeze_path, run_dir=None):
    config, freeze = validate_freeze(config_path, freeze_path)
    if not gc.isenabled():
        raise RuntimeError("normal enabled GC is required before execution")
    run_dir = Path(run_dir or config["paths"]["run_dir"])
    if run_dir.exists():
        raise FileExistsError("v2 runs use a new empty namespace; partial/failed runs cannot be resumed or overwritten")
    run_dir.mkdir(parents=True, exist_ok=False)
    identity = {"config_sha256": sha256(config_path), "freeze_sha256": sha256(freeze_path),
                "runtime_source_manifest_sha256": content_hash(freeze["runtime_source_sha256"]),
                "expected_ledger_sha256": freeze["expected_ledger_sha256"], "versions": freeze["versions"]}
    manifest = {"schema_version": SCHEMA, "status": "started", "started_at_utc": utc_now(),
                **identity, "config_path": str(config_path), "freeze_path": str(freeze_path),
                "runtime_source_sha256": freeze["runtime_source_sha256"], "expected_ledger": freeze["expected_ledger"],
                "process_id": os.getpid(), "thread_environment": {k: os.getenv(k) for k in config["threads"]},
                "hardware": freeze["hardware"], "gc_policy": config["gc_policy"],
                "retention_policy": config["retention_policy"]}
    timed_write(run_dir / "run-manifest.json", manifest)
    outcomes, setups = [], []
    current_setup = None
    progress = {}
    physical_start = time.perf_counter()
    try:
        for case in enumerate_cases(config):
            progress = {"case_key": case.key, "setup_key": case.setup_key, "phase": "pre_run_identity_validation"}
            preflight_start = time.perf_counter()
            validate_freeze(config_path, freeze_path)
            preflight_seconds = time.perf_counter() - preflight_start
            progress = {"case_key": case.key, "setup_key": case.setup_key, "phase": "setup_prepare"}
            if current_setup != case.setup_key:
                context, bank, setup = prepare_setup(case, config, freeze, identity, run_dir, progress=progress)
                current_setup = case.setup_key
                setups.append(setup["identity"])
            start_record = {"schema_version": SCHEMA, **case.record(), **identity,
                            "setup_reference": setup["identity"], "status": "started", "started_at_utc": utc_now(),
                            "pre_run_infrastructure_identity_validation_seconds": preflight_seconds}
            progress.pop("raw_setup_record", None)
            timed_write(run_dir / f"{case.key}-started.json", start_record)
            sequence = 0

            def event_callback(event):
                nonlocal sequence
                sequence += 1
                timed_write(run_dir / f"{case.key}-progress-{sequence:03d}.json", {
                    "schema_version": SCHEMA, "case_key": case.key, **identity,
                    "sequence": sequence, "created_at_utc": utc_now(), **event})
                print(json.dumps({"case": case.ordinal + 1, "of": 54, "case_key": case.key, **event}), flush=True)

            result = run_case(case, context, bank, setup, identity, progress=progress, event_callback=event_callback)
            result["pre_run_infrastructure_identity_validation_seconds"] = preflight_seconds
            path = run_dir / f"{case.key}.json.gz"
            io = timed_write(path, result)
            done = {**case.record(), "schema_version": SCHEMA, **identity, "status": "completed", "record": io,
                    "completed_at_utc": utc_now(), "completed_solver_calls": 36, "prefix_summary_count": 12}
            timed_write(run_dir / f"{case.key}-completed.json", done)
            outcomes.append(done)
            # Do not retain completed-case raw labels into later cases. Normal
            # enabled GC determines collection; no manual collect is called.
            progress = {"case_key": case.key, "phase": "case_completed"}
            del result
        completed = {"schema_version": SCHEMA, **identity, "status": "completed", "completed_at_utc": utc_now(),
                     "physical_process_elapsed_seconds": time.perf_counter() - physical_start,
                     "expected_counts": freeze["expected_ledger"]["counts"], "completed_cases": len(outcomes),
                     "completed_solver_calls": sum(row["completed_solver_calls"] for row in outcomes),
                     "prefix_summary_count": sum(row["prefix_summary_count"] for row in outcomes),
                     "setups": setups, "case_outcomes": outcomes}
        timed_write(run_dir / "run-completed.json", completed)
        return completed
    except BaseException as error:
        trace = traceback.format_exc()
        failure = {"schema_version": SCHEMA, **identity, "status": "halted_for_recorded_source_repair",
                   "failed_at_utc": utc_now(), "case_key": progress.get("case_key"), "setup_key": progress.get("setup_key"),
                   "last_phase": progress.get("phase"), "arm": progress.get("arm"), "seed": progress.get("seed"),
                   "prefix": progress.get("prefix"), "exception_type": type(error).__name__, "exception": str(error),
                   "traceback": trace, "completed_case_outcomes": outcomes, "completed_setup_records": setups,
                   "expected_counts": freeze["expected_ledger"]["counts"],
                   "physical_process_elapsed_seconds": time.perf_counter() - physical_start,
                   "blocked_case_keys": [row["case_key"] for row in freeze["expected_ledger"]["cases"]
                                         if row["case_key"] not in {done["case_key"] for done in outcomes}]}
        if "raw_record" in progress:
            partial = progress["raw_record"]
            partial.update(status="failed", failure_reason=str(error), failed_at_utc=failure["failed_at_utc"])
            reference = timed_write(run_dir / f"{progress['case_key']}-failed-partial.json.gz", partial)
            failure["partial_case_record"] = reference
        elif "raw_setup_record" in progress:
            partial = progress["raw_setup_record"]
            partial.update(status="failed", failure_reason=str(error), failed_at_utc=failure["failed_at_utc"])
            failure["partial_setup_record"] = timed_write(run_dir / f"{progress['setup_key']}-setup-failed-partial.json.gz", partial)
        timed_write(run_dir / "run-failed.json", failure)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--freeze", default=str(NAMESPACE / "freeze.json"))
    parser.add_argument("--run-dir")
    args = parser.parse_args()
    with measurement_lock():
        result = execute(args.config, args.freeze, args.run_dir)
    print(json.dumps({"status": result["status"], "completed_cases": result["completed_cases"],
                      "completed_solver_calls": result["completed_solver_calls"]}), flush=True)


if __name__ == "__main__":
    main()
