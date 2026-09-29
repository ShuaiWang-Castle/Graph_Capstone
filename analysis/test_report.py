"""Tiny schema fixtures, not experiments or evidence about any method.

No numerical runtime is imported. These may run during an approved quiet
engineering window; they never aggregate a partial empirical suite:
    python -m unittest analysis.test_report
"""
from __future__ import annotations

import copy
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analysis.report import (AnalysisError, IncompleteSuiteError, _bank_identity,
    _full_native, _full_original_feasible_Q, _oracle_row, _production_size_mechanism, analyze, audit_suite, expanded_native_groups,
    expected_jobs, generate_report)


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unavailable(reason):
    return {"status": "unavailable", "verification_status": reason, "available": False,
            "certified": False, "strict": False}


def reduction(groups=()):
    groups = [list(g) for g in groups]
    removed = sum(len(group) - 1 for group in groups)
    return {"original_vertices": 4, "remaining_vertices": 4 - removed,
            "removed_vertices": removed, "removed_fraction": removed / 4,
            "original_off_diagonal_edges": 2, "remaining_off_diagonal_edges": 2,
            "merge_groups": groups, "largest_component_under_original_objective": {
                "vertices": 3, "removed_vertices": removed, "removed_fraction": removed / 3}}


def baseline(method):
    result = {"status": "completed", "strict": method != "degree_proportional_twins",
        "checker_seconds": .125, "quotient_seconds": .25, "decision_count": 0,
        "criterion": method, "algorithm_scope": "engineering fixture only", "decisions": [],
        "reduction": reduction(), "new_identifications_beyond_baseline": 1,
        "baseline_identifications_beyond_new": 0}
    if method == "recursive_cheap":
        result["result"] = {"removed_vertices": 0, "strict": True, "round_count": 1,
                            "merge_round_count": 0, "status": "fixed_point", "metadata": {}}
    return result


def block_methods(config):
    methods = {}
    all_methods = config["supplied_block_methods"] + ["degree_median_forced_exact",
        "degree_median_independent_exact", "bocker_almost_clique_weak_side"]
    for method in all_methods:
        certified = method != "degree_median"
        methods[method] = {"checker_seconds": .125, "result": {"block": [0, 1],
            "available": True, "certified": certified, "strict": certified,
            "verification_status": "exact_positive" if certified else "float_screen_rejected",
            "comparison_role": "engineering fixture only"}}
    return methods


def csub_unresolved():
    return {"status": "unresolved", "available": False, "certified": False, "strict": False,
        "checker_seconds": .25, "tie_policy": "isolation_score equals optimum including ties",
        "attempts": [{"arithmetic": "exact", "result": {"status": "unavailable", "certified": False,
            "active_vertices": [], "isolation_score": None, "optimum": None, "oracle": None}},
            {"arithmetic": "numerical", "result": {"status": "unresolved", "certified": False,
             "active_vertices": [0, 1, 2], "isolation_score": .5, "optimum": None,
             "oracle": {"status": 1, "upper_bound": "inf"}, "message": "fixture time guard"}}]}


