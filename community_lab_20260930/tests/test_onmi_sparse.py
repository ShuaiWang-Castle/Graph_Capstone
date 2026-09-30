"""Synthetic equivalence checks for the offline sparse ONMI evaluator only."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.metrics_onmi import compute_onmi, SOURCE_RELATIVE
from lab.metrics_onmi_sparse import compute_onmi_sparse

RANDOM_EQUIVALENCE = {"random_seed": 20260930, "trials": 0, "scored": 0,
                      "undefined": 0, "max_absolute_error": 0.0,
                      "abs_tolerance": 1e-12, "actual_baseline_labels_read": False}


@unittest.skipUnless((ROOT / SOURCE_RELATIVE).is_file(), "Pinned NOCD source not yet fetched")
class SparseOverlappingNMITests(unittest.TestCase):
    def compare(self, truth, pred, n):
        dense = compute_onmi(truth, pred, n)
        sparse = compute_onmi_sparse(truth, pred, n)
        self.assertEqual(dense["onmi_status"], sparse["onmi_status"])
        self.assertEqual(dense["normalization_audit"], sparse["normalization_audit"])
        if dense["onmi"] is None:
            self.assertIsNone(sparse["onmi"])
        else:
            self.assertAlmostEqual(dense["onmi"], sparse["onmi"], delta=1e-12)
        return dense, sparse

    def test_perfect_and_community_permutation(self):
        truth = [{0, 1, 2}, {2, 3, 4}]
        for pred in (truth, list(reversed(truth))):
            _, sparse = self.compare(truth, pred, 6)
            self.assertEqual(sparse["onmi"], 1.)

    def test_complement(self):
        _, sparse = self.compare([{0, 1, 2}], [{3, 4, 5}], 6)
        self.assertEqual(sparse["onmi"], 0.)

    def test_empty_and_zero_entropy(self):
        for truth, pred, n in [([], [{0, 1}], 4), ([{0, 1}], [], 4),
                               ([{0, 1}], [[], []], 4),
                               ([{0, 1, 2}], [{0, 1, 2}], 3)]:
            self.compare(truth, pred, n)

    def test_full_group_against_nonconstant_group(self):
        self.compare([{0, 1, 2, 3}], [{0, 1}], 4)
        self.compare([{0, 1}], [{0, 1, 2, 3}], 4)

    def test_duplicate_groups_and_within_duplicates(self):
        self.compare([[0, 0, 1], [2, 3]], [[0, 1], [0, 1], [2, 3]], 5)

    def test_shared_node_relabelling(self):
        truth, pred = [{0, 1, 2}, {2, 3, 4}], [{0, 1}, {1, 2, 4}]
        base = compute_onmi_sparse(truth, pred, 6)["onmi"]
        perm = {0: 5, 1: 4, 2: 3, 3: 2, 4: 1, 5: 0}
        result = compute_onmi_sparse([{perm[i] for i in c} for c in truth],
                                     [{perm[i] for i in c} for c in pred], 6)
        self.assertAlmostEqual(result["onmi"], base, delta=1e-12)

    def test_no_n_by_community_dense_allocation(self):
        original_zeros = np.zeros
        def guarded_zeros(shape, *args, **kwargs):
            if isinstance(shape, tuple) and len(shape) > 1:
                raise AssertionError("A multidimensional dense zeros allocation is forbidden")
            return original_zeros(shape, *args, **kwargs)
        with patch("lab.metrics_onmi_sparse.np.zeros", side_effect=guarded_zeros):
            result = compute_onmi_sparse([{0, 1, 2}, {2, 3, 4}], [{0, 1}, {1, 2, 4}], 6)
        self.assertEqual(result["onmi_status"], "SCORED")

    def test_no_dense_five_million_pair_guard(self):
        # Six million implicit pairs, no real graph or developer labels. Only a
        # tiny sparse intersection and per-row vectors are needed. Covers retain
        # duplicates on purpose; their score is compared to the analytic same-
        # size-group formula at smaller dimensions checked against the source.
        truth = [{i} for i in range(2000)]
        pred = [{i} for i in range(3000)]
        result = compute_onmi_sparse(truth, pred, 5000)
        self.assertEqual(result["community_pairs"], 6_000_000)
        self.assertEqual(result["intersection_nnz"], 2000)
        self.assertEqual(result["onmi_status"], "SCORED")
        self.assertAlmostEqual(result["onmi"], 2/3, delta=1e-12)

    def test_invalid_nodes(self):
        with self.assertRaises(ValueError):
            compute_onmi_sparse([{0, 1}], [{4}], 4)

    def test_source_unavailable_or_changed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"source.py"
            self.assertEqual(compute_onmi_sparse([{0, 1}], [{0, 1}], 4, source_path=p)["onmi_status"], "UNAVAILABLE_PINNED_SOURCE")
            p.write_text("# incompatible source\n")
            with self.assertRaises(ValueError):
                compute_onmi_sparse([{0, 1}], [{0, 1}], 4, source_path=p)

    def test_symmetry(self):
        truth, pred = [{0, 1, 2}, {2, 3, 4}], [{0, 1}, {1, 2, 4}]
        self.assertAlmostEqual(compute_onmi_sparse(truth, pred, 6)["onmi"],
                               compute_onmi_sparse(pred, truth, 6)["onmi"], delta=1e-12)

    def test_two_thousand_random_covers_agree_with_pinned_dense_source(self):
        rng = np.random.default_rng(20260930)
        for _ in range(2000):
            n = int(rng.integers(2, 65))
            counts = [int(rng.integers(0, 13)), int(rng.integers(0, 13))]
            covers = []
            for count in counts:
                p = float(rng.choice([0., .05, .2, .5, .8, .95, 1.]))
                cover = [[int(node) for node in np.flatnonzero(rng.random(n) < p)] for __ in range(count)]
                if cover and rng.random() < .2:
                    cover.append(cover[0][:])  # Across-group duplicates retained.
                if cover and cover[0] and rng.random() < .2:
                    cover[0].append(cover[0][0])  # Within duplicates normalized.
                covers.append(cover)
            dense, sparse = self.compare(*covers, n)
            RANDOM_EQUIVALENCE["trials"] += 1
            if dense["onmi"] is None:
                RANDOM_EQUIVALENCE["undefined"] += 1
            else:
                RANDOM_EQUIVALENCE["scored"] += 1
                RANDOM_EQUIVALENCE["max_absolute_error"] = max(RANDOM_EQUIVALENCE["max_absolute_error"], abs(dense["onmi"]-sparse["onmi"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
