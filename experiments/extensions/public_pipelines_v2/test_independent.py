"""Independent tiny engineering references for the prospective public v2 study.

No public dataset is loaded. Dense Python-integer/Fraction references and full
tiny partition enumeration are independent of the new sparse evaluator. Manual
merge groups below test transport, not mathematical certification. The only
real downstream calls are nine fixed seeds on a positive-loop one-node quotient.
"""
from __future__ import annotations

from fractions import Fraction
from copy import deepcopy
import itertools
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import numpy as np
from scipy import sparse

from degree_contraction import (certify_block, contract_certified_blocks, modularity_exact,
                                prepare_graph, quotient_adjacency)
from experiments.pipeline import discovery_quotient_labels, networkx_quotient, solve_louvain
from research.baselines.recursive_cheap import recursive_cheap

from . import collect as collector
from . import run_case as runner
from . import stages
from .contracts import (ARM_PHASES, ARMS, COMMON_PHASES, ArmState, CaseKey, FixedBank, OriginalContext,
                        PhaseLedger, canonical_partition, compose_membership, content_hash, rational_record,
                        rational_value, read_json, sha256, standalone_cost, write_once)
from .integer_objective import (aggregate_integer_rows, integer_modularity,
                                prepare_integer_objective, validate_quotient)
from .schedule import expected_ledger, preprocessing_order, seed_arm_order


def dense_q(matrix, labels, gamma):
    """Full ordered adjacency sum with independent arbitrary-precision arithmetic."""
    n = len(matrix)
    if len(labels) != n:
        raise ValueError("reference labels do not cover the graph")
    degree = [sum(int(weight) for weight in row) for row in matrix]
    total = sum(degree)
    within = sum(int(matrix[u][v]) for u in range(n) for v in range(n)
                 if labels[u] == labels[v])
    communities = set(labels)
    squares = sum(sum(degree[u] for u in range(n) if labels[u] == label) ** 2
                  for label in communities)
    return Fraction(within, total) - gamma * Fraction(squares, total * total)


def partitions(n):
    """Restricted-growth strings enumerate each set partition exactly once."""
    if n == 0:
        yield ()
        return
    def extend(prefix, maximum):
        if len(prefix) == n:
            yield tuple(prefix)
            return
        for label in range(maximum + 2):
            yield from extend(prefix + [label], max(maximum, label))
    yield from extend([0], 0)


def dense_aggregate(matrix, membership):
    count = max(membership) + 1
    answer = [[0] * count for _ in range(count)]
    for u in range(len(matrix)):
        for v in range(len(matrix)):
            answer[membership[u]][membership[v]] += int(matrix[u][v])
    return answer


def fixture_context(matrix):
    adjacency = sparse.csr_matrix(np.asarray(matrix, dtype=np.float64))
    cache = prepare_integer_objective(adjacency)
    graph = networkx_quotient(adjacency)
    component = tuple(sorted(max(nx.connected_components(graph), key=lambda g: (len(g), -min(g)))))
    return OriginalContext(graph, cache.adjacency, cache,
                           {"fixture": True, "n": len(matrix), "m": graph.number_of_edges()},
                           component, tuple(range(len(matrix))))


def fixture_bank(blocks, discovery):
    blocks = tuple(tuple(block) for block in blocks)
    return FixedBank(blocks, tuple(discovery), stages.bank_identity(blocks), {"fixture": True})


class MutableClock:
    def __init__(self):
        self.value = 0.0
    def __call__(self):
        return self.value
    def advance(self, value):
        self.value += value