def fixture(project: Path) -> tuple[Path, dict]:
    """One graph schema, three discovery seeds, one computation-only control."""
    control = {"case_id": "controlled-000-profile_scaling", "family": "profile_scaling",
        "parameters": {"k": 2, "outside_vertices": 2, "hub_size": 0, "core_weight": 1,
                       "attachment_weight": 1, "outside_weight": 1},
        "gamma": ["1"], "role": "engineering_fixture", "native_preprocessing": False,
        "candidate_bank_seed": 0, "supplied_block_comparison": True, "candidate_bank_evaluation": False}
    config = {"public_datasets": ["fixture"], "development_datasets": [], "proposal": {"seeds": [0, 1, 2]},
        "gamma": ["1"], "controlled_cases": [control], "threads": {"OMP_NUM_THREADS": "1"},
        "global_baselines": ["singleton_dominance", "positive_closure_edge", "degree_proportional_twins"],
        "public_supplied_baselines": ["bocker_almost_clique_strict"],
        "supplied_block_config": {"development_bank_seed": 0},
        "supplied_block_methods": ["degree_median", "degree_zero", "degree_anchor", "degree_full_pair", "uniform_copy", "lange_positive_closure_star", "bocker_almost_clique"],
        "scaling": {"methods": ["degree_median", "degree_full_pair", "dense_exterior_diagnostic"], "replicate_count": 3, "memory_replicate_count": 1},
        "downstream": {"seeds": [10, 11, 12], "workload_prefixes": [1, 3]}}
    write(project / "experiments/config.json", config)
    (project / "experiments/source.py").write_text("# schema-only engineering fixture\n")
    write(project / "data/registry.json", {"fixture": {"sha256": "archive-fixture"}})
    versions = {"python": "fixture", "numpy": "fixture", "scipy": "fixture", "networkx": "fixture"}
    freeze = {"status": "frozen_after_independent_design_review", "config_sha256": sha(project / "experiments/config.json"),
        "runtime_source_sha256": {"experiments/source.py": sha(project / "experiments/source.py")},
        "data_registry_sha256": sha(project / "data/registry.json"), "versions": versions,
        "hardware": {"platform": "fixture", "machine": "fixture"}, "source_commit": "fixture"}
    write(project / "experiments/freeze.json", freeze)
    run_dir = project / "run"
    run_dir.mkdir()
    manifest = {"status": "launched", "suites": ["public", "controls", "scaling"], "config": config, "freeze": freeze,
        "config_sha256": freeze["config_sha256"], "freeze_sha256": sha(project / "experiments/freeze.json")}
    write(run_dir / "run-manifest.json", manifest)
    provenance = {"config_sha256": manifest["config_sha256"], "freeze_sha256": manifest["freeze_sha256"],
        "runtime_source_sha256": freeze["runtime_source_sha256"], "versions": versions,
        "platform": "fixture", "machine": "fixture", "thread_environment": config["threads"]}
    dataset = {"name": "fixture", "n": 4, "m": 2, "isolates": 1, "components": 2,
               "largest_component_n": 3, "raw_sha256": "archive-fixture"}
    blocks = [[0, 1], [0, 1, 2]]
    bank_sha = _bank_identity(blocks)
    certs = [{"block": blocks[0], "size": 2, "certified": True, "strict": True, "verification_status": "exact_positive"},
             {"block": blocks[1], "size": 3, "certified": False, "strict": False, "verification_status": "exact_size_limit_preassembly"}]
    outcomes, events = [], []
    for job in expected_jobs(config, manifest["suites"]):
        outcome = {"event": "completed", "job": job.name, "exit_code": 0, "seconds": 1,
                   "log": f"{job.name}.log", "utc": "fixture"}
        outcomes.append(outcome)
        events.extend([{"event": "started", "job": job.name, "utc": "fixture"}, outcome])
        (run_dir / outcome["log"]).write_text("schema-only fixture, no experiment\n")
        if job.stratum == "public":
            started = {**provenance, "dataset": "fixture", "proposal_seed": job.seed}
            write(run_dir / f"{job.prefix}-started.json", started)
            write(run_dir / f"{job.prefix}-candidates.json.gz", {"seed": job.seed, "bank_sha256": bank_sha,
                "blocks": blocks, "discovery_labels": [0, 0, 0, 1], "dataset": dataset})
            pairs = []
            for seed in config["downstream"]["seeds"]:
                arm = {"seed": seed, "solver_seconds": 1, "label_conversion_seconds": .25,
                       "objective_evaluation_seconds": .25, "modularity": .5,
                       "labels": [0, 0, 0, 1], "best_of_discovery_and_downstream": .5}
                reduced = {**arm, "solver_seconds": .5, "modularity": .375,
                           "modularity_lifted": .375, "lift_and_original_evaluation_seconds": .25,
                           "best_of_discovery_and_downstream": .375}
                pairs.append({"seed": seed, "execution_order": ["unreduced", "reduced"], "unreduced": arm, "reduced": reduced})
            # Synthetic seed-varying checker time exercises median/range and
            # independently stored amortization formulas, never performance.
            checker_seconds = .5 + job.seed/8
            preprocessing_seconds = 2.5 + job.seed/8
            workloads = [{"solves": count, "unreduced_seconds": 1.5*count,
                "discovery_plus_unreduced_seconds": .75+1.5*count, "full_reduced_seconds": preprocessing_seconds+1.25*count,
                "speedup_vs_cold_unreduced": 1.5*count/(preprocessing_seconds+1.25*count),
                "speedup_vs_discovery_control": (.75+1.5*count)/(preprocessing_seconds+1.25*count)} for count in (1, 3)]
            methods = config["global_baselines"] + config["public_supplied_baselines"] + ["recursive_cheap"]
            raw = {"status": "completed", "dataset": dataset, "proposal_seed": job.seed, "gamma": "1",
                "bank_sha256": bank_sha, "graph_fingerprint": "fixture", "candidate_certificates": certs,
                "certification_status_counts": {"exact_positive": 1, "exact_size_limit_preassembly": 1},
                "reduction": reduction([[0, 1]]), "global_baselines": {method: baseline(method) for method in methods},
                "graph_loading_seconds": .5, "preparation_seconds": .25, "proposal_seconds": .5,
                "refinement_seconds": .25, "checker_seconds": checker_seconds, "quotient_seconds": .25,
                "quotient_conversion_seconds": .25, "discovery_incumbent_seconds": .5,
                "original_discovery_evaluation_seconds": .25, "quotient_discovery_evaluation_seconds": .25,
                "preprocessing_seconds": preprocessing_seconds, "modularity_discovery": .25, "downstream": pairs, "workloads": workloads,
                "peak_case_process_RSS_bytes": 1000, "timing_scope": "fixture", "memory_semantics": "fixture"}
            write(run_dir / f"{job.prefix}-gamma0.json.gz", raw)
            write(run_dir / f"{job.prefix}-completed.json", {"status": "completed"})
        elif job.stratum == "controlled":
            started = {**provenance, "stratum": "controlled", "case_id": control["case_id"], "specification": control}
            meta = {**dataset, "name": "profile_scaling", "family": "profile_scaling", "generation_parameters": control["parameters"]}
            write(run_dir / f"{job.prefix}-started.json", started)
            input_record = {"provenance": started, "dataset": meta, "graph_fingerprint": "fixture", "bank_sha256": None,
                "graph_loading_seconds": .5, "graph_preparation_seconds": .25, "candidate_bank": None,
                "bank_status": "skipped_predeclared_profile_computation_only", "supplied_blocks": [[0, 1]],
                "baseline_preparation": {"integer_baseline_preparation_seconds": .125,
                    "weighted_reference_preparation_seconds": .125, "weighted_reference_available": True}}
            write(run_dir / f"{job.prefix}-input.json.gz", input_record)
            raw = {"status": "completed", "provenance": started, "dataset": meta, "gamma_exact": "1",
                "graph_fingerprint": "fixture", "bank_sha256": None,
                "production_independent_bank": unavailable("predeclared_computation_only_bank_skip"),
                "global_baselines": {method: baseline(method) for method in config["global_baselines"]},
                "same_bank_criterion_comparison": [], "controlled_supplied_block_comparison": [{
                    "block": [0, 1], "block_source": "controlled generator optional reference",
                    "methods": block_methods(config), "c_subinstance": csub_unresolved()}],
                "native_weighted_preprocessing": unavailable("not_predeclared_for_case"),
                "native_full_solver": unavailable("not_predeclared_for_case"), "numerical_modularity_milp": None,
                "gamma_compute_seconds": .5, "peak_case_process_RSS_bytes": 1000, "performance_scope": "fixture"}
            write(run_dir / f"{job.prefix}-gamma0.json.gz", raw)
            write(run_dir / f"{job.prefix}-completed.json", {"status": "completed", "provenance": started})
        else:
            checker_time = 1000 if job.measurement == "memory" else job.replicate+1
            result = {"certified": job.method != "dense_exterior_diagnostic", "strict": True, "status": "fixture"}
            if job.method == "degree_median":
                result["metadata"] = {"exterior_assembly_seconds": checker_time/4,
                    "dense_eigensolve_seconds": checker_time/8, "exact_verification_seconds": checker_time/8}
            elif job.method == "degree_full_pair":
                result["metadata"] = {"assembly_seconds": checker_time/2, "verification_seconds": checker_time/8}
            else:
                result["metadata"] = {"dense_exterior_assembly_seconds": checker_time/2,
                    "dense_exterior_shape": [2, 2], "dense_exterior_payload_bytes": 32}
                result["assembly_seconds"] = checker_time/2
            write(run_dir / f"{job.name}.json.gz", {"status": "completed", "case_id": control["case_id"],
                "method": job.method, "replicate": job.replicate, "measurement": job.measurement, "gamma": "1",
                "dataset": {**dataset, "family": "profile_scaling", "generation_parameters": control["parameters"]},
                "provenance": provenance, "checker_result": result, "loading_seconds": .5, "preparation_seconds": .25,
                "checker_seconds": checker_time, "checker_traced_current_bytes": 10 if job.measurement == "memory" else None,
                "checker_traced_peak_bytes": 20 if job.measurement == "memory" else None,
                "process_peak_RSS_before_checker_bytes": 900, "process_peak_RSS_bytes": 1000,
                "timing_semantics": "memory time excluded", "memory_semantics": "includes graph preparation"})
    write(run_dir / "run-completed.json", {"status": "completed", "outcomes": outcomes, "not_launched_due_failure": []})
    (run_dir / "orchestration.jsonl").write_text("".join(json.dumps(item)+"\n" for item in events))
    return run_dir, config


