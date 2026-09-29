"""Only new callback/orchestration engineering concerns, explicit n<=6.

The old author suite, scientific inputs, solver and formal workers are not run.
The comparisons invoke the sealed old function on these small exact fixtures.
"""
from __future__ import annotations

from fractions import Fraction as F
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import numpy as np
from scipy import sparse

from experiments.extensions.metric_sdp import safe_composition as old
from experiments.extensions.metric_sdp.freeze import write_once
from . import composition as new


HERE = Path(__file__).resolve().parent


def adjacency(n, edges=(), loops=()):
    assert n <= 6
    a = np.zeros((n, n), dtype=np.int64)
    for u, v, weight in edges:
        a[u, v] = a[v, u] = weight
    for u, weight in loops:
        a[u, u] = weight
    return sparse.csr_matrix(a)


def two_phase():
    # One exact pair, then a heterogeneous four-cycle collective D/W step.
    # Moving the old remote mass onto the first pair keeps this fixture at n6.
    a = adjacency(6, [(0, 1, 10), (2, 3, 10), (3, 4, 10),
                      (4, 5, 10), (2, 5, 10)], [(0, 100000), (2, 80)])
    return a, [(2, 3, 4, 5)]


def noncontiguous():
    a = adjacency(6, [(0, 4, 10), (1, 2, 1), (2, 3, 1),
                      (3, 5, 1), (1, 5, 1)])
    return a, [(1, 2, 3, 5), tuple(range(6)), (1, 2, 3, 5)]