class MembershipAndSequentialTests(unittest.TestCase):
    def test_actual_core_ids_mapped_bank_and_sequential_transport(self):
        matrix = [[0, 0, 0, 0], [0, 0, 3, 0], [0, 3, 0, 0], [0, 0, 0, 0]]
        original = sparse.csr_matrix(matrix, dtype=float)
        result = recursive_cheap(original, ((1, 2),), Fraction(1), max_block_size=64,
                                 include_round_decisions=False)
        actual = quotient_adjacency(original, result["merge_groups"], require_exact=True)
        internal = tuple(result["original_membership"])
        membership = tuple(map(int, actual.membership))
        self.assertEqual(internal, (0, 1, 1, 2))
        self.assertEqual(membership, (1, 0, 0, 2))
        self.assertNotEqual(internal, membership)
        self.assertEqual(canonical_partition(internal), canonical_partition(membership))
        self.assertEqual(tuple(actual.lift_labels((70, 80, 90))), (80, 70, 70, 90))
        self.assertEqual(actual.adjacency.toarray().tolist(), dense_aggregate(matrix, membership))
        self.assertEqual(actual.adjacency[0, 0], 6)

        # Disjoint original entries acquire overlapping current images. The
        # actual group {1,2} expands source {0,1} to include vertex 2 as well.
        bank = ((0, 1), (2, 3), (0, 2), (1, 2))
        mapped = stages.map_original_bank(bank, membership, (0, 0, 1, 1), max_block_size=64)
        self.assertEqual(mapped.blocks, ((0, 1), (0, 2)))
        self.assertEqual(mapped.summary["duplicate_nontrivial_images_removed"], 1)
        self.assertEqual(mapped.summary["trivial_original_image_count"], 1)
        entries = {tuple(row["current_block"]): row for row in mapped.entries}
        self.assertEqual(entries[(0, 1)]["original_bank_indices"], [0, 2])
        self.assertEqual(entries[(0, 1)]["expanded_original_vertices"], [0, 1, 2])
        self.assertTrue(entries[(0, 1)]["crosses_discovery_communities"])
        self.assertEqual(entries[(0,)]["classification"], "trivial_image")

        # Transport alone: these manually selected second groups are not
        # asserted safe; exact direct aggregation and lifting are the claims.
        second = quotient_adjacency(actual.adjacency, ((0, 2),), require_exact=True)
        composed = compose_membership(membership, tuple(map(int, second.membership)))
        direct = dense_aggregate(matrix, composed)
        self.assertEqual(second.adjacency.toarray().tolist(), direct)
        cache, validation = validate_quotient(prepare_integer_objective(original), second.adjacency, composed)
        self.assertEqual(cache.total, 6)
        self.assertTrue(validation["all_diagonal_entries_verified"])
        self.assertEqual(tuple(second.lift_labels((17, 23))[v] for v in membership),
                         tuple((17, 23)[v] for v in composed))

    def test_complete_original_oversized_mapping_before_cap(self):
        # Pure membership metadata: no 66-node graph is generated or timed.
        membership = [None] * 66
        membership[1] = membership[2] = membership[65] = 0
        next_id = 1
        for u in range(66):
            if membership[u] is None:
                membership[u] = next_id
                next_id += 1
        mapped = stages.map_original_bank((tuple(range(65)), tuple(range(66)), (1, 2, 65)),
                                         membership, tuple(u % 2 for u in range(66)), max_block_size=64)
        target = next(row for row in mapped.entries if row["current_size"] == 64)
        self.assertEqual(target["original_sizes"], [65, 66])
        self.assertEqual(target["original_bank_indices"], [0, 1])
        self.assertEqual(target["expanded_original_size"], 66)
        self.assertEqual(target["classification"], "admissible")
        self.assertEqual(mapped.summary["current_cap_exclusions"], 0)
        self.assertEqual(mapped.summary["duplicate_nontrivial_images_removed"], 1)
        self.assertEqual(mapped.summary["trivial_original_image_count"], 1)

    def test_actual_named_and_degree_stages_preserve_enumerated_optimum(self):
        examples = (
            ([[0, 3, 3], [3, 0, 3], [3, 3, 0]], Fraction(1, 2), ((0, 1, 2),)),
            ([[0, 0, 0, 0], [0, 0, 3, 0], [0, 3, 0, 0], [0, 0, 0, 0]], Fraction(1), ((1, 2),)),
            ([[0, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0]], Fraction(10), ((0, 1, 2, 3),)),
            # A looped regular five-vertex signed cycle plus a disjoint pair.
            # At gamma51/50, S510, the first five vertices have d100 and
            # Boff=1 to vertex0,11 on the four-cycle,−10 across its opposite
            # vertices. R merges only the extra pair; RD then accepts the
            # five-vertex block. This exercises two nontrivial safe stages.
            ([[16, 21, 21, 21, 21, 0, 0],
              [21, 7, 31, 10, 31, 0, 0],
              [21, 31, 7, 31, 10, 0, 0],
              [21, 10, 31, 7, 31, 0, 0],
              [21, 31, 10, 31, 7, 0, 0],
              [0, 0, 0, 0, 0, 0, 5],
              [0, 0, 0, 0, 0, 5, 0]], Fraction(51, 50), ((0, 1, 2, 3, 4),)),
        )
        removed = {"D": 0, "R": 0, "RD": 0}
        for matrix, gamma, blocks in examples:
            context = fixture_context(matrix)
            bank = fixture_bank(blocks, tuple(range(len(matrix))))
            optimum = max(dense_q(matrix, labels, gamma) for labels in partitions(len(matrix)))
            states = {arm: stages.prepare_arm(context, bank, gamma, arm, PhaseLedger()) for arm in ARMS}
            stages.validate_r_prefixes(states, PhaseLedger())
            for arm, state in states.items():
                with self.subTest(gamma=str(gamma), n=len(matrix), arm=arm):
                    quotient_dense = dense_aggregate(matrix, state.membership)
                    self.assertEqual(state.adjacency.toarray().tolist(), quotient_dense)
                    scores = []
                    for labels in partitions(state.objective.n):
                        lifted = tuple(labels[v] for v in state.membership)
                        original_q = dense_q(matrix, lifted, gamma)
                        quotient_q = dense_q(quotient_dense, labels, gamma)
                        self.assertEqual(original_q, quotient_q)
                        scores.append(original_q)
                    self.assertEqual(max(scores), optimum)
                    if arm in removed:
                        removed[arm] += len(matrix) - state.objective.n
            self.assertLessEqual(states["RD"].objective.n, states["R"].objective.n)
            if len(matrix) == 7:
                self.assertEqual({arm: state.objective.n for arm, state in states.items()},
                                 {"U": 7, "D": 3, "R": 6, "RD": 2})
                self.assertEqual(states["RD"].provenance["degree_stage"]["accepted_count"], 1)
                self.assertEqual(states["RD"].provenance["additional_removed_vertices_after_r"], 4)
        self.assertTrue(all(count > 0 for count in removed.values()))

    def test_current_fingerprint_and_gamma_cannot_be_mixed(self):
        adjacency = sparse.csr_matrix([[0, 3, 3], [3, 0, 3], [3, 3, 0]], dtype=float)
        prepared = prepare_graph(adjacency)
        first = certify_block(prepared, (0, 1, 2), Fraction(1), verification="auto")
        second = certify_block(prepared, (0, 1, 2), Fraction(1, 2), verification="auto")
        self.assertTrue(first.certified and second.certified)
        with self.assertRaisesRegex(ValueError, "same exact resolution"):
            contract_certified_blocks(prepared, (first, second))
        changed = sparse.csr_matrix([[0, 4, 3], [4, 0, 3], [3, 3, 0]], dtype=float)
        with self.assertRaisesRegex(ValueError, "for this graph"):
            contract_certified_blocks(changed, (first,))


