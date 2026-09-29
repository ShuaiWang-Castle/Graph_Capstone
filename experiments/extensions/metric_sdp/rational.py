"""Exact rational repair for the plain PSD/box/all-metric-triangle SDP.

Float matrices and eigendecompositions are proposals only.  The proof path
uses shared-denominator Python integers, including every Gram multiplication.
The objective is the FULL symmetric trace, with diagonal included.  A
quotient upper bound transfers to the original optimum only through a
separately proved relaxation-safe reduction sequence.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math
from numbers import Integral, Real
from typing import Mapping, Sequence

import numpy as np


DEFAULT_DENOMINATOR = 1 << 40
SCHEMA = "metric-sdp-rational-interval-v1"


def _integer(value, name="integer"):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer, never a bool or float")
    return int(value)


def _denominator(value):
    value = _integer(value, "denominator")
    if value <= 0:
        raise ValueError("denominator must be positive")
    return value


def _fraction(value):
    if isinstance(value, Fraction):
        return value
    return Fraction(_integer(value, "exact coefficient"))


def _fraction_payload(value):
    return {"numerator": value.numerator, "denominator": value.denominator}


def _fraction_from_payload(value):
    if not isinstance(value, Mapping) or set(value) != {"numerator", "denominator"}:
        raise ValueError("invalid rational scalar payload")
    return Fraction(_integer(value["numerator"]), _denominator(value["denominator"]))


def _require_rational(*values):
    if any(not isinstance(x, Fraction) for x in values):
        raise TypeError("proof scalars must be exact Fractions")


def _freeze(array):
    return tuple(tuple(int(x) for x in row) for row in array.tolist())


@dataclass(frozen=True)
class RationalMatrix:
    """Shared positive denominator and immutable Python-integer numerators."""

    numerators: tuple[tuple[int, ...], ...]
    denominator: int

    def __post_init__(self):
        den = _denominator(self.denominator)
        rows = tuple(tuple(_integer(x, "matrix numerator") for x in row)
                     for row in self.numerators)
        if not rows or any(len(row) != len(rows[0]) for row in rows):
            raise ValueError("matrix must have nonempty, equally sized rows")
        object.__setattr__(self, "numerators", rows)
        object.__setattr__(self, "denominator", den)

    @property
    def shape(self):
        return len(self.numerators), len(self.numerators[0])

    def integers(self):
        # dtype=object is deliberate: int64 cannot hold even ordinary2^40
        # rounded-factor products.  Every element is a Python integer.
        return np.array(self.numerators, dtype=object)

    def fractions(self):
        return tuple(tuple(Fraction(x, self.denominator) for x in row)
                     for row in self.numerators)

    def to_dict(self):
        return {"denominator": self.denominator,
                "numerators": [list(row) for row in self.numerators]}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping) or set(value) != {"denominator", "numerators"}:
            raise ValueError("invalid rational matrix payload")
        return cls(value["numerators"], value["denominator"])


def exact_matrix(values):
    """Accept exact Fraction/integer coefficients; reject all floating C."""
    if isinstance(values, RationalMatrix):
        matrix = values
        # Bind the exact coefficient VALUES, not an arbitrary shared-
        # denominator spelling.  This also keeps proof replay canonical.
        divisor = matrix.denominator
        for row in matrix.numerators:
            for value in row:
                divisor = math.gcd(divisor, value)
            if divisor == 1:
                break
        if divisor > 1:
            matrix = RationalMatrix(tuple(tuple(x // divisor for x in row)
                                          for row in matrix.numerators),
                                    matrix.denominator // divisor)
    else:
        rows = tuple(tuple(_fraction(x) for x in row) for row in values)
        if not rows or any(len(row) != len(rows) for row in rows):
            raise ValueError("C must be a nonempty square exact matrix")
        den = math.lcm(*(x.denominator for row in rows for x in row))
        matrix = RationalMatrix(tuple(tuple(x.numerator * (den // x.denominator)
                                            for x in row) for row in rows), den)
    q, columns = matrix.shape
    if q != columns:
        raise ValueError("C must be square")
    if any(matrix.numerators[i][j] != matrix.numerators[j][i]
           for i in range(q) for j in range(i)):
        raise ValueError("C must be exactly symmetric")
    return matrix


def _proposal_number(value):
    if isinstance(value, (bool, np.bool_)):
        raise TypeError("proposals must be finite real numbers, not bools")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Integral):
        return Fraction(int(value))
    if not isinstance(value, Real):
        raise TypeError("proposal must be a real number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("nonfinite numerical proposal")
    return Fraction(*value.as_integer_ratio())


def _round_number(value, den):
    """Exact nearest rounding of the represented proposal; ties to even."""
    value = _proposal_number(value)
    sign = -1 if value < 0 else 1
    whole, remainder = divmod(abs(value.numerator) * den, value.denominator)
    twice = 2 * remainder
    if twice > value.denominator or (twice == value.denominator and whole % 2):
        whole += 1
    return sign * whole


def _factor(values, q, den):
    if values is None:
        return RationalMatrix(tuple(() for _ in range(q)), den)
    rows = tuple(tuple(_round_number(x, den) for x in row) for row in values)
    matrix = RationalMatrix(rows, den)
    if matrix.shape[0] != q:
        raise ValueError("Gram factor must have q rows")
    return matrix


def _gram(factor):
    integers = factor.integers()
    return integers @ integers.T


def propose_gram_factor(matrix):
    """Floating positive-part factor, never a certificate or proof premise."""
    values = np.asarray(matrix, dtype=float)
    if (values.ndim != 2 or values.shape[0] < 1
            or values.shape[0] != values.shape[1] or not np.all(np.isfinite(values))):
        raise ValueError("factor proposal needs a finite nonempty square matrix")
    symmetric = 0.5 * values + 0.5 * values.T
    eigenvalues, vectors = np.linalg.eigh(symmetric)
    result = vectors * np.sqrt(np.maximum(eigenvalues, 0.0))
    if not np.all(np.isfinite(result)):
        raise ValueError("nonfinite proposed Gram factor")
    return result


def _row_shift(residual):
    q = residual.shape[0]
    radii = tuple(sum(abs(int(residual[i, j])) for j in range(q) if j != i)
                  for i in range(q))
    need = max((0, *(radii[i] - int(residual[i, i]) for i in range(q))))
    return need, radii


def _triangle_max(integers, den):
    """All three inequalities per distinct triple; repeated rows contribute0.

    For each middle vertex j, evaluate every negative edge i<k using object
    integer vectors.  Repeated-index rows have value0 under diag/box, so this
    also implements the explicit empty-set convention for q1 and q2.
    Only O(q^2) scratch space is used, not a Python constraint per triangle.
    """
    q = integers.shape[0]
    endpoints_i, endpoints_k = np.triu_indices(q, 1)
    if not len(endpoints_i):
        return 0
    negative_edges = integers[endpoints_i, endpoints_k]
    largest = 0
    for j in range(q):
        values = integers[endpoints_i, j] + integers[j, endpoints_k] - negative_edges - den
        largest = max(largest, int(values.max(initial=0)))
    return largest


@dataclass(frozen=True)
class Inequality:
    """Boxes, or Yij+Yjk-Yik<=1; triangle's negative edge is(i,k)."""

    kind: str
    i: int
    j: int
    k: int | None = None

    def __post_init__(self):
        i, j = _integer(self.i, "index"), _integer(self.j, "index")
        if min(i, j) < 0:
            raise ValueError("indices must be nonnegative")
        if self.kind in {"lower", "upper"}:
            if self.k is not None or i == j:
                raise ValueError("box must use one off-diagonal pair")
            i, j = sorted((i, j))
        elif self.kind == "triangle":
            k = _integer(self.k, "index")
            if k < 0 or len({i, j, k}) != 3:
                raise ValueError("triangle indices must be distinct and nonnegative")
            i, k = sorted((i, k))
            object.__setattr__(self, "k", k)
        else:
            raise ValueError("unknown inequality kind")
        object.__setattr__(self, "i", i)
        object.__setattr__(self, "j", j)

    @property
    def bound(self):
        return 0 if self.kind == "lower" else 1

    def terms(self):
        if self.kind == "triangle":
            return ((self.i, self.j, 1), (self.j, self.k, 1), (self.i, self.k, -1))
        return ((self.i, self.j, -1 if self.kind == "lower" else 1),)

    def to_dict(self):
        return {"kind": self.kind, "i": self.i, "j": self.j, "k": self.k}


