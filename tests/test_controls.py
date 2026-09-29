"""Control-runner engineering checks; no frozen performance experiment runs."""
from copy import deepcopy
from fractions import Fraction
import gzip
import json
from pathlib import Path

import networkx as nx
import numpy as np
import pytest
from scipy import sparse

from degree_contraction import modularity_exact, prepare_graph, quotient_adjacency
from experiments import run_controls as controls
from experiments.candidates import candidate_bank
from experiments.exact_oracle import CSubinstanceResult, OracleResult


@pytest.fixture
def config():
    # Only tiny unit fixtures are exercised; full case spec/hash freeze is
    # mocked where workflow mechanics are tested, never for measurements.
    return {
        "threads": {}, "proposal": {"resolution": "1", "minimum_size": 2},
        "checker": {"verification": "auto", "exact_max_size": 64,
                    "dense_max_size": 64, "screen_tolerance": 1e-10},
        "global_baselines": ["singleton_dominance", "positive_closure_edge", "degree_proportional_twins"],
        "global_baseline_policy": {"pair_strict": True, "twin_strict": False},
        "supplied_block_methods": ["degree_median", "degree_zero", "degree_anchor",
                                   "degree_full_pair", "uniform_copy", "lange_positive_closure_star",
                                   "bocker_almost_clique"],
        "supplied_block_config": {"exact_max_size": 64, "uniform_max_graph_vertices": 150,
                                  "uniform_max_exterior_vertices": 150, "positive_closure_max_vertices": 128,
                                  "signed_internal_enumeration_max_size": 16},
        "c_subinstance": {"exact_max_active_vertices": 10, "numerical_max_active_vertices": 50,
                          "numerical_time_limit_seconds": 5, "tolerance": 1e-8},
        "native_kapoce": {"routine": "weighted_recursive", "full_solver": False,
                          "max_vertices": 2000, "timeout_seconds": 30, "datasets": ["karate"]},
        "native_full_solver": {"max_vertices": 2000, "timeout_seconds": 30},
        "recursive_cheap": {"max_block_size": 64, "include_round_decisions": False},
        "numerical_milp": {"max_vertices": 150, "time_limit_seconds": 60, "datasets": ["karate"]},
        "gamma": ["1/2", "1", "2"], "development_datasets": ["karate"], "controlled_cases": [],
    }


def test_freeze_rejection_precedes_loading_generation_and_output(monkeypatch, tmp_path, config):
    def reject(*args):
        raise ValueError("independent design freeze required")
    monkeypatch.setattr(controls, "validate_freeze", reject)
    monkeypatch.setattr(controls, "load_family", lambda *args, **kwargs: pytest.fail("unfrozen generation"))
    monkeypatch.setattr(controls, "load_development", lambda *args, **kwargs: pytest.fail("unfrozen loading"))
    with pytest.raises(ValueError, match="freeze required"):
        controls.run_case("development", "karate", config, tmp_path / "runs", "draft.json", "freeze.json")
    assert not (tmp_path / "runs").exists()


def test_auto_median_result_is_not_replaced_by_exact_boundary_panels(config):
    a = sparse.csr_matrix([[0, 1], [1, 0]])
    prepared = prepare_graph(a)
    integer, module, weighted, _ = controls.prepare_references(a)
    result = controls.evaluate_block_references(prepared, integer, module, weighted, [0, 1], Fraction(2), config)
    assert not result["degree_median"]["result"]["certified"]
    assert result["degree_median"]["result"]["verification_status"] == "auto_screened_without_verification"
    for key in ("degree_median_forced_exact", "degree_median_independent_exact"):
        assert result[key]["result"]["certified"]
        assert not result[key]["result"]["strict"]
        assert "panel" in result[key]["result"]["comparison_role"]
    assert not result["lange_positive_closure_star"]["result"]["certified"]
    assert len(result["lange_positive_closure_star"]["result"]["safe_pairs"]) == 1
    assert "bocker_almost_clique_weak_side" not in result
    supplied = controls.evaluate_block_references(prepared, integer, module, weighted, [0, 1], Fraction(2), config,
                                                 include_weak_bocker=True)
    assert supplied["bocker_almost_clique_weak_side"]["result"]["certified"]
    assert not supplied["bocker_almost_clique_weak_side"]["result"]["strict"]


def test_missing_reference_is_explicit_not_a_simplified_substitute(config):
    a = sparse.csr_matrix([[0, 1], [1, 0]])
    integer = controls.sparse_criteria.prepare_integer_graph(a)
    result = controls.evaluate_block_references(prepare_graph(a), integer, None, None, [0, 1], Fraction(1), config)
    for key in ("degree_median_independent_exact", "degree_zero", "degree_anchor", "degree_full_pair"):
        assert result[key]["result"]["available"] is False
        assert result[key]["result"]["verification_status"] == "independent_reference_module_missing"


