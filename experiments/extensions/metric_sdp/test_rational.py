"""Small explicit-matrix engineering checks, never paper experiments."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import json
import unittest

from .rational import (
    DEFAULT_DENOMINATOR, Inequality, RationalMatrix, exact_trace,
    interval_from_payload, propose_gram_factor, repair_dual, repair_interval,
    repair_primal, verify_dual, verify_interval, verify_primal,
)


C = tuple(tuple(F(x, 529) for x in row) for row in
          ((-98, 109, -11), (109, -121, 12), (-11, 12, -1)))


def independent_trace(C_exact, Y):
    return sum((C_exact[i][j] * Y[i][j] for i in range(len(C_exact))
                for j in range(len(C_exact))), F(0))


def independent_gram(factor):
    rows = factor.fractions()
    return tuple(tuple(sum((rows[i][k] * rows[j][k] for k in range(len(rows[i]))), F(0))
                       for j in range(len(rows))) for i in range(len(rows)))


def independent_triangle_max(Y):
    q = len(Y)
    return max([F(0)] + [Y[i][j] + Y[j][k] - Y[i][k] - 1
                         for i in range(q) for j in range(q) for k in range(q)
                         if len({i, j, k}) == 3])


def independent_psd_small(test, matrix):
    """All principal minors, with direct determinant formulas for q<=3."""
    q = len(matrix)
    test.assertLessEqual(q, 3)
    test.assertTrue(all(matrix[i][j] == matrix[j][i] for i in range(q) for j in range(q)))
    for i in range(q):
        test.assertGreaterEqual(matrix[i][i], 0)
        for j in range(i):
            test.assertGreaterEqual(matrix[i][i] * matrix[j][j] - matrix[i][j] ** 2, 0)
    if q == 3:
        a, b, c = matrix[0]
        _, d, e = matrix[1]
        _, _, f = matrix[2]
        test.assertGreaterEqual(a * d * f + 2 * b * c * e - a * e * e - d * c * c - f * b * b, 0)


class RationalRepairTests(unittest.TestCase):
    def assert_full_primal(self, proof):
        Y = proof.matrix.fractions()
        independent_psd_small(self, Y)
        self.assertTrue(all(Y[i][i] == 1 for i in range(len(Y))))
        self.assertTrue(all(0 <= x <= 1 for row in Y for x in row))
        self.assertEqual(independent_triangle_max(Y), 0)
        for i in range(len(Y)):
            for j in range(len(Y)):
                for k in range(len(Y)):
                    self.assertLessEqual(Y[i][j] + Y[j][k] - Y[i][k], 1)

    def known_interval(self):
        # This exact C comes from the stated3x3 A, d=(11,11,1), S23.
        # At lambda22/529 and y1=-22/529, the max-dual slack is a path
        # Laplacian with weights98/529 and1/529.  Its value and the all-one
        # primal value are0, proving the exact optimum without a solver.
        slack = ((F(98, 529), F(-98, 529), F(0)),
                 (F(-98, 529), F(99, 529), F(-1, 529)),
                 (F(0), F(-1, 529), F(1, 529)))
        factor = propose_gram_factor([[float(x) for x in row] for row in slack])
        boxes = [Inequality(kind, i, j) for kind in ("lower", "upper")
                 for i, j in ((0, 1), (0, 2), (1, 2))]
        return repair_interval(C, [[1, 1, 1]] * 3, [0, -22 / 529, 0],
                               boxes + [Inequality("triangle", 0, 1, 2)],
                               [0] * 6 + [22 / 529], primal_factor=[[1]] * 3,
                               dual_factor=factor)

    def test_known_full_trace_normalized_max_dual_certificate(self):
        result = self.known_interval()
        self.assertEqual(result.lower, 0)
        self.assertGreaterEqual(result.upper, 0)
        self.assertLess(result.width, F(1, 10**8))
        self.assertTrue(verify_interval(C, result))
        self.assert_full_primal(result.primal)
        independent_psd_small(self, result.dual.slack.fractions())
        alpha = F(result.dual.lambda_numerators[-1], DEFAULT_DENOMINATOR)
        yr = F(result.dual.y_numerators[1], DEFAULT_DENOMINATOR)
        expected_M = ((F(98, 529), alpha / 2 - F(109, 529), -alpha / 2 + F(11, 529)),
                      (alpha / 2 - F(109, 529), yr + F(121, 529), alpha / 2 - F(12, 529)),
                      (-alpha / 2 + F(11, 529), alpha / 2 - F(12, 529), F(1, 529)))
        self.assertEqual(result.dual.model.fractions(), expected_M)
        self.assertEqual(result.upper, yr + alpha + 3 * result.dual.tau)
        self.assertEqual(independent_trace(C, result.primal.matrix.fractions()), result.lower)
        # The unordered-pair sum alone is110/529, so missing diagonal/factor2
        # would not reproduce the independent normalized optimum0.
        self.assertEqual(sum((C[i][j] for i in range(3) for j in range(i)), F(0)), F(110, 529))

    def test_psd_and_missing_triangle_repair(self):
        proof = repair_primal([[1, 1, 0], [1, 1, 1], [0, 1, 1]])
        self.assertEqual(proof.tau_psd, 1)
        self.assertEqual(proof.triangle_violation, 1)
        self.assertEqual(proof.tau, 1)
        self.assertEqual(proof.matrix.fractions(), ((F(1), F(1, 2), F(0)),
                                                  (F(1, 2), F(1), F(1, 2)),
                                                  (F(0), F(1, 2), F(1))))
        self.assert_full_primal(proof)
        self.assertTrue(verify_primal(proof))

    def test_fractional_relaxed_lower_is_not_discrete_upper(self):
        # Rational Gram with two shared1/2 coordinates and two private1/2
        # coordinates per row: diagonal1, offdiagonal1/2, exact PSD.
        G = [[F(1, 2), F(1, 2)] + [F(1, 2) if k // 2 == i else F(0) for k in range(6)]
             for i in range(3)]
        H = [[1 if i == j else F(1, 2) for j in range(3)] for i in range(3)]
        proof = repair_primal(H, factor=G)
        self.assertEqual(proof.tau, 0)
        self.assertEqual(exact_trace(C, proof.matrix), F(-110, 529))
        self.assertEqual(proof.matrix.fractions()[0][1], F(1, 2))
        self.assertLess(exact_trace(C, proof.matrix), 0)  # all-one partition has Q0
        self.assert_full_primal(proof)

    def test_factor_free_q1_and_q2_empty_triangles(self):
        one = repair_interval([[F(7, 8)]], [[-9]], [F(7, 8)])
        self.assertEqual((one.lower, one.upper, one.width), (F(7, 8), F(7, 8), F(0)))
        self.assertEqual(one.primal.triangle_violation, 0)
        self.assert_full_primal(one.primal)
        q2 = ((F(-1, 529), F(1, 529)), (F(1, 529), F(-1, 529)))
        two = repair_interval(q2, [[1, 1], [1, 1]], [0, 0])
        self.assertEqual((two.lower, two.upper, two.width), (F(0), F(0), F(0)))
        self.assertEqual(two.primal.triangle_violation, 0)
        self.assert_full_primal(two.primal)

    def test_all_original_trace_equals_lifted_quotient_trace(self):
        q2 = ((F(-1, 529), F(1, 529)), (F(1, 529), F(-1, 529)))
        Z = ((F(1), F(1, 4)), (F(1, 4), F(1)))
        labels = (0, 0, 1)
        lifted = tuple(tuple(Z[labels[i]][labels[j]] for j in range(3)) for i in range(3))
        # Direct aggregation includes BOTH original offdiagonal entries.
        direct = tuple(tuple(sum((C[i][j] for i in range(3) for j in range(3)
                                  if labels[i] == a and labels[j] == b), F(0))
                             for b in range(2)) for a in range(2))
        self.assertEqual(direct, q2)
        self.assertEqual(independent_trace(C, lifted), F(-3, 1058))
        self.assertEqual(exact_trace(q2, Z), independent_trace(C, lifted))

    def test_no_active_cuts_and_clipped_negative_duals_remain_valid(self):
        primal = [[1, 1, 0], [1, 1, 1], [0, 1, 1]]
        result = repair_interval(C, primal, [0, 0, 0])
        self.assertGreaterEqual(result.upper, 0)
        self.assertEqual(result.primal.triangle_violation, 1)
        self.assert_full_primal(result.primal)
        clipped = repair_dual(C, [0, 0, 0], [Inequality("lower", 0, 1)], [-4])
        self.assertEqual(clipped.lambda_numerators, (0,))
        self.assertTrue(verify_dual(C, clipped))
        independent_psd_small(self, clipped.slack.fractions())

    def test_arbitrary_huge_factor_uses_python_integer_gram(self):
        proof = repair_primal([[1, 0], [0, 1]], factor=[[2.0**80], [-2.0**80]])
        gram = independent_gram(proof.factor)
        self.assertEqual(gram[0][0], F(1 << 160))
        self.assertEqual(gram[0][1], -F(1 << 160))
        self.assertGreater(max(abs(x) for row in proof.residual.numerators for x in row), 1 << 200)
        self.assertEqual(proof.tau_psd, F((1 << 161) - 1))
        self.assertTrue(verify_primal(proof))
        self.assert_full_primal(proof)

    def test_exact_gram_residuals_and_serialized_replay(self):
        result = self.known_interval()
        for base, factor, residual in ((result.primal.h, result.primal.factor, result.primal.residual),
                                       (result.dual.model, result.dual.factor, result.dual.residual)):
            before, gram, after = base.fractions(), independent_gram(factor), residual.fractions()
            self.assertEqual(after, tuple(tuple(before[i][j] - gram[i][j] for j in range(3))
                                          for i in range(3)))
        restored = interval_from_payload(json.loads(json.dumps(result.to_dict())))
        self.assertEqual(restored, result)
        self.assertTrue(verify_interval(C, restored))

    def test_equivalent_exact_coefficient_storage_replays(self):
        result = self.known_interval()
        coefficient = result.coefficient
        scaled = RationalMatrix(tuple(tuple(3 * x for x in row) for row in coefficient.numerators),
                                3 * coefficient.denominator)
        self.assertTrue(verify_interval(scaled, result))
        self.assertEqual(exact_trace(scaled, result.primal.matrix), result.lower)

    def test_proof_tampering_is_rejected_exactly(self):
        result = self.known_interval()
        mutations = []
        for path in (("dual", "tau", "numerator"), ("primal", "matrix", "numerators"),
                     ("dual", "model", "numerators"), ("primal", "residual", "numerators")):
            p = deepcopy(result.to_dict())
            if path[-1] == "numerator":
                p[path[0]][path[1]][path[2]] += 1
            else:
                p[path[0]][path[1]][path[2]][0][0] += 1
            mutations.append(p)
        for p in mutations:
            with self.subTest(mutation=p):
                with self.assertRaises(ArithmeticError):
                    verify_interval(C, interval_from_payload(p))
        other_C = [list(row) for row in C]
        other_C[0][0] += F(1, 529)
        with self.assertRaises(ArithmeticError):
            verify_interval(other_C, result)
        with self.assertRaises(ArithmeticError):
            verify_dual(C, replace(result.dual, lambda_numerators=(-1,) * 7))
        with self.assertRaises(TypeError):
            verify_primal(replace(result.primal, tau=0.0))

    def test_symmetric_clamping_and_invalid_inputs(self):
        proof = repair_primal([[9, 2], [-1, -3]])
        self.assertEqual(proof.h.fractions(), ((F(1), F(1, 2)), (F(1, 2), F(1))))
        self.assert_full_primal(proof)
        bad_calls = [
            lambda: repair_interval([[0.0]], [[1]], [0]),
            lambda: repair_interval([[F(0)]], [[float("nan")]], [0]),
            lambda: repair_primal([[1]], factor=[[float("inf")]]),
            lambda: repair_dual([[F(0)]], [float("nan")]),
            lambda: repair_dual([[F(0)]], []),
            lambda: repair_primal([[1]], denominator=0),
            lambda: repair_primal([[1]], denominator=True),
            lambda: repair_interval([[F(0), F(1)], [F(0), F(0)]], [[1, 0], [0, 1]], [0, 0]),
            lambda: repair_dual([[F(0)]], [0], [Inequality("upper", 0, 1)], [0]),
            lambda: Inequality("triangle", 0, 0, 1),
            lambda: Inequality("unknown", 0, 1),
            lambda: RationalMatrix(((0.0,),), 1),
        ]
        for call in bad_calls:
            with self.subTest(call=call):
                with self.assertRaises((TypeError, ValueError)):
                    call()


if __name__ == "__main__":
    unittest.main()