def _inequalities(values, q):
    records = tuple(x if isinstance(x, Inequality) else Inequality(**x) for x in values)
    for record in records:
        if max(record.i, record.j, record.k if record.k is not None else 0) >= q:
            raise ValueError("inequality index out of bounds")
    return records


def _dual_model(coefficient, y, records, multipliers, den):
    q = coefficient.shape[0]
    common = math.lcm(coefficient.denominator, den * den, 2 * den)
    model = -coefficient.integers() * (common // coefficient.denominator)
    for i in range(q):
        model[i, i] += y[i] * (common // den)
    for record, multiplier in zip(records, multipliers):
        amount = multiplier * (common // (2 * den))
        for i, j, sign in record.terms():
            model[i, j] += sign * amount
            model[j, i] += sign * amount
    return model, common


@dataclass(frozen=True)
class PrimalRepair:
    h: RationalMatrix
    factor: RationalMatrix
    residual: RationalMatrix
    row_abs_sums: tuple[int, ...]
    tau_psd: Fraction
    triangle_violation: Fraction
    tau: Fraction
    matrix: RationalMatrix

    def to_dict(self):
        return {"h": self.h.to_dict(), "factor": self.factor.to_dict(),
                "residual": self.residual.to_dict(), "row_abs_sums": list(self.row_abs_sums),
                "tau_psd": _fraction_payload(self.tau_psd),
                "triangle_violation": _fraction_payload(self.triangle_violation),
                "tau": _fraction_payload(self.tau), "matrix": self.matrix.to_dict()}


def repair_primal(H, *, factor=None, denominator=DEFAULT_DENOMINATOR):
    den = _denominator(denominator)
    raw = tuple(tuple(_proposal_number(x) for x in row) for row in H)
    q = len(raw)
    if q < 1 or any(len(row) != q for row in raw):
        raise ValueError("primal proposal must be nonempty and square")
    integers = np.empty((q, q), dtype=object)
    for i in range(q):
        integers[i, i] = den
        for j in range(i):
            symmetric = (raw[i][j] + raw[j][i]) / 2
            value = _round_number(min(Fraction(1), max(Fraction(0), symmetric)), den)
            integers[i, j] = integers[j, i] = value
    h = RationalMatrix(_freeze(integers), den)
    gram_factor = _factor(factor, q, den)
    residual = integers * den - _gram(gram_factor)
    shift, radii = _row_shift(residual)
    tau_psd = Fraction(shift, den * den)
    violation = Fraction(_triangle_max(integers, den), den)
    tau = max(tau_psd, violation)
    numerator = integers * tau.denominator
    for i in range(q):
        numerator[i, i] += den * tau.numerator
    repaired = RationalMatrix(_freeze(numerator), den * (tau.denominator + tau.numerator))
    return PrimalRepair(h, gram_factor, RationalMatrix(_freeze(residual), den * den),
                        radii, tau_psd, violation, tau, repaired)


@dataclass(frozen=True)
class DualRepair:
    denominator: int
    y_numerators: tuple[int, ...]
    lambda_numerators: tuple[int, ...]
    inequalities: tuple[Inequality, ...]
    factor: RationalMatrix
    model: RationalMatrix
    residual: RationalMatrix
    row_abs_sums: tuple[int, ...]
    tau: Fraction
    slack: RationalMatrix
    upper: Fraction

    def to_dict(self):
        return {"denominator": self.denominator, "y_numerators": list(self.y_numerators),
                "lambda_numerators": list(self.lambda_numerators),
                "inequalities": [x.to_dict() for x in self.inequalities],
                "factor": self.factor.to_dict(), "model": self.model.to_dict(),
                "residual": self.residual.to_dict(), "row_abs_sums": list(self.row_abs_sums),
                "tau": _fraction_payload(self.tau), "slack": self.slack.to_dict(),
                "upper": _fraction_payload(self.upper)}


def repair_dual(C, y, inequalities=(), lambdas=(), *, factor=None,
                denominator=DEFAULT_DENOMINATOR):
    coefficient = exact_matrix(C)
    q = coefficient.shape[0]
    den = _denominator(denominator)
    y = tuple(_round_number(x, den) for x in y)
    records = _inequalities(inequalities, q)
    multipliers = tuple(max(0, _round_number(x, den)) for x in lambdas)
    if len(y) != q or len(records) != len(multipliers):
        raise ValueError("dual proposal dimensions do not match")
    gram_factor = _factor(factor, q, den)
    model, common = _dual_model(coefficient, y, records, multipliers, den)
    residual = model - _gram(gram_factor) * (common // (den * den))
    shift, radii = _row_shift(residual)
    tau = Fraction(shift, common)
    slack = model.copy()
    for i in range(q):
        slack[i, i] += shift
    upper = Fraction(sum(y) + sum(x * r.bound for x, r in zip(multipliers, records)), den) + q * tau
    return DualRepair(den, y, multipliers, records, gram_factor,
                      RationalMatrix(_freeze(model), common),
                      RationalMatrix(_freeze(residual), common), radii, tau,
                      RationalMatrix(_freeze(slack), common), upper)


def exact_trace(C, Y):
    coefficient = exact_matrix(C)
    if not isinstance(Y, RationalMatrix):
        Y = exact_matrix(Y)
    if coefficient.shape != Y.shape:
        raise ValueError("trace dimensions do not match")
    total = sum(int(x) for x in (coefficient.integers() * Y.integers()).flat)
    return Fraction(total, coefficient.denominator * Y.denominator)


@dataclass(frozen=True)
class IntervalResult:
    coefficient: RationalMatrix
    primal: PrimalRepair
    dual: DualRepair
    lower: Fraction
    upper: Fraction
    width: Fraction

    def to_dict(self):
        return {"schema": SCHEMA, "coefficient": self.coefficient.to_dict(),
                "primal": self.primal.to_dict(), "dual": self.dual.to_dict(),
                "L": _fraction_payload(self.lower), "U": _fraction_payload(self.upper),
                "width": _fraction_payload(self.width)}


def repair_interval(C, H, y, inequalities=(), lambdas=(), *, primal_factor=None,
                    dual_factor=None, denominator=DEFAULT_DENOMINATOR):
    coefficient = exact_matrix(C)
    primal = repair_primal(H, factor=primal_factor, denominator=denominator)
    if primal.matrix.shape != coefficient.shape:
        raise ValueError("primal and objective dimensions do not match")
    dual = repair_dual(coefficient, y, inequalities, lambdas,
                       factor=dual_factor, denominator=denominator)
    lower = exact_trace(coefficient, primal.matrix)
    result = IntervalResult(coefficient, primal, dual, lower, dual.upper, dual.upper - lower)
    verify_interval(coefficient, result)
    return result


def _equal_matrix(actual, expected, name):
    if actual != expected:
        raise ArithmeticError(f"{name} proof matrix mismatch")


def verify_primal(proof):
    """Recompute exact Gram, residual, DD bounds, all triangles and repaired Y."""
    _require_rational(proof.tau_psd, proof.triangle_violation, proof.tau)
    tuple(_integer(x, "row radius") for x in proof.row_abs_sums)
    den = _denominator(proof.h.denominator)
    h = proof.h.integers()
    q = len(h)
    if proof.h.shape != (q, q) or proof.factor.shape[0] != q or proof.factor.denominator != den:
        raise ArithmeticError("invalid primal proof dimensions/denominators")
    if (any(h[i, i] != den for i in range(q))
            or any(h[i, j] != h[j, i] or not 0 <= h[i, j] <= den
                   for i in range(q) for j in range(i))):
        raise ArithmeticError("primal H violates exact symmetry/diagonal/boxes")
    residual = h * den - _gram(proof.factor)
    _equal_matrix(proof.residual, RationalMatrix(_freeze(residual), den * den), "primal residual")
    need, radii = _row_shift(residual)
    tau_psd = Fraction(need, den * den)
    violation = Fraction(_triangle_max(h, den), den)
    tau = max(tau_psd, violation)
    if (proof.row_abs_sums != radii or proof.tau_psd != tau_psd
            or proof.triangle_violation != violation or proof.tau != tau):
        raise ArithmeticError("primal DD/triangle/shift proof mismatch")
    numerator = h * tau.denominator
    for i in range(q):
        numerator[i, i] += den * tau.numerator
    expected = RationalMatrix(_freeze(numerator), den * (tau.denominator + tau.numerator))
    _equal_matrix(proof.matrix, expected, "primal feasible")
    # Verify the FINAL full-domain constraints as well as their derivation.
    final = proof.matrix.integers()
    final_den = proof.matrix.denominator
    if (any(final[i, i] != final_den for i in range(q))
            or any(not 0 <= final[i, j] <= final_den for i in range(q) for j in range(q))
            or _triangle_max(final, final_den) != 0):
        raise ArithmeticError("repaired primal violates the full domain")
    return True


def verify_dual(C, proof):
    """Reconstruct max-dual coefficients and exact PSD proof; no solver trust."""
    _require_rational(proof.tau, proof.upper)
    tuple(_integer(x, "row radius") for x in proof.row_abs_sums)
    coefficient = exact_matrix(C)
    q = coefficient.shape[0]
    den = _denominator(proof.denominator)
    y = tuple(_integer(x) for x in proof.y_numerators)
    multipliers = tuple(_integer(x) for x in proof.lambda_numerators)
    records = _inequalities(proof.inequalities, q)
    if (len(y) != q or len(records) != len(multipliers) or any(x < 0 for x in multipliers)
            or proof.factor.shape[0] != q or proof.factor.denominator != den):
        raise ArithmeticError("invalid dual proof dimensions/signs")
    model, common = _dual_model(coefficient, y, records, multipliers, den)
    _equal_matrix(proof.model, RationalMatrix(_freeze(model), common), "dual model")
    residual = model - _gram(proof.factor) * (common // (den * den))
    _equal_matrix(proof.residual, RationalMatrix(_freeze(residual), common), "dual residual")
    need, radii = _row_shift(residual)
    tau = Fraction(need, common)
    if proof.row_abs_sums != radii or proof.tau != tau:
        raise ArithmeticError("dual DD/shift proof mismatch")
    slack = model.copy()
    for i in range(q):
        slack[i, i] += need
        if int(residual[i, i]) + need < radii[i]:
            raise ArithmeticError("dual exact DD inequality failed")
    _equal_matrix(proof.slack, RationalMatrix(_freeze(slack), common), "dual slack")
    upper = Fraction(sum(y) + sum(x * r.bound for x, r in zip(multipliers, records)), den) + q * tau
    if proof.upper != upper:
        raise ArithmeticError("dual full-trace upper bound mismatch")
    return True


def verify_interval(C, result):
    _require_rational(result.lower, result.upper, result.width)
    coefficient = exact_matrix(C)
    if result.coefficient.fractions() != coefficient.fractions():
        raise ArithmeticError("proof is bound to a different exact objective")
    verify_primal(result.primal)
    verify_dual(coefficient, result.dual)
    lower = exact_trace(coefficient, result.primal.matrix)
    if (result.lower != lower or result.upper != result.dual.upper
            or result.width != result.upper - result.lower or result.width < 0):
        raise ArithmeticError("exact interval/trace mismatch")
    return True


def interval_from_payload(value):
    """Decode proof integers/rationals; call verify_interval before trusting it."""
    if not isinstance(value, Mapping) or set(value) != {"schema", "coefficient", "primal", "dual", "L", "U", "width"}:
        raise ValueError("invalid interval payload keys")
    if value["schema"] != SCHEMA:
        raise ValueError("unknown interval payload schema")
    p, d = value["primal"], value["dual"]
    expected_p = {"h", "factor", "residual", "row_abs_sums", "tau_psd", "triangle_violation", "tau", "matrix"}
    expected_d = {"denominator", "y_numerators", "lambda_numerators", "inequalities", "factor", "model", "residual", "row_abs_sums", "tau", "slack", "upper"}
    if not isinstance(p, Mapping) or not isinstance(d, Mapping) or set(p) != expected_p or set(d) != expected_d:
        raise ValueError("invalid primal/dual payload keys")
    primal = PrimalRepair(*(RationalMatrix.from_dict(p[x]) for x in ("h", "factor", "residual")),
                          tuple(_integer(x) for x in p["row_abs_sums"]),
                          *(_fraction_from_payload(p[x]) for x in ("tau_psd", "triangle_violation", "tau")),
                          RationalMatrix.from_dict(p["matrix"]))
    dual = DualRepair(_denominator(d["denominator"]), tuple(_integer(x) for x in d["y_numerators"]),
                      tuple(_integer(x) for x in d["lambda_numerators"]),
                      tuple(Inequality(**x) for x in d["inequalities"]),
                      *(RationalMatrix.from_dict(d[x]) for x in ("factor", "model", "residual")),
                      tuple(_integer(x) for x in d["row_abs_sums"]), _fraction_from_payload(d["tau"]),
                      RationalMatrix.from_dict(d["slack"]), _fraction_from_payload(d["upper"]))
    return IntervalResult(RationalMatrix.from_dict(value["coefficient"]), primal, dual,
                          *(_fraction_from_payload(value[x]) for x in ("L", "U", "width")))
