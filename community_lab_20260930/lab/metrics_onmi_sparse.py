"""Sparse contingency evaluation of the pinned NOCD McDaid NMI_max formula.

This is an offline metric implementation repair, not a community algorithm.
The original dense implementation and its source hash remain unchanged. A sparse
community-by-node incidence product supplies intersections; each truth-community
row computes both directional conditional entropies with the original anti-
complement guard. Only O(number of predicted groups) dense scratch is allocated.

Derived from the MIT-licensed NOCD implementation by Oleksandr Shchur (2019):
https://github.com/shchur/overlapping-community-detection/blob/
414856fd0d8f61d5bbeec06deb60c3e7b477a342/nocd/metrics/supervised.py
The upstream MIT license is preserved in the accompanying audit provenance.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import scipy
import scipy.sparse as sp

from lab.metrics_onmi import (ROOT, SOURCE_COMMIT, SOURCE_SHA256, SOURCE_RELATIVE,
                              SOURCE_URL, PAPER_URL, VARIANT, _sha256)


def _cover_incidence(cover, n):
    rows, columns = [], []
    cardinalities = []
    groups = []
    empty_groups = within_duplicates = 0
    for community in cover:
        values = list(community)
        if any(type(node) is not int or not 0 <= node < n for node in values):
            raise ValueError("ONMI cover has node outside the explicit universe")
        nodes = set(values)
        within_duplicates += len(values) - len(nodes)
        if not nodes:
            empty_groups += 1
            continue
        row = len(cardinalities)
        cardinalities.append(len(nodes))
        groups.append(frozenset(nodes))
        rows.extend([row] * len(nodes))
        columns.extend(sorted(nodes))
    matrix = sp.csr_matrix((np.ones(len(rows), dtype=np.int64),
                            (rows, columns)), shape=(len(cardinalities), n), dtype=np.int64)
    audit = {"empty_groups_removed": empty_groups,
             "within_group_duplicates_removed": within_duplicates,
             "duplicate_groups_retained": len(groups) - len(set(groups))}
    return matrix, np.asarray(cardinalities, dtype=np.int64), audit


def _entropy_terms(counts, n):
    counts = np.asarray(counts)
    result = np.zeros(counts.shape, dtype=np.float64)
    nonzero = counts != 0
    selected = counts[nonzero]
    result[nonzero] = -selected * np.log2(selected / n)
    return result


def compute_onmi_sparse(truth, pred, n, source_path=None):
    """Return equivalent NMI_max without dense n-by-community indicators.

    Covers use the same explicit n-node universe; the caller checks complete
    ground-truth metadata. Undefined/missing-source cases follow compute_onmi.
    The dense comparator's 5,000,000-pair guard is unnecessary for a full pair
    matrix here: pair entropies are streamed row-wise, though total O(a*b) work
    and potentially dense intersection sparsity remain real limitations.
    """
    if type(n) is not int or n < 1:
        raise ValueError("ONMI requires a positive integer node universe")
    x, tx, truth_audit = _cover_incidence(truth, n)
    y, py, pred_audit = _cover_incidence(pred, n)
    a_groups, b_groups = len(tx), len(py)
    source = Path(source_path) if source_path is not None else ROOT / SOURCE_RELATIVE
    record = {"onmi": None, "onmi_status": None, "variant": VARIANT,
              "normalization": "I(X:Y)/max(H(X),H(Y)); anti-complement guard; many-to-one entropy minima",
              "implementation": "sparse_contingency_rowwise_equivalent_v1",
              "implementation_source_sha256": _sha256(__file__),
              "source_commit": SOURCE_COMMIT, "source_sha256_expected": SOURCE_SHA256,
              "source_relative_path": SOURCE_RELATIVE, "source_url": SOURCE_URL,
              "paper_url": PAPER_URL, "paper_equations": [2, 3, 4, 5, 10],
              "numpy_version": np.__version__, "scipy_version": scipy.__version__,
              "explicit_n": n, "truth_groups": a_groups, "predicted_groups": b_groups,
              "community_pairs": int(a_groups * b_groups),
              "normalization_audit": {"truth": truth_audit, "prediction": pred_audit}}
    if not source.is_file():
        record.update(onmi_status="UNAVAILABLE_PINNED_SOURCE",
                      reason="Pinned NOCD metrics source is unavailable; equivalent implementation cannot claim the checked pin")
        return record
    digest = _sha256(source)
    record["source_sha256_observed"] = digest
    if digest != SOURCE_SHA256:
        raise ValueError("ONMI source differs from the pinned audited SHA-256")
    if not a_groups or not b_groups:
        record.update(onmi_status="UNDEFINED_EMPTY_COVER",
                      reason="The original entropy-minimum implementation is undefined when either cover has no nonempty groups")
        return record
    hx_terms = _entropy_terms(tx, n) + _entropy_terms(n - tx, n)
    hy_terms = _entropy_terms(py, n) + _entropy_terms(n - py, n)
    # Python sum follows the upstream's community-order accumulation, limiting
    # differences from alternative tree/pairwise floating-point reductions.
    hx = float(sum(hx_terms))
    hy = float(sum(hy_terms))
    if hx == 0 and hy == 0:
        record.update(onmi_status="UNDEFINED_ZERO_ENTROPY",
                      reason="Both covers have zero binary membership entropy; NMI_max denominator is zero")
        return record
    intersections = (x @ y.T).tocsr()
    record.update(truth_incidence_nnz=int(x.nnz), predicted_incidence_nnz=int(y.nnz),
                  intersection_nnz=int(intersections.nnz))
    row_minima = np.empty(a_groups, dtype=np.float64)
    col_minima = np.full(b_groups, np.inf, dtype=np.float64)
    for row in range(a_groups):
        intersection = np.zeros(b_groups, dtype=np.int64)
        first, last = intersections.indptr[row:row + 2]
        intersection[intersections.indices[first:last]] = intersections.data[first:last]
        # Original contingency counts: a=neither, b=Y-only, c=X-only, d=both.
        d = intersection
        b = py - d
        c = tx[row] - d
        a = n - tx[row] - py + d
        ha, hb, hc, hd = (_entropy_terms(z, n) for z in (a, b, c, d))
        guard = ha + hd >= hb + hc
        # Preserve the upstream arithmetic order for each directional H.
        conditional_x = ha + hb + hc + hd - _entropy_terms(b + d, n) - _entropy_terms(a + c, n)
        conditional_y = ha + hc + hb + hd - _entropy_terms(c + d, n) - _entropy_terms(a + b, n)
        conditional_x = np.where(guard, conditional_x, hx_terms[row])
        conditional_y = np.where(guard, conditional_y, hy_terms)
        row_minima[row] = np.min(conditional_x)
        col_minima = np.minimum(col_minima, conditional_y)
    conditional_x_sum = float(sum(row_minima))
    conditional_y_sum = float(sum(col_minima))
    information = .5 * (hx + hy - conditional_x_sum - conditional_y_sum)
    value = float(information / max(hx, hy))
    record["entropy_diagnostics"] = {"H_X": hx, "H_Y": hy,
                                     "H_X_given_Y": conditional_x_sum,
                                     "H_Y_given_X": conditional_y_sum}
    record["dense_reference_shape_warning_applicable"] = bool(a_groups > n or b_groups > n)
    record["shape_note"] = "Group count may exceed n for valid duplicate/fragmented covers; arrays retain explicit shape, not inferred orientation"
    if not np.isfinite(value):
        record.update(onmi_status="UPSTREAM_NONFINITE", reason="Equivalent formula returned nonfinite value")
    elif not -1e-10 <= value <= 1 + 1e-10:
        record.update(onmi_status="UPSTREAM_OUT_OF_RANGE", upstream_value=value,
                      reason="Equivalent formula returned value outside [0,1]; not clipped")
    else:
        record.update(onmi=value, onmi_status="SCORED")
    return record
