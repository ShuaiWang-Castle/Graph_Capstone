"""Offline overlapping NMI using the pinned, unmodified NOCD upstream function.

Variant: McDaid--Greene--Hurley NMI_max (arXiv:1110.2515v2 eqs. 2--5, 10),
not the Lancichinetti--Fortunato--Kertesz normalization. No labels enter an
algorithm adapter. Loading only the exact upstream function AST avoids NOCD's
package-wide Torch import; its algorithmic body is neither copied nor changed.
"""
from __future__ import annotations

import ast
import hashlib
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np

SOURCE_COMMIT = "414856fd0d8f61d5bbeec06deb60c3e7b477a342"
SOURCE_SHA256 = "94dd415648cabdaffc1995fd9516e76650859110b21a988ec25cb55fb10e3cdc"
SOURCE_LICENSE_SHA256 = "00993270d80aadc3ae704f42d37a6365fe990050a098d5125403a7ff255fd950"
SOURCE_RELATIVE = "external/nocd/nocd/metrics/supervised.py"
SOURCE_URL = ("https://github.com/shchur/overlapping-community-detection/blob/"
              + SOURCE_COMMIT + "/nocd/metrics/supervised.py")
PAPER_URL = "https://arxiv.org/html/1110.2515v2"
VARIANT = "McDaid_Greene_Hurley_NMI_max_NOCD_PyTorch"
ROOT = Path(__file__).resolve().parents[1]


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@lru_cache(maxsize=4)
def _load_exact_function(path, digest):
    # digest is part of the cache key; compute_onmi rehashes the file each call.
    if digest != SOURCE_SHA256:
        raise ValueError("ONMI source differs from the pinned audited SHA-256")
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == "overlapping_nmi"]
    if len(functions) != 1:
        raise ValueError("Pinned source must contain one overlapping_nmi function")
    exact_function = ast.Module(body=functions, type_ignores=[])
    namespace = {"np": np, "warnings": warnings, "__name__": "lab_exact_upstream_onmi"}
    exec(compile(exact_function, str(path), "exec"), namespace)
    return namespace["overlapping_nmi"]


def _membership_matrix(cover, n):
    groups = []
    empty_groups = 0
    within_duplicates = 0
    for group in cover:
        values = list(group)
        if any(type(node) is not int or not 0 <= node < n for node in values):
            raise ValueError("ONMI cover has node outside the explicit universe")
        nodes = set(values)
        within_duplicates += len(values) - len(nodes)
        if nodes:
            groups.append(nodes)
        else:
            empty_groups += 1
    # Across-group duplicates are intentionally retained, matching lab.io.
    matrix = np.zeros((n, len(groups)), dtype=np.int64)
    for index, nodes in enumerate(groups):
        matrix[list(nodes), index] = 1
    audit = {"empty_groups_removed": empty_groups,
             "within_group_duplicates_removed": within_duplicates,
             "duplicate_groups_retained": len(groups) - len({frozenset(x) for x in groups})}
    return matrix, audit


def compute_onmi(truth, pred, n, source_path=None):
    """Return a scored/explicitly undefined ONMI record for complete covers.

    ``truth`` and ``pred`` are community lists/sets using the SAME 0..n-1 node
    universe. ``n`` preserves missing/uncovered nodes; no max-ID inference occurs.
    The caller must independently enforce complete ground-truth metadata.
    Empty cover and both-zero-entropy cases remain undefined, as the pinned
    implementation has no mathematical division/minimum in these cases. No
    fabricated zero, one, partition NMI or label-driven repair is substituted.
    """
    if type(n) is not int or n < 1:
        raise ValueError("ONMI requires a positive integer node universe")
    x, truth_audit = _membership_matrix(truth, n)
    y, pred_audit = _membership_matrix(pred, n)
    source = Path(source_path) if source_path is not None else ROOT / SOURCE_RELATIVE
    record = {"onmi": None, "onmi_status": None, "variant": VARIANT,
              "normalization": "I(X:Y)/max(H(X),H(Y)); anti-complement guard; many-to-one entropy minima",
              "source_commit": SOURCE_COMMIT, "source_sha256_expected": SOURCE_SHA256,
              "source_relative_path": SOURCE_RELATIVE, "source_url": SOURCE_URL,
              "paper_url": PAPER_URL, "paper_equations": [2, 3, 4, 5, 10],
              "numpy_version": np.__version__, "explicit_n": n,
              "truth_groups": int(x.shape[1]), "predicted_groups": int(y.shape[1]),
              "normalization_audit": {"truth": truth_audit, "prediction": pred_audit}}
    if not source.is_file():
        record.update(onmi_status="UNAVAILABLE_PINNED_SOURCE",
                      reason="Pinned NOCD metrics/supervised.py is not present; no substitute metric used")
        return record
    digest = _sha256(source)
    record["source_sha256_observed"] = digest
    function = _load_exact_function(str(source.resolve()), digest)
    if not x.shape[1] or not y.shape[1]:
        record.update(onmi_status="UNDEFINED_EMPTY_COVER",
                      reason="The original entropy-minimum implementation is undefined when either cover has no nonempty groups")
        return record
    if x.shape[1] * y.shape[1] > 5_000_000:
        record.update(onmi_status="NOT_SCORED_SIZE_GUARD",
                      reason="More than 5,000,000 community pairs; offline dense calculation was not attempted")
        return record
    x_nonconstant = np.any((x.sum(axis=0) > 0) & (x.sum(axis=0) < n))
    y_nonconstant = np.any((y.sum(axis=0) > 0) & (y.sum(axis=0) < n))
    if not x_nonconstant and not y_nonconstant:
        record.update(onmi_status="UNDEFINED_ZERO_ENTROPY",
                      reason="Both covers have zero binary membership entropy; NMI_max denominator is zero")
        return record
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        value = float(function(x, y))
    record["upstream_warnings"] = [str(w.message) for w in observed]
    if not np.isfinite(value):
        record.update(onmi_status="UPSTREAM_NONFINITE", reason="Pinned implementation returned nonfinite value")
    elif not -1e-10 <= value <= 1 + 1e-10:
        record.update(onmi_status="UPSTREAM_OUT_OF_RANGE", upstream_value=value,
                      reason="Pinned implementation returned value outside [0,1]; not clipped")
    else:
        # Preserve the exact returned value; do not post-process/clip it.
        record.update(onmi=value, onmi_status="SCORED")
    return record
