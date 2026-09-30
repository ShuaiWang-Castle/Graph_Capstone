"""Small artificial cover checks only, not baseline/algorithm performance tests."""
from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.metrics_onmi import compute_onmi, _load_exact_function, SOURCE_SHA256, SOURCE_RELATIVE, VARIANT


@unittest.skipUnless((ROOT / SOURCE_RELATIVE).is_file(), "Pinned NOCD source not yet fetched")
class OverlappingNMITests(unittest.TestCase):
    def test_perfect_overlapping_cover(self):
        result = compute_onmi([{0, 1, 2}, {2, 3, 4}], [{0, 1, 2}, {2, 3, 4}], 6)
        self.assertEqual(result["onmi_status"], "SCORED")
        self.assertAlmostEqual(result["onmi"], 1.0)
        self.assertEqual(result["variant"], VARIANT)
        self.assertEqual(result["source_sha256_observed"], SOURCE_SHA256)

    def test_community_label_permutation(self):
        result = compute_onmi([{0, 1, 2}, {2, 3, 4}], [{2, 3, 4}, {0, 1, 2}], 6)
        self.assertAlmostEqual(result["onmi"], 1.0)

    def test_common_node_permutation(self):
        truth = [{0, 1, 2}, {2, 3, 4}]
        pred = [{0, 1}, {1, 2, 4}]
        perm = {0: 5, 1: 4, 2: 3, 3: 2, 4: 1, 5: 0}
        reference = compute_onmi(truth, pred, 6)["onmi"]
        result = compute_onmi([{perm[i] for i in c} for c in truth], [{perm[i] for i in c} for c in pred], 6)
        self.assertAlmostEqual(result["onmi"], reference)

    def test_complement_is_not_perfect(self):
        # One cover {0,1,2}, the other its exact complement; unlike partition NMI.
        result = compute_onmi([{0, 1, 2}], [{3, 4, 5}], 6)
        self.assertEqual(result["onmi_status"], "SCORED")
        self.assertAlmostEqual(result["onmi"], 0.0)

    def test_empty_prediction_is_explicitly_undefined(self):
        result = compute_onmi([{0, 1}], [], 4)
        self.assertIsNone(result["onmi"])
        self.assertEqual(result["onmi_status"], "UNDEFINED_EMPTY_COVER")

    def test_empty_truth_is_explicitly_undefined(self):
        result = compute_onmi([], [{0, 1}], 4)
        self.assertIsNone(result["onmi"])
        self.assertEqual(result["onmi_status"], "UNDEFINED_EMPTY_COVER")

    def test_empty_groups_do_not_create_a_fake_community(self):
        result = compute_onmi([{0, 1}], [[], []], 4)
        self.assertEqual(result["onmi_status"], "UNDEFINED_EMPTY_COVER")
        self.assertEqual(result["normalization_audit"]["prediction"]["empty_groups_removed"], 2)

    def test_zero_entropy_is_not_filled_with_one(self):
        result = compute_onmi([{0, 1, 2}], [{0, 1, 2}], 3)
        self.assertIsNone(result["onmi"])
        self.assertEqual(result["onmi_status"], "UNDEFINED_ZERO_ENTROPY")

    def test_explicit_node_universe_keeps_uncovered_nodes(self):
        truth = [{0, 1, 2}]
        pred = [{0, 1}]
        self.assertNotEqual(compute_onmi(truth, pred, 4)["onmi"], compute_onmi(truth, pred, 8)["onmi"])

    def test_invalid_nodes_rejected(self):
        with self.assertRaises(ValueError):
            compute_onmi([{0, 1}], [{4}], 4)

    def test_duplicate_predicted_groups_retained(self):
        result = compute_onmi([{0, 1}], [{0, 1}, {0, 1}], 4)
        self.assertEqual(result["normalization_audit"]["prediction"]["duplicate_groups_retained"], 1)
        self.assertLess(result["onmi"], 1.0)

    def test_source_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "supervised.py"
            path.write_text("def overlapping_nmi(X,Y):\n    return 1.0\n")
            with self.assertRaises(ValueError):
                compute_onmi([{0, 1}], [{0, 1}], 4, source_path=path)

    def test_missing_source_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            result = compute_onmi([{0, 1}], [{0, 1}], 4, source_path=Path(td)/"missing.py")
            self.assertIsNone(result["onmi"])
            self.assertEqual(result["onmi_status"], "UNAVAILABLE_PINNED_SOURCE")

    def test_symmetry(self):
        truth = [{0, 1, 2}, {2, 3, 4}]
        pred = [{0, 1}, {1, 2, 4}]
        self.assertAlmostEqual(compute_onmi(truth, pred, 6)["onmi"], compute_onmi(pred, truth, 6)["onmi"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