class ExternalIncumbentTests(unittest.TestCase):
    def test_crossed_original_incumbent_wins_all_four_arms(self):
        matrix = [[0, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0]]
        context = fixture_context(matrix)
        discovery = (0, 0, 1, 1)
        bank = fixture_bank(((0, 1), (2, 3)), discovery)
        quotient = quotient_adjacency(context.adjacency, ((1, 2),), require_exact=True)
        with self.assertRaisesRegex(ValueError, "not feasible"):
            discovery_quotient_labels(discovery, quotient)
        membership = tuple(map(int, quotient.membership))
        representation = stages.discovery_representability(membership, discovery)
        self.assertFalse(representation["representable"])
        self.assertEqual(representation["crossing_group_count"], 1)
        discovery_q = dense_q(matrix, discovery, Fraction(1))
        self.assertEqual(discovery_q, Fraction(1, 6))
        for arm in ARMS:
            # Manual quotient is a transport fixture. U uses its actual identity.
            if arm == "U":
                adjacency, member, cache = context.adjacency, tuple(range(4)), context.objective
            else:
                adjacency, member = quotient.adjacency, membership
                cache = prepare_integer_objective(adjacency)
            state = ArmState(arm, adjacency, member, networkx_quotient(adjacency), cache)
            raw = tuple(0 for _ in range(cache.n))
            diagnostics = {"modularity": 0.0, "solver_seconds": 0.0,
                           "label_conversion_seconds": 0.0, "objective_evaluation_seconds": 0.0}
            with patch.object(runner, "solve_louvain", return_value=(raw, diagnostics)) as called:
                record = runner.run_seed(context, bank, state, Fraction(1), 10, discovery_q, PhaseLedger())
            self.assertEqual(called.call_count, 1)
            self.assertEqual(len(called.call_args.args), 4)
            self.assertEqual(called.call_args.kwargs, {})
            self.assertEqual(record["raw_original_Q_exact"], rational_record(Fraction(0)))
            self.assertEqual(record["returned_Q_exact"], rational_record(discovery_q))
            self.assertEqual(record["returned_original_labels"], list(discovery))
            self.assertTrue(record["discovery_fallback"])
            self.assertFalse(record["louvain_initial_partition_supplied"])
        malformed = {**diagnostics, "objective_evaluation_seconds": float("nan")}
        with patch.object(runner, "solve_louvain", return_value=(raw, malformed)):
            with self.assertRaisesRegex(ArithmeticError, "nonfinite Q/timer"):
                runner.run_seed(context, bank, state, Fraction(1), 11, discovery_q, PhaseLedger())

    def test_exact_selection_and_prefix_tie_order_use_real_partition_scores(self):
        matrix = [[0, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0]]
        gamma = Fraction(1)
        singleton, fused, optimum = (0, 1, 2, 3), (0, 0, 0, 0), (0, 0, 1, 1)
        scores = {p: dense_q(matrix, p, gamma) for p in (singleton, fused, optimum)}
        self.assertLess(scores[singleton], scores[fused])
        self.assertLess(scores[fused], scores[optimum])
        for discovery, raw in ((optimum, fused), (fused, fused), (singleton, optimum)):
            record = runner.select_external_incumbent(discovery, scores[discovery], raw, scores[raw], 10)
            expected = raw if scores[raw] > scores[discovery] else discovery
            self.assertEqual(tuple(record["returned_original_labels"]), expected)
            self.assertEqual(rational_value(record["returned_Q_exact"]), max(scores[raw], scores[discovery]))
        with self.assertRaises(TypeError):
            runner.select_external_incumbent(fused, 0.0, fused, Fraction(0), 10)

        bank = fixture_bank((), fused)
        state = ArmState("R", None, (0, 1, 2, 3))
        # A seed tying discovery cannot displace it. Two later equal improving
        # scores must leave the first improvement (seed 11) as the winner.
        outcomes = (fused, optimum, optimum) + (singleton,) * 6
        for seed, raw in zip(range(10, 19), outcomes):
            selected = runner.select_external_incumbent(fused, scores[fused], raw, scores[raw], seed)
            state.seed_results.append({"status": "completed", "seed": seed,
                                       "raw_original_Q_exact": rational_record(scores[raw]),
                                       "raw_original_labels": list(raw), **selected})
        one = runner.finalize_prefix(bank, state, scores[fused], 1)
        three = runner.finalize_prefix(bank, state, scores[fused], 3)
        nine = runner.finalize_prefix(bank, state, scores[fused], 9)
        self.assertEqual(one["winner_kind"], "discovery")
        self.assertIsNone(one["winner_seed"])
        self.assertEqual(three["winner_seed"], 11)
        self.assertEqual(nine["winner_seed"], 11)
        self.assertEqual(nine["fallback_count"], 7)
        state.seed_results[1]["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "failed seed"):
            runner.finalize_prefix(bank, state, scores[fused], 3)


class IndependentIntegerTests(unittest.TestCase):
    def test_random_integer_loops_original_and_quotient_against_dense_and_core(self):
        rng = random.Random(521)
        for n in range(1, 6):
            for trial in range(4):
                matrix = [[0] * n for _ in range(n)]
                for u in range(n):
                    for v in range(u, n):
                        matrix[u][v] = matrix[v][u] = rng.randrange(0, 8)
                matrix[0][0] += 1
                adjacency = sparse.csr_matrix(matrix, dtype=float)
                cache = prepare_integer_objective(adjacency)
                labels = tuple(rng.randrange(-2, n + 2) for _ in range(n))
                gamma = Fraction(trial + 1, 3)
                with self.subTest(n=n, trial=trial):
                    expected = dense_q(matrix, labels, gamma)
                    self.assertEqual(integer_modularity(cache, labels, gamma), expected)
                    self.assertEqual(modularity_exact(adjacency, labels, gamma), expected)
                    self.assertEqual(cache.degrees, tuple(sum(row) for row in matrix))
                    self.assertEqual(cache.total, sum(map(sum, matrix)))
                    group = tuple(range(min(n, 2)))
                    quotient = quotient_adjacency(adjacency, (group,), require_exact=True)
                    membership = tuple(map(int, quotient.membership))
                    quotient_cache, _ = validate_quotient(cache, quotient.adjacency, membership)
                    dense = dense_aggregate(matrix, membership)
                    self.assertEqual(quotient.adjacency.toarray().tolist(), dense)
                    self.assertEqual(aggregate_integer_rows(cache, membership),
                                     tuple(tuple((v, w) for v, w in enumerate(row) if w) for row in dense))
                    current_labels = tuple(rng.randrange(-3, 4) for _ in range(quotient_cache.n))
                    lifted = tuple(current_labels[v] for v in membership)
                    q = dense_q(matrix, lifted, gamma)
                    self.assertEqual(integer_modularity(quotient_cache, current_labels, gamma), q)
                    self.assertEqual(modularity_exact(quotient.adjacency, current_labels, gamma), q)

    def test_full_loop_mass_large_python_integers_and_nonrepresentable_aggregate(self):
        path = sparse.csr_matrix([[0, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0]], dtype=float)
        quotient = quotient_adjacency(path, ((0, 1), (2, 3)), require_exact=True)
        cache = prepare_integer_objective(quotient.adjacency)
        self.assertEqual(quotient.adjacency.toarray().tolist(), [[2, 1], [1, 2]])
        self.assertEqual(cache.degrees, (3, 3))
        self.assertEqual(cache.total, 6)
        graph = networkx_quotient(quotient.adjacency)
        self.assertEqual(graph[0][0]["weight"], 1)
        self.assertEqual(graph[1][1]["weight"], 1)
        self.assertEqual(integer_modularity(cache, (0, 1), Fraction(1)), Fraction(1, 6))

        huge = 2 ** 53
        matrix = [[huge, 1], [1, 0]]
        original = sparse.csr_matrix(matrix, dtype=np.int64)
        large = prepare_integer_objective(original)
        self.assertEqual(large.degrees, (huge + 1, 1))
        self.assertGreater(large.total ** 2, 2 ** 63)
        for labels in ((0, 0), (0, 1)):
            self.assertEqual(integer_modularity(large, labels, Fraction(7, 3)),
                             dense_q(matrix, labels, Fraction(7, 3)))
            self.assertEqual(integer_modularity(large, labels, Fraction(7, 3)),
                             modularity_exact(original, labels, Fraction(7, 3)))
        loop = prepare_integer_objective(sparse.csr_matrix([[10.0]]))
        for gamma in (Fraction(0), Fraction(1, 2), Fraction(1), Fraction(3)):
            self.assertEqual(integer_modularity(loop, (73,), gamma), 1 - gamma)

        bad_aggregate = sparse.csr_matrix([[0, 0, huge], [0, 0, 1], [huge, 1, 0]], dtype=np.int64)
        with self.assertRaisesRegex(ArithmeticError, "rounded exact weights"):
            quotient_adjacency(bad_aggregate, ((0, 1),), require_exact=True)
        with self.assertRaises(ArithmeticError):
            prepare_integer_objective(sparse.csr_matrix([[huge + 1]], dtype=np.int64))

    def test_invalid_cache_inputs_are_rejected_and_validity_is_exact(self):
        invalid = (
            sparse.csr_matrix([[0.5]]), sparse.csr_matrix([[float("nan")]]),
            sparse.csr_matrix([[float("inf")]]), sparse.csr_matrix([[-1.0]]),
            sparse.csr_matrix([[0.0]]), sparse.csr_matrix([[0, 1], [2, 0]], dtype=float),
            sparse.csr_matrix((np.asarray([1.0, 2.0]), np.asarray([0, 0]), np.asarray([0, 2])), shape=(1, 1)),
        )
        for adjacency in invalid:
            with self.subTest(data=adjacency.data.tolist()):
                with self.assertRaises((ValueError, ArithmeticError)):
                    prepare_integer_objective(adjacency)
        with self.assertRaises(TypeError):
            prepare_integer_objective(sparse.csc_matrix([[1.0]]))
        cache = prepare_integer_objective(sparse.csr_matrix([[1.0]]))
        for labels, gamma in (((True,), Fraction(1)), ((0, 1), Fraction(1)), ((0,), 1.0), ((0,), Fraction(-1))):
            with self.assertRaises(ValueError):
                integer_modularity(cache, labels, gamma)


class AccountingOrderAndPathsTests(unittest.TestCase):
    def test_complete_case_synthetic_schedule_setup_attribution_and_partial_failure(self):
        # Newly connected run_case integration. The solver is stubbed; actual
        # tiny R/D staging and all 36 scheduled wrapper calls still execute.
        matrix = [[0, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0]]
        context = fixture_context(matrix)
        bank = fixture_bank(((0, 1), (2, 3)), (0, 0, 1, 1))
        # The fixed case name/order is drawn from the expected public ledger;
        # its data remains the explicit four-node matrix above.
        case = CaseKey("ca-GrQc", 1, Fraction(1), 4)
        setup_key = case.setup_key
        setup = {"identity": {"fixture": True, "setup_key": setup_key},
                 "physical_setup_elapsed_seconds": 15.0,
                 "primary_phase_records": [
                     {"phase": phase, "arm": None, "seed": None, "prefix": None,
                      "status": "completed", "applicability": "applicable", "seconds": seconds,
                      "interval_domain": setup_key, "start_offset_seconds": None, "end_offset_seconds": None}
                     for phase, seconds in (("common_original_prepare", 2.0),
                                            ("common_discovery", 10.0), ("fixed_bank_refinement", 3.0))]}
        initial_setup_rows = [dict(row) for row in setup["primary_phase_records"]]
        calls, events = [], []
        class TickClock:
            def __init__(self):
                self.value = 0.0
            def __call__(self):
                value = self.value
                self.value += 0.01
                return value
        def fake_solver(graph, adjacency, gamma, seed):
            labels = (0,) * adjacency.shape[0]
            calls.append(seed)
            return labels, {"modularity": float(dense_q(adjacency.toarray().tolist(), labels, gamma)),
                            "solver_seconds": 999.0, "label_conversion_seconds": 999.0,
                            "objective_evaluation_seconds": 999.0, "fixture_stub": True}
        with patch.object(runner, "solve_louvain", side_effect=fake_solver):
            result = runner.run_case(case, context, bank, setup, {"fixture_identity": True},
                                     clock=TickClock(), event_callback=events.append)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed_solver_calls"], 36)
        self.assertEqual(result["scheduled_solver_calls"], 36)
        self.assertEqual(calls, [seed for seed in range(10, 19) for _ in range(4)])
        expected_seed_events = [(arm, 10 + r) for r in range(9) for arm in seed_arm_order(4, r)]
        self.assertEqual([(event["arm"], event["seed"]) for event in events if event["phase"] == "seed_completed"],
                         expected_seed_events)
        self.assertEqual([event["arm"] for event in events if event["phase"] == "arm_prepared"],
                         list(preprocessing_order(4)))
        self.assertEqual(setup["primary_phase_records"], initial_setup_rows)
        self.assertEqual(result["per_arm_peak_memory"], "not_measured")
        self.assertEqual(result["prefix_summary_count"], 12)
        self.assertEqual(result["discovery_original_Q_exact"], rational_record(Fraction(1, 6)))
        for arm in ARMS:
            records = result["arms"][arm]
            self.assertEqual(len(records["seed_results"]), 9)
            self.assertEqual(len(records["prefixes"]), 3)
            for prefix in records["prefixes"]:
                cost = prefix["cost"]
                self.assertAlmostEqual(cost["common_seconds"], 12.01)
                self.assertEqual(cost["fixed_bank_refinement_seconds"], 0 if arm == "U" else 3)
                self.assertAlmostEqual(cost["seed_compute_seconds"], 0.03 * prefix["prefix"])
                self.assertAlmostEqual(cost["prefix_finalize_seconds"], 0.01)
                self.assertLess(cost["constructed_standalone_seconds"], 20)
                self.assertEqual(prefix["returned_original_labels"], list(bank.discovery_labels))

        progress = {}
        failed_calls = []
        def fail_second_call(graph, adjacency, gamma, seed):
            failed_calls.append(seed)
            if len(failed_calls) == 2:
                raise ArithmeticError("synthetic new-path solver failure")
            return fake_solver(graph, adjacency, gamma, seed)
        with patch.object(runner, "solve_louvain", side_effect=fail_second_call):
            with self.assertRaisesRegex(ArithmeticError, "synthetic new-path"):
                runner.run_case(case, context, bank, setup, {"fixture_identity": True},
                                progress=progress, clock=TickClock())
        partial = progress["raw_record"]
        self.assertEqual(len(failed_calls), 2)
        self.assertNotEqual(partial["status"], "completed")
        self.assertNotIn("completed_solver_calls", partial)
        self.assertEqual(partial["primary_phase_records"][-1]["status"], "failed")
        attempted_records = [row for arm in partial["arms"].values() for row in arm["seed_results"]]
        self.assertEqual(len(attempted_records), 2)
        self.assertEqual(sum(row["status"] == "completed" for row in attempted_records), 1)
        self.assertTrue(all(not arm["prefixes"] for arm in partial["arms"].values()))

        # One bounded source-collection integration, entirely in a disposable
        # engineering directory. Real frozen-source validation is bypassed by
        # an explicit test-only stub; all collector record validators execute.
        config = {"datasets": ["ca-GrQc", "ca-HepTh", "email-Eu-core", "facebook_combined", "ca-CondMat", "p2p-Gnutella08"],
                  "discovery_seeds": [0, 1, 2], "gamma": ["1/2", "1", "2"],
                  "arms": ["U", "D", "R", "RD"], "downstream_seeds": list(range(10, 19)), "prefixes": [1, 3, 9]}
        expected = expected_ledger(config)
        self.assertEqual(expected["cases"][4]["case_key"], case.key)
        with tempfile.TemporaryDirectory(prefix="public-v2-independent-collection-") as directory:
            directory = Path(directory)
            run_dir = directory / "synthetic-run"
            run_dir.mkdir()
            config_path, freeze_path = directory / "config.json", directory / "freeze.json"
            archive_path = directory / "archived-fixture-bank.json"
            archived = {"blocks": [list(block) for block in bank.blocks], "discovery_labels": list(bank.discovery_labels),
                        "bank_sha256": bank.identity_sha256, "dataset": context.metadata}
            write_once(archive_path, archived)
            synthetic_freeze = {"runtime_source_sha256": {}, "expected_ledger": expected,
                                "expected_ledger_sha256": content_hash(expected), "versions": {"fixture": True},
                                "archived_bank_identity": {case.setup_key: {"path": str(archive_path),
                                                                           "sha256": sha256(archive_path)}}}
            write_once(config_path, config)
            write_once(freeze_path, synthetic_freeze)
            identity = {"config_sha256": sha256(config_path), "freeze_sha256": sha256(freeze_path),
                        "runtime_source_manifest_sha256": content_hash({}),
                        "expected_ledger_sha256": content_hash(expected), "versions": {"fixture": True}}
            manifest = {"schema_version": result["schema_version"], **identity,
                        "runtime_source_sha256": {}, "expected_ledger": expected}
            write_once(run_dir / "run-manifest.json", manifest)
            setup_record = {"schema_version": result["schema_version"], **identity, "status": "completed",
                            "setup_key": case.setup_key, "dataset": case.dataset, "discovery_seed": case.discovery_seed,
                            "fixed_bank": {**archived, "discovery_partition_sha256": content_hash(canonical_partition(bank.discovery_labels))},
                            "dataset_metadata": context.metadata,
                            "archived_v1_bank_reference": synthetic_freeze["archived_bank_identity"][case.setup_key],
                            "original": {"graph_counts": {"vertices": 4}, "degrees_exact": [1, 2, 2, 1], "S_exact": 6}}
            setup_path = run_dir / f"{case.setup_key}-setup.json.gz"
            write_once(setup_path, setup_record)
            write_once(run_dir / f"{case.setup_key}-setup-completed.json", {
                "schema_version": result["schema_version"], **identity, "status": "completed",
                "record": {"path": str(setup_path), "sha256": sha256(setup_path)}})
            result.update(identity)
            result["setup_reference"] = {"path": str(setup_path), "sha256": sha256(setup_path), "setup_key": case.setup_key}
            collector.validate_case(result, expected["cases"][4], setup_record, manifest)
            damaged = deepcopy(result)
            damaged["arms"]["R"]["seed_results"][0]["raw_original_labels"][0] = 99
            with self.assertRaisesRegex(ValueError, "wrong IDs"):
                collector.validate_case(damaged, expected["cases"][4], setup_record, manifest)
            with self.assertRaisesRegex(ValueError, "partial/failed case"):
                collector.validate_case({**result, "status": "failed"}, expected["cases"][4], setup_record, manifest)
            case_path = run_dir / f"{case.key}.json.gz"
            write_once(case_path, result)
            write_once(run_dir / f"{case.key}-completed.json", {"schema_version": result["schema_version"], **identity,
                                                               "status": "completed", "record": {"path": str(case_path),
                                                                                                     "sha256": sha256(case_path)}})
            for sequence, event in enumerate(events, 1):
                write_once(run_dir / f"{case.key}-progress-{sequence:03d}.json", {
                    "schema_version": result["schema_version"], **identity, "sequence": sequence, **event})
            failed_case = expected["cases"][5]
            write_once(run_dir / f"{failed_case['case_key']}-failed-partial.json.gz", {
                "schema_version": result["schema_version"], **identity, "status": "failed",
                "case_key": failed_case["case_key"], "synthetic_fixture_failure": True})
            write_once(run_dir / "run-failed.json", {"schema_version": result["schema_version"], **identity,
                                                      "status": "halted_for_recorded_source_repair"})
            with patch.object(collector, "validate_freeze", return_value=(config, synthetic_freeze)):
                collected = collector.collect_records(config_path, freeze_path, run_dir, directory / "collection")
            self.assertEqual(collected["status"], "partial_with_failure_denominators")
            self.assertEqual(collected["case_status_counts"], {"not_executed": 52, "completed": 1, "failed": 1})
            self.assertEqual(collected["seed_execution_rows"], 1944)
            self.assertEqual(collected["table_rows"], {"arm_prefix_rows": 648, "paired_comparison_rows": 810})
            self.assertEqual(collected["seed_execution_status_counts"], {
                "not_executed": 1872, "completed": 36, "unavailable_after_case_failure": 36})
            table = read_json(directory / "collection" / "tables.json")
            self.assertEqual(sum(row["status"] == "completed" for row in table["arm_prefix_rows"]), 12)
            self.assertEqual(sum(row["status"] == "completed" for row in table["paired_comparison_rows"]), 15)
            self.assertEqual(sum(row["status"] == "unavailable" for row in table["paired_comparison_rows"]), 795)
            self.assertEqual(sum(row["eligible_for_completed_case_metrics"] for row in table["seed_execution_rows"]), 36)
            self.assertTrue(all(row["quality_matched_speedup_B_over_A"] is None
                                for row in table["paired_comparison_rows"] if row["status"] == "unavailable"))
            with patch.object(collector, "validate_freeze", return_value=(config, synthetic_freeze)):
                with self.assertRaises(FileExistsError):
                    collector.collect_records(config_path, freeze_path, run_dir, directory / "collection")
            write_once(run_dir / "unlisted-repeat.json", {"status": "completed", "fixture": True})
            with patch.object(collector, "validate_freeze", return_value=(config, synthetic_freeze)):
                with self.assertRaisesRegex(ValueError, "unexpected raw path"):
                    collector.collect_records(config_path, freeze_path, run_dir, directory / "rejected-collection")
            self.assertFalse((directory / "rejected-collection").exists())

    def test_disjoint_outer_costs_include_full_rd_and_exclude_reports(self):
        clock = MutableClock()
        ledger = PhaseLedger(clock)
        def add(phase, duration, arm=None, seed=None, prefix=None):
            with ledger.measure(phase, arm=arm, seed=seed, prefix=prefix) as row:
                row["nested_source_seconds_not_added"] = 1000.0
                clock.advance(duration)
        add("common_original_prepare", 2)
        clock.advance(20)
        diagnostics = ledger.attribute_candidate_call(20, 5, 12)
        add("common_discovery_evaluate", 3)
        self.assertEqual(diagnostics["B_minus_F_seconds"], 15)
        self.assertEqual(diagnostics["source_residual_overhead_seconds"], 3)
        phase_amounts = {
            "U": {"arm_solver_prepare": 1},
            "D": {"degree_prepare_check": 2, "degree_contract_validate": 3, "arm_solver_prepare": 1},
            "R": {"recursive_prefix": 10, "recursive_csr_reconstruct_validate": 2, "arm_solver_prepare": 1},
            "RD": {"recursive_prefix": 11, "recursive_csr_reconstruct_validate": 2,
                   "mapped_bank_prepare": 3, "degree_prepare_check": 4, "degree_contract_validate": 5,
                   "r_prefix_cross_arm_validate": 6, "arm_solver_prepare": 1},
        }
        seeds = tuple(range(10, 19))
        for arm in ARMS:
            for phase in ARM_PHASES:
                if phase in phase_amounts[arm]:
                    add(phase, phase_amounts[arm][phase], arm=arm)
                else:
                    ledger.not_applicable(phase, arm)
            for seed in seeds:
                add("seed_solve_and_float_validate", 2, arm=arm, seed=seed)
                add("seed_lift_exact_validate", 3, arm=arm, seed=seed)
                add("seed_select_materialize", 4, arm=arm, seed=seed)
            for prefix in (1, 3, 9):
                add("prefix_finalize", prefix / 10, arm=arm, prefix=prefix)
        expected_preparation = {"U": 1, "D": 6, "R": 13, "RD": 32}
        before = {}
        for arm, prefix in itertools.product(ARMS, (1, 3, 9)):
            cost = standalone_cost(ledger, arm, prefix, seeds)
            expected = 20 + (0 if arm == "U" else 5) + expected_preparation[arm] + 9 * prefix + prefix / 10
            self.assertAlmostEqual(cost["constructed_standalone_seconds"], expected)
            self.assertEqual(cost["common_seconds"], 20)
            self.assertEqual(cost["fixed_bank_refinement_seconds"], 0 if arm == "U" else 5)
            self.assertEqual(cost["arm_preparation_seconds"], expected_preparation[arm])
            before[(arm, prefix)] = cost
        clock.advance(100)  # Output/report-only interval has no primary phase.
        self.assertEqual(before, {(arm, prefix): standalone_cost(ledger, arm, prefix, seeds)
                                  for arm, prefix in itertools.product(ARMS, (1, 3, 9))})
        actual = [row for row in ledger.records if row.get("start_offset_seconds") is not None]
        for previous, current in zip(actual, actual[1:]):
            self.assertLessEqual(previous["end_offset_seconds"], current["start_offset_seconds"])
        with ledger.measure("common_original_prepare"):
            with self.assertRaisesRegex(ValueError, "nested primary"):
                with ledger.measure("common_discovery"):
                    pass
        with self.assertRaises(ArithmeticError):
            ledger.attribute_candidate_call(2, 3, 0)
        with self.assertRaises(ArithmeticError):
            ledger.attribute_candidate_call(20, 5, 16)
        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            with ledger.measure("degree_prepare_check", arm="D"):
                clock.advance(7)
                raise RuntimeError("fixture failure")
        self.assertEqual(ledger.records[-1]["status"], "failed")
        self.assertEqual(ledger.sum(("degree_prepare_check",), arm="D"), 2)

    def test_fixed_complete_grid_order_and_exclusive_raw_records(self):
        config = {"datasets": ["ca-GrQc", "ca-HepTh", "email-Eu-core", "facebook_combined", "ca-CondMat", "p2p-Gnutella08"],
                  "discovery_seeds": [0, 1, 2], "gamma": ["1/2", "1", "2"],
                  "arms": ["U", "D", "R", "RD"], "downstream_seeds": list(range(10, 19)), "prefixes": [1, 3, 9]}
        ledger = expected_ledger(config)
        self.assertEqual(ledger["counts"], {"setups": 18, "cases": 54, "arm_states": 216,
                                             "executions": 1944, "prefixes": 648})
        all_calls = {(row["case_key"], row["arm"], row["seed"]) for row in ledger["executions"]}
        expected_calls = {(row["case_key"], arm, seed) for row in ledger["cases"]
                          for arm in ("U", "D", "R", "RD") for seed in range(10, 19)}
        self.assertEqual(all_calls, expected_calls)
        self.assertEqual(len({row["execution_key"] for row in ledger["executions"]}), 1944)
        self.assertEqual(len({row["prefix_key"] for row in ledger["prefixes"]}), 648)
        fixed = ("U", "D", "R", "RD")
        for j, case in enumerate(ledger["cases"]):
            expected_prepare = tuple(fixed[(j + offset) % 4] for offset in range(4))
            self.assertEqual(preprocessing_order(j), expected_prepare)
            self.assertEqual(tuple(case["preprocessing_order"]), expected_prepare)
            for r, seed_row in enumerate(case["downstream_order"]):
                order = tuple(fixed[(j + r + offset) % 4] for offset in range(4))
                expected = order if (j // 4) % 2 == 0 else order[::-1]
                self.assertEqual(seed_arm_order(j, r), expected)
                self.assertEqual(tuple(seed_row["arms"]), expected)
                self.assertEqual(seed_row["seed"], 10 + r)
        altered = {**config, "downstream_seeds": [10]}
        with self.assertRaises(ValueError):
            expected_ledger(altered)
        with tempfile.TemporaryDirectory(prefix="public-v2-independent-") as directory:
            for name in ("partial.json", "partial.json.gz"):
                path = Path(directory) / name
                record = {"status": "failed", "expected_calls": 1944, "completed_calls": 1,
                          "failed_calls": 1, "not_executed_calls": 1942, "reason": "synthetic fixture"}
                write_once(path, record)
                original = path.read_bytes()
                self.assertEqual(read_json(path), record)
                with self.assertRaises(FileExistsError):
                    write_once(path, {"status": "completed"})
                self.assertEqual(path.read_bytes(), original)

    def test_actual_stage_policy_fresh_prefixes_and_edge_paths(self):
        context = fixture_context([[0, 1, 1], [1, 0, 1], [1, 1, 0]])
        bank = fixture_bank((), (0, 1, 2))
        gamma = Fraction(3)
        ledger = PhaseLedger()
        with patch.object(stages, "recursive_cheap", wraps=recursive_cheap) as recursive_called:
            states = {arm: stages.prepare_arm(context, bank, gamma, arm, ledger) for arm in ("RD", "R", "D", "U")}
        self.assertEqual(recursive_called.call_count, 2)
        for call in recursive_called.call_args_list:
            self.assertEqual(call.args, (context.adjacency, bank.blocks, gamma))
            self.assertEqual(call.kwargs, {"max_block_size": 64, "include_round_decisions": False})
        self.assertIsNot(states["R"].provenance["recursive_result"], states["RD"].provenance["recursive_result"])
        stages.validate_r_prefixes(states, ledger)
        for state in states.values():
            self.assertEqual(canonical_partition(state.membership), (0, 1, 2))
        self.assertEqual(states["RD"].provenance["degree_stage"]["accepted_count"], 0)
        self.assertEqual(states["RD"].provenance["additional_removed_vertices_after_r"], 0)
        self.assertEqual(states["RD"].provenance["mapped_bank"]["summary"]["complete_original_bank_count"], 0)
        full_bank = fixture_bank(((0, 1, 2),), (0, 0, 0))
        with patch.object(stages, "certify_block", wraps=certify_block) as degree_called:
            full = stages.prepare_arm(context, full_bank, Fraction(1, 2), "D", PhaseLedger())
        self.assertEqual(full.objective.n, 1)
        self.assertGreater(full.adjacency[0, 0], 0)
        self.assertEqual(degree_called.call_count, 1)
        self.assertEqual(degree_called.call_args.args[1:], ((0, 1, 2), Fraction(1, 2)))
        self.assertEqual(degree_called.call_args.kwargs, {"verification": "auto", "exact_max_size": 64,
                                                        "dense_max_size": 64, "screen_tolerance": 1e-10})

        # R does contract its strong pair, while the subsequent bank image
        # includes isolates; degree abstention leaves the R quotient intact.
        sparse_context = fixture_context([[0, 0, 0, 0], [0, 0, 3, 0], [0, 3, 0, 0], [0, 0, 0, 0]])
        sparse_bank = fixture_bank(((0, 1, 2, 3),), (0, 1, 1, 2))
        rd = stages.prepare_arm(sparse_context, sparse_bank, Fraction(1), "RD", PhaseLedger())
        self.assertEqual(rd.objective.n, 3)
        self.assertEqual(rd.provenance["degree_stage"]["accepted_count"], 0)
        self.assertEqual(rd.provenance["additional_removed_vertices_after_r"], 0)

    def test_nine_real_unchanged_one_node_positive_loop_calls(self):
        context = fixture_context([[0, 5], [5, 0]])
        bank = fixture_bank(((0, 1),), (0, 0))
        quotient = quotient_adjacency(context.adjacency, ((0, 1),), require_exact=True)
        self.assertEqual(quotient.adjacency.toarray().tolist(), [[10.0]])
        cache = prepare_integer_objective(quotient.adjacency)
        state = ArmState("RD", quotient.adjacency, (0, 0), networkx_quotient(quotient.adjacency), cache)
        ledger = PhaseLedger()
        with patch.object(runner, "solve_louvain", wraps=solve_louvain) as real_called:
            for seed in range(10, 19):
                result = runner.run_seed(context, bank, state, Fraction(1), seed, Fraction(0), ledger)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["raw_solver_labels"], [0])
                self.assertEqual(result["raw_original_labels"], [0, 0])
                self.assertEqual(rational_value(result["raw_original_Q_exact"]), 0)
        self.assertEqual(real_called.call_count, 9)
        self.assertEqual([call.args[3] for call in real_called.call_args_list], list(range(10, 19)))
        self.assertTrue(all(len(call.args) == 4 and not call.kwargs for call in real_called.call_args_list))
        self.assertEqual(len(state.seed_results), 9)
        for prefix in (1, 3, 9):
            result = runner.finalize_prefix(bank, state, Fraction(0), prefix)
            self.assertEqual(result["winner_kind"], "discovery")
            self.assertEqual(result["fallback_count"], prefix)
        self.assertEqual(len(ledger.records), 27)
        for row in ledger.records:
            self.assertGreaterEqual(row["seconds"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