class CompositionProgress(unittest.TestCase):
    def assert_semantics(self, expected, actual):
        # The unchanged W helper records two measured spans inside its proof
        # metadata. Compare their exact proof fields, not two independent clocks.
        def without_weighted_clocks(value):
            if isinstance(value, dict):
                return {k: without_weighted_clocks(v) for k, v in value.items()
                        if k not in {"assembly_seconds", "verification_seconds"}}
            if isinstance(value, (tuple, list)):
                return [without_weighted_clocks(v) for v in value]
            return value
        self.assertEqual(without_weighted_clocks(expected.operations),
                         without_weighted_clocks(actual.operations))
        self.assertEqual(expected.groups, actual.groups)
        self.assertEqual(expected.membership.tolist(), actual.membership.tolist())
        self.assertEqual(expected.adjacency.toarray().tolist(), actual.adjacency.toarray().tolist())
        self.assertEqual(expected.degrees, actual.degrees)
        self.assertEqual(expected.total_degree, actual.total_degree)
        self.assertEqual(expected.graph.fingerprint, actual.graph.fingerprint)
        ignored = {"schema", "stage_seconds", "outer_call_seconds",
                   "progress_callback_seconds", "progress_policy"}
        self.assertEqual({k: v for k, v in expected.metadata.items() if k not in ignored},
                         {k: v for k, v in actual.metadata.items() if k not in ignored})

    def test_no_progress_preserves_all_four_modes_and_frozen_helper_identity(self):
        for helper in ("_bank", "_mapped_bank", "_merge", "_signed", "_degree_collective",
                       "_weighted_collective", "uniform_collective", "optimized_pair",
                       "prepare_exact_graph", "prepare_graph", "prepare_weighted_reference_graph",
                       "CompositionResult"):
            self.assertIs(getattr(new, helper), getattr(old, helper))
        a, bank = two_phase()
        for mode in ("S", "D", "SD", "SW"):
            expected = old.run_composition(a, bank, mode=mode)
            actual = new.run_composition(a, bank, mode=mode)
            self.assert_semantics(expected, actual)
            self.assertEqual(actual.metadata["progress_callback_seconds"], 0)
            if mode in ("SD", "SW"):
                self.assertEqual([op["stage"] for op in actual.operations],
                                 ["S", "D" if mode == "SD" else "W"])

    def test_callback_sees_valid_actual_noncontiguous_memberships_in_order(self):
        a, bank = noncontiguous()
        expected = old.run_composition(a, bank, F(1, 2), max_block_size=4)
        original = old.prepare_exact_graph(a)
        events = []
        def progress(event):
            json.dumps(event, allow_nan=False)
            self.assertEqual(event["kind"], "accepted_operation")
            op = event["operation"]
            self.assertEqual(op["index"], len(events))
            self.assertLess(op["current_n_after"], op["current_n_before"])
            membership = op["original_membership_after"]
            volumes = [sum((original.degrees[u] for u, v in enumerate(membership) if v == group), F())
                       for group in range(op["current_n_after"])]
            self.assertEqual(list(map(str, volumes)), op["quotient_degrees_exact"])
            self.assertEqual(sum(volumes, F()), F(op["S_exact"]))
            if events:
                self.assertEqual(op["original_membership_before"],
                                 events[-1]["operation"]["original_membership_after"])
                self.assertEqual(op["current_graph_sha256"],
                                 events[-1]["operation"]["quotient_graph_sha256"])
            events.append(event)
        actual = new.run_composition(a, bank, F(1, 2), max_block_size=4, progress=progress)
        self.assert_semantics(expected, actual)
        self.assertEqual([e["operation"] for e in events], list(actual.operations))
        self.assertEqual(events[0]["operation"]["block_current"], [0, 4])
        self.assertEqual(events[1]["operation"]["block_current"], [1, 2, 3, 4])
        self.assertEqual(actual.membership.tolist(), [0, 1, 1, 1, 0, 1])
        self.assertGreater(actual.metadata["progress_callback_seconds"], 0)
        self.assertLessEqual(actual.metadata["progress_callback_seconds"],
                             actual.metadata["outer_call_seconds"])
        self.assertEqual(actual.metadata["progress_callback_seconds"],
                         actual.metadata["stage_seconds"]["progress_callback"])

    def test_callback_payload_mutation_cannot_union_weak_original_endpoints(self):
        a = adjacency(3, [(0, 1, 3), (0, 2, 3)], [(0, 2), (1, 5), (2, 5)])
        bank = [(0, 1, 2)]
        expected = old.run_composition(a, bank, F(3, 4), max_block_size=2)
        seen = []
        def mutate(event):
            seen.append(json.loads(json.dumps(event)))
            event["operation"]["original_membership_after"][0] = 999
            event["operation"]["certificate"]["p"] = "not-a-number"
            event["counts_snapshot"]["pair_checks"] = 9999
            event["completed_phases"].append({"stage": "fake"})
        actual = new.run_composition(a, bank, F(3, 4), max_block_size=2, progress=mutate)
        self.assert_semantics(expected, actual)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["operation"]["certificate"]["p"], "0")
        self.assertFalse(seen[0]["operation"]["certificate"]["strict"])
        self.assertEqual(actual.groups, ((0, 1), (2,)))
        self.assertEqual(actual.metadata["counts"]["uniform_checks"], 1)

    def test_callback_failure_retains_durable_prefix_and_returns_no_partial_result(self):
        a, bank = two_phase()
        expected = old.run_composition(a, bank, mode="SD")
        prefix = HERE / ("formal-composition-author-attempt-fixture-" + uuid.uuid4().hex[:10])
        first = prefix.with_name(prefix.name + "-operation-0000.json")
        failed = prefix.with_name(prefix.name + "-operation-0001.json.partial")
        calls = []
        def writer(event):
            calls.append(event["operation"]["index"])
            if event["operation"]["index"] == 0:
                write_once(first, event)
            else:
                with failed.open("x") as handle:
                    handle.write("injected incomplete JSON")
                raise OSError("injected checkpoint failure")
        with self.assertRaisesRegex(OSError, "injected checkpoint failure"):
            new.run_composition(a, bank, mode="SD", progress=writer)
        self.assertEqual(calls, [0, 1])
        self.assertTrue(failed.exists())
        self.assertEqual(json.loads(first.read_text())["operation"], expected.operations[0])
        self.assertFalse(prefix.with_name(prefix.name + "-operation-0001.json").exists())

    def test_callback_waits_for_composed_degree_and_volume_validation(self):
        a = adjacency(2, [(0, 1, 1)])
        actual_merge = new._merge
        def damaged(graph, vertices):
            result, membership = actual_merge(graph, vertices)
            return SimpleNamespace(n=result.n, degrees=(F(999),), volume=result.volume), membership
        events = []
        with patch.object(new, "_merge", damaged):
            with self.assertRaisesRegex(ArithmeticError, "composed original membership"):
                new.run_composition(a, [], progress=events.append)
        self.assertEqual(events, [])

    def test_noncallable_callback_rejected_without_other_interface_changes(self):
        a = adjacency(2, [(0, 1, 1)])
        with self.assertRaisesRegex(TypeError, "progress must be callable"):
            new.run_composition(a, [], progress=1)
        expected = old.run_composition(a, [], mode="SW")
        actual = new.run_composition(a, [], mode="SW", progress=lambda event: "ignored return value")
        self.assert_semantics(expected, actual)


if __name__ == "__main__":
    unittest.main()
