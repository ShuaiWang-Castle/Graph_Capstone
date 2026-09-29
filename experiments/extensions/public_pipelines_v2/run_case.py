"""Nine unchanged solves per arm, external incumbent selection and complete costs."""
from __future__ import annotations

from fractions import Fraction
import gc
import math
import resource
import sys
import time

from experiments.pipeline import solve_louvain

from .contracts import (ARMS, SCHEMA, PhaseLedger, integer_labels, rational_record,
                        rational_value, standalone_cost, utc_now)
from .integer_objective import integer_modularity
from .schedule import DOWNSTREAM_SEEDS, PREFIXES, preprocessing_order, seed_arm_order
from .stages import prepare_arm, validate_r_prefixes


def select_external_incumbent(discovery_labels, discovery_q, raw_labels, raw_q, seed):
    """A quotient need not represent discovery; ties choose the original incumbent."""
    if not isinstance(discovery_q, Fraction) or not isinstance(raw_q, Fraction):
        raise TypeError("selection requires exact rational objective values")
    if raw_q <= discovery_q:
        return {"winner_kind": "discovery", "winner_seed": None, "returned_Q_exact": rational_record(discovery_q),
                "returned_original_labels": list(integer_labels(discovery_labels)), "discovery_fallback": True}
    return {"winner_kind": "downstream_seed", "winner_seed": int(seed), "returned_Q_exact": rational_record(raw_q),
            "returned_original_labels": list(integer_labels(raw_labels)), "discovery_fallback": False}


def run_seed(context, bank, state, gamma, seed, discovery_q, ledger, *, progress=None):
    progress = {} if progress is None else progress
    arm = state.arm
    record = {"arm": arm, "seed": int(seed), "status": "started"}
    state.seed_results.append(record)
    progress.update(phase="seed_solve_and_float_validate", arm=arm, seed=seed)
    with ledger.measure("seed_solve_and_float_validate", arm=arm, seed=seed):
        raw_labels, diagnostic = solve_louvain(state.graph, state.adjacency, gamma, seed)
        if any(not math.isfinite(diagnostic[name]) or diagnostic[name] < 0 for name in
               ("solver_seconds", "label_conversion_seconds", "objective_evaluation_seconds")) or not math.isfinite(diagnostic["modularity"]):
            raise ArithmeticError("unchanged solver returned a nonfinite Q/timer diagnostic")
        # The entire unchanged interface (including its diagnostics) is primary.
        record["nested_source_diagnostics"] = diagnostic
    progress["phase"] = "seed_lift_exact_validate"
    with ledger.measure("seed_lift_exact_validate", arm=arm, seed=seed):
        raw_labels = integer_labels(raw_labels, state.objective.n)
        lifted = tuple(raw_labels[v] for v in state.membership)
        raw_q = integer_modularity(context.objective, lifted, gamma)
        quotient_q = raw_q if arm == "U" else integer_modularity(state.objective, raw_labels, gamma)
        if quotient_q != raw_q:
            raise ArithmeticError("raw exact quotient-Q differs from independently lifted original-Q")
        record.update(raw_solver_labels=list(raw_labels), raw_original_labels=list(lifted),
                      raw_original_Q_exact=rational_record(raw_q), raw_quotient_Q_exact=rational_record(quotient_q),
                      exact_raw_quotient_original_equality_verified=True,
                      raw_solver_float_Q_diagnostic=float(diagnostic["modularity"]))
    progress["phase"] = "seed_select_materialize"
    with ledger.measure("seed_select_materialize", arm=arm, seed=seed):
        selected = select_external_incumbent(bank.discovery_labels, discovery_q, lifted, raw_q, seed)
        if len(selected["returned_original_labels"]) != context.objective.n:
            raise ArithmeticError("materialized selected partition does not cover the original graph")
        record.update(selected)
        record.update(status="completed", control_kind="discovery-incumbent control",
                      louvain_initial_partition_supplied=False)
    return record


def finalize_prefix(bank, state, discovery_q, prefix):
    if prefix not in PREFIXES or len(state.seed_results) != 9:
        raise ValueError("prefix finalization requires all nine fixed seed records")
    best_q, winner = discovery_q, None
    for record in state.seed_results[:prefix]:
        if record["status"] != "completed":
            raise ValueError("a failed seed cannot produce a successful prefix")
        value = rational_value(record["raw_original_Q_exact"])
        if value > best_q:
            best_q, winner = value, record
    labels = bank.discovery_labels if winner is None else winner["raw_original_labels"]
    labels = list(integer_labels(labels, len(bank.discovery_labels)))
    fallback_count = sum(record["discovery_fallback"] for record in state.seed_results[:prefix])
    return {"arm": state.arm, "prefix": prefix, "status": "completed", "returned_Q_exact": rational_record(best_q),
            "returned_original_labels": labels, "winner_kind": "discovery" if winner is None else "downstream_seed",
            "winner_seed": None if winner is None else winner["seed"],
            "raw_seed_Q_exact": [record["raw_original_Q_exact"] for record in state.seed_results[:prefix]],
            "fallback_count": fallback_count, "fallback_frequency": fallback_count / prefix,
            "prefixes_are_correlated_summaries_of_one_nine_seed_execution": True}