def recovery_fixture(project: Path, *, bank_mismatch=False, unexpected_failure=False) -> dict:
    """Seventeen schema-only logical jobs, eighteen actual source attempts.

    The fake native artifact copies the reviewed allowlist fields; fake binary
    hashes are explicitly patched by tests. No solver or graph is executed.
    Preserved failure precedes the five timing fields exactly as in run_controls.
    """
    from analysis import collect_recovery as collector
    parent, config = fixture(project)
    config["development_datasets"] = ["davis"]
    config["gamma"] = ["1/2", "1", "2"]
    write(project/"experiments/config.json", config)
    binary = project/"research/full_kapoce/build/kapoce_full"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"non-executable schema fixture binary\n")
    write(project/"research/full_kapoce/build-provenance.json", {"scope": "fixture"})
    binary_sha, build_sha = sha(binary), sha(project/"research/full_kapoce/build-provenance.json")
    freeze = json.loads((project/"experiments/freeze.json").read_text())
    freeze["config_sha256"] = sha(project/"experiments/config.json")
    freeze["runtime_source_sha256"].update({"research/full_kapoce/build/kapoce_full": binary_sha,
        "research/full_kapoce/build-provenance.json": build_sha})
    write(project/"experiments/freeze.json", freeze)
    manifest = {"status": "launched", "suites": ["public", "controls", "scaling"],
        "config": config, "freeze": freeze, "config_sha256": freeze["config_sha256"],
        "freeze_sha256": sha(project/"experiments/freeze.json")}
    provenance = {"config_sha256": manifest["config_sha256"], "freeze_sha256": manifest["freeze_sha256"],
        "runtime_source_sha256": freeze["runtime_source_sha256"], "versions": freeze["versions"],
        "platform": "fixture", "machine": "fixture", "thread_environment": config["threads"]}
    # Refresh base provenance and expand the public gamma schema after config
    # change, before prospective freezes exist. This is fixture construction.
    for path in list(parent.iterdir()):
        if not path.name.endswith((".json", ".json.gz")) or path.name.startswith("run-"):
            continue
        value = json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())
        if "runtime_source_sha256" in value:
            value.update(provenance)
        if "provenance" in value:
            value["provenance"].update(provenance)
        write(path, value)
    for seed in config["proposal"]["seeds"]:
        raw = json.loads(gzip.decompress((parent/f"fixture-proposal{seed}-gamma0.json.gz").read_bytes()))
        for index, gamma in enumerate(config["gamma"]):
            value = copy.deepcopy(raw)
            value["gamma"] = str(Fraction(gamma))
            write(parent/f"fixture-proposal{seed}-gamma{index}.json.gz", value)
    jobs = expected_jobs(config, manifest["suites"])
    failed_index = [job.name for job in jobs].index("development-davis")
    recovery = project/"recovery"
    recovery.mkdir()
    collection = project/"analysis/collections/recovered-fixture"
    spec = {"case_id": "davis", "role": "development", "candidate_bank_seed": 0,
            "gamma": config["gamma"], "native_preprocessing": True}
    started = {**provenance, "stratum": "development", "case_id": "davis", "specification": spec}
    dataset = {"name": "davis", "family": "davis", "n": 32, "m": 89, "isolates": 0,
               "components": 1, "largest_component_n": 32, "raw_sha256": "fixture-davis"}
    blocks = [[0, 1], [0, 1, 2]]
    bank = {"blocks": blocks, "seed": 0, "discovery_labels": [0]*32,
            "proposal_seconds": .5, "refinement_seconds": .25}
    input_record = {"provenance": started, "dataset": dataset, "graph_fingerprint": "fixture-davis",
        "graph_content_sha256": "fixture-davis-content", "bank_sha256": _bank_identity(blocks),
        "graph_loading_seconds": .5, "graph_preparation_seconds": .25, "candidate_bank": bank,
        "bank_status": "completed", "supplied_blocks": [], "baseline_preparation": {
            "integer_baseline_preparation_seconds": .125, "weighted_reference_preparation_seconds": .125,
            "weighted_reference_available": True}}
    def davis_reduction(groups=()):
        groups = list(map(list, groups))
        removed = sum(len(group)-1 for group in groups)
        return {"original_vertices": 32, "remaining_vertices": 32-removed, "removed_vertices": removed,
            "removed_fraction": removed/32, "merge_groups": groups, "original_off_diagonal_edges": 89,
            "remaining_off_diagonal_edges": 89, "largest_component_under_original_objective": {
                "vertices": 32, "removed_vertices": removed, "removed_fraction": removed/32}}
    Q = "-106/7921"
    def native_core(index):
        arms = {}
        for name in ("unreduced", "reduced"):
            arm = {"status": "failed" if index == 2 else "optimal", "case_name": f"development-davis-gamma{index}-{name}",
                "binary_sha256": binary_sha, "build_provenance_sha256": build_sha,
                "full_solver_entry_called": True, "full_kapoce_solver": True,
                "incumbent_Q_original_exact": Q, "incumbent": {"Q": Q, "verified_independently": True},
                "runner_wall_seconds": 1, "native_process_wall_seconds": .75, "timeout_seconds": 30,
                "conversion": {"input_sha256": collector.INPUT_SHA, "gamma": str(Fraction(config["gamma"][index])),
                    "volume": 178, "degrees": [1]*32, "integer_divisor": 2, "max_absolute_pair_cost": 168,
                    "sum_absolute_pair_costs": 15172, "budget": 3419, "incumbent_Q": Q},
                "native": {"exit_code": -6 if index == 2 else 0, "outer_timeout_triggered": False,
                    "stderr": collector.STDERR if index == 2 else "",
                    "events": [{"event": event} for event in ("input_accepted", "initial_bound", "full_solve_entered")]},
                # Deliberately present on a failed record: reporting must suppress
                # these bounds rather than interpret initial search output.
                "bounds": {"Q_lower_bound": Q, "Q_upper_bound": "1"}}
            if index != 2:
                arm.update(optimality_proved=True, solution={"Q": Q}, lifted_Q_original_exact=Q,
                           bounds={"Q_lower_bound": Q, "Q_upper_bound": Q})
            arms[name] = arm
        return {"paired_arms": arms, "records": list(arms.values()), "execution_order": ["unreduced", "reduced"],
            "same_feasible_incumbent_Q_exact": Q, "quotient_incumbent_alignment_seconds": .25,
            "original_incumbent_evaluation_seconds": .5}
    core_failed = native_core(2)
    # Original failure wrapper and partial gamma records are retained but are
    # never primary selected artifacts. Their timing differs from recovery.
    for run in (parent, recovery):
        write(run/"development-davis-started.json", started)
        current_input = copy.deepcopy(input_record)
        if run == parent:
            current_input["graph_loading_seconds"] = 99
            current_input["candidate_bank"]["proposal_seconds"] = 99
            if bank_mismatch:
                current_input["candidate_bank"]["discovery_labels"][0] = 1
        write(run/"development-davis-input.json.gz", current_input)
        write(run/"development-davis-gamma2-full-solver-failed.json", {"status": "failed", "method": "full-solver", "native_record": core_failed})
    for index, gamma in enumerate(config["gamma"]):
        certificates = [{"block": blocks[0], "size": 2, "certified": True, "strict": True, "verification_status": "exact_positive"},
            {"block": blocks[1], "size": 3, "certified": False, "strict": False, "verification_status": "exact_size_limit_preassembly"}]
        primary = {"status": "completed", "reduction": davis_reduction([[0, 1]]),
            "candidate_certificates": certificates, "certification_status_counts": {"exact_positive": 1, "exact_size_limit_preassembly": 1},
            "modularity_discovery_exact": Q, "modularity_discovery_quotient_exact": Q, "checker_seconds": .5, "quotient_seconds": .25}
        comparisons = []
        for block in blocks:
            methods = block_methods(config)
            methods.pop("bocker_almost_clique_weak_side")
            for item in methods.values():
                item["result"]["block"] = block
            comparisons.append({"block": block, "methods": methods, "c_subinstance": csub_unresolved()})
        baselines = {method: baseline(method) for method in [*config["global_baselines"], "recursive_cheap"]}
        for item in baselines.values():
            item["reduction"] = davis_reduction()
        native = native_core(index)
        native.update(shared_graph_preparation_seconds=.25, shared_discovery_seconds=.5,
            reduced_additional_preprocessing_seconds=1.25,
            matched_pipeline_seconds={"unreduced": 2.25, "reduced": 3.5},
            pipeline_scope="prepared in-memory graph, discovery incumbent, optional refinement/certification/quotient, input conversion, complete solver, independent validation; shared raw loading and report panels excluded")
        raw = {"status": "completed", "provenance": started, "dataset": dataset, "gamma_exact": str(Fraction(gamma)),
            "graph_fingerprint": "fixture-davis", "bank_sha256": input_record["bank_sha256"],
            "production_independent_bank": primary, "global_baselines": baselines,
            "same_bank_criterion_comparison": comparisons, "controlled_supplied_block_comparison": [],
            "native_weighted_preprocessing": unavailable("fixture_domain_exclusion"), "native_full_solver": native,
            "numerical_modularity_milp": None, "gamma_compute_seconds": .5,
            "peak_case_process_RSS_bytes": 1000, "performance_scope": "schema fixture only"}
        if unexpected_failure and index == 0:
            raw["native_weighted_preprocessing"]["status"] = "failed"
        write(recovery/f"development-davis-gamma{index}.json.gz", raw)
        if index < 2:
            old_raw = copy.deepcopy(raw)
            old_raw["gamma_compute_seconds"] = 99
            write(parent/f"development-davis-gamma{index}.json.gz", old_raw)
    write(recovery/"development-davis-completed.json", {"status": "completed", "provenance": started})
    old_outcomes, new_outcomes = [], []
    old_events, new_events = [], []
    for index, job in enumerate(jobs):
        if index < failed_index:
            run = parent
        else:
            run = recovery
            if job.stratum == "scaling":
                for filename in job.required_artifacts():
                    (run/filename).write_bytes((parent/filename).read_bytes())
                    (parent/filename).unlink()
        terminal = {"event": "completed", "job": job.name, "exit_code": 0, "seconds": 1,
                    "log": f"{job.name}.log", "utc": "fixture"}
        (run/terminal["log"]).write_text("schema-only process log\n")
        if index < failed_index:
            old_outcomes.append(terminal)
            old_events.extend([{ "event": "started", "job": job.name, "utc": "fixture"}, terminal])
        else:
            new_outcomes.append(terminal)
            new_events.extend([{ "event": "started", "job": job.name, "utc": "fixture"}, terminal])
        if index == failed_index:
            failed = {**terminal, "event": "failed", "exit_code": 1}
            (parent/failed["log"]).write_text("schema-only preserved failure log\n")
            old_outcomes.append(failed)
            old_events.extend([{ "event": "started", "job": job.name, "utc": "fixture"}, failed,
                               {"event": "halted_for_repair", "trigger_job": job.name, "utc": "fixture"}])
    # Remove old fixture scaling logs too: parent launch halted before scalers.
    for job in jobs[failed_index+1:]:
        (parent/f"{job.name}.log").unlink(missing_ok=True)
    write(parent/"run-manifest.json", manifest)
    write(parent/"run-completed.json", {"status": "halted_for_repair", "outcomes": old_outcomes,
        "not_launched_due_failure": [job.name for job in jobs[failed_index+1:]]})
    (parent/"orchestration.jsonl").write_text("".join(json.dumps(item)+"\n" for item in old_events))
    # Freeze maps deliberately separate unchanged numerical runtime, the five
    # recovery overlay sources, and the three analysis/selection sources.
    overlay = {}
    for filename in ("__init__.py", "policy.py", "run_case.py", "run_remaining.py", "prepare_freeze.py"):
        source = project/f"experiments/recovery/{filename}"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# fixture recovery source, never executed\n")
        overlay[source.relative_to(project).as_posix()] = sha(source)
    source_root = Path(__file__).resolve().parent
    analysis_sources = {}
    for filename in ("collect_recovery.py", "report.py", "test_report.py"):
        source = project/f"analysis/{filename}"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes((source_root/filename).read_bytes())
        analysis_sources[source.relative_to(project).as_posix()] = sha(source)
    evidence = project/"research/full_kapoce/incidents/davis-gamma2/report.md"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("schema-only independently reviewed incident evidence fixture\n")
    incident = {evidence.relative_to(project).as_posix(): sha(evidence)}
    choices = [{"job": job.name, "source_job": job.name, "source_role": "parent" if index < failed_index else "recovery",
                "source_run_dir": "run" if index < failed_index else "recovery"} for index, job in enumerate(jobs)]
    selection = {"kind": "prospective_fixed_recovery_selection", "logical_jobs": choices,
        "logical_job_count": len(jobs), "orchestration_attempt_count_if_complete": len(jobs)+1,
        "parent_run_dir": "run", "recovery_run_dir": "recovery", "collection_dir": "analysis/collections/recovered-fixture",
        "base_config_sha256": manifest["config_sha256"], "base_freeze_sha256": manifest["freeze_sha256"],
        "process_completion_is_native_solver_success": False}
    write(project/"experiments/recovery/collection-selection-plan.json", selection)
    write(project/"experiments/recovery/engineering-validation.json", {"status": "passed", "source_sha256": overlay})
    review = {"status": collector.REVIEW_STATUS, "overlay_runtime_source_sha256": overlay,
        "collection_analysis_source_sha256": analysis_sources, "incident_evidence_sha256": incident,
        "selection_plan_sha256": sha(project/"experiments/recovery/collection-selection-plan.json"),
        "engineering_validation_sha256": sha(project/"experiments/recovery/engineering-validation.json")}
    write(project/"reviews/native-incident-recovery-review.json", review)
    recovery_freeze = {"status": collector.RECOVERY_STATUS, "original_config_path": "experiments/config.json",
        "original_freeze_path": "experiments/freeze.json", "original_freeze_sha256": manifest["freeze_sha256"],
        "parent_run_dir": "run", "planned_recovery_run_dir": "recovery", "planned_collection_dir": selection["collection_dir"],
        "overlay_runtime_source_sha256": overlay, "collection_analysis_source_sha256": analysis_sources,
        "incident_evidence_sha256": incident,
        "parent_artifact_sha256": {path.relative_to(project).as_posix(): sha(path) for path in parent.iterdir() if path.is_file()},
        "selection_plan_path": "experiments/recovery/collection-selection-plan.json", "selection_plan_sha256": review["selection_plan_sha256"],
        "engineering_validation_path": "experiments/recovery/engineering-validation.json", "engineering_validation_sha256": review["engineering_validation_sha256"],
        "review_path": "reviews/native-incident-recovery-review.json", "review_sha256": sha(project/"reviews/native-incident-recovery-review.json"),
        "scheduled_jobs": [job.name for job in jobs[failed_index:]], "logical_job_count": len(jobs),
        "orchestration_attempt_count_if_complete": len(jobs)+1}
    write(project/"experiments/recovery/freeze.json", recovery_freeze)
    recovery_sha = sha(project/"experiments/recovery/freeze.json")
    recovered_manifest = {**manifest, "status": "launched_recovery", "recovery": recovery_freeze,
        "recovery_freeze_sha256": recovery_sha, "scheduled_jobs": recovery_freeze["scheduled_jobs"],
        "parent_run_dir": "run", "parent_manifest_sha256": sha(parent/"run-manifest.json")}
    write(recovery/"run-manifest.json", recovered_manifest)
    write(recovery/"run-completed.json", {"status": collector.RECOVERY_COMPLETE, "outcomes": new_outcomes,
        "not_launched_due_failure": [], "process_completion_is_native_solver_success": False})
    (recovery/"orchestration.jsonl").write_text("".join(json.dumps(item)+"\n" for item in new_events))
    for job in jobs[failed_index:]:
        write(recovery/f"{job.name}-recovery-job-provenance.json", {"job": job.name,
            "overlay_applied_to_case_runtime": job.name == "development-davis", "base_freeze_sha256": manifest["freeze_sha256"],
            "recovery_freeze_sha256": recovery_sha, "overlay_runtime_source_sha256": overlay, "review_sha256": recovery_freeze["review_sha256"]})
    write(recovery/"development-davis-recovery-provenance.json", {"case": "development-davis", "overlay_applied": True,
        "config_sha256": manifest["config_sha256"], "base_freeze_sha256": manifest["freeze_sha256"],
        "recovery_freeze_sha256": recovery_sha, "overlay_runtime_source_sha256": overlay, "review_sha256": recovery_freeze["review_sha256"]})
    write(recovery/"development-davis-gamma2-reviewed-incident.json", {"status": "known_native_failure_preserved_not_solver_success",
        "prefix": "development-davis", "gamma_index": 2, "method": "full-solver", "native_status_retained": "failed",
        "recovery_freeze_sha256": recovery_sha, "failed_artifact": "development-davis-gamma2-full-solver-failed.json",
        "failed_artifact_sha256": sha(recovery/"development-davis-gamma2-full-solver-failed.json"),
        "input_sha256": collector.INPUT_SHA, "binary_sha256": binary_sha, "excluded_inferences": collector.EXCLUSIONS,
        "retained_inference": "independently verified feasible supplied incumbent only"})
    return {"parent": parent, "recovery": recovery, "collection": collection, "count": len(jobs),
            "binary_sha": binary_sha, "build_sha": build_sha}


