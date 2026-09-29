"""Read-only independent closeout for the fixed six-job U-only feasibility pilot.

Do not import or execute this file during measurements. The CLI requires an
explicit finished-measurements flag and terminal controller/operator records.
It never imports the numerical runner or calls any solver/discovery/criterion.
Graph regeneration and exact proof replay are post-measurement audit work;
their durations are recorded separately and never added to measured costs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
from fractions import Fraction as F
import hashlib
import importlib.metadata as metadata
import itertools
import json
import math
import os
from pathlib import Path
import platform
import re
import struct
import sys
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = "experiments/extensions/metric_sdp"
DEFAULT_RUN = "experiments/runs/20260929-metric-sdp-pilot-v1"
EXPECTED_FREEZE_SHA = "170a50585740e7796d513db244a672e878e8ef88e14c8e7dc463ae571f89a7ad"
EXPECTED_CONFIG_SHA = "edae3553694e3d791d45d735589482c6ba2ced0c3fa1af4be9b6abce1a09244f"
SENTINELS = (
    "controlled-009-weighted_planted_blocks",
    "development-les_miserables",
    "controlled-012-noisy_planted_clusters",
)
EXPECTED_N = dict(zip(SENTINELS, (15, 77, 240)))
RUNTIME_PATHS = (
    "src/degree_contraction/__init__.py",
    "src/degree_contraction/certificate.py",
    "src/degree_contraction/quotient.py",
    "experiments/candidates.py", "experiments/datasets.py",
    "experiments/families.py", "experiments/pipeline.py",
    "experiments/extensions/__init__.py", "research/baselines/weighted_reference.py",
    *(NAMESPACE + "/" + name for name in (
        "__init__.py", "rational.py", "safe_composition.py", "numerical.py",
        "runtime.py", "freeze.py", "run_case.py", "run_pilot.py")),
)
AUDIT_DIR = ROOT / "analysis/metric_sdp/pilot-audit-attempts"
REVIEW_MD = ROOT / "reviews/metric-sdp-pilot-closeout.md"
REVIEW_JSON = ROOT / "reviews/metric-sdp-pilot-closeout.json"


class AuditFailure(Exception):
    pass


def require(condition, message):
    if not condition:
        raise AuditFailure(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def portable(path):
    return str(Path(path).resolve().relative_to(ROOT))


def json_file(path):
    def reject(value):
        raise AuditFailure("nonstandard JSON constant: " + value)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def artifact(path):
    path = Path(path)
    return {"path": portable(path), "sha256": digest(path),
            "bytes": path.stat().st_size}


def finite_nonnegative(value, name):
    require(not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0, name)
    return value


def canonical_hash(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def fixed_schedule():
    answer = []
    for index, sentinel in enumerate(SENTINELS):
        order = ("direct", "indirect") if index % 2 == 0 else ("indirect", "direct")
        answer.extend({"case_id": sentinel, "backend": backend, "arm": "U"}
                      for backend in order)
    return answer


def inspect_environment(frozen):
    """Read distributions/library bytes independently; do not import a solver."""
    actual = {
        "python": platform.python_version(), "platform": platform.platform(),
        "machine": platform.machine(),
        "versions": {name: metadata.version(name) for name in
                     ("cvxpy", "scs", "numpy", "scipy", "networkx", "psutil")},
        "installed_packages": dict(sorted(
            (dist.metadata["Name"].lower(), dist.version)
            for dist in metadata.distributions())),
    }
    cvx = metadata.distribution("cvxpy")
    scs = metadata.distribution("scs")
    libraries = {
        "cvxpy.problem": cvx.locate_file("cvxpy/problems/problem.py"),
        "cvxpy.scs_conif": cvx.locate_file(
            "cvxpy/reductions/solvers/conic_solvers/scs_conif.py"),
        "scs.python": scs.locate_file("scs/__init__.py"),
    }
    for key, stem in (("scs.direct", "_scs_direct"),
                      ("scs.indirect", "_scs_indirect")):
        matches = [p for p in (scs.files or ())
                   if Path(str(p)).parent == Path("scs")
                   and Path(str(p)).name.startswith(stem + ".")
                   and Path(str(p)).suffix in {".so", ".pyd", ".dylib"}]
        require(len(matches) == 1, "unique installed native-library path: " + key)
        libraries[key] = scs.locate_file(matches[0])
    actual["inspected_library_sha256"] = {
        name: digest(path) for name, path in libraries.items()}
    require(actual == frozen["environment"], "installed audit environment differs from freeze")
    return actual


def check_identities(config_path, freeze_path):
    config, frozen = json_file(config_path), json_file(freeze_path)
    require(digest(freeze_path) == EXPECTED_FREEZE_SHA and
            digest(config_path) == EXPECTED_CONFIG_SHA, "externally pinned v1 identity")
    require(frozen["status"] == "frozen_for_six_bounded_U_only_pilot_jobs",
            "not the fixed pilot-only freeze")
    require(frozen["pilot_execution_approved"] is True and
            frozen["formal_execution_approved"] is False and
            frozen["scientific_utility_approved"] is False and
            frozen["configuration_freeze_blockers"] == [], "pilot-only approval boundary")
    require(frozen["config_sha256"] == digest(config_path), "config changed")
    require(set(frozen["runtime_source_sha256"]) == set(RUNTIME_PATHS),
            "runtime source set is not the declared 17 files")
    for path, sha in frozen["runtime_source_sha256"].items():
        require(digest(ROOT / path) == sha, "changed runtime source: " + path)
    for path, sha in frozen["required_artifact_sha256"].items():
        require(digest(ROOT / path) == sha, "changed required artifact: " + path)
    require(len(frozen["required_artifact_sha256"]) == 220, "required artifact denominator")
    for path, sha in frozen["sealed_independent_approval_sha256"].items():
        require(frozen["required_artifact_sha256"].get(path) == sha and
                digest(ROOT / path) == sha, "sealed independent approval identity")
    require(digest(ROOT / config["original_config"]) ==
            config["original_config_sha256"], "original workload config changed")
    require(config["solver"]["backend"] is None, "pilot backend was preselected")
    require(config["pilot"]["sentinels"] == list(SENTINELS), "fixed sentinel list changed")
    require(config["pilot"]["backends"] == ["direct", "indirect"], "backend list changed")
    require(config["pilot"]["jobs"] == 6 and config["pilot"]["wall_seconds"] == 180
            and config["pilot"]["rss_bytes"] == 6 * 1024 ** 3, "fixed pilot budgets changed")
    require(F(config["solver"]["width_target"]) == F(1, 1000)
            and config["solver"]["rational_denominator"] == 2 ** 40,
            "quality/rounding target changed")
    require(config["formal"]["jobs"] == 215, "formal fixed denominator changed")
    cases = config["cases"]
    require(len(cases) == 43 and len({c["case_id"] for c in cases}) == 43,
            "43-case config denominator/uniqueness")
    require(Counter(c["stratum"] for c in cases) ==
            Counter({"controlled": 39, "development": 4}), "stratum denominator")
    for key, expected in config["threads"].items():
        require(os.environ.get(key) == expected, "audit single-thread environment: " + key)
    return config, frozen, inspect_environment(frozen)


def original_graph(case):
    """Only called after authorization. Frozen loaders, independently assembled A."""
    from experiments.datasets import load_development
    from experiments.families import load_family
    for module_name, relative in (
        ("experiments.datasets", "experiments/datasets.py"),
        ("experiments.families", "experiments/families.py"),
    ):
        require(Path(sys.modules[module_name].__file__).resolve() ==
                (ROOT / relative).resolve(), "actual generator import origin")
    if case["stratum"] == "controlled":
        graph, info = load_family(case["family"], **case["parameters"],
                                  include_oracle_blocks=False)
    else:
        graph, info = load_development(case["dataset"])
    n = len(graph)
    require(n == EXPECTED_N[case["case_id"]] and set(graph) == set(range(n)),
            "fixed original size/labels mismatch")
    require(not graph.is_directed() and not graph.is_multigraph(), "simple undirected source")
    A = [[F() for _ in range(n)] for _ in range(n)]
    for u, v, data in graph.edges(data=True):
        weight = float(data.get("weight", 1))
        require(math.isfinite(weight) and weight >= 0, "original represented weight")
        A[u][v] = F.from_float(weight)
        if u != v:
            A[v][u] = A[u][v]
    d = tuple(sum(row, F()) for row in A)
    S = sum(d, F())
    gamma = F(case["gamma"])
    require(S > 0 and gamma >= 0, "original volume/resolution")
    C = tuple(tuple(A[i][j] / S - gamma * d[i] * d[j] / (S * S)
                    for j in range(n)) for i in range(n))
    # Independent canonical CSR byte fingerprint: no prepare_graph/cache use.
    indptr, indices, values = [0], [], []
    for row in A:
        for j, weight in enumerate(row):
            if weight:
                indices.append(j)
                values.append(float(weight))
        indptr.append(len(indices))
    h = hashlib.sha256()
    for integer in (n, n, *indptr, *indices):
        h.update(struct.pack("<q", integer))
    for value in values:
        h.update(struct.pack("<d", value))
    return {"A": A, "C": C, "d": d, "S": S, "n": n, "metadata": info,
            "fingerprint": h.hexdigest()}


def positive_components(C):
    remaining = set(range(len(C)))
    groups = []
    while remaining:
        start = min(remaining)
        todo, seen = [start], {start}
        while todo:
            u = todo.pop()
            for v in sorted(remaining - seen):
                if C[u][v] > 0:
                    seen.add(v)
                    todo.append(v)
        remaining -= seen
        groups.append(sorted(seen))
    return groups


def preprocessing(pre, original, case, config):
    n, C = original["n"], original["C"]
    require(pre["case_id"] == case["case_id"] and pre["arm"] == "U",
            "preprocessing identity/arm")
    require(pre["original_n"] == pre["quotient_n"] == n
            and pre["membership"] == list(range(n)) and pre["composition"] is None,
            "U has an unexpected fusion/quotient map")
    require(F(pre["S_exact"]) == original["S"]
            and F(pre["gamma_exact"]) == F(case["gamma"])
            and pre["original_fingerprint"] == original["fingerprint"],
            "original full-degree/normalization/fingerprint")
    groups = positive_components(C)
    require(pre["component_nodes"] == groups, "independent positive-signed components")
    require(sum(groups, []) and sorted(sum(groups, [])) == list(range(n)),
            "component coverage")
    targets = [F(len(group), n) * F(config["solver"]["width_target"])
               for group in groups]
    require(list(map(F, pre["component_width_targets"])) == targets
            and sum(targets, F()) == F(config["solver"]["width_target"]),
            "original-multiplicity quality allocation")
    qv = pre["quotient_validation"]
    require(qv["membership"] == list(range(n)) and qv["original_n"] == qv["quotient_n"] == n
            and all(qv[k] is True for k in (
                "exact_full_trace_aggregation", "exact_degrees", "original_total_preserved")),
            "recorded U quotient validation")
    bank = pre["bank"]
    require(canonical_hash(bank) == pre["bank_sha256"], "recorded original bank content hash")
    labels = bank["discovery_labels"]
    require(len(labels) == n and all(type(x) is int for x in labels), "discovery labels")
    for block in bank["blocks"]:
        require(len(block) >= 2 and len(set(block)) == len(block)
                and all(type(x) is int and 0 <= x < n for x in block), "original bank block")
    incumbent = sum((C[i][j] for i in range(n) for j in range(n)
                     if labels[i] == labels[j]), F())
    require(F(pre["incumbent_Q_exact"]) == incumbent, "full original partition Q")
    return groups, targets, incumbent


def raw_round(path, q, allowed_incomplete):
    import numpy as np
    try:
        with np.load(path, allow_pickle=False) as archive:
            require(set(archive.files) ==
                    {"H", "y", "lambdas", "psd_dual_slack", "triangles"}, "raw proposal keys")
            arrays = {key: archive[key].copy() for key in archive.files}
    except (OSError, ValueError, EOFError, zipfile.BadZipFile):
        if allowed_incomplete:
            return {"retained_unreadable_partial": True}, None
        raise
    tri = arrays["triangles"]
    require(arrays["H"].shape == (q, q) and arrays["y"].shape == (q,)
            and arrays["psd_dual_slack"].shape == (q, q)
            and tri.ndim == 2 and tri.shape[1] == 3, "raw shapes")
    require(tri.dtype.kind in "iu", "raw triangle integer type")
    keys = [tuple(map(int, row)) for row in tri]
    require(keys == sorted(set(keys)) and all(
        len(set(t)) == 3 and 0 <= min(t) and max(t) < q and t[0] < t[2] for t in keys),
        "raw canonical active triangles")
    require(arrays["lambdas"].shape == (q * (q - 1) + len(keys),), "raw dual count")
    finite = all(np.isfinite(arrays[name]).all()
                 for name in ("H", "y", "lambdas", "psd_dual_slack"))
    return {"active_triangles": len(keys), "all_proposals_finite": bool(finite)}, arrays


def rounded(value, denominator):
    return round(F.from_float(float(value)) * denominator)


def proof_raw_binding(interval, arrays, config):
    """Exact ties-even rounding and model order; no eigensolver/factor regeneration."""
    q, den = len(arrays["H"]), config["solver"]["rational_denominator"]
    require(interval.primal.h.denominator == interval.dual.denominator == den,
            "proof rounding denominator")
    for i in range(q):
        require(interval.primal.h.numerators[i][i] == den, "proof H diagonal")
        for j in range(i):
            symmetric = (F.from_float(float(arrays["H"][i, j])) +
                         F.from_float(float(arrays["H"][j, i]))) / 2
            value = round(min(F(1), max(F(), symmetric)) * den)
            require(interval.primal.h.numerators[i][j] == value
                    and interval.primal.h.numerators[j][i] == value, "raw-to-proof H binding")
    require(interval.dual.y_numerators ==
            tuple(rounded(x, den) for x in arrays["y"]), "raw-to-proof diagonal dual")
    require(interval.dual.lambda_numerators ==
            tuple(max(0, rounded(x, den)) for x in arrays["lambdas"]),
            "raw-to-proof nonnegative multipliers")
    pairs = list(itertools.combinations(range(q), 2))
    expected = [("lower", i, j, None) for i, j in pairs]
    expected += [("upper", i, j, None) for i, j in pairs]
    expected += [("triangle", *map(int, row)) for row in arrays["triangles"]]
    actual = [(r.kind, r.i, r.j, r.k) for r in interval.dual.inequalities]
    require(actual == expected, "full-trace box/active-triangle order")


def global_primal(C, groups, intervals, analytic):
    """Independent full original trace/boxes/triangles; PSD by verified direct sum."""
    n = len(C)
    Y = [[F() for _ in range(n)] for _ in range(n)]
    for index, nodes in enumerate(groups):
        if index in analytic:
            Y[nodes[0]][nodes[0]] = F(1)
        else:
            local = intervals[index].primal.matrix.fractions()
            for i, u in enumerate(nodes):
                for j, v in enumerate(nodes):
                    Y[u][v] = local[i][j]
    lower = sum((C[i][j] * Y[i][j] for i in range(n) for j in range(n)), F())
    den = math.lcm(*(x.denominator for row in Y for x in row))
    integers = [[int(x * den) for x in row] for row in Y]
    require(all(integers[i][i] == den for i in range(n)) and all(
        integers[i][j] == integers[j][i] and 0 <= integers[i][j] <= den
        for i in range(n) for j in range(n)), "original lifted diagonal/symmetry/boxes")
    for i, j, k in itertools.combinations(range(n), 3):
        a, b, c = integers[i][j], integers[j][k], integers[i][k]
        require(a + b - c <= den and a + c - b <= den and b + c - a <= den,
                "original lifted ALL distinct triangles")
    return lower


def check_job(run_dir, entry, case, original, config, config_sha, freeze_sha):
    index, backend = entry["index"], entry["backend"]
    directory = run_dir / f"job-{index:03d}-{case['case_id']}-{backend}"
    require(directory.is_dir(), "missing dispatched job directory")
    fixed_names = {"input.json", "timer-start.json", "compute-finished.json",
                   "preprocessing.json", "result.json", "failure.json"}
    for path in directory.iterdir():
        require(path.is_file(), "unexpected nested job namespace")
        name = path.name.removesuffix(".partial")
        require(name in fixed_names or re.fullmatch(
            r"component-\d{3}-(?:proof\.json|round-\d{3}-(?:raw\.npz|metrics\.json))", name),
            "unexpected job artifact: " + path.name)
        require(not path.name.endswith(".partial") or not entry["credited_verified_target"],
                "credited job with incomplete exclusive serialization")
    require((run_dir / f"job-{index:03d}.log").is_file(), "missing retained worker log")
    result_path, failure_path = directory / "result.json", directory / "failure.json"
    result = json_file(result_path) if result_path.exists() else None
    failure = json_file(failure_path) if failure_path.exists() else None
    require(entry["result_sha256"] == (digest(result_path) if result else None),
            "job result hash binding")
    require(entry["failure"] == failure, "failure retention binding")
    require(not (result is not None and failure is not None), "both result and worker failure")
    input_path = directory / "input.json"
    if input_path.exists():
        decoded = json_file(input_path)
        require(decoded["case"] == case and decoded["metadata"] == original["metadata"]
                and decoded["arm"] == "U" and decoded["backend"] == backend
                and decoded["config_sha256"] == config_sha
                and decoded["freeze_sha256"] == freeze_sha, "worker input/source identity")
    peak = finite_nonnegative(entry["monitored_peak_RSS_bytes"], "monitored peak RSS")
    require(type(entry["monitored_peak_RSS_bytes"]) is int and
            entry["monitored_peak_RSS_GiB"] == peak / (1024 ** 3), "RSS unit identity")
    finite_nonnegative(entry["process_wall_seconds_including_import_input_output"],
                       "monitored process wall")
    require(entry["limit_reason"] in {None, "rss_limit", "full_wall_limit",
                                     "final_serialization_limit", "initialization_limit"},
            "unknown physical limit status")
    if (directory / "timer-start.json").exists():
        timer = json_file(directory / "timer-start.json")
        require(timer["wall_seconds"] == config["pilot"]["wall_seconds"], "timer budget")
        finite_nonnegative(timer["perf_counter"], "timer start")
    if result:
        require(input_path.exists() and (directory / "timer-start.json").exists()
                and (directory / "compute-finished.json").exists(), "complete worker markers")
        require(result["config_sha256"] == config_sha and result["freeze_sha256"] == freeze_sha
                and result["case_id"] == case["case_id"] and result["arm"] == "U"
                and result["backend"] == backend and result["scientific_measurement"] is True,
                "result identity/source gate")
        require(result["status"] == entry["status"]
                and result["full_compute_seconds"] == entry["full_compute_seconds"],
                "terminal status/compute cost")
        compute = json_file(directory / "compute-finished.json")
        require(compute["status"] == result["status"] and
                compute["full_compute_seconds"] == result["full_compute_seconds"],
                "compute completion marker")
        finite_nonnegative(result["full_compute_seconds"], "full compute cost")
        stages = result["stage_seconds"]
        for name, seconds in stages.items():
            finite_nonnegative(seconds, "stage cost " + name)
        accounted = sum(stages.values())
        require(result["accounted_stage_seconds"] == accounted and
                result["unassigned_compute_seconds"] ==
                result["full_compute_seconds"] - accounted, "stage/outer accounting")
        require(result["unassigned_compute_seconds"] >= -1e-9, "overlapping stage cost")
    elif failure:
        require(entry["status"] == (entry["limit_reason"] or failure["status"]),
                "failure status precedence")
    else:
        require(entry["status"] == (entry["limit_reason"] or "missing_final_result"),
                "missing-result status retention")
    pre_path = directory / "preprocessing.json"
    pre = json_file(pre_path) if pre_path.exists() else None
    groups, targets, incumbent = (None, None, None)
    if pre:
        groups, targets, incumbent = preprocessing(pre, original, case, config)
        require(pre["backend"] == backend, "preprocessing backend")
    if result:
        require(pre is not None, "result without original preprocessing")
        for key in ("original_n", "quotient_n", "S_exact", "gamma_exact",
                    "original_fingerprint", "bank_sha256", "bank", "incumbent_Q_exact",
                    "quotient_validation", "membership", "component_nodes",
                    "component_width_targets", "composition"):
            require(result[key] == pre[key], "preprocessing/result continuity: " + key)
    raw_summaries, arrays_by_key, metrics_by_key = {}, {}, {}
    partials = []
    for path in sorted(directory.glob("component-*-round-*-raw.npz")):
        match = re.fullmatch(r"component-(\d{3})-round-(\d{3})-raw.npz", path.name)
        require(match is not None and groups is not None, "raw without a component map")
        ci, ri = map(int, match.groups())
        require(ci < len(groups) and ri < config["solver"]["max_rounds"], "raw index bound")
        summary, arrays = raw_round(path, len(groups[ci]), not entry["credited_verified_target"])
        raw_summaries[f"{ci}:{ri}"] = summary
        if arrays is not None:
            arrays_by_key[(ci, ri)] = arrays
        else:
            partials.append(portable(path))
    for path in sorted(directory.glob("component-*-round-*-metrics.json")):
        match = re.fullmatch(r"component-(\d{3})-round-(\d{3})-metrics.json", path.name)
        require(match is not None and groups is not None, "metrics component map")
        key = tuple(map(int, match.groups()))
        require(key[0] < len(groups) and key[1] < config["solver"]["max_rounds"], "metrics index")
        try:
            metric = json_file(path)
        except (json.JSONDecodeError, UnicodeError):
            if not entry["credited_verified_target"]:
                partials.append(portable(path))
                continue
            raise
        require(metric["round"] == key[1], "metric round order")
        metrics_by_key[key] = metric
        if "width_exact" in metric:
            require(key in arrays_by_key and raw_summaries[f"{key[0]}:{key[1]}"][
                "all_proposals_finite"], "bounded round has no complete finite raw proposal")
            require(F(metric["upper_exact"]) - F(metric["lower_exact"]) ==
                    F(metric["width_exact"]) >= 0, "recorded round interval width")
            require(metric["epsilon"] in config["solver"]["eps_sequence"] and
                    metric["active_triangles"] ==
                    raw_summaries[f"{key[0]}:{key[1]}"]["active_triangles"],
                    "raw model/quality policy")
    from experiments.extensions.metric_sdp.rational import interval_from_payload, verify_interval
    require(Path(sys.modules["experiments.extensions.metric_sdp.rational"].__file__).resolve() ==
            (ROOT / NAMESPACE / "rational.py").resolve(), "actual exact verifier origin")
    intervals, proof_summaries = {}, []
    for path in sorted(directory.glob("component-*-proof.json")):
        match = re.fullmatch(r"component-(\d{3})-proof.json", path.name)
        require(match is not None and groups is not None, "proof without original component map")
        ci = int(match.group(1))
        require(ci < len(groups) and len(groups[ci]) > 1, "nontrivial proof component index")
        try:
            payload = json_file(path)
        except (json.JSONDecodeError, UnicodeError):
            if not entry["credited_verified_target"]:
                partials.append(portable(path))
                continue
            raise
        nodes = groups[ci]
        exact_C = tuple(tuple(original["C"][u][v] for v in nodes) for u in nodes)
        interval = interval_from_payload(payload)
        require(verify_interval(exact_C, interval) is True, "complete exact interval replay")
        candidate_keys = [key for key, metric in metrics_by_key.items()
                          if key[0] == ci and "width_exact" in metric]
        require(candidate_keys, "complete proof without a bounded recorded round")
        key = max(candidate_keys)
        metric = metrics_by_key[key]
        require(F(metric["lower_exact"]) == interval.lower and
                F(metric["upper_exact"]) == interval.upper and
                F(metric["width_exact"]) == interval.width, "terminal proof/round endpoints")
        proof_raw_binding(interval, arrays_by_key[key], config)
        intervals[ci] = interval
        proof_summaries.append({"component": ci, "original_nodes": nodes,
                                "proof": artifact(path), "exact_replay": True,
                                "raw_round": key[1], "lower_exact": str(interval.lower),
                                "upper_exact": str(interval.upper),
                                "width_exact": str(interval.width),
                                "dual_scope": "full original-normalized component domain; inactive cuts multiplier0"})
    analytic, component_lowers, component_uppers = set(), [], []
    if result:
        require(len(result["components"]) == len(groups), "component status denominator")
        for ci, component in enumerate(result["components"]):
            nodes = groups[ci]
            require(component["index"] == ci and component["nodes"] == nodes
                    and F(component["width_target_exact"]) == targets[ci],
                    "component order/allocation")
            require(type(component["analytic"]) is bool
                    and component["analytic"] == (len(nodes) == 1), "analytic singleton classification")
            successful_rounds = [metrics_by_key[(ci, r["round"])] for r in component["rounds"]]
            require(component["rounds"] == successful_rounds
                    and [r["round"] for r in component["rounds"]] ==
                    list(range(len(component["rounds"]))), "all saved successful rounds retained")
            if component["analytic"]:
                analytic.add(ci)
                value = original["C"][nodes[0]][nodes[0]]
                require(component["status"] == "verified_target"
                        and component["rounds"] == []
                        and F(component["lower_exact"]) == F(component["upper_exact"]) == value,
                        "analytic exact singleton value")
                component_lowers.append(value)
                component_uppers.append(value)
            elif component["lower_exact"] is not None:
                require(ci in intervals, "bounded component missing complete exact proof")
                interval = intervals[ci]
                require(F(component["lower_exact"]) == interval.lower
                        and F(component["upper_exact"]) == interval.upper, "component bound binding")
                component_lowers.append(interval.lower)
                component_uppers.append(interval.upper)
            else:
                require(component["upper_exact"] is None and ci not in intervals,
                        "unbounded component status")
        if len(component_lowers) == len(groups):
            lower, upper = sum(component_lowers, F()), sum(component_uppers, F())
            lifted = global_primal(original["C"], groups, intervals, analytic)
            require(lower == lifted == F(result["lower_exact"])
                    and upper == F(result["upper_exact"])
                    and upper - lower == F(result["width_exact"])
                    and upper - incumbent == F(result["discrete_incumbent_gap_exact"])
                    and upper >= incumbent, "original normalized interval/lift/incumbent gap")
            lift = result["lift_validation"]
            require(F(lift["original_lifted_trace_exact"]) == lifted
                    and lift["all_cross_coefficients_nonpositive"] is True, "recorded original lift")
            mathematical_status = ("verified_target" if upper - lower <=
                                   F(config["solver"]["width_target"]) else "verified_interval_too_wide")
            if result["full_compute_seconds"] > config["pilot"]["wall_seconds"]:
                mathematical_status = "full_wall_limit"
            require(result["status"] == mathematical_status, "actual interval target status")
        else:
            require(result["status"] in {"incomplete_component_bounds", "full_wall_limit"},
                    "missing component bounds mislabeled")
    credited = bool(entry["exit_code"] == 0 and entry["limit_reason"] is None
                    and result and result["status"] == "verified_target"
                    and result["full_compute_seconds"] <= config["pilot"]["wall_seconds"]
                    and peak <= config["pilot"]["rss_bytes"])
    require(type(entry["credited_verified_target"]) is bool and
            entry["credited_verified_target"] == credited, "independent credit conditions")
    if credited:
        require(len(component_lowers) == len(groups), "credit without ALL complete exact bounds")
    return {"index": index, "case_id": case["case_id"], "backend": backend, "arm": "U",
            "n": original["n"], "status": entry["status"],
            "credited_verified_target": credited, "full_compute_seconds": entry["full_compute_seconds"],
            "process_wall_seconds_including_import_input_output":
                entry["process_wall_seconds_including_import_input_output"],
            "monitored_peak_RSS_bytes": peak, "limit_reason": entry["limit_reason"],
            "complete_exact_proofs_replayed": proof_summaries,
            "analytic_singletons": sorted(analytic),
            "component_count": len(groups) if groups is not None else None,
            "raw_round_summaries": raw_summaries, "retained_unreadable_partial_files": partials,
            "lower_exact": result.get("lower_exact") if result else None,
            "upper_exact": result.get("upper_exact") if result else None,
            "width_exact": result.get("width_exact") if result else None,
            "failure": failure}


def backend_choice(entries, config):
    """Independent fixed ranking; unresolved jobs retain their full180 allowance."""
    summaries = {}
    for backend in ("direct", "indirect"):
        rows = [r for r in entries if r["backend"] == backend]
        success = {r["case_id"] for r in rows if r["credited_verified_target"]}
        summaries[backend] = {
            "eligible": SENTINELS[-1] in success,
            "completed_sentinels": len(success),
            "selection_cost_with_unresolved_penalty": sum(
                r["full_compute_seconds"] if r["credited_verified_target"]
                else config["pilot"]["wall_seconds"] for r in rows)}
    eligible = [backend for backend in ("direct", "indirect") if summaries[backend]["eligible"]]
    selected = min(eligible, key=lambda backend: (
        -summaries[backend]["completed_sentinels"],
        summaries[backend]["selection_cost_with_unresolved_penalty"],
        0 if backend == "direct" else 1)) if eligible else None
    return selected, summaries


def audit(config_path, freeze_path, run_dir):
    """No raw measurement mutation. Must be called only after root authorization."""
    require(run_dir.is_dir(), "pilot output absent")
    launch_base = run_dir.with_name(run_dir.name + "-launch-attempt.json")
    require(launch_base.exists(), "operator is not terminal")
    decision_path, halt_path = run_dir / "pilot-decision.json", run_dir / "pilot-halted.json"
    require(decision_path.exists() != halt_path.exists(), "exactly one terminal controller record")
    config, frozen, environment = check_identities(config_path, freeze_path)
    config_sha, freeze_sha = digest(config_path), digest(freeze_path)
    launch = json_file(launch_base)
    expected_command = [".venv-sdp/bin/python", "-m",
                        "experiments.extensions.metric_sdp.run_pilot",
                        "--config", portable(config_path), "--freeze", portable(freeze_path),
                        "--output", portable(run_dir)]
    require(launch["command"] == expected_command and launch["cwd"] == "."
            and launch["config_sha256"] == config_sha and launch["freeze_sha256"] == freeze_sha
            and launch["runtime_source_sha256"] == frozen["runtime_source_sha256"]
            and launch["operator_source_sha256"] ==
            digest(ROOT / NAMESPACE / "pilot_launch_operator.py"), "one-shot operator identity")
    require(launch["environment"] == {"PYTHONPATH": "src:.", **config["threads"]},
            "operator thread/PYTHONPATH environment")
    log_path = ROOT / launch["retained_stdout_stderr"]
    require(digest(log_path) == launch["retained_stdout_stderr_sha256"], "operator retained log hash")
    started_operator = json_file(run_dir.with_name(run_dir.name + "-launch-started.json"))
    require(all(launch[k] == value for k, value in started_operator.items()),
            "operator started/final continuity")
    require(dt.datetime.fromisoformat(launch["ended_at_utc"]) >=
            dt.datetime.fromisoformat(launch["started_at_utc"]), "operator UTC order")
    require(dt.datetime.fromisoformat(frozen["frozen_at_utc"]) <=
            dt.datetime.fromisoformat(launch["started_at_utc"]), "freeze precedes measurements")
    finite_nonnegative(launch["operator_wall_seconds"], "operator diagnostic duration")
    started = json_file(run_dir / "pilot-started.json")
    require(started["jobs"] == fixed_schedule()
            and started["config_sha256"] == config_sha and started["freeze_sha256"] == freeze_sha,
            "fixed six preselected schedule and source identities")
    require(dt.datetime.fromisoformat(started["utc"]) >=
            dt.datetime.fromisoformat(launch["started_at_utc"]), "controller started UTC order")
    paths = sorted(run_dir.glob("job-*-closeout.json"))
    for path in run_dir.iterdir():
        if path.is_file():
            require(path.name in {"pilot-started.json", "pilot-decision.json", "pilot-halted.json"}
                    or re.fullmatch(r"job-\d{3}(?:\.log|-closeout\.json)", path.name),
                    "unexpected controller artifact: " + path.name)
    entries = [json_file(path) for path in paths]
    expected_jobs = fixed_schedule()
    require(len(entries) <= 6 and entries, "dispatched outcome denominator")
    for index, (path, entry) in enumerate(zip(paths, entries)):
        require(path.name == f"job-{index:03d}-closeout.json" and entry["index"] == index
                and all(entry[k] == value for k, value in expected_jobs[index].items()),
                "fixed job prefix/order/uniqueness")
    decision = json_file(decision_path) if decision_path.exists() else None
    halt = json_file(halt_path) if halt_path.exists() else None
    if decision:
        require(len(entries) == 6 and decision["entries"] == entries
                and decision["formal_execution_approved"] is False
                and launch["exit_code"] == 0, "complete six denominator and pilot-only closeout")
    else:
        require(halt["retained_entries"] == entries
                and halt["unexecuted_jobs"] == expected_jobs[len(entries):]
                and halt["reason"] == "source_or_exactness_failure"
                and launch["exit_code"] == 2, "halted source version and blocked denominator")
    events, other_lines = [], 0
    for line in log_path.read_text(errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            other_lines += 1
            continue
        if isinstance(value, dict) and value.get("event") in {
                "pilot_job_start", "pilot_job_closeout", "pilot_finished"}:
            events.append(value)
        else:
            other_lines += 1
    require(len([x for x in events if x["event"] == "pilot_job_start"]) == len(entries)
            and len([x for x in events if x["event"] == "pilot_job_closeout"]) == len(entries),
            "retained operator event denominator")
    for index, entry in enumerate(entries):
        start_event, close_event = events[2 * index:2 * index + 2]
        require(start_event == {"event": "pilot_job_start", "index": index,
                                **expected_jobs[index]} and
                close_event == {"event": "pilot_job_closeout", **entry}, "actual log order")
    if decision:
        require(events[-1] == {"event": "pilot_finished",
                              "selected_backend": decision["selected_backend"],
                              "backend_summaries": decision["backend_summaries"]}, "terminal event")
    else:
        require(len(events) == 2 * len(entries), "no post-halt job/event")
    cases = {case["case_id"]: case for case in config["cases"]}
    originals = {}
    audited = []
    # No candidate discovery, optimization or remeasurement occurs below.
    for entry in entries:
        case_id = entry["case_id"]
        if case_id not in originals:
            originals[case_id] = original_graph(cases[case_id])
        audited.append(check_job(run_dir, entry, cases[case_id], originals[case_id],
                                 config, config_sha, freeze_sha))
    selected, summaries = backend_choice(entries, config)
    if decision:
        require(decision["selected_backend"] == selected
                and decision["backend_summaries"] == summaries
                and decision["status"] == ("feasibility_pass" if selected else
                                          "feasibility_fail_stop_version"),
                "independent n240 eligibility and backend ranking")
    else:
        selected = None
    # Every immutable run output and operator sidecar is bound, including failure partials.
    inventory_paths = [p for p in run_dir.rglob("*") if p.is_file()]
    inventory_paths += [launch_base, log_path,
                        run_dir.with_name(run_dir.name + "-launch-started.json")]
    inventory = [artifact(path) for path in sorted(inventory_paths)]
    expected_dirs = {f"job-{e['index']:03d}-{e['case_id']}-{e['backend']}" for e in entries}
    require({p.name for p in run_dir.iterdir() if p.is_dir()} == expected_dirs,
            "unexpected repeat job namespace")
    return {
        "schema": "independent-metric-sdp-six-U-pilot-closeout-v1",
        "integrity_status": "validated",
        "scientific_scope": "fixed U-only solver feasibility; no preprocessing utility or C001 verdict",
        "expected_jobs": 6, "dispatched_jobs": len(entries), "retained_outcomes": len(entries),
        "blocked_unexecuted_jobs": 6 - len(entries),
        "status_counts": dict(Counter(e["status"] for e in entries)),
        "credited_verified_target_jobs": sum(e["credited_verified_target"] for e in entries),
        "analytic_singletons": sum(len(e["analytic_singletons"]) for e in audited),
        "exact_component_proofs_replayed": sum(
            len(e["complete_exact_proofs_replayed"]) for e in audited),
        "n240_eligibility": {b: summaries[b]["eligible"] for b in summaries},
        "selected_backend": selected, "backend_summaries": summaries,
        "pilot_feasibility_outcome": (
            "source_version_halted" if halt else
            "pass" if selected else "fail_stop_version"),
        "formal215_authorized_by_this_audit": False,
        "next_step_constraint": (
            "Stop this source/protocol version; formal215 is forbidden and no smaller favorable suite may replace it."
            if halt or selected is None else
            "Feasibility only; a separate prospective selected-backend formal freeze is still required."),
        "fixed_schedule": expected_jobs, "jobs": audited,
        "config": artifact(config_path), "freeze": artifact(freeze_path),
        "runtime_source_sha256": frozen["runtime_source_sha256"],
        "required_artifact_sha256": frozen["required_artifact_sha256"],
        "environment": environment, "operator": artifact(launch_base),
        "all_raw_output_artifacts": inventory,
        "operator_non_event_log_lines_retained": other_lines,
        "reference_method": {
            "original_coefficients": "Direct represented edge rows, full degrees/loops, C=A/S-gamma*d*d.T/S^2; no runtime coefficient helper",
            "graph_fingerprint": "Independently packed canonical CSR bytes",
            "components": "Independent positive-coefficient connected components; exact nonpositive cross-block transfer",
            "primal": "Complete interval verifier plus independent original full trace/boxes/ALL triangles; PSD via verified direct sum",
            "dual": "Component exact Gram+DD proof; full-domain inactive cuts have multiplier0; valid original upper by component decomposition",
            "proposals": "Complete raw matrices/dual shape and exact ties-even denominator2^40 quantization bound to terminal proof",
        },
        "audit_only_graph_regenerations": len(originals), "audit_solver_calls": 0,
        "discovery_or_bank_recomputations": 0, "new_benchmark_or_backend_jobs": 0,
        "limitations": [
            "Passing this pilot does not compare preprocessing arms or establish utility, integrality, exact optimum, C001 closure or venue quality.",
            "Only saved complete exact proof payloads are replayed; nonterminal round scalar intervals without Gram payloads are retained as runtime records, not newly certified proofs.",
            "Peak RSS is the watchdog-sampled whole process-tree peak, not exact continuous peak or per-component memory.",
            "Audit graph regeneration/proof replay and report serialization are excluded from all measured pilot costs.",
            "All unresolved/partial/failure outcomes remain in the fixed six denominator."
        ],
    }


def report_body(result):
    rows = "\n".join(
        "| {index} | {case_id} | {backend} | {status} | {credited_verified_target} |".format(**row)
        for row in result["jobs"])
    return (
        "# Independent closeout of the fixed six-job U-only metric-SDP pilot\n\n"
        "Integrity: **validated**. Pilot feasibility: **" + result["pilot_feasibility_outcome"] +
        "**. Selected backend: **" + str(result["selected_backend"]) + "**.\n\n"
        "This is solver feasibility evidence, not a preprocessing utility comparison, "
        "a C001 decision or a conference-quality verdict. No pilot/backend/job was rerun.\n\n"
        "| Index | Fixed case | Backend | Retained status | Credited exact target |\n"
        "|---|---|---|---|---|\n" + rows + "\n\n"
        "Fixed denominator:6; dispatched:" + str(result["dispatched_jobs"]) +
        "; blocked unexecuted:" + str(result["blocked_unexecuted_jobs"]) +
        "; credited:" + str(result["credited_verified_target_jobs"]) + ". "
        "Exact component proof payloads replayed:" + str(result["exact_component_proofs_replayed"]) +
        "; analytic singletons:" + str(result["analytic_singletons"]) + ".\n\n"
        + result["next_step_constraint"] + "\n\n"
        "The companion JSON binds the freeze, all17 runtime sources, required review/test "
        "artifacts, environment, exact operator command, every raw output/log/failure file, "
        "fixed schedule, credit conditions and independently recomputed backend ranking. "
        "Original full-trace coefficients, full degrees/S, U identity membership, component "
        "maps, exact intervals and original primal lifts were independently checked. "
        "Float solver diagnostics were not treated as exact certificates.\n\n"
        "Audit elapsed time is reported separately in the JSON and immutable audit attempt. "
        "It is not added to any measured compute or process cost. All failures, incomplete "
        "proofs and limit outcomes are retained. Only complete proof payloads were replayed; "
        "nonterminal raw-round scalar intervals remain runtime records. Monitored RSS is a "
        "sampled process-tree peak. No formal215 execution is authorized by this closeout.\n"
    )


def exclusive_json(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=NAMESPACE + "/config.json")
    parser.add_argument("--freeze", default=NAMESPACE + "/pilot-freeze.json")
    parser.add_argument("--run-dir", default=DEFAULT_RUN)
    parser.add_argument("--measurements-finished", action="store_true",
                        help="Use ONLY after root explicitly authorizes post-measurement replay")
    parser.add_argument("--write-reports", action="store_true")
    args = parser.parse_args()
    if not args.measurements_finished:
        parser.error("root's explicit finished-measurement authorization is required")
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    os.chdir(ROOT)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    number = 1
    while (AUDIT_DIR / f"attempt-{number:03d}.json").exists():
        number += 1
    attempt_path = AUDIT_DIR / f"attempt-{number:03d}.json"
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    started = time.perf_counter()
    attempt = {"schema": "metric-sdp-independent-pilot-audit-attempt-v1",
               "attempt": number, "command": [sys.executable, *sys.argv],
               "audit_source": artifact(__file__), "started_at_utc": started_at,
               "duration_interpretation": "audit-only; never a measured cost or benchmark endpoint",
               "measurements_finished_explicitly_authorized": True,
               "new_solver_backend_or_job_calls": 0}
    try:
        config_path = (ROOT / args.config).resolve()
        freeze_path = (ROOT / args.freeze).resolve()
        run_dir = (ROOT / args.run_dir).resolve()
        result = audit(config_path, freeze_path, run_dir)
        # Make sure the records did not change during this read-only replay.
        for item in result["all_raw_output_artifacts"]:
            require(digest(ROOT / item["path"]) == item["sha256"], "output changed during audit")
        for path, sha in result["runtime_source_sha256"].items():
            require(digest(ROOT / path) == sha, "source changed during audit")
        require(digest(config_path) == result["config"]["sha256"] and
                digest(freeze_path) == result["freeze"]["sha256"], "identity changed during audit")
        result["audit_elapsed_seconds_before_report_serialization"] = time.perf_counter() - started
        result["audit_elapsed_role"] = "separate integrity work; excluded from all pilot endpoints"
        result["audit_source"] = artifact(__file__)
        if args.write_reports:
            require(not REVIEW_MD.exists() and not REVIEW_JSON.exists(),
                    "canonical closeout exists; preserve it and ask root for a versioned boundary")
            with REVIEW_MD.open("x") as handle:
                handle.write(report_body(result))
            result["review_body"] = artifact(REVIEW_MD)
            exclusive_json(REVIEW_JSON, result)
            attempt["created_reports"] = [artifact(REVIEW_MD), artifact(REVIEW_JSON)]
        attempt.update(status="passed", exit_code=0, result=result)
        exit_code = 0
    except BaseException as error:
        attempt.update(status="failed", exit_code=1,
                       error_type=type(error).__name__, message=str(error),
                       traceback=traceback.format_exc())
        exit_code = 1
    attempt.update(ended_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   audit_total_elapsed_seconds=time.perf_counter() - started)
    exclusive_json(attempt_path, attempt)
    print(json.dumps({"audit_status": attempt["status"], "exit_code": exit_code,
                      "attempt": artifact(attempt_path),
                      "audit_elapsed_seconds": attempt["audit_total_elapsed_seconds"],
                      "pilot_measurement_or_solver_calls": 0}, allow_nan=False), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