def test_csub_score_equality_keeps_ties_and_exact_certification(config):
    a = sparse.csr_matrix(np.ones((3, 3)) - np.eye(3))
    result = controls.evaluate_c_subinstance(prepare_graph(a), [0, 1], Fraction(3, 2), config)
    assert result["status"] == "exact_match" and result["certified"]
    oracle = result["attempts"][0]["result"]["oracle"]
    assert oracle["objective"] == "0" and oracle["optimum_count"] > 1
    assert "including ties" in result["tie_policy"]


def test_csub_guard_fallback_never_certifies_numerical_output(monkeypatch, config):
    calls = []
    def stub(a, block, gamma, **kwargs):
        calls.append(kwargs)
        status = "unavailable" if kwargs["arithmetic"] == "exact" else "unresolved"
        return CSubinstanceResult(tuple(block), (), None, None, status, False, None, "guard/timeout")
    monkeypatch.setattr(controls, "check_c_subinstance", stub)
    result = controls.evaluate_c_subinstance(None, [0, 1], Fraction(1), config)
    assert result["status"] == "unresolved" and not result["available"] and not result["certified"]
    assert [x["arithmetic"] for x in calls] == ["exact", "numerical"]
    assert calls[0]["max_vertices"] == 10
    assert calls[1]["max_vertices"] == 50 and calls[1]["time_limit"] == 5


def test_native_uses_actual_discovery_partition_and_named_preprocessing(monkeypatch, config):
    captured = []
    def stub(case, **kwargs):
        captured.append((case, kwargs))
        return {"full_kapoce_solver": False, "records": [{"status": "completed"}]}
    monkeypatch.setattr(controls, "run_native_case", stub)
    a = sparse.csr_matrix([[0, 3, 0], [3, 0, 1], [0, 1, 0]])
    labels = np.array([0, 0, 1])
    result = controls.evaluate_native(a, labels, Fraction(1, 2), config, requested=True, case_name="fixture")
    case, kwargs = captured[0]
    assert case["partition"] == [0, 0, 1] and case["gamma"] == "1/2"
    assert all(type(x) is int for row in case["adjacency"] for x in row)
    assert kwargs == {"routines": ("weighted_recursive",), "timeout_seconds": 30}
    assert not result["full_kapoce_solver"]
    skipped = controls.evaluate_native(a, labels, Fraction(1), config, requested=False, case_name="fixture")
    assert not skipped["available"] and len(captured) == 1


def test_numerical_incumbents_are_lifted_and_re_evaluated_exactly(monkeypatch, config):
    a = sparse.csr_matrix([[0, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0]])
    quotient = quotient_adjacency(a, [(0, 1), (2, 3)])
    calls = []
    def solver(adjacency, gamma, time_limit):
        calls.append((adjacency.shape[0], gamma, time_limit))
        labels = np.array([0, 0, 1, 1]) if adjacency.shape[0] == 4 else np.array([0, 1])
        return OracleResult(labels, float(modularity_exact(adjacency, labels, gamma)), 0.9,
                            1, "time limit", 0.7, 0.01, 0.02, 1, 0)
    monkeypatch.setattr(controls, "solve_modularity", solver)
    result = controls.evaluate_numerical_milp(a, quotient, Fraction(1), config, order=["reduced", "unreduced"])
    assert [x[0] for x in calls] == [2, 4] and all(x[2] == 60 for x in calls)
    arms = result["paired_arms"]
    assert arms["reduced"]["feasible_Q_exact"] == arms["reduced"]["lifted_original_Q_exact"] == "1/6"
    assert arms["unreduced"]["feasible_Q_exact"] == "1/6"
    assert arms["reduced"]["lifted_labels"] == [0, 0, 1, 1]
    assert all(x["status"] == 1 and x["upper_bound"] == 0.9 and not x["global_optimum_certified"] for x in arms.values())


def test_generic_weak_pair_decisions_are_not_unioned(config):
    a = sparse.csr_matrix([[0, 1], [1, 0]])
    changed = deepcopy(config)
    changed["global_baseline_policy"]["pair_strict"] = False
    with pytest.raises(ValueError, match="Weak generic"):
        controls.evaluate_global_baselines(a, controls.sparse_criteria.prepare_integer_graph(a), Fraction(1), changed, {0, 1})


