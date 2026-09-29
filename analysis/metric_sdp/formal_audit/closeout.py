"""Read-only independent exact closeout for the once-only 43x5 study.

The CLI requires finished measurements, a pinned diagnostic collection and a
separately authored, externally pinned source approval for this helper. It does
not import the numerical/runtime/controller/composition modules, call discovery,
reconstruct numerical factors, scan negative candidates or run any solver.
Only recorded accepted operations are checked. Fixed-point phase attribution
uses the separately reviewed frozen orchestration; an interrupted prefix is
never promoted to a completed phase or final quotient.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
from fractions import Fraction as F
import hashlib
import importlib
import itertools
import json
import math
from pathlib import Path
import re
import struct
import sys
import time
import traceback

# Keep all transitive imports read-only within the assigned write boundary.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[3]
BASE = "analysis/metric_sdp/formal_audit/"
REVIEWER = "/root/formal_data_auditor"
COMPOSITION_AUTHOR = "/root/experiment_supervisor"
SCHEMA = "metric-sdp-formal-independent-exactness-closeout-v1"
APPROVAL_SCHEMA = "metric-sdp-formal-audit-helper-source-review-v1"
PILOT_HELPER = "analysis/metric_sdp/pilot_validation.py"
PILOT_SHA = "54b070b18247eb238235c3d3147d3be3871b516f749814b3144f6cd86532420d"
RATIONAL_REVIEW = "reviews/metric-sdp-rational-source-review.json"
RATIONAL_REVIEW_SHA = "71ca7c2024de4157fcbef6c8283667578883f59112b15bfff98b0d965f5f7c43"
PILOT_REVIEW = "reviews/metric-sdp-pilot-closeout.json"
PILOT_REVIEW_SHA = "4724d5223f65e54786b5cd8567f852637f3776726a9e6bc186c88b85af947324"
HELPER_SOURCES = (BASE + "__init__.py", BASE + "closeout.py")
DISALLOWED_IMPORTS = (
    "cvxpy", "scs", "experiments.candidates", "experiments.pipeline",
    "experiments.extensions.metric_sdp.numerical",
    "experiments.extensions.metric_sdp.runtime",
    "experiments.extensions.metric_sdp.safe_composition",
    "experiments.extensions.metric_sdp.run_case",
    "experiments.extensions.metric_sdp.run_pilot",
    "experiments.extensions.metric_sdp_formal.runtime",
    "experiments.extensions.metric_sdp_formal.composition",
    "experiments.extensions.metric_sdp_formal.run_case",
    "experiments.extensions.metric_sdp_formal.run_study",
)


class AuditFailure(ValueError):
    pass


def require(value, message):
    if not value:
        raise AuditFailure(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()


def read_json(path):
    def pairs(items):
        answer = {}
        for key, value in items:
            require(key not in answer, "duplicate JSON key: " + key)
            answer[key] = value
        return answer
    def reject(value):
        raise AuditFailure("nonstandard JSON constant: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=pairs, parse_constant=reject)


def number(value, name):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "invalid finite nonnegative " + name)
    return value


def exact(value, name):
    require(isinstance(value, str), "exact string required: " + name)
    try:
        answer = F(value)
    except (ValueError, ZeroDivisionError) as error:
        raise AuditFailure("invalid exact " + name) from error
    require(str(answer) == value, "noncanonical exact " + name)
    return answer


def imported(module, relative):
    result = importlib.import_module(module)
    require(Path(result.__file__).resolve() == (ROOT / relative).resolve(),
            "actual import origin differs: " + module)
    return result


def no_scientific_imports():
    require(not any(any(name == prefix or name.startswith(prefix + ".")
                        for prefix in DISALLOWED_IMPORTS) for name in sys.modules),
            "audit process imported a scientific execution module")


def authenticate_dependencies(source_approval, expected_approval_sha):
    require(digest(ROOT / PILOT_HELPER) == PILOT_SHA, "reused pilot helper changed")
    require(digest(ROOT / RATIONAL_REVIEW) == RATIONAL_REVIEW_SHA,
            "rational independent review identity changed")
    require(digest(ROOT / PILOT_REVIEW) == PILOT_REVIEW_SHA,
            "pilot independent closeout identity changed")
    rational_review, pilot_review = read_json(ROOT / RATIONAL_REVIEW), read_json(ROOT / PILOT_REVIEW)
    require(rational_review["verdict"]["rational_module_source"] ==
            "APPROVED_FOR_SCOPED_EXACT_REPAIR_IMPLEMENTATION_USE"
            and rational_review["verdict"]["blocking_source_defects"] == [],
            "rational review does not approve exact implementation use")
    bound = next(x["sha256"] for x in rational_review["inputs"]
                 if x["path"] == "experiments/extensions/metric_sdp/rational.py")
    require(digest(ROOT / "experiments/extensions/metric_sdp/rational.py") == bound,
            "actual rational proof dependency differs from reviewed source")
    require(pilot_review["integrity_status"] == "validated"
            and pilot_review["retained_outcomes"] == pilot_review["expected_jobs"] == 6
            and pilot_review["credited_verified_target_jobs"] == 6
            and pilot_review["selected_backend"] == "direct",
            "pilot closeout does not support the recorded backend/dependency scope")
    require(expected_approval_sha and digest(source_approval) == expected_approval_sha,
            "external helper source-approval SHA mismatch")
    approval = read_json(source_approval)
    require(approval.get("schema") == APPROVAL_SCHEMA
            and approval.get("approved_for_post_measurement_exact_audit") is True
            and approval.get("blocking_defects") == []
            and approval.get("reviewer_task") not in (None, "", REVIEWER, COMPOSITION_AUTHOR)
            and approval.get("independent_of_helper_author") is True,
            "separate helper source approval absent")
    actual = {path: digest(ROOT / path) for path in HELPER_SOURCES}
    require(all(approval.get("source_sha256", {}).get(path) == sha for path, sha in actual.items()),
            "helper source changed after independent source review")
    pilot = imported("analysis.metric_sdp.pilot_validation", PILOT_HELPER)
    no_scientific_imports()
    return pilot, {"helper_source_sha256": actual,
                   "helper_source_approval_sha256": expected_approval_sha,
                   "helper_source_approval_reviewer": approval["reviewer_task"],
                   "reused_pilot_helper": {"path": PILOT_HELPER, "sha256": PILOT_SHA,
                       "functions": ["inspect_environment", "positive_components", "raw_round",
                                     "proof_raw_binding", "global_primal"]},
                   "reused_rational_verifier": {"path": "experiments/extensions/metric_sdp/rational.py",
                       "sha256": bound, "source_review_sha256": RATIONAL_REVIEW_SHA,
                       "functions": ["interval_from_payload", "verify_interval"]},
                   "reused_pilot_closeout_sha256": PILOT_REVIEW_SHA}


def graph_from_dense(A, gamma, metadata=None):
    """Independent full-loop exact objective and both runtime fingerprints."""
    A = tuple(tuple(row) for row in A)
    n = len(A)
    require(n >= 1 and all(len(row) == n for row in A)
            and all(type(x) is F and x >= 0 for row in A for x in row)
            and all(A[i][j] == A[j][i] for i in range(n) for j in range(n)),
            "invalid exact dense adjacency")
    d = tuple(sum(row, F()) for row in A)
    S = sum(d, F())
    require(S > 0 and type(gamma) is F and gamma >= 0, "positive S/exact nonnegative gamma")
    C = tuple(tuple(A[i][j] / S - gamma * d[i] * d[j] / S ** 2
                    for j in range(n)) for i in range(n))
    entries = [(i, j, str(A[i][j])) for i in range(n) for j in range(n) if A[i][j]]
    exact_sha = hashlib.sha256(json.dumps({"n": n, "entries": entries},
                                        separators=(",", ":")).encode()).hexdigest()
    indices, indptr, values = [], [0], []
    weighted = hashlib.sha256(str(n).encode("ascii"))
    for i, row in enumerate(A):
        for j, weight in enumerate(row):
            if not weight:
                continue
            value = float(weight)
            require(math.isfinite(value) and F.from_float(value) == weight,
                    "current quotient is not exactly float64 representable")
            indices.append(j)
            values.append(value)
            weighted.update(f";{i},{j},{weight.numerator}/{weight.denominator}".encode("ascii"))
        indptr.append(len(indices))
    csr = hashlib.sha256()
    for value in (n, n, *indptr, *indices):
        csr.update(struct.pack("<q", value))
    for value in values:
        csr.update(struct.pack("<d", value))
    return {"A": A, "C": C, "d": d, "S": S, "n": n, "gamma": gamma,
            "metadata": metadata, "fingerprint": csr.hexdigest(),
            "exact_fingerprint": exact_sha, "weighted_fingerprint": weighted.hexdigest(),
            "indptr": indptr, "indices": indices, "values": values}


def original_graph(case):
    """After measurements only: frozen input loader once per encountered case."""
    if case["stratum"] == "controlled":
        module = imported("experiments.families", "experiments/families.py")
        graph, metadata = module.load_family(case["family"], **case["parameters"],
                                            include_oracle_blocks=False)
    else:
        module = imported("experiments.datasets", "experiments/datasets.py")
        graph, metadata = module.load_development(case["dataset"])
    n = len(graph)
    require(1 <= n <= 300 and set(graph) == set(range(n))
            and not graph.is_directed() and not graph.is_multigraph(),
            "whole frozen source graph size/IDs/type")
    A = [[F() for _ in range(n)] for _ in range(n)]
    for u, v, data in graph.edges(data=True):
        value = float(data.get("weight", 1))
        require(math.isfinite(value) and value >= 0, "source represented edge weight")
        A[u][v] = F.from_float(value)
        if u != v:
            A[v][u] = A[u][v]
    no_scientific_imports()
    return graph_from_dense(A, F(case["gamma"]), metadata)


def check_original(directory, checkpoint, original, decoded):
    import numpy as np
    require(decoded is not None and decoded["metadata"] == original["metadata"],
            "original metadata differs from independently reconstructed input")
    with np.load(directory / "original-adjacency.npz", allow_pickle=False) as archive:
        require(set(archive.files) == {"data", "indices", "indptr", "shape"}, "original CSR keys")
        data, indices, indptr, shape = (archive[name].copy() for name in
                                       ("data", "indices", "indptr", "shape"))
    n = original["n"]
    require(shape.shape == (2,) and shape.dtype.kind in "iu" and shape.tolist() == [n, n]
            and data.ndim == indices.ndim == indptr.ndim == 1
            and data.dtype.kind == "f" and data.dtype.itemsize == 8
            and indices.dtype.kind in "iu" and indptr.dtype.kind in "iu"
            and np.isfinite(data).all() and (data > 0).all(), "original CSR shapes/types/finite support")
    require(indptr.tolist() == original["indptr"] and indices.tolist() == original["indices"]
            and [F.from_float(float(x)) for x in data] == [F.from_float(x) for x in original["values"]],
            "stored canonical original CSR differs from exact reconstructed whole input")
    require(checkpoint["original_n"] == n and checkpoint["original_fingerprint"] == original["fingerprint"]
            and checkpoint["degrees_exact"] == list(map(str, original["d"]))
            and exact(checkpoint["S_exact"], "original S") == original["S"]
            and exact(checkpoint["gamma_exact"], "original gamma") == original["gamma"],
            "stored full degrees/loops/S/gamma/fingerprint")
    bank = checkpoint["bank"]
    require(set(bank) == {"blocks", "discovery_labels"} and canonical_hash(bank) == checkpoint["bank_sha256"],
            "stored original bank exact content/hash")
    labels = bank["discovery_labels"]
    require(len(labels) == n and all(type(x) is int for x in labels), "original incumbent labels")
    blocks = bank["blocks"]
    require(isinstance(blocks, list) and len({tuple(b) for b in blocks}) == len(blocks)
            and all(isinstance(b, list) and b == sorted(set(b)) and 2 <= len(b) <= n
                    and all(type(v) is int and 0 <= v < n and original["d"][v] > 0 for v in b)
                    and len({labels[v] for v in b}) == 1 for b in blocks),
            "bank blocks are unique positive-degree subsets of discovery communities")
    incumbent = sum((original["C"][i][j] for i in range(n) for j in range(n)
                     if labels[i] == labels[j]), F())
    require(exact(checkpoint["incumbent_Q_exact"], "original partition incumbent") == incumbent,
            "original incumbent full trace mismatch")
    return incumbent


def psd(matrix):
    """Independent diagonal-pivot exact Schur characterization, no eigensolver."""
    n = len(matrix)
    require(all(len(row) == n for row in matrix) and all(type(x) is F for row in matrix for x in row) and all(
        matrix[i][j] == matrix[j][i] for i in range(n) for j in range(n)), "PSD matrix symmetry")
    residual, rank = [list(row) for row in matrix], 0
    while residual:
        if any(residual[i][i] < 0 for i in range(len(residual))):
            return False, False, rank
        pivot = max(range(len(residual)), key=lambda i: residual[i][i])
        value = residual[pivot][pivot]
        if value == 0:
            return all(x == 0 for row in residual for x in row), False, rank
        keep = [i for i in range(len(residual)) if i != pivot]
        residual = [[residual[i][j] - residual[i][pivot] * residual[pivot][j] / value
                     for j in keep] for i in keep]
        rank += 1
    return True, True, rank


def projection(matrix, weights, pivot):
    keep = [i for i in range(len(weights)) if i != pivot]
    return [[matrix[i][j] - weights[i] / weights[pivot] * matrix[pivot][j]
             - weights[j] / weights[pivot] * matrix[i][pivot]
             + weights[i] * weights[j] / weights[pivot] ** 2 * matrix[pivot][pivot]
             for j in keep] for i in keep]


def laplacian(weights):
    return [[sum(weights[i], F()) if i == j else -weights[i][j]
             for j in range(len(weights))] for i in range(len(weights))]


def matrix_strings(matrix):
    return [[str(x) for x in row] for row in matrix]


def check_criterion(current, block, certificate, stage):
    """Dense independent criterion reconstruction on this exact current quotient."""
    A, d, S, g, n = (current[x] for x in ("A", "d", "S", "gamma", "n"))
    beta, k, outside = g / S, len(block), sorted(set(range(n)) - set(block))
    B = lambda u, v: A[u][v] - beta * d[u] * d[v]
    require(certificate.get("certified") is True and type(certificate.get("strict")) is bool,
            "accepted operation lacks exact certificate boolean")
    name = certificate.get("criterion")
    if stage == "S" and name == "exact optimized constant-mixture pair copy":
        require(k == 2, "pair criterion used on a nonpair")
        u, v = block
        terms = [(B(u, w) / (B(u, w) + B(v, w)), abs(B(u, w) + B(v, w)))
                 for w in outside if B(u, w) + B(v, w)]
        total = sum((weight for _, weight in terms), F())
        p, cumulative = F(), F()
        for root, weight in sorted(terms):
            cumulative += weight
            if 2 * cumulative >= total:
                p = min(F(1), max(F(), root))
                break
        loss = sum((abs(p * B(v, w) - (1 - p) * B(u, w)) for w in outside), F())
        affinity, margin = B(u, v), B(u, v) - loss
        active = [w for w in outside if A[u][w] or A[v][w]]
        require(affinity >= 0 and margin >= 0, "unsafe recorded pair operation")
        expected = {"u": u, "v": v, "p": str(p), "loss": str(loss), "affinity": str(affinity),
                    "margin": str(margin), "strict": margin > 0, "active_exterior_columns": len(active),
                    "inactive_volume": str(sum((d[w] for w in outside if w not in active), F())),
                    "tie_policy": "smallest minimizing probability",
                    "weak_anchor_support": [u] if p == 1 else [v] if p == 0 else [u, v]}
        require(all(certificate.get(key) == value for key, value in expected.items()),
                "pair certificate differs from independent lower-median/loss calculation")
        return {"criterion": name, "exact_margin": str(margin), "strict": margin > 0}
    require(all(d[u] > 0 for u in block) or stage == "S", "normalized copy used a zero-degree vertex")
    weights = [[F() for _ in block] for _ in block]
    if stage == "S":
        require(name == "exact uniform collective copy" and certificate["block"] == block,
                "S bank criterion identity")
        distances = [[sum((abs(B(u, w) - B(v, w)) for w in outside), F())
                      for v in block] for u in block]
        for i, u in enumerate(block):
            for j, v in enumerate(block):
                if i != j:
                    weights[i][j] = B(u, v) - distances[i][j] / k
        projected = projection(laplacian(weights), [F(1)] * k, k - 1)
        require(certificate["distances"] == matrix_strings(distances), "uniform full exterior distances")
        recorded = certificate["projected_matrix"]
    elif stage == "D":
        require(name == "core exact actual-median degree copy" and certificate["block"] == block,
                "D criterion identity")
        degrees = [d[u] for u in block]
        centers = {}
        for w in outside:
            values = sorted(A[u][w] / d[u] for u in block)
            centers[w] = values[k // 2] if k % 2 else (values[k // 2 - 1] + values[k // 2]) / 2
        delta = [sum((abs(A[u][w] / d[u] - centers[w]) for w in outside), F()) for u in block]
        volume = sum(degrees, F())
        mean = sum((d[u] * value for u, value in zip(block, delta)), F()) / volume
        matrix = [[-A[u][v] if i != j else sum((A[u][w] for w in block if w != u), F())
                   - d[u] * (delta[i] + mean + g * volume / S)
                   for j, v in enumerate(block)] for i, u in enumerate(block)]
        pivot = max(range(k), key=lambda i: degrees[i])
        projected = projection(matrix, degrees, pivot)
        require(certificate["basis_pivot"] == block[pivot] and certificate["delta"] == list(map(str, delta))
                and certificate["weighted_mean_delta"] == str(mean), "D full-degree actual median binding")
        recorded = certificate["projected_matrix"]
    else:
        require(stage == "W" and name == "project-derived exact degree-weighted collective reference"
                and certificate["block"] == block and certificate["penalty"] == "full_pair_distance"
                and certificate["center"] is None and certificate["gamma"] == str(g), "W criterion identity")
        degrees, volume = [d[u] for u in block], sum((d[u] for u in block), F())
        penalties = [[sum((abs(d[v] * A[u][w] - d[u] * A[v][w]) for w in outside), F()) / volume
                      for v in block] for u in block]
        for i, u in enumerate(block):
            for j, v in enumerate(block):
                if i != j:
                    weights[i][j] = B(u, v) - penalties[i][j]
        projected = projection(laplacian(weights), degrees, 0)
        meta = certificate["metadata"]
        require(meta["exact_pair_penalties"] == matrix_strings(penalties)
                and meta["graph_fingerprint"] == current["weighted_fingerprint"]
                and meta["block_volume_exact"] == str(volume) and meta["total_volume_exact"] == str(S)
                and meta["gamma_exact"] == str(g), "W exact pair penalty/current degree/S binding")
        recorded = meta["exact_projected_matrix"]
    accepted, strict, rank = psd(projected)
    require(accepted and certificate["strict"] == strict and recorded == matrix_strings(projected),
            "accepted collective matrix/PSD/strictness differs from independent exact oracle")
    require(certificate.get("available") is True, "unavailable collective operation accepted")
    if stage in {"S", "D"}:
        require(certificate["status"] == "verified_exact_psd", "collective exact status")
    else:
        status = "verified_positive_definite" if strict else "verified_positive_semidefinite"
        require(certificate["status"] == certificate["verification_status"] == status,
                "W exact status")
    return {"criterion": name, "exact_projected_dimension": k - 1, "exact_rank": rank, "strict": strict}


def merge(current, block):
    """Independent canonical one-block full-trace aggregation including loops."""
    selected, first, n = set(block), min(block), current["n"]
    groups = [block if u == first else [u] for u in range(n) if u == first or u not in selected]
    mapping = [None] * n
    for index, group in enumerate(groups):
        for u in group:
            mapping[u] = index
    A = [[sum((current["A"][u][v] for u in a for v in b), F()) for b in groups] for a in groups]
    answer = graph_from_dense(A, current["gamma"])
    require(answer["d"] == tuple(sum((current["d"][u] for u in group), F()) for group in groups)
            and answer["S"] == current["S"], "one-block aggregation changed full degrees/S")
    require(all(answer["C"][i][j] == sum((current["C"][u][v] for u in a for v in b), F())
                for i, a in enumerate(groups) for j, b in enumerate(groups)), "one-block full B/S trace identity")
    return answer, mapping


def phases(mode, events, n):
    sequence = ["S", "D"] if mode == "SD" else ["S", "W"] if mode == "SW" else [mode]
    answer, current, offset = [], n, 0
    for stage in sequence:
        start = current
        selected = [e["operation"] for e in events if e["operation"]["stage"] == stage]
        if selected:
            require(selected[0]["index"] == offset, "phase operations are not stage-contiguous")
            current = selected[-1]["current_n_after"]
        answer.append({"stage": stage, "start_n": start, "end_n": current,
                       "accepted_operations": len(selected), "fixed_point": True})
        offset += len(selected)
    return answer


def replay_operations(original, checkpoint, events, arm, cap):
    current, membership, summaries = original, list(range(original["n"])), []
    for index, event in enumerate(events):
        op, block = event["operation"], event["operation"]["block_current"]
        require(op["index"] == index and op["current_n_before"] == current["n"]
                and op["original_membership_before"] == membership
                and op["current_graph_sha256"] == current["exact_fingerprint"]
                and 2 <= len(block) <= cap, "durable operation actual current quotient identity")
        require(op["S_exact"] == str(current["S"]) and op["gamma_exact"] == str(current["gamma"])
                and op["block_volume_exact"] == str(sum((current["d"][v] for v in block), F())),
                "durable operation true current full degrees/S/gamma")
        mapped = {}
        for source in sorted(set(map(tuple, checkpoint["bank"]["blocks"]))):
            key = tuple(sorted({membership[v] for v in source}))
            if len(key) >= 2:
                mapped.setdefault(key, []).append(list(source))
        pair = op["stage"] == "S" and op["certificate"]["criterion"] == "exact optimized constant-mixture pair copy"
        require(op["original_bank_blocks"] == ([] if pair else mapped.get(tuple(block))),
                "durable operation mapped/deduplicated original-bank source binding")
        expected_prior = phases(arm, events[:index], original["n"])
        stage_order = [p["stage"] for p in expected_prior]
        require(event["completed_phases"] == expected_prior[:stage_order.index(op["stage"])],
                "durable prefix labels an unfinished/current phase complete")
        accepted_counts = Counter(e["operation"]["stage"] for e in events[:index + 1])
        require(all(event["counts_snapshot"].get(s + "_accepted_operations", 0) == accepted_counts[s]
                    for s in ("S", "D", "W")), "durable prefix stage acceptance counts")
        summary = check_criterion(current, block, op["certificate"], op["stage"])
        after, mapping = merge(current, block)
        membership = [mapping[c] for c in membership]
        require(op["old_to_new_membership"] == mapping and op["original_membership_after"] == membership
                and op["current_n_after"] == after["n"]
                and op["quotient_graph_sha256"] == after["exact_fingerprint"]
                and op["quotient_degrees_exact"] == list(map(str, after["d"])),
                "durable operation canonical merge/full-degree/hash binding")
        summaries.append({"index": index, "stage": op["stage"], **summary,
                          "current_n_before": current["n"], "current_n_after": after["n"],
                          "true_current_quotient_replayed": True, "weak_operation_rechecked_sequentially": True})
        current = after
    return current, membership, summaries


def check_preprocessing(pre, original, current, membership, events, config, pilot):
    require(pre["membership"] == membership and pre["quotient_n"] == current["n"],
            "final preprocessing differs from actual committed quotient")
    n, q = original["n"], current["n"]
    direct = [[F() for _ in range(q)] for _ in range(q)]
    for i, a in enumerate(membership):
        for j, b in enumerate(membership):
            direct[a][b] += original["C"][i][j]
    require(tuple(map(tuple, direct)) == current["C"], "complete original full-trace quotient including loops")
    expected_qv = {"exact_full_trace_aggregation": True, "exact_degrees": True,
                   "original_total_preserved": True, "membership": membership, "original_n": n, "quotient_n": q}
    require(pre["quotient_validation"] == expected_qv, "recorded complete quotient validation")
    groups = pilot.positive_components(current["C"])
    require(pre["component_nodes"] == groups and sorted(sum(groups, [])) == list(range(q)),
            "independent current signed-positive components/coverage")
    where = {u: ci for ci, group in enumerate(groups) for u in group}
    require(all(current["C"][i][j] <= 0 for i in range(q) for j in range(q) if where[i] != where[j]),
            "component upper transfer has a positive cross coefficient")
    targets = [F(sum(c in group for c in membership), n) * F(config["solver"]["width_target"])
               for group in groups]
    require(pre["component_width_targets"] == list(map(str, targets))
            and sum(targets, F()) == F(config["solver"]["width_target"]), "original-multiplicity width allocation")
    comp = pre["composition"]
    if comp is not None:
        meta = comp["metadata"]
        require(comp["operations"] == [e["operation"] for e in events]
                and meta["phases"] == phases(pre["arm"], events, n)
                and meta["original_n"] == n and meta["final_n"] == q
                and meta["original_graph_sha256"] == original["exact_fingerprint"]
                and meta["quotient_graph_sha256"] == current["exact_fingerprint"]
                and meta["original_S_exact"] == str(original["S"])
                and meta["gamma_exact"] == str(original["gamma"])
                and meta["original_bank"] == [list(b) for b in sorted(set(map(tuple, pre["bank"]["blocks"])))],
                "complete composition phase/order/map/bank/graph identity")
        require(meta["mode"] == pre["arm"] and meta["exact_block_cap"] == config["checker"]["max_block_size"]
                and meta["graph_cap"] == config["checker"]["max_vertices"], "composition limits/mode")
        counts = Counter(e["operation"]["stage"] for e in events)
        require(all(meta["counts"].get(s + "_accepted_operations", 0) == counts[s] for s in ("S", "D", "W")),
                "completed composition accepted-operation denominator")
        for name, value in meta["stage_seconds"].items():
            number(value, "composition subset " + name)
        require(meta["progress_callback_seconds"] == meta["stage_seconds"]["progress_callback"],
                "callback diagnostic is not the included composition subset")
    return groups, targets


def check_cost(directory, result, entry, arm, config, events):
    full = number(result["full_compute_seconds"], "full compute")
    stages = result["stage_seconds"]
    prefix = ["original_graph_preparation", "common_discovery_and_bank", "original_discovery_incumbent",
              "original_input_checkpoint"] + ([] if arm == "U" else ["safe_composition"]) + [
              "quotient_objective_and_validation", "signed_component_presolve", "checkpoint"]
    require(list(stages)[:len(prefix)] == prefix, "runtime ledger required work stage order")
    require(all(number(stages[name], "stage " + name) >= 0 for name in stages), "stage values")
    require(result["accounted_stage_seconds"] == sum(stages.values())
            and result["unassigned_compute_seconds"] == full - sum(stages.values()) >= 0,
            "full cost and disjoint-stage residual")
    if any(c["analytic"] for c in result["components"]):
        require("analytic_singleton_validation" in stages, "missing analytic exact-validation stage")
    if any(not c["analytic"] for c in result["components"]):
        require({"model_canonicalization", "solver"} <= set(stages), "missing numerical construction/solve stages")
    if list(directory.glob("component-*-round-*-raw.npz")):
        require("proposal_extraction" in stages, "missing raw proposal extraction cost")
    if any(c["lower_exact"] is not None and not c["analytic"] for c in result["components"]):
        require({"proposal_extraction", "triangle_separation", "rational_repair_and_exact_validation"} <= set(stages),
                "missing required bounded-component separation/repair/exact-validation work")
    if result.get("lower_exact") is not None:
        require(list(stages)[-1] == "lift_exact_validation", "missing/finally misplaced original lift-validation cost")
    if arm != "U":
        meta = result["composition"]["metadata"]
        require(number(meta["outer_call_seconds"], "composition outer subset") <= stages["safe_composition"]
                and sum(meta["stage_seconds"].values()) <= meta["outer_call_seconds"]
                and meta["progress_callback_seconds"] <= stages["safe_composition"],
                "composition/checkpoint/callback diagnostics not charged within outer cost")
        require(result["composition_checkpoint_files"] == [f"composition-operation-{i:04d}.json" for i in range(len(events))],
                "required accepted-operation checkpoint denominator")
    timer, finished = read_json(directory / "timer-start.json"), read_json(directory / "compute-finished.json")
    elapsed = number(finished["perf_counter"], "finished perf_counter") - number(timer["perf_counter"], "start perf_counter")
    require(timer["wall_seconds"] == config["formal"]["wall_seconds"]
            and finished["status"] == result["status"] and finished["full_compute_seconds"] == full
            and elapsed >= full and number(entry["process_wall_seconds_including_import_input_output"], "process wall") >= elapsed,
            "timer/compute-finished/outer-process complete cost binding")
    require(entry["full_compute_seconds"] == full, "controller full compute binding")


def check_outcome(directory, entry, result, config):
    """Bind every unresolved and bounded status to the frozen result-first policy."""
    require(entry["status"] not in {"controller_supervision_exception", "controller_record_validation_failure"},
            "controller exception evidence cannot independently authenticate a completed worker outcome")
    failure_path = directory / "failure.json"
    failure = read_json(failure_path) if failure_path.exists() else None
    expected = ((result or {}).get("status") or entry["limit_reason"]
                or (failure or {}).get("status") or "missing_final_result")
    require(entry["status"] == expected, "frozen result-first result/limit/failure/missing status precedence")
    require(not (result is not None and failure is not None), "result and worker failure both published")
    timer_path, finished_path = directory / "timer-start.json", directory / "compute-finished.json"
    timer = read_json(timer_path) if timer_path.exists() else None
    finished = read_json(finished_path) if finished_path.exists() else None
    if timer is not None:
        require(timer["wall_seconds"] == config["formal"]["wall_seconds"], "unresolved timer uses a different budget")
        number(timer["perf_counter"], "unresolved timer start")
    if finished is not None:
        require(timer is not None, "compute-finished marker lacks a timer start")
        require(isinstance(finished["status"], str) and finished["status"], "unresolved compute-finished status")
        full = number(finished["full_compute_seconds"], "unresolved completed compute")
        elapsed = number(finished["perf_counter"], "unresolved compute-finished clock") - timer["perf_counter"]
        require(elapsed >= full and entry["process_wall_seconds_including_import_input_output"] >= elapsed,
                "unresolved completed marker outside its actual process wall")
    process_wall = number(entry["process_wall_seconds_including_import_input_output"], "outcome process wall")
    limit = entry["limit_reason"]
    if limit == "rss_limit":
        require(type(entry["monitored_peak_RSS_bytes"]) is int
                and entry["monitored_peak_RSS_bytes"] > config["formal"]["rss_bytes"],
                "RSS-limit outcome lacks an observed peak above its frozen budget")
    elif limit == "full_wall_limit":
        require(timer is not None and process_wall >= config["formal"]["wall_seconds"],
                "complete-compute wall interruption lacks its timer/300-second process lower bound")
    elif limit == "initialization_limit":
        require(process_wall >= config["watchdog"]["initialization_limit_seconds"],
                "initialization interruption before its frozen wall allowance")
    elif limit == "final_serialization_limit":
        require(finished is not None and process_wall >= elapsed + 60,
                "final-serialization interruption lacks completed compute plus the frozen60-second allowance")
    # A marker may be completed between a watchdog observation and termination.
    # Its presence never cancels the separately retained physical interruption.
    if result is not None:
        require(entry["exit_code"] in (0, -15, -9) or entry["limit_reason"] is not None,
                "result published with an unexplained worker failure exit")
        require(timer is not None and finished is not None, "published result lacks complete compute markers")
    else:
        require(entry["exit_code"] != 0, "successful worker exit lacks its required serialized result")
        require(entry["full_compute_seconds"] is None, "unresolved outcome imputed a complete compute cost without a result")
    if failure is not None:
        require(failure["status"] == "worker_exception" and failure["phase"] in {
            "source_validation", "case_eligibility", "common_input", "complete_arm_compute", "final_serialization"},
            "unknown worker failure status/phase")
        require(type(failure["fatal_source_or_exactness"]) is bool, "worker failure fatal flag type")
        if failure["phase"] == "complete_arm_compute":
            require(timer is not None, "complete-arm failure lacks its committed timer marker")
        if failure["phase"] == "final_serialization":
            require(timer is not None and finished is not None,
                    "final-serialization failure lacks completed compute markers")
        elapsed = failure["elapsed_compute_seconds"]
        if elapsed is not None:
            number(elapsed, "failure elapsed compute diagnostic")
            if finished is not None:
                require(elapsed >= finished["full_compute_seconds"], "failure elapsed compute excludes completed work")
        else:
            require(timer is None and finished is None, "no-start worker failure has compute markers")
        if failure["phase"] in {"source_validation", "case_eligibility"} or failure["exception_type"] in {
                "ArithmeticError", "FloatingPointError", "OverflowError", "ZeroDivisionError", "ValueError", "JSONDecodeError"}:
            require(failure["fatal_source_or_exactness"] is True, "source/exactness worker failure did not mark the source version fatal")
        if entry["limit_reason"] is None:
            require(entry["exit_code"] == (2 if failure["fatal_source_or_exactness"] else 1),
                    "worker failure exit differs from frozen fatal/nonfatal policy")
    return failure


def replay_proofs(directory, pre, result, current, groups, targets, config, pilot):
    arrays, metrics, raw_summaries, incomplete = {}, {}, {}, []
    for path in sorted(directory.glob("component-*-round-*-raw.npz")):
        match = re.fullmatch(r"component-(\d{3})-round-(\d{3})-raw\.npz", path.name)
        require(match is not None, "raw proposal filename")
        ci, ri = map(int, match.groups())
        require(ci < len(groups) and len(groups[ci]) > 1 and ri < config["solver"]["max_rounds"], "raw proposal index")
        summary, values = pilot.raw_round(path, len(groups[ci]), result is None)
        raw_summaries[f"{ci}:{ri}"] = summary
        if values is None:
            incomplete.append(path.name)
        else:
            require(all(values[name].dtype.kind == "f" and values[name].dtype.itemsize == 8
                        for name in ("H", "y", "lambdas", "psd_dual_slack")), "raw proposal represented float64 types")
            arrays[(ci, ri)] = values
    for path in sorted(directory.glob("component-*-round-*-metrics.json")):
        match = re.fullmatch(r"component-(\d{3})-round-(\d{3})-metrics\.json", path.name)
        require(match is not None, "metric filename")
        ci, ri = map(int, match.groups())
        require(ci < len(groups) and len(groups[ci]) > 1 and ri < config["solver"]["max_rounds"], "metric index")
        try:
            metric = read_json(path)
        except (ValueError, UnicodeError):
            require(result is None, "serialized result with unreadable metrics")
            incomplete.append(path.name)
            continue
        require(metric["round"] == ri, "raw/metric round binding")
        metrics[(ci, ri)] = metric
        if "width_exact" in metric:
            require((ci, ri) in arrays and raw_summaries[f"{ci}:{ri}"]["all_proposals_finite"],
                    "reported bounded round has no complete finite raw proposal")
            require(exact(metric["upper_exact"], "round upper") - exact(metric["lower_exact"], "round lower")
                    == exact(metric["width_exact"], "round width") >= 0
                    and metric["epsilon"] in config["solver"]["eps_sequence"]
                    and metric["active_triangles"] == raw_summaries[f"{ci}:{ri}"]["active_triangles"],
                    "reported round width/model/policy")
    rational = imported("experiments.extensions.metric_sdp.rational", "experiments/extensions/metric_sdp/rational.py")
    intervals, summaries = {}, []
    for path in sorted(directory.glob("component-*-proof.json")):
        match = re.fullmatch(r"component-(\d{3})-proof\.json", path.name)
        require(match is not None, "proof filename")
        ci = int(match[1])
        require(ci < len(groups) and len(groups[ci]) > 1, "nontrivial proof component")
        proof = rational.interval_from_payload(read_json(path))
        C = tuple(tuple(current["C"][u][v] for v in groups[ci]) for u in groups[ci])
        require(rational.verify_interval(C, proof) is True, "exact complete component primal/dual proof replay")
        candidates = [key for key, metric in metrics.items() if key[0] == ci and "width_exact" in metric]
        require(candidates, "complete proof without a bounded round")
        key = max(candidates)
        metric = metrics[key]
        require(tuple(map(F, (metric["lower_exact"], metric["upper_exact"], metric["width_exact"])))
                == (proof.lower, proof.upper, proof.width), "terminal exact proof/round endpoints")
        pilot.proof_raw_binding(proof, arrays[key], config)
        intervals[ci] = proof
        summaries.append({"component": ci, "nodes": groups[ci], "proof_sha256": digest(path),
                          "raw_round": key[1], "raw_sha256": digest(directory / f"component-{ci:03d}-round-{key[1]:03d}-raw.npz"),
                          "exact_lower": str(proof.lower), "exact_upper": str(proof.upper),
                          "exact_width": str(proof.width), "full_domain_replayed": True,
                          "inactive_triangle_multipliers": "zero; dual feasible for ALL triangles"})
    analytic, lowers, uppers = set(), [], []
    if result is not None:
        require(len(result["components"]) == len(groups), "result component denominator")
        for ci, component in enumerate(result["components"]):
            nodes = groups[ci]
            require(component["index"] == ci and component["nodes"] == nodes
                    and component["width_target_exact"] == str(targets[ci])
                    and type(component["analytic"]) is bool and component["analytic"] == (len(nodes) == 1),
                    "component order/map/quality/analytic classification")
            bounded = sorted((key, metric) for key, metric in metrics.items() if key[0] == ci and "width_exact" in metric)
            require(component["rounds"] == [metric for _, metric in bounded]
                    and [key[1] for key, _ in bounded] == list(range(len(bounded))), "complete successful round records retained")
            if component["analytic"]:
                value = current["C"][nodes[0]][nodes[0]]
                require(component["status"] == "verified_target" and component["rounds"] == []
                        and component["lower_exact"] == component["upper_exact"] == str(value),
                        "exact analytic singleton including quotient diagonal offset")
                analytic.add(ci)
                lowers.append(value)
                uppers.append(value)
            elif component["lower_exact"] is not None:
                require(ci in intervals and component["lower_exact"] == str(intervals[ci].lower)
                        and component["upper_exact"] == str(intervals[ci].upper), "bounded component exact serialized proof binding")
                if component["status"] == "verified_target":
                    require(intervals[ci].width <= targets[ci], "component target width exceeds its allocation")
                lowers.append(intervals[ci].lower)
                uppers.append(intervals[ci].upper)
            else:
                require(component["upper_exact"] is None and ci not in intervals, "unbounded component proof/status mismatch")
    return intervals, analytic, lowers, uppers, summaries, raw_summaries, incomplete


def check_lift(original, current, membership, groups, intervals, analytic, result, incumbent, pilot):
    """Exact original trace and structural ALL-triangle/PSD membership lift.

    ALL distinct quotient triples are independently enumerated by global_primal.
    Every original triple maps to one of those triples or to repeated quotient
    indices, whose three inequalities follow exactly from diag1 and box[0,1].
    PSD follows by membership congruence of the verified component direct sum.
    """
    q = current["n"]
    Y = [[F() for _ in range(q)] for _ in range(q)]
    for ci, nodes in enumerate(groups):
        local = [[F(1)]] if ci in analytic else intervals[ci].primal.matrix.fractions()
        for i, u in enumerate(nodes):
            for j, v in enumerate(nodes):
                Y[u][v] = local[i][j]
    quotient_lower = pilot.global_primal(current["C"], groups, intervals, analytic)
    original_lower = sum((original["C"][i][j] * Y[a][b]
                          for i, a in enumerate(membership) for j, b in enumerate(membership)), F())
    upper = sum((current["C"][nodes[0]][nodes[0]] if ci in analytic else intervals[ci].upper
                 for ci, nodes in enumerate(groups)), F())
    require(original_lower == quotient_lower == exact(result["lower_exact"], "global original lower")
            and upper == exact(result["upper_exact"], "global original upper")
            and upper - original_lower == exact(result["width_exact"], "global original width") >= 0
            and upper - incumbent == exact(result["discrete_incumbent_gap_exact"], "original incumbent gap") >= 0,
            "original interval/full trace/lift/incumbent gap")
    lift = result["lift_validation"]
    require(lift["original_lifted_trace_exact"] == str(original_lower)
            and lift["all_cross_coefficients_nonpositive"] is True, "recorded original lift transfer")
    return {"lower_exact": str(original_lower), "upper_exact": str(upper), "width_exact": str(upper - original_lower),
            "original_PSD_proof": "membership congruence of exact verified component Gram+DD direct sum",
            "original_all_triangles_proof": "ALL distinct quotient triples checked; repeated mapped indices reduce to exact boxes",
            "upper_transfer": "all sequential accepted relaxed-safe operations plus full quotient trace and nonpositive cross terms"}


def operator_events(root, run, frozen, state, entries, jobs, config):
    launch = read_json(run.with_name(run.name + "-launch-attempt.json"))
    started = read_json(run.with_name(run.name + "-launch-started.json"))
    require(dt.datetime.fromisoformat(frozen["frozen_at_utc"]) <= dt.datetime.fromisoformat(launch["started_at_utc"])
            <= dt.datetime.fromisoformat(launch["ended_at_utc"]), "freeze/operator UTC order")
    require(all(launch.get(k) == value for k, value in started.items()), "actual operator start/end continuity")
    controller_start = read_json(run / "study-started.json")
    require(dt.datetime.fromisoformat(launch["started_at_utc"]) <= dt.datetime.fromisoformat(controller_start["utc"])
            <= dt.datetime.fromisoformat(launch["ended_at_utc"]), "actual controller start UTC outside operator")
    terminal = read_json(run / ("study-completed.json" if state == "completed" else "study-halted.json"))
    ordered_entries = [entry for _, entry in sorted(entries.items())]
    credited = sum(entry["credited_verified_target"] is True for entry in ordered_entries)
    expected_summary = {
        "planned_jobs": 215, "scheduled_jobs": 215, "dispatched_jobs": len(entries),
        "unexecuted_job_count": 215 - len(entries), "detailed_schedule_known": True,
        "credited_verified_target_jobs": credited, "all_jobs_credited_verified_target": credited == 215,
        "status_counts": dict(Counter(entry["status"] for entry in ordered_entries)),
        "per_arm": {arm: {"planned": 43,
                          "dispatched": sum(entry["arm"] == arm for entry in ordered_entries),
                          "credited_verified_target": sum(entry["arm"] == arm and entry["credited_verified_target"] is True
                                                          for entry in ordered_entries),
                          "unexecuted": 43 - sum(entry["arm"] == arm for entry in ordered_entries)}
                    for arm in ("U", "S", "D", "SD", "SW")},
        "runtime_ratios_computed": False,
        "scientific_judgment": "none; completion is an execution/accounting record"}
    require(terminal["summary"] == expected_summary, "actual complete status/per-arm/unexecuted accounting summary")
    fatal_indices = [i for i, entry in sorted(entries.items())
                     if entry.get("exit_code") == 2 or bool((entry.get("failure") or {}).get("fatal_source_or_exactness"))]
    if fatal_indices:
        require(state == "halted" and terminal["reason"] == "source_or_exactness_failure"
                and fatal_indices == [len(entries) - 1], "source version dispatched after a fatal source/exactness outcome")
    elif state == "halted":
        require(terminal["reason"] in {"initial_source_or_contract_validation_failure", "pre_dispatch_source_validation_failure",
                                       "controller_supervision_failure"}, "halted source version lacks its recorded fatal cause")
    log = run.with_name(run.name + "-launch-stdout.txt")
    events = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("event") in {
                "formal_job_start", "formal_job_closeout", "formal_study_finished"}:
            events.append(value)
    expected = []
    for index, entry in sorted(entries.items()):
        expected += [{"event": "formal_job_start", "index": index, **jobs[index]},
                     {"event": "formal_job_closeout", **entry}]
    if state == "completed":
        expected.append({"event": "formal_study_finished", "summary": terminal["summary"]})
    require(events == expected, "actual retained controller events differ from complete ordered outcome log")
    walls = []
    for entry in entries.values():
        require(type(entry["exit_code"]) is int and type(entry["monitored_peak_RSS_bytes"]) is int
                and entry["monitored_peak_RSS_bytes"] >= 0
                and entry["monitored_peak_RSS_GiB"] == entry["monitored_peak_RSS_bytes"] / 1024 ** 3,
                "actual worker exit/monitored RSS unit identity")
        require(entry["limit_reason"] in {None, "rss_limit", "full_wall_limit", "final_serialization_limit", "initialization_limit"},
                "unknown physical watchdog limit")
        walls.append(number(entry["process_wall_seconds_including_import_input_output"], "worker wall"))
    require(number(launch["operator_wall_seconds"], "operator wall") >= sum(walls),
            "actual operator wall does not contain its serial worker walls")
    no_scientific_imports()


def required_checks(row):
    need = {"source_config_freeze_and_outcome_accounting"}
    if row["original_checkpoint_present"]:
        need.add("original_input_full_degrees_bank_and_incumbent")
    if row["durable_prefix_operations"]:
        need.add("all_durable_operations_current_quotient_relaxation_safe")
    if row["composition_completed"]:
        need.add("exact_full_trace_quotient_and_signed_component_presolve")
    if row["reported_lower_exact"] is not None:
        need.update({"component_exact_primal_dual_and_raw_binding", "original_lift_psd_diag_box_all_triangles",
                     "quotient_upper_transfer_all_prior_operations", "original_exact_interval_and_width"})
    if row["controller_target_claimed"]:
        need.add("complete_cost_and_hard_wall_RSS_target_eligibility")
    return need


def audit_job(root, run, row, details, entry, case, config, originals, pilot):
    answer = {key: row[key] for key in ("index", "case_id", "arm", "outcome_status", "result_sha256",
                                      "failure_sha256", "durable_prefix_operations")}
    answer.update(checks={"source_config_freeze_and_outcome_accounting": entry is None}, findings=[],
                  credited_verified_target=False, complete_component_proofs=[], accepted_operation_audits=[],
                  partial_files_retained=row["partial_files"], original_n=None)
    directory = run / f"job-{row['index']:03d}-{row['case_id']}-{row['arm']}"
    try:
        if entry is None:
            require(not directory.exists() and row["outcome_status"] == "unexecuted", "unexecuted outcome has a worker attempt")
            return answer
        require(not row["integrity_issues"], "diagnostic collector refused job identity/accounting: " + "; ".join(row["integrity_issues"]))
        failure = check_outcome(directory, entry, details["result"], config)
        answer["checks"]["source_config_freeze_and_outcome_accounting"] = True
        answer["retained_failure"] = failure
        answer["retained_physical_limit_reason"] = entry["limit_reason"]
        if details["input"] is not None or details["original"] is not None:
            if case["case_id"] not in originals:
                originals[case["case_id"]] = original_graph(case)
            original = originals[case["case_id"]]
            answer["original_n"] = original["n"]
            require(details["input"] is not None and details["input"]["metadata"] == original["metadata"], "actual regenerated original input metadata")
        checkpoint = details["original"]
        if checkpoint is None:
            require(not details["events"] and details["preprocessing"] is None and details["result"] is None,
                    "dependent evidence without complete original checkpoint")
            return answer
        incumbent = check_original(directory, checkpoint, original, details["input"])
        answer["checks"]["original_input_full_degrees_bank_and_incumbent"] = True
        current, membership, operation_summaries = replay_operations(
            original, checkpoint, details["events"], row["arm"], config["checker"]["max_block_size"])
        answer["accepted_operation_audits"] = operation_summaries
        if details["events"]:
            answer["checks"]["all_durable_operations_current_quotient_relaxation_safe"] = True
        pre, result = details["preprocessing"], details["result"]
        if pre is None:
            require(result is None and not list(directory.glob("component-*-proof.json")), "component/result without completed preprocessing")
            answer["prefix_interpretation"] = "durable accepted prefix only; no final quotient or fixed-point credit"
            return answer
        groups, targets = check_preprocessing(pre, original, current, membership, details["events"], config, pilot)
        answer["checks"]["exact_full_trace_quotient_and_signed_component_presolve"] = True
        intervals, analytic, lowers, uppers, proof_summaries, raw_summaries, incomplete = replay_proofs(
            directory, pre, result, current, groups, targets, config, pilot)
        answer.update(complete_component_proofs=proof_summaries, raw_round_summaries=raw_summaries,
                      incomplete_uncredited_artifacts_retained=incomplete)
        if result is not None:
            check_cost(directory, result, entry, row["arm"], config, details["events"])
            require(result["scientific_measurement"] is True and result["schema"] == "metric-sdp-formal-arm-v1", "actual scientific result contract")
            if len(lowers) == len(groups):
                require(sum(lowers, F()) == F(result["lower_exact"]) and sum(uppers, F()) == F(result["upper_exact"]),
                        "all component interval aggregation")
                lift = check_lift(original, current, membership, groups, intervals, analytic, result, incumbent, pilot)
                answer.update(lift)
                for name in ("component_exact_primal_dual_and_raw_binding", "original_lift_psd_diag_box_all_triangles",
                             "quotient_upper_transfer_all_prior_operations", "original_exact_interval_and_width"):
                    answer["checks"][name] = True
                mathematical_status = "verified_target" if F(result["width_exact"]) <= F(config["solver"]["width_target"]) else "verified_interval_too_wide"
            else:
                require(result.get("lower_exact") is result.get("upper_exact") is result.get("width_exact") is None,
                        "incomplete components mislabeled as original bounds")
                mathematical_status = "incomplete_component_bounds"
            if result["full_compute_seconds"] > config["formal"]["wall_seconds"]:
                mathematical_status = "full_wall_limit"
            require(result["status"] == mathematical_status, "exact mathematical/runtime terminal status")
            eligible = (mathematical_status == "verified_target" and entry["exit_code"] == 0
                        and entry["limit_reason"] is None and not row["partial_files"]
                        and entry["monitored_peak_RSS_bytes"] <= config["formal"]["rss_bytes"])
            require(row["controller_target_claimed"] == eligible, "independent target/time/RSS/full serialization eligibility")
            answer["credited_verified_target"] = eligible
            if eligible:
                answer["checks"]["complete_cost_and_hard_wall_RSS_target_eligibility"] = True
        else:
            require(not row["controller_target_claimed"], "partial final serialization credited as target")
            answer["orphan_proof_interpretation"] = "complete component payloads replayed; absent final result supplies no global bound or target credit"
    except Exception as error:
        answer["findings"].append({"exception_type": type(error).__name__, "message": str(error)})
    return answer


def audit(config_path, freeze_path, run, collection, *, config_sha, freeze_sha,
          collection_sha, source_approval, source_approval_sha):
    started = time.perf_counter()
    require(Path.cwd().resolve() == ROOT, "audit must use the project-root working directory")
    no_scientific_imports()
    pilot, dependencies = authenticate_dependencies(source_approval, source_approval_sha)
    collector = imported("analysis.metric_sdp.formal.collect", "analysis/metric_sdp/formal/collect.py")
    require(digest(collection / "collection-manifest.json") == collection_sha, "external diagnostic collection SHA mismatch")
    recorded = read_json(collection / "collection-manifest.json")
    require(recorded["status"] == "diagnostic_only" and recorded["scientific_credit_authorized"] is False
            and recorded["independent_exactness_audit"] is None, "audit requires an uncredited diagnostic collection")
    fresh = collector.collect(ROOT, config_path, freeze_path, run,
                              expected_config_sha256=config_sha, expected_freeze_sha256=freeze_sha)
    require(not fresh["collection-manifest.json"]["integrity_issues"], "collection source/raw/accounting integrity issues")
    for name in ("raw-inventory.json", "job-rows.json", "primary-pair-rows.json", "summary.json"):
        require(recorded["output_artifact_sha256"][name] == digest(collection / name)
                and (collection / name).read_bytes() == json_bytes(fresh[name]), "diagnostic collection artifact differs: " + name)
    raw, rows = fresh["raw-inventory.json"], fresh["job-rows.json"]
    require(recorded["collector_source_sha256"] == fresh["collection-manifest.json"]["collector_source_sha256"]
            and recorded["raw_inventory_sha256"] == fresh["collection-manifest.json"]["raw_inventory_sha256"]
            and recorded["config_sha256"] == config_sha and recorded["freeze_sha256"] == freeze_sha,
            "diagnostic collection data/source pin binding")
    config, frozen, contract, _, _, issues = collector.authenticate(ROOT, config_path, freeze_path, config_sha, freeze_sha)
    require(not issues and raw["controller_state"] in {"completed", "halted"} and raw["operator"]["state"] == "complete",
            "complete terminal operator and source freeze required")
    jobs = collector.fixed_schedule(contract)
    require(len(jobs) == len(rows) == 215 and len(config["cases"]) == 43,
            "independent audit fixed complete outcome denominator")
    state, entries, issues = collector.controller(run, jobs, config_sha, freeze_sha)
    require(not issues, "independent controller denominator/source binding")
    operator_events(ROOT, run, frozen, state, entries, jobs, config)
    pilot.inspect_environment(frozen)
    originals, job_audits = {}, []
    for index, job in enumerate(jobs):
        _, details = collector.inspect_job(ROOT, run, index, job, config["cases"][job["case_index"]],
                                          entries.get(index), config, config_sha, freeze_sha)
        job_audits.append(audit_job(ROOT, run, rows[index], details, entries.get(index),
                                    config["cases"][job["case_index"]], config, originals, pilot))
        missing = required_checks(rows[index]) - {name for name, passed in job_audits[-1]["checks"].items() if passed is True}
        if missing and not job_audits[-1]["findings"]:
            job_audits[-1]["findings"].append({"exception_type": "AuditFailure",
                                            "message": "missing applicable checks: " + ", ".join(sorted(missing))})
    artifacts, issues = collector.inventory(ROOT, run, jobs)
    require(not issues and artifacts == raw["raw_artifact_sha256"], "immutable full raw inventory changed during exact audit")
    no_scientific_imports()
    findings = [{"index": x["index"], "case_id": x["case_id"], "arm": x["arm"], "findings": x["findings"]}
                for x in job_audits if x["findings"]]
    approved = not findings
    return {"schema": SCHEMA, "integrity_status": "validated" if approved else "not_validated",
            "scientific_credit_approved": approved, "all_215_outcomes_accounted": len(job_audits) == 215,
            "operator_command_logs_exit_and_limits_validated": True, "reviewer_task": REVIEWER,
            "independent_of_composition_author": REVIEWER != COMPOSITION_AUTHOR,
            "independent_of_runtime_and_rational_authors": True,
            "config_sha256": config_sha, "freeze_sha256": freeze_sha,
            "raw_inventory_sha256": recorded["raw_inventory_sha256"],
            "collector_source_sha256": recorded["collector_source_sha256"],
            "diagnostic_collection_manifest_sha256": collection_sha,
            "dependency_scopes": dependencies, "job_audits": job_audits, "findings": findings,
            "outcome_counts": dict(Counter(row["outcome_status"] for row in rows)),
            "credited_verified_target_jobs": sum(x["credited_verified_target"] for x in job_audits) if approved else 0,
            "original_inputs_reconstructed_once": len(originals),
            "audit_wall_seconds_excluded_from_scientific_costs": time.perf_counter() - started,
            "completed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "scope": "exact proof/data integrity for fixed descriptive analysis; no C001 or venue judgment",
            "recorded_bank_scope": "stored content/structure/source hash/cross-arm identity and full original partition value; no discovery regeneration",
            "fixed_point_scope": "frozen independently reviewed orchestration and exact phase/order metadata; no negative-candidate rescans",
            "earlier_round_scope": "raw proposals and scalar diagnostics retained; only complete terminal component payloads are exact bound evidence",
            "factor_binding_scope": "stored factors/Grams/residuals replayed exactly; H/y/lambda quantization and active-model order bound to raw NPZ. Factors are not regenerated from H or PSD slack; numerical-factor producer lineage is the frozen-source dependency",
            "C001_or_venue_approval": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements-finished", action="store_true", required=True)
    for name in ("config", "freeze", "run-dir", "collection", "config-sha256", "freeze-sha256",
                 "collection-sha256", "source-approval", "source-approval-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    output, run, collection = (Path(x).resolve() for x in (args.output, args.run_dir, args.collection))
    require(output.is_relative_to(ROOT / BASE) and not output.is_relative_to(run)
            and not output.is_relative_to(collection), "audit output must be new in the assigned namespace")
    output.mkdir(parents=True, exist_ok=False)
    try:
        result = audit(Path(args.config).resolve(), Path(args.freeze).resolve(), run, collection,
                       config_sha=args.config_sha256, freeze_sha=args.freeze_sha256,
                       collection_sha=args.collection_sha256, source_approval=Path(args.source_approval).resolve(),
                       source_approval_sha=args.source_approval_sha256)
    except Exception as error:
        result = {"schema": SCHEMA, "integrity_status": "refused", "scientific_credit_approved": False,
                  "all_215_outcomes_accounted": False, "fixed_denominator": 215, "reviewer_task": REVIEWER,
                  "exception_type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc(),
                  "C001_or_venue_approval": False}
    with (output / "closeout.json").open("xb") as handle:
        handle.write(json_bytes(result))
    print(json.dumps({"status": result["integrity_status"], "scientific_credit_approved": result["scientific_credit_approved"]}))
    return 0 if result["scientific_credit_approved"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