def run_case(case, context, bank, setup_record, identity, *, progress=None, clock=time.perf_counter,
             event_callback=None):
    if not gc.isenabled():
        raise RuntimeError("the frozen normal enabled GC policy is required")
    progress = {} if progress is None else progress
    physical_started = clock()
    ledger = PhaseLedger(clock)
    # These are measured setup intervals, physically shared but attributed once
    # in each single-gamma workload. Their domain remains the immutable setup.
    ledger.records.extend(dict(row) for row in setup_record["primary_phase_records"])
    record = {"schema_version": SCHEMA, "extension": "public_pipelines_v2", "status": "started",
              **case.record(), **identity, "started_at_utc": utc_now(), "setup_reference": setup_record["identity"],
              "preprocessing_order": list(preprocessing_order(case.ordinal)),
              "downstream_order": [{"seed": seed, "arms": list(seed_arm_order(case.ordinal, r))}
                                   for r, seed in enumerate(DOWNSTREAM_SEEDS)],
              "arms": {}, "primary_phase_records": ledger.records,
              "per_arm_peak_memory": "not_measured", "gc_policy": "normal_enabled_no_manual_collect",
              "object_retention": "all four arm states and raw label vectors retained through case finalization"}
    progress["raw_record"] = record
    states = {}
    progress["phase"] = "common_discovery_evaluate"
    with ledger.measure("common_discovery_evaluate"):
        discovery_q = integer_modularity(context.objective, bank.discovery_labels, case.gamma)
        record["discovery_original_Q_exact"] = rational_record(discovery_q)
        record["original_vertices"] = context.objective.n
    for arm in preprocessing_order(case.ordinal):
        progress.update(phase="arm_preparation", arm=arm, seed=None)
        partial_provenance = {}
        record["arms"][arm] = {"status": "started", "provenance": partial_provenance,
                              "seed_results": [], "prefixes": []}
        state = prepare_arm(context, bank, case.gamma, arm, ledger, partial_provenance=partial_provenance)
        states[arm] = state
        record["arms"][arm] = {"status": "prepared", "provenance": state.provenance,
                              "seed_results": state.seed_results, "prefixes": state.prefixes}
        if event_callback:
            event_callback({"phase": "arm_prepared", "arm": arm, "remaining_vertices": state.objective.n})
    progress["phase"] = "r_prefix_cross_arm_validate"
    validate_r_prefixes(states, ledger)
    for r, seed in enumerate(DOWNSTREAM_SEEDS):
        for arm in seed_arm_order(case.ordinal, r):
            run_seed(context, bank, states[arm], case.gamma, seed, discovery_q, ledger, progress=progress)
            if event_callback:
                event_callback({"phase": "seed_completed", "arm": arm, "seed": seed})
    # Fixed arm/prefix order, after all seeds; finalization never adds a solve.
    for arm in ARMS:
        for prefix in PREFIXES:
            progress.update(phase="prefix_finalize", arm=arm, seed=None, prefix=prefix)
            with ledger.measure("prefix_finalize", arm=arm, prefix=prefix):
                value = finalize_prefix(bank, states[arm], discovery_q, prefix)
                states[arm].prefixes.append(value)
        record["arms"][arm]["status"] = "completed"
    physical_compute_finished = clock()
    reporting_started = clock()
    for arm in ARMS:
        for result in states[arm].prefixes:
            result["cost"] = standalone_cost(ledger, arm, result["prefix"], DOWNSTREAM_SEEDS)
    for row in ledger.records:
        row.setdefault("interval_domain", case.key)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = int(peak if sys.platform == "darwin" else peak * 1024)
    record.update(status="completed", completed_at_utc=utc_now(),
                  whole_case_peak_RSS={"bytes": peak_bytes, "source": "ru_maxrss", "platform": sys.platform,
                                       "meaning": "monotone process peak including retained setup/arm/raw-label objects"},
                  physical_case_elapsed_seconds_excluding_shared_setup=physical_compute_finished - physical_started,
                  shared_setup_physical_elapsed_seconds=setup_record["physical_setup_elapsed_seconds"],
                  reporting_only_seconds=clock() - reporting_started,
                  scheduled_solver_calls=36, completed_solver_calls=36, prefix_summary_count=12)
    return record