class AnalysisFixtureTests(unittest.TestCase):
    def setUp(self):
        # All temporary engineering artifacts stay within this assigned tree.
        self.temporary = tempfile.TemporaryDirectory(prefix=".engineering-", dir=Path(__file__).resolve().parent)
        self.project = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_incomplete_refused_before_reading_measurements_or_writing(self):
        run = self.project / "run"
        run.mkdir()
        (run / "bogus-gamma0.json.gz").write_bytes(b"not gzip")
        with self.assertRaises(IncompleteSuiteError):
            generate_report(run, self.project / "output", project_root=self.project)
        self.assertFalse((self.project / "output").exists())

    def test_complete_fixture_is_deterministic_and_separates_memory_time(self):
        run, config = fixture(self.project)
        summary, tables = analyze(run, project_root=self.project, expected_job_count=16)
        self.assertEqual(summary["completed_processes"], 16)
        self.assertEqual(summary["controls"]["auto_vs_forced_exact"]["exact_accepts_auto_rejects"], 1)
        self.assertEqual(summary["controls"]["c_subinstance_status_counts_by_arithmetic"]["numerical"], {"unresolved": 1})
        coverage = tables["public_aggregate_rows"][0]
        self.assertEqual(coverage["removed_fraction_positive_degree_median"], 1/3)
        self.assertEqual(coverage["removed_fraction_all_median"], 1/4)
        self.assertEqual(coverage["checker_seconds_median"], .625)
        self.assertEqual(coverage["checker_seconds_min"], .5)
        self.assertEqual(coverage["checker_seconds_max"], .75)
        self.assertEqual(coverage["accepted_pair_blocks_median"], 1)
        self.assertEqual(coverage["accepted_collective_blocks_median"], 0)
        self.assertEqual(coverage["pair_only_removed_vertices_median"], 1)
        self.assertEqual(coverage["collective_additions_beyond_accepted_production_pairs_median"], 0)
        self.assertNotIn("accepted_pair_blocks", tables["control_production_rows"][0])
        self.assertTrue(all(row["unprofiled_checker_seconds_median"] == 2 for row in tables["scaling_aggregate_rows"]))
        median_scaling = next(row for row in tables["scaling_aggregate_rows"] if row["method"] == "degree_median")
        self.assertEqual(median_scaling["unprofiled_production_exterior_assembly_seconds_median"], .5)
        pair_scaling = next(row for row in tables["scaling_aggregate_rows"] if row["method"] == "degree_full_pair")
        self.assertEqual(pair_scaling["unprofiled_reference_assembly_seconds_median"], 1)
        self.assertNotEqual(median_scaling["component_timing_scope"], pair_scaling["component_timing_scope"])
        workload = next(row for row in tables["public_workload_rows"] if row["solves"] == 1)
        self.assertEqual(workload["paired_bestQ_difference"], -.125)
        self.assertEqual(workload["speedup_vs_discovery_control"], .6)
        generate_report(run, self.project / "first", project_root=self.project, expected_job_count=16)
        generate_report(run, self.project / "second", project_root=self.project, expected_job_count=16)
        self.assertEqual({p.name:p.read_bytes() for p in (self.project/"first").iterdir()},
                         {p.name:p.read_bytes() for p in (self.project/"second").iterdir()})

    def test_false_completed_marker_with_missing_jobs_refused(self):
        run, _ = fixture(self.project)
        path = run / "run-completed.json"
        data = json.loads(path.read_text())
        data["outcomes"].pop()
        write(path, data)
        with self.assertRaises(IncompleteSuiteError):
            audit_suite(run, project_root=self.project)

    def test_source_drift_and_false_workload_are_rejected(self):
        run, _ = fixture(self.project)
        source = self.project / "experiments/source.py"
        original = source.read_bytes()
        source.write_bytes(b"changed")
        with self.assertRaisesRegex(AnalysisError, "Frozen source"):
            audit_suite(run, project_root=self.project)
        source.write_bytes(original)
        path = run / "fixture-proposal0-gamma0.json.gz"
        raw = json.loads(gzip.decompress(path.read_bytes()))
        raw["workloads"][0]["full_reduced_seconds"] = 30
        write(path, raw)
        with self.assertRaisesRegex(AnalysisError, "full_reduced_seconds"):
            analyze(run, project_root=self.project)

    def test_solved_groups_are_not_residual_vertex_disappearance(self):
        result = {"input_vertices": 4, "remaining_vertices": 0, "groups": [], "solved_groups": [[0, 1], [2, 3]]}
        groups, removed = expanded_native_groups(4, result)
        self.assertEqual(removed, 2)
        self.assertEqual(len(groups), 2)
        result["solved_groups"] = [[0, 1], [1, 2, 3]]
        with self.assertRaises(AnalysisError):
            expanded_native_groups(4, result)

    def test_timeout_is_censored_and_completed_optimum_can_improve_incumbent(self):
        def arm(status, Q="1/2"):
            record = {"status": status, "incumbent_Q_original_exact": "1/4", "runner_wall_seconds": 31,
                "native_process_wall_seconds": 30, "timeout_seconds": 30,
                "full_solver_entry_called": True, "full_kapoce_solver": True,
                "incumbent": {"Q": "1/4"}, "bounds": {"Q_lower_bound": "1/4", "Q_upper_bound": "1/2"}}
            if status == "optimal":
                record.update(optimality_proved=True, solution={"Q": Q}, lifted_Q_original_exact=Q,
                              bounds={"Q_lower_bound": Q, "Q_upper_bound": Q})
            return record
        native = {"paired_arms": {"unreduced": arm("optimal"), "reduced": arm("timeout")},
            "execution_order": ["unreduced", "reduced"], "same_feasible_incumbent_Q_exact": "1/4",
            "matched_pipeline_seconds": {"unreduced": 32, "reduced": 34}}
        tables = {"full_native_pair_rows": [], "full_native_arm_rows": []}
        _full_native(native, {"source": "fixture"}, True, tables)
        self.assertFalse(tables["full_native_pair_rows"][0]["pair_completed"])
        self.assertIsNone(tables["full_native_pair_rows"][0]["completion_time_speedup"])
        timeout = next(row for row in tables["full_native_arm_rows"] if row["status"] == "timeout")
        self.assertIsNone(timeout["completed_runner_seconds"])
        self.assertEqual(timeout["censored_observed_runner_seconds"], 31)
        native["paired_arms"]["reduced"] = arm("optimal")
        tables = {"full_native_pair_rows": [], "full_native_arm_rows": []}
        _full_native(native, {"source": "fixture"}, True, tables)
        self.assertTrue(tables["full_native_pair_rows"][0]["native_only_completed_pair"])
        self.assertEqual(tables["full_native_pair_rows"][0]["matched_pipeline_speedup"], 32/34)

    def test_numeric_isolation_match_cannot_be_certified(self):
        oracle = csub_unresolved()
        oracle.update(status="numerical_match", available=True, certified=True)
        oracle["attempts"][-1]["result"].update(status="numerical_match", certified=True)
        with self.assertRaises(AnalysisError):
            _oracle_row(oracle, {"source": "fixture"}, "controlled_supplied", [0, 1])

    def test_unexpected_failure_artifact_forbids_final_report(self):
        run, _ = fixture(self.project)
        write(run / "unexpected-failed.json", {"status": "failed"})
        with self.assertRaisesRegex(AnalysisError, "Unexpected/failure"):
            audit_suite(run, project_root=self.project)

    def test_collective_size_ranks_preserve_overlap_and_raw_coverage(self):
        records = [{"block": block, "certified": True, "strict": index != 3}
                   for index, block in enumerate(([0, 1], [3, 4], [0, 1, 2], [1, 2, 3]))]
        records.append({"block": [4, 5], "certified": False, "strict": False})
        raw_reduction = {"removed_vertices": 4, "merge_groups": [[0, 1, 2, 3, 4]]}
        result = _production_size_mechanism(records, 6, raw_reduction)
        self.assertEqual(result["accepted_pair_blocks"], 2)
        self.assertEqual(result["accepted_collective_blocks"], 2)
        self.assertEqual(result["accepted_block_size_counts"], {"2": 2, "3": 2})
        self.assertEqual(result["pair_only_removed_vertices"], 2)
        self.assertEqual(result["collective_only_removed_vertices"], 3)
        self.assertEqual(result["all_accepted_certificate_identifications"], 4)
        self.assertEqual(result["collective_additions_beyond_accepted_production_pairs"], 2)
        self.assertNotEqual(result["pair_only_removed_vertices"] + result["collective_only_removed_vertices"],
                            result["all_accepted_certificate_identifications"])
        self.assertIn("post-freeze", result["size_mechanism_endpoint_role"])
        self.assertIn("not an executed", result["pair_only_comparison_scope"])
        with self.assertRaisesRegex(AnalysisError, "immutable all-certificate coverage"):
            _production_size_mechanism(records, 6, {"removed_vertices": 5, "merge_groups": [[0, 1, 2, 3, 4, 5]]})

    def test_completed_native_optimum_cannot_undercut_exact_feasible_milp(self):
        raw = {"production_independent_bank": {"status": "completed", "modularity_discovery_exact": "1/4",
            "modularity_discovery_quotient_exact": "1/4"}, "numerical_modularity_milp": {"paired_arms": {
            "unreduced": {"status": 1, "certified": False, "feasible_Q_exact": "3/4", "lifted_original_Q_exact": "3/4",
                          "upper_bound": 1000}, "reduced": {"feasible_Q_exact": None, "lifted_original_Q_exact": None}}}}
        feasible = _full_original_feasible_Q(raw)
        self.assertEqual(feasible, {"discovery": Fraction(1, 4), "numerical_milp_unreduced": Fraction(3, 4)})
        arm = {"status": "optimal", "incumbent_Q_original_exact": "1/4", "runner_wall_seconds": 1,
            "full_solver_entry_called": True, "full_kapoce_solver": True, "optimality_proved": True,
            "solution": {"Q": "1/2"}, "lifted_Q_original_exact": "1/2",
            "bounds": {"Q_lower_bound": "1/2", "Q_upper_bound": "1/2"}}
        native = {"paired_arms": {"unreduced": arm, "reduced": copy.deepcopy(arm)},
            "execution_order": ["unreduced", "reduced"], "same_feasible_incumbent_Q_exact": "1/4",
            "matched_pipeline_seconds": {"unreduced": 1, "reduced": 1}}
        with self.assertRaisesRegex(AnalysisError, "below exact full-original feasible Q"):
            _full_native(native, {"source": "fixture"}, True,
                {"full_native_pair_rows": [], "full_native_arm_rows": []}, exact_feasible_Q=feasible)
        # Floating bounds do not enter the gate; numerical feasibility alone
        # does not claim a numerical/global optimum.
        raw["numerical_modularity_milp"]["paired_arms"]["unreduced"].update(feasible_Q_exact="3/8", lifted_original_Q_exact="3/8")
        tables = {"full_native_pair_rows": [], "full_native_arm_rows": []}
        _full_native(native, {"source": "fixture"}, True, tables, exact_feasible_Q=_full_original_feasible_Q(raw))
        self.assertTrue(tables["full_native_pair_rows"][0]["pair_completed"])
        self.assertEqual(tables["full_native_arm_rows"][0]["exact_feasible_integrity_check_count"], 3)


class RecoveryFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".recovery-engineering-", dir=Path(__file__).resolve().parent)
        self.project = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _fixture(self, **kwargs):
        packet = recovery_fixture(self.project, **kwargs)
        self.patcher = patch.multiple("analysis.collect_recovery", BINARY_SHA=packet["binary_sha"], BUILD_SHA=packet["build_sha"])
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        return packet

    def test_partial_recovery_and_original_halt_still_refuse_publication(self):
        from analysis.collect_recovery import collect_recovery
        packet = self._fixture()
        with self.assertRaises(IncompleteSuiteError):
            generate_report(packet["parent"], self.project/"parent-report", project_root=self.project, expected_job_count=17)
        (packet["recovery"]/"run-completed.json").unlink()
        with self.assertRaises(IncompleteSuiteError):
            collect_recovery(packet["parent"], packet["recovery"], packet["collection"], project_root=self.project, expected_job_count=17)
        self.assertFalse(packet["collection"].exists())
        self.assertFalse((self.project/"parent-report").exists())

    def test_complete_collection_exact_copies_whole_davis_and_excludes_failed_inferences(self):
        from analysis.collect_recovery import collect_recovery, audit_collection
        packet = self._fixture()
        result = collect_recovery(packet["parent"], packet["recovery"], packet["collection"], project_root=self.project, expected_job_count=17)
        self.assertEqual((result["logical_jobs"], result["actual_source_attempts"]), (17, 18))
        plan = audit_collection(packet["collection"], project_root=self.project, expected_job_count=17)
        self.assertEqual((plan["parent_completed_jobs_retained"], plan["recovery_jobs_selected"]), (4, 13))
        self.assertEqual(len(plan["source_attempts"]), 18)
        self.assertEqual(plan["incident"]["all_source_failed_native_arms"], 4)
        for index in range(3):
            name = f"development-davis-gamma{index}.json.gz"
            self.assertEqual((packet["collection"]/name).read_bytes(), (packet["recovery"]/name).read_bytes())
            if index < 2:
                self.assertNotEqual((packet["collection"]/name).read_bytes(), (packet["parent"]/name).read_bytes())
        # This runs the source-backed report on fake schema data only. It also
        # exercises exact preserved core equality with post-preservation times.
        summary, tables = analyze(packet["collection"], project_root=self.project, expected_job_count=17)
        self.assertEqual(summary["status"], "complete_recovered_collection_with_recorded_native_failures")
        self.assertEqual(summary["run_kind"], "derived_recovered_collection")
        self.assertEqual(summary["recovered_collection"]["actual_source_orchestration_attempts"], 18)
        failed = [row for row in tables["full_native_arm_rows"] if row["status"] == "failed"]
        self.assertEqual(len(failed), 2)
        for row in failed:
            self.assertTrue(row["known_native_failure"])
            self.assertIsNone(row["validated_Q_exact"])
            self.assertIsNone(row["Q_lower_bound_exact"])
            self.assertIsNone(row["Q_upper_bound_exact"])
            self.assertIsNone(row["completed_runner_seconds"])
            self.assertEqual(row["incumbent_Q_exact"], "-106/7921")
            self.assertEqual(row["exact_feasible_integrity_check_count"], 0)
        failed_pair = next(row for row in tables["full_native_pair_rows"] if row.get("known_native_failure"))
        self.assertFalse(failed_pair["pair_completed"])
        self.assertIsNone(failed_pair["completion_time_speedup"])
        self.assertIsNone(failed_pair["matched_pipeline_speedup"])
        # Both sources remain byte-preserved and a derived collection cannot
        # overwrite, choose another output path, or add extra artifacts.
        with self.assertRaisesRegex(AnalysisError, "must not overwrite"):
            collect_recovery(packet["parent"], packet["recovery"], packet["collection"], project_root=self.project, expected_job_count=17)
        (packet["collection"]/"unexpected.json").write_text("{}")
        with self.assertRaisesRegex(AnalysisError, "missing or extra"):
            audit_collection(packet["collection"], project_root=self.project, expected_job_count=17)

    def test_same_bank_mismatch_stops_collection_even_with_frozen_source_hashes(self):
        from analysis.collect_recovery import collect_recovery
        packet = self._fixture(bank_mismatch=True)
        with self.assertRaisesRegex(AnalysisError, "changed original graph/refined bank"):
            collect_recovery(packet["parent"], packet["recovery"], packet["collection"], project_root=self.project, expected_job_count=17)
        self.assertFalse(packet["collection"].exists())

    def test_unreviewed_selected_failure_stops_recovery_collection(self):
        from analysis.collect_recovery import collect_recovery
        packet = self._fixture(unexpected_failure=True)
        with self.assertRaisesRegex(AnalysisError, "Unexpected raw failure"):
            collect_recovery(packet["parent"], packet["recovery"], packet["collection"], project_root=self.project, expected_job_count=17)
        self.assertFalse(packet["collection"].exists())

    def test_reviewed_source_selection_and_incident_marker_are_hash_bound(self):
        from analysis.collect_recovery import build_collection_plan
        packet = self._fixture()
        reviewed_source = self.project/"analysis/report.py"
        original = reviewed_source.read_bytes()
        reviewed_source.write_bytes(original+b"# source drift\n")
        with self.assertRaisesRegex(AnalysisError, "independently frozen"):
            build_collection_plan(packet["parent"], packet["recovery"], project_root=self.project, expected_job_count=17)
        reviewed_source.write_bytes(original)
        selection_path = self.project/"experiments/recovery/collection-selection-plan.json"
        original_selection = selection_path.read_bytes()
        selection = json.loads(original_selection)
        selection["logical_jobs"][4]["source_role"] = "parent"
        write(selection_path, selection)
        with self.assertRaisesRegex(AnalysisError, "selection is not approved"):
            build_collection_plan(packet["parent"], packet["recovery"], project_root=self.project, expected_job_count=17)
        selection_path.write_bytes(original_selection)
        marker_path = packet["recovery"]/"development-davis-gamma2-reviewed-incident.json"
        marker = json.loads(marker_path.read_text())
        marker["excluded_inferences"].remove("bound gap")
        write(marker_path, marker)
        with self.assertRaisesRegex(AnalysisError, "incident marker"):
            build_collection_plan(packet["parent"], packet["recovery"], project_root=self.project, expected_job_count=17)

    def test_unexpected_recovery_artifact_cannot_be_silently_unselected(self):
        from analysis.collect_recovery import build_collection_plan
        packet = self._fixture()
        write(packet["recovery"]/"other-native-failed.json", {"status": "failed"})
        with self.assertRaisesRegex(AnalysisError, "unexpected artifacts"):
            build_collection_plan(packet["parent"], packet["recovery"], project_root=self.project, expected_job_count=17)

    def test_allowlist_payload_and_post_preservation_times_cannot_drift(self):
        from analysis.collect_recovery import build_collection_plan
        packet = self._fixture()
        gamma_path = packet["recovery"]/"development-davis-gamma2.json.gz"
        original = gamma_path.read_bytes()
        raw = json.loads(gzip.decompress(original))
        raw["native_full_solver"]["paired_arms"]["reduced"]["conversion"]["budget"] += 1
        write(gamma_path, raw)
        with self.assertRaisesRegex(AnalysisError, "reviewed paired native incident"):
            build_collection_plan(packet["parent"], packet["recovery"], project_root=self.project, expected_job_count=17)
        raw = json.loads(gzip.decompress(original))
        raw["native_full_solver"]["shared_graph_preparation_seconds"] = 99
        write(gamma_path, raw)
        with self.assertRaisesRegex(AnalysisError, "recovery_shared_preparation"):
            build_collection_plan(packet["parent"], packet["recovery"], project_root=self.project, expected_job_count=17)


if __name__ == "__main__":
    unittest.main()
