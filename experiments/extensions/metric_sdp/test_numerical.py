"""Small independent encodings for the author's new numerical critical path."""
from fractions import Fraction
import time
import unittest

import numpy as np

from .numerical import build_problem, separate_triangles, solve_component
from .runtime import Ledger, coefficient_matrix, signed_components
from .run_pilot import select_backend
from scipy import sparse


POLICY = {"max_rounds": 50, "eps_sequence": [1e-6, 1e-7, 1e-8],
          "max_iters": 1000000, "addition_threshold": 1e-7,
          "cuts_per_round": 5000, "rational_denominator": 2 ** 40}


class NumericalCriticalPath(unittest.TestCase):
    def test_all_three_metric_orientations_and_bounded_ties(self):
        triples = ((0, 1, 2), (1, 0, 2), (0, 2, 1))
        for key in triples:
            y = np.eye(3)
            i, j, k = key
            y[i, j] = y[j, i] = y[j, k] = y[k, j] = 0.9
            y[i, k] = y[k, i] = 0.1
            answer = separate_triangles(y, limit=1)
            self.assertEqual(answer["add"], [key])
            self.assertAlmostEqual(answer["maximum_raw_violation"], 0.7)
            self.assertEqual(separate_triangles(y, active={key})["add"], [])

    def test_hand_encoded_objective_and_metric_optimum_both_backends(self):
        # Directly encoded independently of coefficient_matrix:
        # path-Laplacian dual with triangle lambda22/529 and y=(0,-22/529,0).
        c = tuple(tuple(Fraction(x, 529) for x in row) for row in
                  ((-98, 109, -11), (109, -121, 12), (-11, 12, -1)))
        _, actual, _, total = coefficient_matrix(
            sparse.csr_matrix([[1, 10, 0], [10, 0, 1], [0, 1, 0]]), Fraction(1))
        self.assertEqual(total, 23)
        self.assertEqual(actual, c)
        for backend in ("direct", "indirect"):
            ledger = Ledger()
            result = solve_component(c, backend=backend, width_target=Fraction(1, 1000000),
                                     deadline=time.perf_counter() + 60,
                                     stage=ledger.measure, policy=POLICY)
            self.assertEqual(result["status"], "verified_target")
            interval = result["interval"]
            self.assertLessEqual(interval.lower, 0)
            self.assertGreaterEqual(interval.upper, 0)
            self.assertLessEqual(interval.width, Fraction(1, 1000000))
            # This test's tight target forces the metric-specific active cut.
            self.assertTrue(any(x["active_triangles"] > 0 for x in result["rounds"]))

    def test_backend_eligibility_precedes_small_case_completion(self):
        config = {"pilot": {"sentinels": ["small", "medium", "large"],
                            "backends": ["direct", "indirect"], "wall_seconds": 180}}
        entries = [{"backend": backend, "case_id": case,
                    "credited_verified_target": (
                        (backend == "direct" and case != "large") or
                        (backend == "indirect" and case == "large")),
                    "full_compute_seconds": 1}
                   for backend in ("direct", "indirect")
                   for case in ("small", "medium", "large")]
        winner, summaries = select_backend(entries, config)
        self.assertEqual(winner, "indirect")
        self.assertFalse(summaries["direct"]["eligible"])

    def test_signed_component_control_keeps_zero_cross_coefficients(self):
        c = ((Fraction(0), Fraction(1), Fraction(0)),
             (Fraction(1), Fraction(0), Fraction(-1)),
             (Fraction(0), Fraction(-1), Fraction(2)))
        self.assertEqual(signed_components(c), [[0, 1], [2]])


if __name__ == "__main__":
    unittest.main()
