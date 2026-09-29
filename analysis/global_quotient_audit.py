"""Post-run exploratory exact global audit; never part of frozen benchmarking.

The CLI and API require a complete launch ledger before loading numerical code
or creating output. Every manifest public/control/development resolution gets
original, production, and recursive rows, including unavailable records. The
same exact sign-then-Bell-enumeration policy applies to all arms. No timing
comparison is made. Outputs and the archived new source are created exclusively.

Run only after the coordinating root authorizes execution following completion:
    PYTHONPATH=src:. .venv/bin/python -m analysis.global_quotient_audit \
        --run-dir experiments/runs/20260929-frozen-v1 \
        --output-dir analysis/runs/global-quotient-exploratory-v1
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
import gzip
import hashlib
from itertools import combinations
import json
import math
from numbers import Integral, Real
import os
from pathlib import Path
import platform
import sys
from typing import Any


SCHEMA = "exploratory-global-quotient-audit-v1"
ARMS = ("original", "production", "recursive")
ENUMERATION_CAP = 10
EXACT_STATUSES = {"verified_positive_definite", "verified_positive_semidefinite"}
NATIVE_COMPLETED = {"optimal", "optimal_trivial"}
BASELINE_DEPENDENCIES = {
    "singleton_dominance": {
        "source": "research/baselines/sparse_criteria.py:singleton_dominance",
        "criterion": "Lange2018 dominant-attractive edge with singleton cuts; strict",
        "primary_source": "https://proceedings.mlr.press/v80/lange18a.html"},
    "positive_closure_edge": {
        "source": "research/baselines/sparse_criteria.py:positive_closure_edge",
        "criterion": "Lange2019 Appendix Theorem4 Eq21 positive closure; strict",
        "primary_source": "https://arxiv.org/abs/1812.01426"},
    "degree_proportional_twins": {
        "source": "research/baselines/sparse_criteria.py:degree_proportional_twins",
        "criterion": "compatible exact degree-proportional profile components; weak",
        "primary_source": "https://doi.org/10.4230/LIPIcs.SEA.2022.13"},
    "bocker_almost_clique": {
        "source": "research/baselines/almost_clique.py:almost_clique",
        "criterion": "Bocker2011 Rule4 on the fixed original bank mapped to each quotient; strict",
        "primary_source": "https://doi.org/10.1007/s00453-009-9339-7"},
}
PROOF_FILES = (
    "research/safe_contraction/theory-audit.md",
    "research/baselines/block-theorem-notes.md",
    "research/baselines/completion-manifest.json",
    "reviews/supervisor-experiment-design.md",
    "research/safe_contraction/global-quotient-audit-plan.md",
)


class AuditError(ValueError):
    """An exact identity or recorded dependency is inconsistent."""


class IncompleteRunError(AuditError):
    """No whole-suite audit is permitted before every launched job completes."""


def require(condition, message):
    if not condition:
        raise AuditError(message)


def fraction(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Integral):
        return Fraction(int(value))
    if isinstance(value, str):
        return Fraction(value)
    if isinstance(value, Real) and math.isfinite(float(value)):
        return Fraction.from_float(float(value))
    raise AuditError("Expected a finite exact integer, rational string, or stored binary float")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def payload_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()


def read_json(path):
    def reject(value):
        raise AuditError(f"Nonfinite JSON number: {value}")
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"), parse_constant=reject)


def write_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as target:
        json.dump(value, target, sort_keys=True, ensure_ascii=False, allow_nan=False)
        target.write("\n")


class InputCatalog:
    def __init__(self, root):
        self.root = Path(root)
        self.entries = {}

    def relative(self, path):
        return Path(os.path.relpath(Path(path).resolve(), self.root)).as_posix()

    def observe(self, path):
        path = Path(path)
        key = self.relative(path)
        value = {"status": "present", "sha256": sha256(path), "bytes": path.stat().st_size} if path.is_file() else {
            "status": "missing", "sha256": None}
        require(key not in self.entries or self.entries[key] == value,
                f"Input changed while audit was reading it: {key}")
        self.entries[key] = value
        return value

    def optional(self, path):
        observed = self.observe(path)
        if observed["status"] == "missing":
            return None, "missing_record"
        try:
            value = read_json(path)
            require(isinstance(value, dict), "Expected a JSON object record")
            return value, None
        except (ValueError, OSError, UnicodeError, EOFError) as error:
            return None, f"malformed_record:{type(error).__name__}:{error}"

    def verify_unchanged(self):
        for path in tuple(self.entries):
            self.observe(self.root / path)


@dataclass(frozen=True)
class Case:
    stratum: str
    case_id: str
    prefix: str
    job: str
    gammas: tuple[str, ...]
    specification: dict


def expected_cases(manifest):
    config, suites = manifest["config"], manifest["suites"]
    require(len(suites) == 3 and set(suites) == {"public", "controls", "scaling"},
            "This audit requires the complete frozen public, controls, and scaling launch suites")
    cases = []
    for seed in config["proposal"]["seeds"]:
        for dataset in config["public_datasets"]:
            prefix = f"{dataset}-proposal{seed}"
            cases.append(Case("public", prefix, prefix, f"public-{prefix}",
                              tuple(config["gamma"]), {"dataset": dataset, "proposal_seed": seed}))
    for spec in config["controlled_cases"]:
        prefix = spec["case_id"]
        cases.append(Case("controlled", prefix, prefix, prefix, tuple(spec["gamma"]), spec))
    for dataset in config["development_datasets"]:
        prefix = f"development-{dataset}"
        cases.append(Case("development", dataset, prefix, prefix, tuple(config["gamma"]),
                          {"dataset": dataset}))
    require(len({c.prefix for c in cases}) == len(cases), "Duplicate manifest case identifier")
    return cases


def expected_jobs(manifest):
    jobs = [case.job for case in expected_cases(manifest)]
    config = manifest["config"]
    if "scaling" in manifest["suites"]:
        settings = config["scaling"]
        for case in config["controlled_cases"]:
            if case["family"] != "profile_scaling":
                continue
            for measurement, count in (("timing", settings["replicate_count"]),
                                       ("memory", settings["memory_replicate_count"])):
                for replicate in range(count):
                    methods = settings["methods"]
                    ordered = methods[replicate % len(methods):] + methods[:replicate % len(methods)]
                    jobs.extend(f"scaling-{case['case_id']}-{method}-{measurement}-{replicate}"
                                for method in ordered)
    require(len(set(jobs)) == len(jobs), "Duplicate expected launch job")
    return jobs


def validate_complete_run(run_dir, catalog):
    manifest, error = catalog.optional(Path(run_dir) / "run-manifest.json")
    if error:
        raise IncompleteRunError(f"Run manifest unavailable: {error}")
    completed, error = catalog.optional(Path(run_dir) / "run-completed.json")
    if error or not completed or completed.get("status") != "completed":
        raise IncompleteRunError("Formal run has not completed successfully; no audit output created")
    jobs = expected_jobs(manifest)
    outcomes = completed.get("outcomes", [])
    if (completed.get("not_launched_due_failure") or len(outcomes) != len(jobs)
            or [row.get("job") for row in outcomes] != jobs
            or any(row.get("event") != "completed" or row.get("exit_code") != 0 for row in outcomes)):
        raise IncompleteRunError("Complete marker does not cover every expected successful launch job")
    return manifest, completed


@dataclass(frozen=True)
class ExactGraph:
    rows: tuple[dict[int, Fraction], ...]
    degrees: tuple[Fraction, ...]
    volume: Fraction

    @property
    def n(self):
        return len(self.rows)

    @classmethod
    def from_rows(cls, supplied):
        n = len(supplied)
        rows = []
        for row in supplied:
            converted = {}
            for vertex, value in row.items():
                require(isinstance(vertex, Integral) and 0 <= vertex < n, "Invalid adjacency index")
                weight = fraction(value)
                require(weight >= 0, "Audit adjacency must be nonnegative")
                if weight:
                    converted[int(vertex)] = weight
            rows.append(converted)
        require(all(rows[v].get(u, Fraction()) == weight
                    for u, row in enumerate(rows) for v, weight in row.items()), "Asymmetric exact adjacency")
        degree = tuple(sum(row.values(), Fraction()) for row in rows)
        volume = sum(degree, Fraction())
        require(volume > 0, "Modularity requires positive full graph volume")
        return cls(tuple(rows), degree, volume)

    @classmethod
    def from_csr(cls, adjacency):
        return cls.from_rows([{int(adjacency.indices[pos]): fraction(adjacency.data[pos])
                               for pos in range(adjacency.indptr[u], adjacency.indptr[u + 1])}
                              for u in range(adjacency.shape[0])])

    def objective(self, labels, gamma):
        require(len(labels) == self.n, "Witness does not cover every vertex")
        gamma = fraction(gamma)
        require(gamma >= 0, "Resolution must be nonnegative")
        volumes = defaultdict(Fraction)
        internal = Fraction()
        for u, row in enumerate(self.rows):
            volumes[labels[u]] += self.degrees[u]
            internal += sum((weight for v, weight in row.items() if labels[u] == labels[v]), Fraction())
        return internal / self.volume - gamma * sum((v * v for v in volumes.values()), Fraction()) / self.volume ** 2

    def content_hash(self):
        return payload_hash({"n": self.n, "upper_including_diagonal": [
            [u, v, str(weight)] for u, row in enumerate(self.rows)
            for v, weight in sorted(row.items()) if v >= u]})


def partition_groups(n, supplied):
    used, groups = set(), []
    for block in supplied:
        require(block and all(isinstance(u, Integral) and 0 <= u < n for u in block), "Malformed recorded group")
        group = tuple(sorted(map(int, block)))
        require(len(set(group)) == len(group) and not used.intersection(group), "Recorded final groups overlap or duplicate vertices")
        used.update(group)
        groups.append(group)
    groups.extend((u,) for u in range(n) if u not in used)
    return tuple(sorted(groups, key=lambda group: group[0]))


def merged_groups(n, blocks):
    parent = list(range(n))
    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u
    for block in blocks:
        require(len(block) >= 2 and all(isinstance(u, Integral) and 0 <= u < n for u in block), "Invalid certified block")
        require(len(set(block)) == len(block), "Duplicate vertex in certified block")
        for u in block[1:]:
            parent[find(u)] = find(block[0])
    groups = defaultdict(list)
    for u in range(n):
        groups[find(u)].append(u)
    return partition_groups(n, list(groups.values()))


def exact_quotient(graph, groups):
    groups = partition_groups(graph.n, groups)
    membership = [None] * graph.n
    for label, group in enumerate(groups):
        for u in group:
            membership[u] = label
    rows = [defaultdict(Fraction) for _ in groups]
    for u, row in enumerate(graph.rows):
        for v, weight in row.items():
            rows[membership[u]][membership[v]] += weight
    quotient = ExactGraph.from_rows(rows)
    require(quotient.volume == graph.volume, "Quotient changed total volume")
    require(quotient.degrees == tuple(sum((graph.degrees[u] for u in group), Fraction()) for group in groups),
            "Quotient changed aggregated degrees")
    return quotient, groups, tuple(membership)


def solve_exact(graph, gamma, *, enumeration_cap=ENUMERATION_CAP):
    require(enumeration_cap == ENUMERATION_CAP, "The predeclared enumeration cap is fixed at ten")
    gamma = fraction(gamma)
    require(gamma >= 0, "Resolution must be nonnegative")
    checked, positive = 0, None
    for u, row in enumerate(graph.rows):
        for v, weight in row.items():
            if v <= u:
                continue
            checked += 1
            contrast = weight - gamma * graph.degrees[u] * graph.degrees[v] / graph.volume
            if contrast > 0 and positive is None:
                positive = {"u": u, "v": v, "B_exact": str(contrast)}
    base = {"quotient_vertices": graph.n, "sign_test_positive_adjacency_pairs_checked": checked,
            "implicit_absent_pairs_nonpositive": True, "trivial": graph.n == 1,
            "timing_comparison": False}
    if positive is None:
        labels = tuple(range(graph.n))
        value = graph.objective(labels, gamma)
        return {**base, "resolution_status": "resolved_sign", "certificate_type": "all_nonpositive_offdiagonal",
                "Q_exact": str(value), "upper_bound_Q_exact": str(value), "labels": list(labels),
                "resolved": True, "uniqueness_asserted": False, "partitions_evaluated": 0}
    if graph.n > enumeration_cap:
        return {**base, "resolution_status": "unresolved_above_enumeration_cap", "resolved": False,
                "certificate_type": None, "reason": "positive pair and vertex count exceeds fixed enumeration cap",
                "first_positive_pair": positive, "Q_exact": None, "labels": None}
    pairs = list(combinations(range(graph.n), 2))
    coefficients = [graph.rows[u].get(v, Fraction()) - gamma * graph.degrees[u] * graph.degrees[v] / graph.volume
                    for u, v in pairs]
    denominator = math.lcm(*(c.denominator for c in coefficients))
    matrix = [[0] * graph.n for _ in range(graph.n)]
    for (u, v), value in zip(pairs, coefficients):
        matrix[u][v] = matrix[v][u] = value.numerator * (denominator // value.denominator)
    labels = [0] * graph.n
    best, witness, ties, count = None, None, 0, 0
    def visit(vertex, largest, score):
        nonlocal best, witness, ties, count
        if vertex == graph.n:
            count += 1
            if best is None or score > best:
                best, witness, ties = score, tuple(labels), 1
            elif score == best:
                ties += 1
            return
        for label in range(largest + 2):
            labels[vertex] = label
            gain = sum(matrix[vertex][u] for u in range(vertex) if labels[u] == label)
            visit(vertex + 1, max(largest, label), score + gain)
    visit(1, 0, 0)
    value = graph.objective(witness, gamma)
    diagonal = sum((graph.rows[u].get(u, Fraction()) - gamma * graph.degrees[u] ** 2 / graph.volume
                    for u in range(graph.n)), Fraction())
    require(value == (2 * Fraction(best, denominator) + diagonal) / graph.volume, "Enumeration objective disagrees with full-Q witness")
    return {**base, "resolution_status": "resolved_enumeration", "resolved": True,
            "certificate_type": "all_set_partitions_exact_integer_enumeration", "labels": list(witness),
            "Q_exact": str(value), "upper_bound_Q_exact": str(value), "partitions_evaluated": count,
            "optimum_partition_count": ties, "first_positive_pair": positive}


def unavailable(reason, *, source_status=None):
    return {"resolution_status": "unavailable", "resolved": False, "certificate_type": None,
            "Q_exact": None, "labels": None, "quotient_vertices": None, "trivial": False,
            "original_optimum_established": False, "original_optimum_proof_passed": False,
            "native_adapter_status": {"status": "not_inspected_unavailable_record"},
            "source_status": source_status, "reason": reason}


def error_unavailable(error, *, source_status=None):
    message = f"{type(error).__name__}:{error}"
    return {**unavailable(f"audit_error:{message}", source_status=source_status),
            "audit_errors": [message]}


def strip_timing(value):
    if isinstance(value, dict):
        return {key: strip_timing(item) for key, item in value.items()
                if not key.endswith("seconds") and "timing" not in key}
    if isinstance(value, (list, tuple)):
        return [strip_timing(item) for item in value]
    return value


def production_recheck(prepared, exact_graph, raw, gamma, bank, checker, certify):
    records = raw.get("candidate_certificates")
    require(isinstance(records, list), "Production candidate certificate records missing")
    accepted = [r for r in records if r.get("certified")]
    checks = []
    bank_set = {tuple(block) for block in bank}
    for record in accepted:
        block, metadata = tuple(record["block"]), record.get("metadata", {})
        require(block in bank_set, "Accepted production block absent from recorded bank")
        require(record.get("verification_status") in EXACT_STATUSES, "Accepted production certificate was not exact")
        require(metadata.get("graph_fingerprint") == prepared.fingerprint, "Accepted production graph fingerprint mismatch")
        require(metadata.get("gamma_exact") == str(gamma), "Accepted production resolution mismatch")
        require(all(exact_graph.degrees[u] > 0 for u in block), "Accepted production block has zero degree")
        result = certify(prepared, block, gamma, verification="exact",
                         exact_max_size=checker["exact_max_size"], dense_max_size=checker["dense_max_size"],
                         screen_tolerance=checker["screen_tolerance"])
        require(result.certified and result.verification_status in EXACT_STATUSES, "Forced exact production recheck failed")
        require(result.strict == record.get("strict"), "Forced exact strictness differs from recorded production certificate")
        require(result.metadata.get("graph_fingerprint") == prepared.fingerprint and result.metadata.get("gamma_exact") == str(gamma),
                "Forced exact certificate metadata mismatch")
        checks.append({"block": list(block), "recorded_status": record["verification_status"],
                       "forced_exact_status": result.verification_status, "strict": result.strict,
                       "verification_requested": "exact", "forced_exact_metadata": strip_timing(result.metadata)})
    expected = partition_groups(exact_graph.n, raw["reduction"]["merge_groups"])
    require(merged_groups(exact_graph.n, [r["block"] for r in accepted]) == expected,
            "Recorded production groups do not equal the union of its accepted certificates")
    return {"status": "verified", "accepted_block_count": len(accepted), "checks": checks,
            "basis": "forced exact frozen production checker plus positive-degree optimal-anchor compatibility proof",
            "source": "src/degree_contraction/certificate.py; src/degree_contraction/quotient.py",
            "proof": "research/safe_contraction/theory-audit.md#5-persistence-and-contraction-composition"}


def recursive_replay(adjacency, raw, gamma, bank, settings, replay):
    recorded = raw["result"]
    require(recorded.get("certified") is True and recorded.get("available") is True,
            "Recorded recursive baseline does not assert its reviewed safety guarantee")
    result = replay(adjacency, bank, gamma, max_block_size=settings["max_block_size"], include_round_decisions=True)
    n = adjacency.shape[0]
    require(partition_groups(n, result["merge_groups"]) == partition_groups(n, raw["reduction"]["merge_groups"]),
            "Recursive replay final groups differ from raw reporting groups")
    require(partition_groups(n, result["merge_groups"]) == partition_groups(n, recorded["merge_groups"]),
            "Recursive replay final groups differ from raw result groups")
    for key in ("gamma_exact", "input_vertices", "remaining_vertices", "removed_vertices", "strict", "round_count"):
        require(result.get(key) == recorded.get(key), f"Recursive replay differs on {key}")
    for key in ("original_graph_sha256", "original_bank_sha256", "final_quotient_sha256", "total_volume_exact", "max_block_size"):
        require(result["metadata"].get(key) == recorded["metadata"].get(key), f"Recursive replay identity mismatch: {key}")
    def round_contract(rounds):
        return [{key: item for key, item in strip_timing(row).items() if key != "decisions_current_vertex_ids"}
                for row in rounds]
    require(round_contract(result["round_stats"]) == round_contract(recorded["round_stats"]),
            "Recursive replay round decision counts differ from raw round statistics")
    return {"status": "replayed_groups_match", "basis": "reproducibility replay of independently reviewed frozen criterion implementation",
            "independent_reimplementation_of_prior_criteria": False,
            "safety_dependency": "reviewed strict criteria plus compatible weak twins, composed on exact current quotients",
            "criterion_dependencies": BASELINE_DEPENDENCIES, "proof_support": list(PROOF_FILES[1:4]),
            "trace": strip_timing(result)}


def validate_native(raw, graph, gamma, quotients=None, memberships=None):
    container = raw.get("native_full_solver") or {}
    if not isinstance(container, dict):
        message = "Malformed native full-solver container"
        return {arm: {"status": "malformed_record", "validation_status": "error", "audit_errors": [message]}
                for arm in ("unreduced", "reduced")}, {}
    paired = container.get("paired_arms", {})
    if not isinstance(paired, dict):
        message = "Malformed native paired-arm container"
        return {arm: {"status": "malformed_record", "validation_status": "error", "audit_errors": [message]}
                for arm in ("unreduced", "reduced")}, {}
    observations, values = {}, {}
    for arm in ("unreduced", "reduced"):
        record = paired.get(arm)
        if not record:
            observations[arm] = {"status": container.get("status", "not_recorded"),
                                 "reason": container.get("reason", container.get("verification_status", "no native paired arm"))}
            continue
        if not isinstance(record, dict):
            observations[arm] = {"status": "malformed_record", "validation_status": "error",
                                 "audit_errors": ["Malformed native arm record"]}
            continue
        observations[arm] = {"status": record.get("status"), "reason": record.get("reason"),
                             "optimality_proved": record.get("optimality_proved", False)}
        if record.get("status") not in NATIVE_COMPLETED:
            continue
        try:
            require(record.get("optimality_proved") is True, "Completed native status lacks optimality proof flag")
            labels = record.get("lifted_labels")
            require(isinstance(labels, list) and all(isinstance(label, Integral) for label in labels),
                    "Completed native optimum lacks integer lifted original labels")
            value = graph.objective(labels, gamma)
            require(value == fraction(record["solution"]["Q"]) == fraction(record["lifted_Q_original_exact"]),
                    "Completed native witness has inconsistent exact original modularity")
            solution_labels = record["solution"]["labels"]
            require(isinstance(solution_labels, list) and all(isinstance(label, Integral) for label in solution_labels),
                    "Completed native optimum lacks integer solver labels")
            if arm == "unreduced":
                require(solution_labels == labels, "Native original solver labels differ from its lifted labels")
            elif quotients and "production" in quotients:
                membership = memberships["production"]
                require(len(solution_labels) == quotients["production"].n, "Native reduced labels have the wrong quotient size")
                require([solution_labels[membership[u]] for u in range(graph.n)] == labels,
                        "Native reduced solution labels do not lift through the recorded production groups")
                require(quotients["production"].objective(solution_labels, gamma) == value,
                        "Native reduced witness fails exact quotient/lift identity")
                observations[arm]["quotient_lift_identity_verified"] = True
            else:
                observations[arm]["quotient_lift_identity_verified"] = False
                observations[arm]["quotient_lift_identity_reason"] = "production groups unavailable"
            values[arm] = value
            observations[arm].update(validation_status="verified_exact_witness",
                                     independently_checked_original_Q_exact=str(value))
        except Exception as error:
            observations[arm].update(validation_status="error", audit_errors=[f"{type(error).__name__}:{error}"])
    if len(set(values.values())) > 1:
        for observation in observations.values():
            observation.setdefault("audit_errors", []).append("Completed native original and reduced optima disagree")
    return observations, values


@contextmanager
def at_root(root):
    previous = Path.cwd()
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(previous)


def frozen_dependencies(root, manifest):
    # This is deliberately called only after the complete-run guard.
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "src"))
    from degree_contraction import certify_block, prepare_graph
    from experiments.datasets import load_development, load_snap
    from experiments.families import load_family
    from experiments.pipeline import graph_adjacency
    from research.baselines.recursive_cheap import recursive_cheap
    import networkx
    import numpy
    import scipy
    versions = {"python": platform.python_version(), "networkx": networkx.__version__,
                "numpy": numpy.__version__, "scipy": scipy.__version__}
    for name, expected in manifest["freeze"].get("versions", {}).items():
        require(versions.get(name) == expected, f"Runtime version changed since freeze: {name}")
    return {"certify": certify_block, "prepare": prepare_graph, "snap": load_snap,
            "development": load_development, "family": load_family, "adjacency": graph_adjacency,
            "replay": recursive_cheap, "versions": versions}


def case_bank(case, run_dir, catalog):
    suffix = "candidates.json.gz" if case.stratum == "public" else "input.json.gz"
    record, error = catalog.optional(run_dir / f"{case.prefix}-{suffix}")
    if error:
        return None, error, record
    try:
        data = record if case.stratum == "public" else record.get("candidate_bank")
        if data is None:
            if (case.stratum == "controlled" and case.specification.get("candidate_bank_evaluation") is False
                    and case.specification.get("family") == "profile_scaling"
                    and record.get("bank_status") == "skipped_predeclared_profile_computation_only"):
                return [], "predeclared_bank_skip", record
            return None, "missing_candidate_bank", record
        require(isinstance(data, dict), "Malformed candidate bank record")
        blocks = data.get("blocks")
        require(isinstance(blocks, list), "Candidate bank blocks missing")
        require(all(isinstance(block, list) and len(block) >= 2
                    and all(isinstance(u, Integral) and u >= 0 for u in block)
                    and len(set(block)) == len(block) for block in blocks), "Malformed candidate bank block")
        bank_hash = hashlib.sha256(json.dumps(blocks, separators=(",", ":")).encode()).hexdigest()
        require(bank_hash == record.get("bank_sha256"), "Recorded candidate bank hash mismatch")
        return blocks, None, record
    except Exception as error:
        return None, f"invalid_candidate_bank:{type(error).__name__}:{error}", record


def load_case_graph(case, dependencies):
    if case.stratum == "public":
        graph, metadata = dependencies["snap"](case.specification["dataset"])
    elif case.stratum == "development":
        graph, metadata = dependencies["development"](case.case_id)
    else:
        spec = case.specification
        graph, metadata = dependencies["family"](spec["family"], **spec["parameters"],
                                                   include_oracle_blocks=spec["supplied_block_comparison"])
    adjacency = dependencies["adjacency"](graph)
    prepared = dependencies["prepare"](adjacency)
    return adjacency, prepared, ExactGraph.from_csr(prepared.adjacency), metadata


def arm_payloads(case, raw, bank, bank_error):
    production = raw if case.stratum == "public" else raw.get("production_independent_bank")
    baselines = raw.get("global_baselines", {})
    recursive = baselines.get("recursive_cheap") if isinstance(baselines, dict) else None
    payloads = {"original": {"groups": [], "source_status": "uncontracted"}}
    if production is not None and not isinstance(production, dict):
        payloads["production"] = {"unavailable": "malformed_production_arm", "source_status": "malformed_record"}
    elif bank_error == "predeclared_bank_skip" and production and production.get("verification_status") == "predeclared_computation_only_bank_skip":
        payloads["production"] = {"groups": [], "source_status": production.get("status"),
                                  "identity_due_to_predeclared_skip": True, "raw": production}
    elif bank_error:
        payloads["production"] = {"unavailable": bank_error, "source_status": None}
    elif production and production.get("status") == "completed" and (
            not isinstance(production.get("reduction"), dict)
            or not isinstance(production["reduction"].get("merge_groups"), list)):
        payloads["production"] = {"unavailable": "malformed_production_reduction_groups", "source_status": "completed"}
    elif production and production.get("status") == "completed" and "reduction" in production:
        payloads["production"] = {"groups": production["reduction"]["merge_groups"],
                                  "source_status": "completed", "raw": production}
    else:
        payloads["production"] = {"unavailable": "missing_or_unavailable_production_arm",
                                  "source_status": None if not production else production.get("status")}
    if not isinstance(baselines, dict) or (recursive is not None and not isinstance(recursive, dict)):
        payloads["recursive"] = {"unavailable": "malformed_recursive_arm", "source_status": "malformed_record"}
    elif bank_error:
        payloads["recursive"] = {"unavailable": bank_error, "source_status": None}
    elif recursive and recursive.get("status") == "completed" and (
            not isinstance(recursive.get("reduction"), dict)
            or not isinstance(recursive["reduction"].get("merge_groups"), list)):
        payloads["recursive"] = {"unavailable": "malformed_recursive_reduction_groups", "source_status": "completed"}
    elif recursive and recursive.get("status") == "completed" and "reduction" in recursive:
        payloads["recursive"] = {"groups": recursive["reduction"]["merge_groups"],
                                 "source_status": "completed", "raw": recursive}
    else:
        payloads["recursive"] = {"unavailable": "missing_or_unavailable_recursive_arm",
                                 "source_status": None if not recursive else recursive.get("status")}
    return payloads


def audit_case_gamma(case, raw, graph_data, bank, bank_error, gamma, config, dependencies):
    adjacency, prepared, graph, _ = graph_data
    require(raw.get("graph_fingerprint") == prepared.fingerprint, "Raw graph fingerprint differs from reconstructed frozen graph")
    require(fraction(raw.get("gamma_exact", raw.get("gamma"))) == gamma, "Raw resolution differs from manifest tuple")
    payloads = arm_payloads(case, raw, bank, bank_error)
    rows, quotients, groups_by_arm = {}, {}, {}
    for arm in ARMS:
        payload = payloads[arm]
        if "unavailable" in payload:
            rows[arm] = unavailable(payload["unavailable"], source_status=payload.get("source_status"))
            if payload["unavailable"].startswith(("invalid_", "malformed_")):
                rows[arm]["audit_errors"] = [payload["unavailable"]]
            continue
        try:
            quotient, groups, membership = exact_quotient(graph, payload["groups"])
            rows[arm] = solve_exact(quotient, gamma)
            rows[arm].update({"source_status": payload["source_status"], "quotient_exact_graph_sha256": quotient.content_hash(),
                              "original_optimum_established": False, "identity_due_to_predeclared_skip": payload.get("identity_due_to_predeclared_skip", False),
                              "recorded_merge_group_count": sum(len(g) > 1 for g in groups),
                              "quotient_groups_original_vertex_ids": [list(group) for group in groups]})
            quotients[arm], groups_by_arm[arm] = quotient, (groups, membership)
        except Exception as error:
            rows[arm] = error_unavailable(error, source_status=payload.get("source_status"))
    production_check = {"status": "not_rechecked_no_arm_resolved"}
    if any(row.get("resolved") for row in rows.values()):
        payload = payloads["production"]
        if payload.get("identity_due_to_predeclared_skip"):
            production_check = {"status": "identity_predeclared_bank_skip", "accepted_block_count": 0}
        elif "raw" not in payload:
            production_check = {"status": "unavailable", "reason": payload.get("unavailable")}
        else:
            try:
                production_check = production_recheck(prepared, graph, payload["raw"], gamma, bank,
                                                     config["checker"], dependencies["certify"])
            except Exception as error:
                production_check = {"status": "error", "reason": f"{type(error).__name__}:{error}"}
    native_observations, native_values = validate_native(
        raw, graph, gamma, quotients, {arm: value[1] for arm, value in groups_by_arm.items()})
    recursive_check = {"status": "not_replayed_unresolved_or_unavailable"}
    if rows["recursive"].get("resolved"):
        try:
            recursive_check = recursive_replay(adjacency, payloads["recursive"]["raw"], gamma, bank,
                                               config["recursive_cheap"], dependencies["replay"])
        except Exception as error:
            recursive_check = {"status": "error", "reason": f"{type(error).__name__}:{error}",
                               "independent_reimplementation_of_prior_criteria": False}
    for arm, row in rows.items():
        row["production_certificate_recheck"] = {k: v for k, v in production_check.items() if k != "checks"}
        row["native_adapter_records"] = native_observations
        row["native_adapter_status"] = native_observations["unreduced" if arm == "original" else "reduced"] if arm != "recursive" else {
            "status": "not_predeclared_recursive_native_arm"}
        native_errors = [message for observation in native_observations.values()
                         for message in observation.get("audit_errors", [])]
        if native_errors:
            row.setdefault("audit_errors", []).extend(sorted(set(native_errors)))
        if arm == "production" and production_check["status"] == "error":
            row.setdefault("audit_errors", []).append(production_check["reason"])
        if arm == "recursive":
            row["recursive_safety_replay"] = {k: v for k, v in recursive_check.items() if k != "trace"}
            if recursive_check["status"] == "error":
                row.setdefault("audit_errors", []).append(recursive_check["reason"])
        if not row.get("resolved"):
            continue
        try:
            groups, membership = groups_by_arm[arm]
            lifted = [row["labels"][membership[u]] for u in range(graph.n)]
            value = quotients[arm].objective(row["labels"], gamma)
            require(value == graph.objective(lifted, gamma) == fraction(row["Q_exact"]), "Reported quotient witness fails exact lift identity")
        except Exception as error:
            row.setdefault("audit_errors", []).append(f"{type(error).__name__}:{error}")
            row["quotient_lift_objective_identity_verified"] = False
            continue
        row.update({"lifted_original_labels": lifted, "lifted_Q_original_exact": str(value),
                    "quotient_lift_objective_identity_verified": True})
        if arm == "original":
            row["original_optimum_established"] = True
            row["original_optimum_basis"] = "exact proof on the uncontracted original graph; independent of reduced-arm safety"
        elif arm == "production":
            row["original_optimum_established"] = production_check["status"] in {"verified", "identity_predeclared_bank_skip"}
            row["original_optimum_basis"] = production_check.get("basis", "identity quotient" if row["identity_due_to_predeclared_skip"] else "production safety unavailable")
        else:
            row["original_optimum_established"] = recursive_check["status"] == "replayed_groups_match"
            row["original_optimum_basis"] = recursive_check.get("basis", "recursive safety replay unavailable")
        row["original_optimum_proof_passed"] = row["original_optimum_established"]
        if row["original_optimum_established"]:
            row["completed_native_optima_compared"] = list(native_values)
            row["completed_native_comparison_consistent"] = all(value == expected for expected in native_values.values())
            if not row["completed_native_comparison_consistent"]:
                row.setdefault("audit_errors", []).append("Audit optimum disagrees with completed exact native optimum")
                # Preserve the independent original proof even when a recorded
                # native dependency is inconsistent; reduced claims remain
                # withheld until the discrepancy is investigated.
                if arm != "original":
                    row["original_optimum_established"] = False
    established = {row["Q_exact"] for row in rows.values() if row.get("original_optimum_established")}
    if len(established) > 1:
        for arm, row in rows.items():
            if row.get("original_optimum_established"):
                row.setdefault("audit_errors", []).append("Safe audit arms disagree on the original global optimum")
                if arm != "original":
                    row["original_optimum_established"] = False
    return rows, {"production": production_check, "recursive": recursive_check}


def summarize(rows, expected_tuples):
    require(len(rows) == expected_tuples * len(ARMS), "Audit lost an expected case/resolution/arm row")
    cells = defaultdict(lambda: {"denominator": 0, "status_counts": Counter(), "unavailability_reasons": Counter(),
                                 "source_status_counts": Counter(), "native_adapter_status_counts": Counter(),
                                 "production_recheck_status_counts": Counter(), "recursive_replay_status_counts": Counter(),
                                 "original_optima_established": 0, "original_optimum_proofs_passed": 0,
                                 "trivial_rows": 0, "audit_error_rows": 0})
    for row in rows:
        cell = cells[(row["stratum"], row["arm"])]
        cell["denominator"] += 1
        cell["status_counts"][row["resolution_status"]] += 1
        cell["source_status_counts"][str(row.get("source_status"))] += 1
        cell["native_adapter_status_counts"][str(row.get("native_adapter_status", {}).get("status"))] += 1
        cell["production_recheck_status_counts"][row.get("production_certificate_recheck", {}).get("status", "not_inspected_unavailable_record")] += 1
        if row["arm"] == "recursive":
            cell["recursive_replay_status_counts"][row.get("recursive_safety_replay", {}).get("status", "not_inspected_unavailable_record")] += 1
        cell["original_optima_established"] += bool(row.get("original_optimum_established"))
        cell["original_optimum_proofs_passed"] += bool(row.get("original_optimum_proof_passed"))
        cell["trivial_rows"] += bool(row.get("trivial"))
        cell["audit_error_rows"] += bool(row.get("audit_errors"))
        if row.get("reason"):
            cell["unavailability_reasons"][row["reason"]] += 1
    errors = sum(bool(row.get("audit_errors")) for row in rows)
    return {"schema": SCHEMA, "exploratory": True, "expected_case_resolution_tuples": expected_tuples,
            "expected_arm_rows": expected_tuples * len(ARMS), "observed_arm_rows": len(rows),
            "status": "completed_with_audit_errors" if errors else "completed", "audit_error_rows": errors,
            "stratum_arm_cells": [{"stratum": stratum, "arm": arm, **{k: dict(v) if isinstance(v, Counter) else v for k, v in cell.items()}}
                                  for (stratum, arm), cell in sorted(cells.items())],
            "performance_or_dominance_claim": False,
            "interpretation": "quotient exact optima establish original optima only when their explicitly recorded safety dependencies pass"}


def validate_output_directory(root, run_dir, output_dir):
    protected = (run_dir, root / "src", root / "experiments", root / "data",
                 root / "research/baselines", root / "research/full_kapoce")
    for directory in protected:
        try:
            output_dir.relative_to(directory)
        except ValueError:
            continue
        raise AuditError("Audit outputs must be separate from frozen inputs and runtime trees")
    require(not output_dir.exists(), "Immutable audit output directory already exists")


def run_audit(run_dir, output_dir, *, repo_root="."):
    root = Path(repo_root).resolve()
    run_dir = (root / run_dir).resolve()
    output_dir = (root / output_dir).resolve()
    validate_output_directory(root, run_dir, output_dir)
    catalog = InputCatalog(root)
    manifest, completed = validate_complete_run(run_dir, catalog)
    config = manifest["config"]
    for path, expected in manifest["freeze"]["runtime_source_sha256"].items():
        require(catalog.observe(root / path)["sha256"] == expected, f"Frozen runtime source mismatch: {path}")
    for path, expected in (("experiments/config.json", manifest["config_sha256"]),
                           ("experiments/freeze.json", manifest["freeze_sha256"]),
                           ("data/registry.json", manifest["freeze"]["data_registry_sha256"])):
        require(catalog.observe(root / path)["sha256"] == expected, f"Frozen input identity mismatch: {path}")
    require(read_json(root / "experiments/config.json") == config, "Manifest and frozen configuration differ")
    registry = read_json(root / "data/registry.json")
    for dataset in config["public_datasets"]:
        catalog.observe(root / registry[dataset]["path"])
    for path in PROOF_FILES:
        catalog.observe(root / path)
    cases = expected_cases(manifest)
    expected = sum(len(case.gammas) for case in cases)
    own_sources = ("analysis/global_quotient_audit.py", "analysis/test_global_quotient_audit.py")
    source_hashes = {path: catalog.observe(root / path)["sha256"] for path in own_sources}
    require(all(source_hashes.values()), "New audit source or engineering fixture file missing")
    with at_root(root):
        dependencies = frozen_dependencies(root, manifest)
        output_dir.mkdir(parents=True, exist_ok=False)
        write_once(output_dir / "audit-config.json", {
            "schema": SCHEMA, "exploratory": True, "created_utc": datetime.now(timezone.utc).isoformat(),
            "run_dir": catalog.relative(run_dir), "output_dir": catalog.relative(output_dir),
            "source_sha256": source_hashes, "frozen_runtime_source_sha256": manifest["freeze"]["runtime_source_sha256"],
            "manifest_sha256": sha256(run_dir / "run-manifest.json"), "complete_run_sha256": sha256(run_dir / "run-completed.json"),
            "frozen_config_sha256": manifest["config_sha256"], "freeze_sha256": manifest["freeze_sha256"],
            "data_registry_sha256": manifest["freeze"]["data_registry_sha256"],
            "independent_review_at_freeze": manifest["freeze"].get("independent_review"),
            "proof_support_records": {path: catalog.entries[path] for path in PROOF_FILES},
            "expected_launch_jobs": len(expected_jobs(manifest)), "expected_case_resolution_tuples": expected,
            "expected_cases": [{"stratum": c.stratum, "case_id": c.case_id, "prefix": c.prefix,
                                "job": c.job, "gammas": list(c.gammas), "specification": c.specification} for c in cases],
            "arms": list(ARMS), "policy": "rational sign certificate first, otherwise all set partitions for n<=10",
            "enumeration_cap": ENUMERATION_CAP, "runtime_versions": dependencies["versions"],
            "scaling_microbenchmarks_excluded": True, "controlled_profile_cases_retained_as_identity_production_arms": True,
            "recursive_validation": "frozen replay with round decisions, raw exact-group match; not an independent criterion implementation",
            "timing_comparison": False})
        for path in own_sources:
            target = output_dir / "source" / Path(path).name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write((root / path).read_bytes())
        all_rows = []
        for case in cases:
            case_marker, marker_error = catalog.optional(run_dir / f"{case.prefix}-completed.json")
            bank, bank_error, bank_record = case_bank(case, run_dir, catalog)
            graph_data = None
            for index, gamma_text in enumerate(case.gammas):
                gamma = fraction(gamma_text)
                input_path = run_dir / f"{case.prefix}-gamma{index}.json.gz"
                raw, error = catalog.optional(input_path)
                base = {"schema": SCHEMA, "exploratory": True, "stratum": case.stratum, "case_id": case.case_id,
                        "case_prefix": case.prefix, "gamma_index": index, "gamma_exact": str(gamma),
                        "input_record": catalog.relative(input_path), "input_record_sha256": catalog.entries[catalog.relative(input_path)]["sha256"],
                        "bank_record_status": bank_error or "completed",
                        "original_optimum_established": False, "original_optimum_proof_passed": False}
                reasons = error or marker_error
                if not reasons and case_marker.get("status") != "completed":
                    reasons = f"case_completion_status:{case_marker.get('status')}"
                if not reasons and raw.get("status") != "completed":
                    reasons = f"gamma_record_status:{raw.get('status')}"
                traces = {}
                if reasons:
                    arm_rows = {arm: unavailable(reasons, source_status=None if not raw else raw.get("status")) for arm in ARMS}
                else:
                    try:
                        if graph_data is None:
                            graph_data = load_case_graph(case, dependencies)
                        base["original_exact_graph_sha256"] = graph_data[2].content_hash()
                        effective_bank_error = bank_error
                        if bank_record and case.stratum != "public":
                            if bank_record.get("graph_fingerprint") != graph_data[1].fingerprint:
                                effective_bank_error = "invalid_candidate_bank:input-record graph fingerprint mismatch"
                        if bank_error is None:
                            if raw.get("bank_sha256") != bank_record.get("bank_sha256"):
                                effective_bank_error = "invalid_candidate_bank:gamma record and candidate bank hashes differ"
                        if bank is not None and any(u >= graph_data[2].n for block in bank for u in block):
                            effective_bank_error = "invalid_candidate_bank:vertex index exceeds reconstructed graph"
                        base["bank_record_status"] = effective_bank_error or "completed"
                        arm_rows, traces = audit_case_gamma(case, raw, graph_data, bank, effective_bank_error, gamma, config, dependencies)
                    except Exception as error:
                        arm_rows = {arm: error_unavailable(error) for arm in ARMS}
                for name, trace in traces.items():
                    if trace.get("status") in {"verified", "replayed_groups_match"}:
                        relative = f"traces/{case.prefix}-gamma{index}-{name}.json"
                        write_once(output_dir / relative, trace)
                        for row in arm_rows.values():
                            row.setdefault("dependency_trace_files", {})[name] = relative
                for arm in ARMS:
                    row = {**base, "arm": arm, **arm_rows[arm]}
                    write_once(output_dir / "records" / f"{case.prefix}-gamma{index}-{arm}.json", row)
                    all_rows.append(row)
        summary = summarize(all_rows, expected)
        catalog.verify_unchanged()
        write_once(output_dir / "input-hashes.json", {"schema": SCHEMA, "records": catalog.entries})
        write_once(output_dir / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    try:
        result = run_audit(args.run_dir, args.output_dir, repo_root=args.repo_root)
    except (AuditError, OSError, KeyError) as error:
        print(f"Audit not executed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 2 if result["audit_error_rows"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