def test_controlled_metadata_cannot_seed_bank_and_results_are_immutable(monkeypatch, tmp_path, config):
    spec = {"case_id": "controlled-fixture", "family": "matching_cliques", "parameters": {"k": 3},
            "gamma": ["1"], "role": "unit_fixture", "native_preprocessing": False,
            "candidate_bank_seed": 0, "supplied_block_comparison": True, "candidate_bank_evaluation": True}
    config["controlled_cases"] = [spec]
    config["supplied_block_methods"] = []
    config["global_baselines"] = []
    config_path, freeze_path = tmp_path / "config.json", tmp_path / "freeze.json"
    config_path.write_text(json.dumps(config))
    freeze_path.write_text('{}')
    monkeypatch.setattr(controls, "validate_freeze", lambda *args: {"runtime_source_sha256": {"fixture": "unit-test"}})
    monkeypatch.setattr(controls, "controlled_grid", lambda: [spec])
    graph = nx.path_graph(4)
    calls = []
    monkeypatch.setattr(controls, "load_family", lambda *args, **kwargs: (graph, {"oracle_blocks": [[0, 1]], "n": 4}))
    def bank(observed_graph, **kwargs):
        assert observed_graph is graph and not observed_graph.graph
        assert kwargs == {"seed": 0, "resolution": 1.0, "minimum_size": 2}
        calls.append(observed_graph)
        return candidate_bank(observed_graph, **kwargs)
    monkeypatch.setattr(controls, "candidate_bank", bank)
    monkeypatch.setattr(controls, "evaluate_c_subinstance", lambda *args: {"status": "unit_stub", "certified": False})
    output = tmp_path / "results"
    controls.run_case("controlled", spec["case_id"], config, output, config_path, freeze_path)
    assert len(calls) == 1
    with gzip.open(output / 'controlled-fixture-input.json.gz', 'rt') as source:
        recorded = json.load(source)
    assert recorded["supplied_blocks"] == [[0, 1]]
    assert recorded["candidate_bank"]["seed"] == 0
    previous = {path.name: path.read_bytes() for path in output.iterdir()}
    with pytest.raises(FileExistsError):
        controls.run_case("controlled", spec["case_id"], config, output, config_path, freeze_path)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == previous
    assert len(calls) == 1


def test_json_logging_retains_rational_values_and_nonfinite_diagnostics():
    value = controls.jsonable({"exact": Fraction(2, 3), "array": np.array([1, 2]), "bound": float('inf')})
    assert value == {"exact": "2/3", "array": [1, 2], "bound": "inf"}
    json.dumps(value, allow_nan=False)


def test_parser_accepts_orchestration_contract_without_running_experiments():
    args = controls.make_parser().parse_args([
        '--config', 'config.json', '--freeze', 'freeze.json', '--run-dir', 'results',
        '--stratum', 'controlled', '--case', 'controlled-000-matching_cliques',
    ])
    assert args.stratum == 'controlled' and args.case == 'controlled-000-matching_cliques'
    all_args = controls.make_parser().parse_args(['--run-dir', 'results', '--stratum', 'development', '--all'])
    assert all_args.all and all_args.stratum == 'development'


def test_full_frozen_grid_cannot_silently_omit_a_control(config, monkeypatch):
    first = {"case_id": "first", "family": "matching_cliques", "parameters": {"k": 3},
             "gamma": ["1"], "candidate_bank_seed": 0}
    second = dict(first, case_id="second")
    monkeypatch.setattr(controls, "controlled_grid", lambda: [first, second])
    config["controlled_cases"] = [first]
    with pytest.raises(ValueError, match="entire unique predeclared grid"):
        controls._validate_case('controlled', 'first', config)


def test_unexpected_native_failure_is_preserved_and_halts(tmp_path):
    record = {"records": [{"status": "failed", "exit_code": 2,
                            "stderr": "assertion failed", "result": None}]}
    with pytest.raises(RuntimeError, match="preserved"):
        controls.preserve_native_failure(tmp_path, "fixture", 0, record, method="preprocessing")
    artifact = json.loads((tmp_path / "fixture-gamma0-preprocessing-failed.json").read_text())
    assert artifact["native_record"] == record
    for status in ("completed", "timeout", "skipped_numeric_domain", "skipped_input_domain"):
        controls.preserve_native_failure(tmp_path, "normal", 0,
                                         {"records": [{"status": status}]}, method="preprocessing")
    assert not list(tmp_path.glob("normal*"))


def test_complete_native_pair_retains_same_incumbent_and_validates_lift(monkeypatch, config):
    a = sparse.csr_matrix([[0, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0]])
    quotient = quotient_adjacency(a, [(0, 1), (2, 3)])
    discovery = np.array([0, 0, 1, 1])
    calls = []
    def stub(case, **kwargs):
        calls.append((case, kwargs))
        adjacency = sparse.csr_matrix(case["adjacency"])
        q = modularity_exact(adjacency, case["partition"], Fraction(case["gamma"]))
        return {"status": "optimal", "optimality_proved": True,
                "solution": {"labels": case["partition"], "Q": str(q)}}
    monkeypatch.setattr(controls, "run_full_case", stub)
    record = controls.evaluate_full_native(a, quotient, discovery, Fraction(1), config,
                                          requested=True, case_name="fixture", order=["reduced", "unreduced"])
    assert [len(case["adjacency"]) for case, _ in calls] == [2, 4]
    assert all(kwargs == {"timeout_seconds": 30} for _, kwargs in calls)
    assert record["same_feasible_incumbent_Q_exact"] == "1/6"
    assert record["paired_arms"]["reduced"]["lifted_labels"] == discovery.tolist()
    calls.clear()
    singleton = quotient_adjacency(a, [(0, 1, 2, 3)])
    trivial = controls.evaluate_full_native(a, singleton, np.zeros(4, dtype=int), Fraction(1), config,
                                           requested=True, case_name="trivial", order=["reduced", "unreduced"])
    assert trivial["paired_arms"]["reduced"]["status"] == "optimal_trivial"
    assert len(calls) == 1
