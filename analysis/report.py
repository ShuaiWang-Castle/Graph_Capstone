"""Aggregate a complete frozen suite without importing its numerical runtime.

The field contracts below are backed by the SHA-256-identified frozen runners.
An incomplete, failed, identity-mismatched, or internally inconsistent suite
raises before publication-facing tables are written. Timeouts and declared
input-domain exclusions remain observations, with explicit denominators.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from fractions import Fraction
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable


SCHEMA_VERSION = "frozen-suite-analysis-v1"
FROZEN_STATUS = "frozen_after_independent_design_review"
BAD_STATUSES = {"failed", "validation_failure", "unavailable_build", "failed_or_interrupted"}
FULL_COMPLETED = {"optimal", "optimal_trivial"}
BLOCK_EXTRA_METHODS = ("degree_median_forced_exact", "degree_median_independent_exact")
SCALING_COMPONENTS = (
    "production_exterior_assembly_seconds", "production_dense_eigensolve_seconds",
    "production_exact_verification_seconds", "reference_assembly_seconds", "reference_verification_seconds",
    "dense_diagnostic_assembly_seconds", "dense_diagnostic_dense_exterior_assembly_seconds",
)
SCALING_COMPONENT_SCOPES = {
    "degree_median": "production exterior assembly measures sparse dispersion only; dense eigensolve and exact verification are separate instrumented stages; whole checker includes other assembly and O(n) CSR slicing workspace",
    "degree_full_pair": "reference assembly includes rational contrast matrix and projected-basis construction; reference verification measures exact projected PSD checking; float diagnostics and other overhead remain in whole checker",
    "dense_exterior_diagnostic": "dense diagnostic assembly includes exterior table and float contrast matrix; no certification or exact verification; later float diagnostic work remains in whole checker",
}
SOURCE_CONTRACTS = {
    "completion_and_job_identity": "experiments/run_all.py:jobs/main",
    "public_paired_workloads": "experiments/run_public.py:run_case",
    "quotient_counts_and_loop_convention": "experiments/pipeline.py:summarize_quotient",
    "positive_degree_denominator": "experiments/datasets.py:load_snap; src/degree_contraction/certificate.py:certify_block",
    "controlled_and_development_panels": "experiments/run_controls.py:run_case/evaluate_block_references",
    "c_subinstance_ties_and_arithmetic": "experiments/exact_oracle.py:check_c_subinstance",
    "native_completed_pair_eligibility": "experiments/run_controls.py:evaluate_full_native; research/full_kapoce/run_full.py:run_full_case",
    "native_optimum_feasible_Q_integrity": "experiments/run_controls.py:evaluate_numerical_milp/run_case; analysis/report.py:_full_original_feasible_Q/_full_native",
    "selected_native_expanded_groups": "research/baselines/kapoce_selected.cpp:weighted_recursive; research/baselines/run_kapoce.py:run_case",
    "scaling_timing_memory_separation": "experiments/run_scaling.py:run_scaling",
    "weak_composition_scope": "research/baselines/recursive_cheap.py:recursive_cheap",
    "post_freeze_size_mechanism_basis": "reviews/novelty-strength-audit.md; analysis/report.py:_production_size_mechanism",
}
INTERPRETATION_LIMITS = [
    "Join-rank additional identifications compare structural equivalence relations only. They do not prove safe composition of separately weak contractions, domination, or downstream superiority over a baseline without paired downstream arms.",
    "Public coverage is production AUTO with its recorded cap/screen exclusions. Forced EXACT and independent rational references are separate mathematical side panels, never substituted into production coverage.",
    "Every reported public workload retains the same discovery incumbent for both arms. Primary timing comparison uses discovery plus unreduced Louvain; cold unreduced timing is a separately labeled reference.",
    "Complete native solve-time ratios require both arm statuses optimal/optimal_trivial and independently validated exact original Q. Analytic one-node quotients are separate from native-only completed pairs. Timeout wall duration is censored observation time, never a completed solve time.",
    "Native integer editing costs use independently chosen GCD scales. Only original exact modularity Q or exactly converted Q bounds are compared across arms; editing costs are not compared.",
    "Selected weighted preprocessing uses expanded residual groups plus solved_groups. A cleared residual after cliques_stop does not mean that all original vertices disappeared or fused into one vertex.",
    "Numerical MILP bounds, numerical C-subinstance matches, and dense exterior assembly are diagnostics and never mathematical certificates. Unresolved/guarded cases remain unavailable.",
    "Scaling performance uses only the three unprofiled timing repetitions. The separate memory repetition has tracemalloc enabled; its time is excluded. Process RSS includes graph/preparation and the full checker includes O(n) CSR column-slicing workspace.",
    "Controlled generator reference blocks are supplied only to the labeled mathematical-criterion study. Independent bank coverage uses the fixed certificate-independent seed0 bank. Development data and exploratory stress controls are not public holdout evidence.",
    "Acceptance-by-size and pair-only/collective-only ranks are post-freeze descriptive mechanism summaries, not new predeclared primary endpoints. Pair-only means accepted production size-two certificates; no exact Böcker Rule5 implementation or execution is implied. Collective additions are measured within the already accepted production certificate family, while raw all-certificate coverage stays unchanged.",
    "A recovered collection is a derived logical selection, not a complete original v1 run. Whole recovery Davis is primary; parent partial Davis timings are nonprimary evidence. The reviewed two-arm native assertion retains failed status, with no native optimum, packing bound, gap, or completed time ratio; only its independently verified supplied incumbent remains usable.",
    "For every completed native claimed optimum, an integrity gate requires its exact lifted original Q to be at least every source-backed exact full-original discovery/MILP feasible Q. Numerical bounds and local C-subinstance objectives are excluded; reviewed failed native arms make no optimum comparison.",
]


class AnalysisError(ValueError):
    """A complete suite is inconsistent with its frozen source contract."""


class IncompleteSuiteError(AnalysisError):
    """A publication-facing summary is forbidden until all jobs complete."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def _reject_constant(value: str):
    raise AnalysisError(f"Nonfinite JSON number is outside the raw contract: {value}")


def read_json(path: Path) -> Any:
    try:
        raw = path.read_bytes()
        if path.suffix == ".gz":
            raw = gzip.decompress(raw)
        return json.loads(raw, parse_constant=_reject_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, gzip.BadGzipFile) as error:
        raise AnalysisError(f"Cannot read required artifact {path.name}: {error}") from error


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise AnalysisError(f"Cannot hash required artifact {path.name}: {error}") from error
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _number(value: Any, name: str, *, nonnegative: bool = False) -> float:
    _require(type(value) in (int, float) and math.isfinite(value), f"Nonfinite/nonnumeric {name}: {value!r}")
    _require(not nonnegative or value >= 0, f"Negative {name}")
    return float(value)


def _optional_number(value: Any) -> float | None:
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _time(record: dict, key: str) -> float:
    _require(key in record, f"Missing measured time {key}")
    return _number(record[key], key, nonnegative=True)


def _close(actual: Any, expected: float, name: str) -> None:
    _require(math.isclose(_number(actual, name), expected, rel_tol=1e-9, abs_tol=1e-8),
             f"Inconsistent derived value {name}: {actual!r} != {expected!r}")


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _stats(values: Iterable[Any]) -> dict:
    numbers = [float(x) for x in values if type(x) in (int, float) and math.isfinite(x)]
    return {"n": len(numbers), "median": statistics.median(numbers) if numbers else None,
            "min": min(numbers) if numbers else None, "max": max(numbers) if numbers else None}


def _flatten_stats(values: Iterable[Any], prefix: str) -> dict:
    return {f"{prefix}_{key}": value for key, value in _stats(values).items()}


def _block_key(block: Iterable[int], n: int) -> tuple[int, ...]:
    result = tuple(block)
    _require(all(type(u) is int and 0 <= u < n for u in result), "Block has an invalid original vertex")
    _require(len(set(result)) == len(result), "Block contains duplicate vertices")
    return result


def identifications(n: int, groups: Iterable[Iterable[int]]) -> int:
    """Rank of the structural equivalence relation, not a joint certificate."""
    parent = list(range(n))
    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u
    for group in groups:
        block = _block_key(group, n)
        for u in block[1:]:
            parent[find(u)] = find(block[0])
    return n - len({find(u) for u in range(n)})


def expanded_native_groups(n: int, result: dict) -> tuple[list[list[int]], int]:
    """Use the upstream expanded idmaps, never residual vertex disappearance."""
    groups = [list(_block_key(group, n)) for group in
              [*result.get("groups", []), *result.get("solved_groups", [])]]
    _require(all(groups), "Selected native returned an empty expanded group")
    members = [u for group in groups for u in group]
    _require(len(members) == len(set(members)), "Selected native expanded groups overlap")
    _require(set(members) == set(range(n)), "Selected native expanded groups do not partition the original vertices")
    _require(result.get("input_vertices") == n, "Selected native input vertex identity mismatch")
    _require(result.get("remaining_vertices") == len(result.get("groups", [])), "Selected native residual idmap mismatch")
    return groups, n - len(groups)


@dataclass(frozen=True)
class Job:
    name: str
    stratum: str
    prefix: str
    identifier: str
    gamma: tuple[str, ...] = ()
    seed: int | None = None
    method: str | None = None
    measurement: str | None = None
    replicate: int | None = None

    def required_artifacts(self) -> tuple[str, ...]:
        if self.stratum == "scaling":
            return (f"{self.name}.json.gz",)
        bank = "candidates" if self.stratum == "public" else "input"
        return (f"{self.prefix}-started.json", f"{self.prefix}-{bank}.json.gz",
                *(f"{self.prefix}-gamma{i}.json.gz" for i in range(len(self.gamma))),
                f"{self.prefix}-completed.json")


def expected_jobs(config: dict, suites: list[str]) -> list[Job]:
    """Faithful naming/order contract from frozen run_all.jobs; no runtime import."""
    _require(len(set(suites)) == len(suites) and set(suites) == {"public", "controls", "scaling"},
             "Final analysis requires the complete public/controls/scaling suite")
    jobs: list[Job] = []
    if "public" in suites:
        for seed in config["proposal"]["seeds"]:
            for dataset in config["public_datasets"]:
                prefix = f"{dataset}-proposal{seed}"
                jobs.append(Job(f"public-{prefix}", "public", prefix, dataset, tuple(config["gamma"]), seed))
    if "controls" in suites:
        for case in config["controlled_cases"]:
            jobs.append(Job(case["case_id"], "controlled", case["case_id"], case["case_id"], tuple(case["gamma"]), case["candidate_bank_seed"]))
        for dataset in config["development_datasets"]:
            jobs.append(Job(f"development-{dataset}", "development", f"development-{dataset}", dataset, tuple(config["gamma"]), config["supplied_block_config"].get("development_bank_seed", 0)))
    if "scaling" in suites:
        for case in config["controlled_cases"]:
            if case["family"] != "profile_scaling":
                continue
            for measurement, repetitions in (("timing", config["scaling"]["replicate_count"]),
                                             ("memory", config["scaling"]["memory_replicate_count"])):
                for replicate in range(repetitions):
                    methods = config["scaling"]["methods"]
                    methods = methods[replicate % len(methods):] + methods[:replicate % len(methods)]
                    for method in methods:
                        name = f"scaling-{case['case_id']}-{method}-{measurement}-{replicate}"
                        jobs.append(Job(name, "scaling", name, case["case_id"], (), None, method, measurement, replicate))
    _require(len({job.name for job in jobs}) == len(jobs), "Frozen configuration produces duplicate jobs")
    return jobs


@dataclass
class AuditedSuite:
    project: Path
    run_dir: Path
    config: dict
    freeze: dict
    manifest: dict
    completion: dict
    jobs: list[Job]
    raw_hashes: dict[str, str]
    collection: dict | None = None

    def load(self, filename: str) -> Any:
        path = self.run_dir / filename
        value = read_json(path)
        self.raw_hashes[filename] = sha256(path)
        return value

    def provenance(self, record: dict, where: str) -> None:
        _require(record.get("config_sha256") == self.manifest["config_sha256"], f"Config identity mismatch in {where}")
        _require(record.get("freeze_sha256") == self.manifest["freeze_sha256"], f"Freeze identity mismatch in {where}")
        _require(record.get("runtime_source_sha256") == self.freeze["runtime_source_sha256"], f"Runtime identity mismatch in {where}")
        _require(record.get("versions") == self.freeze["versions"], f"Numerical runtime versions differ in {where}")
        _require(record.get("thread_environment") == self.config["threads"], f"Thread configuration mismatch in {where}")
        for key in ("platform", "machine"):
            if key in self.freeze.get("hardware", {}):
                _require(record.get(key) == self.freeze["hardware"][key], f"Hardware identity mismatch in {where}")

    def known_native_failure(self, record: dict) -> bool:
        if not self.collection or record.get("status") != "failed":
            return False
        digest = hashlib.sha256(_canonical(record)).hexdigest()
        return digest in self.collection["incident"]["allowed_native_record_sha256"].values()


def _verify_frozen_packet(project: Path, config: dict, freeze: dict, config_path: str, freeze_path: str,
                          config_sha: str, freeze_sha: str) -> None:
    _require(freeze.get("status") == FROZEN_STATUS, "Manifest has no independently reviewed freeze")
    for path_text, expected, snapshot in ((config_path, config_sha, config), (freeze_path, freeze_sha, freeze)):
        path = project/path_text
        _require(sha256(path) == expected and read_json(path) == snapshot, f"Current {path_text} differs from manifest snapshot")
    _require(freeze["config_sha256"] == config_sha, "Freeze/config cross-identity mismatch")
    frozen_paths = dict(freeze["runtime_source_sha256"])
    for field, path in (("data_registry_sha256", "data/registry.json"), ("processed_metadata_sha256", "data/processed-metadata.json"), ("protocol_sha256", "experiments/protocol.md")):
        if field in freeze:
            frozen_paths[path] = freeze[field]
    for field in ("independent_review", "engineering_validation"):
        item = freeze.get(field)
        if item:
            frozen_paths[item["path"]] = item["sha256"]
    for path_text, expected in frozen_paths.items():
        path = project/path_text
        _require(path.is_file() and sha256(path) == expected, f"Frozen source/data/discipline artifact changed: {path_text}")


def audit_suite(run_dir: Path | str, *, project_root: Path | str = ".",
                config_path: str = "experiments/config.json", freeze_path: str = "experiments/freeze.json",
                expected_job_count: int | None = None) -> AuditedSuite:
    """Fail on incompleteness before reading any gamma measurement artifact."""
    project = Path(project_root).resolve()
    run_dir = Path(run_dir).resolve()
    if (run_dir/"collection-manifest.json").is_file():
        from analysis.collect_recovery import audit_collection
        collection = audit_collection(run_dir, project_root=project, expected_job_count=expected_job_count)
        manifest, completion = read_json(run_dir/"run-manifest.json"), read_json(run_dir/"run-completed.json")
        config, freeze = manifest["config"], manifest["freeze"]
        _verify_frozen_packet(project, config, freeze, config_path, freeze_path, manifest["config_sha256"], manifest["freeze_sha256"])
        hashes = {name: sha256(run_dir/name) for name in ("collection-manifest.json", "run-manifest.json", "run-completed.json", "orchestration.jsonl")}
        hashes.update({name: item["sha256"] for name, item in collection["copied_artifacts"].items()})
        return AuditedSuite(project, run_dir, config, freeze, manifest, completion,
            expected_jobs(config, ["public", "controls", "scaling"]), hashes, collection)
    complete_path = run_dir / "run-completed.json"
    if not complete_path.is_file():
        raise IncompleteSuiteError("No run-completed.json: the suite is still running or interrupted; no final summary is generated")
    completion = read_json(complete_path)
    if completion.get("status") != "completed" or completion.get("not_launched_due_failure"):
        raise IncompleteSuiteError("Orchestration did not complete every configured job; no final summary is generated")
    manifest = read_json(run_dir / "run-manifest.json")
    _require(manifest.get("status") == "launched", "Unexpected manifest status")
    config, freeze = manifest["config"], manifest["freeze"]
    _verify_frozen_packet(project, config, freeze, config_path, freeze_path, manifest["config_sha256"], manifest["freeze_sha256"])
    jobs = expected_jobs(config, manifest["suites"])
    if expected_job_count is not None:
        _require(len(jobs) == expected_job_count, f"Expected {expected_job_count} processes but frozen manifest declares {len(jobs)}")
    expected_names = [job.name for job in jobs]
    outcomes = completion.get("outcomes", [])
    if [item.get("job") for item in outcomes] != expected_names:
        raise IncompleteSuiteError("Completed outcomes do not match every expected job in frozen order")
    _require(all(item.get("event") == "completed" and item.get("exit_code") == 0 for item in outcomes), "A process failed in a nominally completed suite")
    events_path = run_dir / "orchestration.jsonl"
    try:
        events = [json.loads(line, parse_constant=_reject_constant) for line in events_path.read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as error:
        raise AnalysisError("Orchestration ledger is unreadable") from error
    _require(len(events) == 2 * len(jobs), "Orchestration ledger contains missing/extra events")
    expected_artifacts = {"run-manifest.json", "run-completed.json", "orchestration.jsonl"}
    for index, (job, outcome) in enumerate(zip(jobs, outcomes)):
        _require(events[2 * index].get("event") == "started" and events[2 * index].get("job") == job.name,
                 f"Missing/out-of-order launch for {job.name}")
        _require(events[2 * index + 1] == outcome, f"Ledger/completion terminal mismatch for {job.name}")
        _time(outcome, "seconds")
        _require(outcome.get("log") == f"{job.name}.log" and (run_dir / outcome["log"]).is_file(), f"Missing process log for {job.name}")
        expected_artifacts.update(job.required_artifacts())
        expected_artifacts.add(outcome["log"])
        for filename in job.required_artifacts():
            if not (run_dir / filename).is_file():
                raise IncompleteSuiteError(f"Missing completed-case artifact {filename}")
    measurement_files = {path.name for path in run_dir.iterdir() if path.is_file() and
                         (path.name.endswith(".json") or path.name.endswith(".json.gz") or path.name.endswith(".jsonl"))}
    _require(not measurement_files - expected_artifacts, f"Unexpected/failure measurement artifacts: {sorted(measurement_files - expected_artifacts)}")
    hashes = {name: sha256(run_dir / name) for name in ("run-manifest.json", "run-completed.json", "orchestration.jsonl")}
    return AuditedSuite(project, run_dir, config, freeze, manifest, completion, jobs, hashes)


def _no_failures(value: Any, where: str, *, allowed_failure=None) -> None:
    if isinstance(value, dict):
        _require(value.get("status") not in BAD_STATUSES or
                 (allowed_failure is not None and ".native_full_solver." in where and allowed_failure(value)),
                 f"Unexpected raw failure in {where}: {value.get('status')}")
        for key, item in value.items():
            _no_failures(item, f"{where}.{key}", allowed_failure=allowed_failure)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _no_failures(item, f"{where}[{index}]", allowed_failure=allowed_failure)


def _coverage(reduction: dict, dataset: dict) -> dict:
    n = dataset["n"]
    _require(type(n) is int and n >= 1 and reduction.get("original_vertices") == n, "Graph/reduction original size mismatch")
    groups = reduction.get("merge_groups", [])
    removed = identifications(n, groups)
    _require(reduction.get("removed_vertices") == removed and reduction.get("remaining_vertices") == n - removed,
             "Reported quotient vertex disappearance differs from its merge groups")
    _close(reduction["removed_fraction"], removed / n, "removed_fraction")
    positive = n - dataset["isolates"] if "isolates" in dataset else None
    _require(positive is None or 0 <= positive <= n, "Invalid positive-degree denominator")
    lcc = reduction.get("largest_component_under_original_objective", {})
    if "largest_component_n" in dataset:
        _require(lcc.get("vertices") == dataset["largest_component_n"], "LCC denominator differs from original full graph")
    if lcc:
        _require(0 <= lcc["removed_vertices"] <= lcc["vertices"], "Invalid LCC coverage")
        _close(lcc["removed_fraction"], _ratio(lcc["removed_vertices"], lcc["vertices"]) or 0, "lcc_removed_fraction")
    return {"original_vertices": n, "positive_degree_vertices": positive,
            "remaining_vertices": n - removed, "removed_vertices": removed,
            "removed_fraction_all": removed / n,
            "removed_fraction_positive_degree": _ratio(removed, positive) if positive is not None else None,
            "lcc_vertices": lcc.get("vertices"), "lcc_removed_vertices": lcc.get("removed_vertices"),
            "removed_fraction_lcc_under_original_objective": lcc.get("removed_fraction"),
            "original_edges": reduction.get("original_off_diagonal_edges"),
            "remaining_edges": reduction.get("remaining_off_diagonal_edges")}


def _certificate_counts(records: list[dict], expected_blocks: list, status_counts: dict | None = None) -> dict:
    _require([tuple(item["block"]) for item in records] == [tuple(block) for block in expected_blocks], "Certificate bank/order identity mismatch")
    statuses = dict(sorted(Counter(item["verification_status"] for item in records).items()))
    if status_counts is not None:
        _require(statuses == status_counts, "Raw certification status counts do not reconcile")
    accepted = [item for item in records if item.get("certified") is True]
    return {"candidate_count": len(records), "accepted_blocks": len(accepted),
            "accepted_strict_blocks": sum(item.get("strict") is True for item in accepted),
            "accepted_weak_blocks": sum(item.get("strict") is not True for item in accepted),
            "cap_exclusions": sum(count for status, count in statuses.items() if "size_limit" in status or "guard" in status or "cap" in status),
            "certification_status_counts": statuses}


def _production_size_mechanism(records: list[dict], n: int, reduction: dict) -> dict:
    """Post-freeze descriptive ranks within the accepted production family.

    This does not execute a new criterion, form a new quotient, or compare to
    exact Rule5. The original accepted-certificate union is reconciled against
    the immutable production reduction before taking any size-specific ranks.
    """
    accepted = [_block_key(record["block"], n) for record in records if record.get("certified") is True]
    _require(all(len(block) >= 2 for block in accepted), "Production accepted a block below the predeclared size-two minimum")
    pair_blocks = [block for block in accepted if len(block) == 2]
    collective_blocks = [block for block in accepted if len(block) > 2]
    all_rank = identifications(n, accepted)
    raw_rank = identifications(n, reduction["merge_groups"])
    _require(all_rank == raw_rank == reduction["removed_vertices"], "Accepted production certificates do not reconcile with immutable all-certificate coverage")
    pair_rank = identifications(n, pair_blocks)
    collective_rank = identifications(n, collective_blocks)
    return {"accepted_pair_blocks": len(pair_blocks), "accepted_collective_blocks": len(collective_blocks),
            "accepted_block_size_counts": dict(sorted(Counter(str(len(block)) for block in accepted).items(), key=lambda item: int(item[0]))),
            "pair_only_removed_vertices": pair_rank, "collective_only_removed_vertices": collective_rank,
            "all_accepted_certificate_identifications": all_rank,
            "collective_additions_beyond_accepted_production_pairs": all_rank - pair_rank,
            "size_mechanism_endpoint_role": "post-freeze descriptive mechanism summary; not a predeclared primary endpoint",
            "pair_only_comparison_scope": "accepted production size-two certificates; not an executed exact Bocker Rule5 baseline"}


def _bank_identity(blocks: list) -> str:
    return hashlib.sha256(json.dumps(blocks, separators=(",", ":")).encode()).hexdigest()


def _baseline_rows(raw: dict, primary: dict | None, context: dict, dataset: dict) -> list[dict]:
    rows = []
    n = dataset["n"]
    new_groups = primary["reduction"]["merge_groups"] if primary and primary.get("status") == "completed" else None
    for name, record in sorted(raw.items()):
        _require(record.get("status") == "completed", f"Global baseline {name} did not complete")
        row = {**context, "method": name, "criterion": record.get("criterion"),
               "algorithm_scope": record.get("algorithm_scope"), "strict_output": record.get("strict"),
               **_coverage(record["reduction"], dataset),
               "checker_seconds": _time(record, "checker_seconds"),
               "reporting_quotient_seconds": _time(record, "quotient_seconds"),
               "decision_count": record.get("decision_count"),
               "weak_composition_scope": record.get("result", {}).get("metadata", {}).get("weak_composition") or
                    ("compatible degree-proportional profile components" if name == "degree_proportional_twins" else "every-optimum strict facts" if record.get("strict") else record.get("algorithm_scope")),
               "guarantee_scope": record.get("result", {}).get("metadata", {}).get("guarantee"),
               "checker_timing_scope": record.get("timing_scope") or
                    ("includes method-specific sparse preparation" if context["stratum"] == "public" else "reuses separately charged shared baseline representation")}
        row["checker_plus_reporting_quotient_seconds"] = row["checker_seconds"] + row["reporting_quotient_seconds"]
        if new_groups is not None:
            old_groups = record["reduction"]["merge_groups"]
            joint = identifications(n, [*new_groups, *old_groups])
            row["new_structural_identifications_beyond_baseline"] = joint - identifications(n, old_groups)
            row["baseline_structural_identifications_beyond_new"] = joint - identifications(n, new_groups)
            for field, derived in (("new_identifications_beyond_baseline", row["new_structural_identifications_beyond_baseline"]),
                                   ("baseline_identifications_beyond_new", row["baseline_structural_identifications_beyond_new"])):
                if field in record:
                    _require(record[field] == derived, "Stored structural join-rank comparison does not reconcile")
        if name == "recursive_cheap":
            result = record["result"]
            _require(result["removed_vertices"] == row["removed_vertices"], "Recursive final group/count mismatch")
            row.update(recursive_round_count=result["round_count"], recursive_merge_round_count=result["merge_round_count"],
                       recursive_weak_profile_used=not result["strict"], recursive_status=result["status"])
            decision_totals = Counter()
            strict_decisions = weak_decisions = 0
            for round_record in result.get("round_stats", []):
                for criterion, criterion_record in round_record.get("criteria", {}).items():
                    count = criterion_record["decision_count"]
                    decision_totals[criterion] += count
                    if criterion_record["strict"]:
                        strict_decisions += count
                    else:
                        weak_decisions += count
            row.update(recursive_round_decision_totals=dict(sorted(decision_totals.items())),
                       recursive_strict_round_decisions=strict_decisions, recursive_weak_profile_round_decisions=weak_decisions)
        rows.append(row)
    return rows


def _public(suite: AuditedSuite, job: Job, tables: dict[str, list]) -> None:
    started = suite.load(f"{job.prefix}-started.json")
    suite.provenance(started, job.prefix)
    _require(started.get("dataset") == job.identifier and started.get("proposal_seed") == job.seed, "Public started identity mismatch")
    bank = suite.load(f"{job.prefix}-candidates.json.gz")
    _require(bank["seed"] == job.seed and bank["bank_sha256"] == _bank_identity(bank["blocks"]), "Public discovery bank/hash mismatch")
    for index, gamma in enumerate(job.gamma):
        filename = f"{job.prefix}-gamma{index}.json.gz"
        raw = suite.load(filename)
        _no_failures(raw, filename)
        _require(raw.get("status") == "completed" and Fraction(raw["gamma"]) == Fraction(gamma), "Public gamma/status mismatch")
        _require(raw["proposal_seed"] == job.seed and raw["bank_sha256"] == bank["bank_sha256"] and raw["dataset"] == bank["dataset"], "Public gamma bank/graph identity mismatch")
        dataset = raw["dataset"]
        _require(dataset.get("name") == job.identifier and len(bank["discovery_labels"]) == dataset["n"], "Public dataset/labels mismatch")
        registry = read_json(suite.project / "data/registry.json")
        if job.identifier in registry:
            _require(dataset["raw_sha256"] == registry[job.identifier]["sha256"], "Public graph archive identity mismatch")
        context = {"stratum": "public", "dataset": job.identifier, "proposal_seed": job.seed,
                   "gamma": str(Fraction(gamma)), "source": filename,
                   "graph_fingerprint": raw["graph_fingerprint"], "bank_sha256": raw["bank_sha256"]}
        counts = _certificate_counts(raw["candidate_certificates"], bank["blocks"], raw["certification_status_counts"])
        counts.update(_production_size_mechanism(raw["candidate_certificates"], dataset["n"], raw["reduction"]))
        component_times = ("preparation_seconds", "proposal_seconds", "refinement_seconds", "checker_seconds",
                           "quotient_seconds", "quotient_conversion_seconds", "discovery_incumbent_seconds")
        preprocessing = sum(_time(raw, key) for key in component_times)
        _close(raw["preprocessing_seconds"], preprocessing, "preprocessing_seconds")
        _close(raw["discovery_incumbent_seconds"], _time(raw, "original_discovery_evaluation_seconds") + _time(raw, "quotient_discovery_evaluation_seconds"), "discovery_incumbent_seconds")
        q_discovery = _number(raw["modularity_discovery"], "discovery_Q")
        tables["public_seed_rows"].append({**context, **_coverage(raw["reduction"], dataset), **counts,
            **{key: _time(raw, key) for key in component_times}, "preprocessing_seconds": preprocessing,
            "graph_loading_seconds": _time(raw, "graph_loading_seconds"), "discovery_Q": q_discovery,
            "peak_case_process_RSS_bytes": raw["peak_case_process_RSS_bytes"],
            "timing_scope": raw["timing_scope"], "memory_semantics": raw["memory_semantics"]})
        baselines = raw["global_baselines"]
        expected_baselines = set(suite.config["global_baselines"] + suite.config["public_supplied_baselines"] + ["recursive_cheap"])
        _require(set(baselines) == expected_baselines, "Public baseline methods differ from frozen configuration")
        tables["baseline_seed_rows"].extend(_baseline_rows(baselines, raw, context, dataset))
        _require([item["seed"] for item in raw["downstream"]] == suite.config["downstream"]["seeds"], "Missing/out-of-order paired downstream seed")
        arm_times = {"unreduced": [], "reduced": []}
        arm_best = {"unreduced": [], "reduced": []}
        for pair in raw["downstream"]:
            _require(set(pair["execution_order"]) == {"unreduced", "reduced"}, "Invalid paired downstream execution order")
            row = {**context, "downstream_seed": pair["seed"], "execution_order": pair["execution_order"], "discovery_Q": q_discovery}
            for arm in ("unreduced", "reduced"):
                record = pair[arm]
                _require(record["seed"] == pair["seed"], "Downstream seed differs between paired arms")
                elapsed = sum(_time(record, key) for key in ("solver_seconds", "label_conversion_seconds", "objective_evaluation_seconds"))
                if arm == "reduced":
                    elapsed += _time(record, "lift_and_original_evaluation_seconds")
                    _close(record["modularity_lifted"], _number(record["modularity"], "reduced_Q"), "lifted_Q")
                    _require(len(record["labels"]) == dataset["n"], "Lifted downstream labels have wrong original dimension")
                best = max(q_discovery, _number(record["modularity"], f"{arm}_Q"))
                _close(record["best_of_discovery_and_downstream"], best, f"{arm}_bestQ")
                arm_times[arm].append(elapsed)
                arm_best[arm].append(best)
                row.update({f"{arm}_solver_seconds": _time(record, "solver_seconds"),
                            f"{arm}_complete_solve_seconds": elapsed, f"{arm}_Q": record["modularity"],
                            f"{arm}_best_of_discovery_and_downstream_Q": best})
            row["paired_bestQ_difference_reduced_minus_unreduced"] = row["reduced_best_of_discovery_and_downstream_Q"] - row["unreduced_best_of_discovery_and_downstream_Q"]
            tables["public_downstream_rows"].append(row)
        _require([item["solves"] for item in raw["workloads"]] == suite.config["downstream"]["workload_prefixes"], "Frozen workload prefixes do not reconcile")
        for workload in raw["workloads"]:
            count = workload["solves"]
            _require(1 <= count <= len(raw["downstream"]), "Workload is outside paired downstream bank")
            cold = sum(arm_times["unreduced"][:count])
            discovery_control = _time(raw, "proposal_seconds") + _time(raw, "original_discovery_evaluation_seconds") + cold
            reduced = preprocessing + sum(arm_times["reduced"][:count])
            for key, expected in (("unreduced_seconds", cold), ("discovery_plus_unreduced_seconds", discovery_control), ("full_reduced_seconds", reduced)):
                _close(workload[key], expected, key)
            for key, expected in (("speedup_vs_cold_unreduced", _ratio(cold, reduced)), ("speedup_vs_discovery_control", _ratio(discovery_control, reduced))):
                _require(expected is not None, "Zero reduced workload time")
                _close(workload[key], expected, key)
            tables["public_workload_rows"].append({**context, "solves": count,
                "cold_unreduced_seconds": cold, "discovery_plus_unreduced_seconds": discovery_control,
                "full_reduced_seconds": reduced, "speedup_vs_cold_unreduced": _ratio(cold, reduced),
                "speedup_vs_discovery_control": _ratio(discovery_control, reduced),
                "unreduced_bestQ_over_workload_and_discovery": max(arm_best["unreduced"][:count]),
                "reduced_bestQ_over_workload_and_discovery": max(arm_best["reduced"][:count]),
                "paired_bestQ_difference": max(arm_best["reduced"][:count]) - max(arm_best["unreduced"][:count])})
    completed = suite.load(f"{job.prefix}-completed.json")
    _require(completed.get("status") == "completed", "Public case has no successful completion marker")


def _oracle_row(oracle: dict, context: dict, panel: str, block: list) -> dict:
    status = oracle["status"]
    attempts = oracle.get("attempts", [])
    _require(attempts and attempts[0]["arithmetic"] == "exact", "C-subinstance omitted the initial exact attempt")
    final = attempts[-1]
    result = final["result"]
    _require(result["status"] == status and oracle["certified"] == (status == "exact_match"), "C-subinstance certificate/status mismatch")
    _require(oracle["available"] == (status not in {"unavailable", "unresolved"}), "C-subinstance availability mismatch")
    if status.startswith("numerical") or final["arithmetic"] == "numerical":
        _require(not oracle["certified"] and not result["certified"], "Numerical C-subinstance incorrectly certified")
    if status in {"exact_match", "exact_nonmatch"}:
        optimum, isolation = Fraction(result["optimum"]), Fraction(result["isolation_score"])
        _require(optimum >= isolation and (optimum == isolation) == (status == "exact_match"), "Exact C-subinstance score/tie comparison inconsistent")
    native = result.get("oracle") or {}
    return {**context, "panel": panel, "block": block, "block_size": len(block),
            "status": status, "arithmetic": final["arithmetic"], "available": oracle["available"],
            "certified": oracle["certified"], "active_vertices": len(result["active_vertices"]) if result.get("active_vertices") else None,
            "isolation_score": result.get("isolation_score"), "optimum": result.get("optimum"),
            "exact_optimum_tie_count": native.get("optimum_count"),
            "checker_seconds": _time(oracle, "checker_seconds"), "solver_status": native.get("status"),
            "numeric_upper_bound": native.get("upper_bound"), "message": result.get("message"),
            "tie_policy": oracle["tie_policy"]}


def _block_rows(comparisons: list[dict], context: dict, panel: str, suite: AuditedSuite, tables: dict[str, list]) -> None:
    expected = set(suite.config["supplied_block_methods"]) | set(BLOCK_EXTRA_METHODS)
    if panel == "controlled_supplied":
        expected.add("bocker_almost_clique_weak_side")
    for comparison in comparisons:
        block = comparison["block"]
        methods = comparison["methods"]
        _require(set(methods) == expected, f"Supplied/same-bank method omissions in {context['source']}")
        for method, record in sorted(methods.items()):
            result = record["result"]
            available = result.get("available", "size_limit" not in result.get("verification_status", ""))
            certified = result.get("certified") is True
            _require(not certified or available, "An unavailable block result claims certification")
            row = {**context, "panel": panel, "block": block, "block_size": len(block), "method": method,
                   "verification_status": result.get("verification_status", result.get("status")),
                   "available": available, "certified": certified, "strict": result.get("strict") is True,
                   "checker_seconds": _time(record, "checker_seconds"),
                   "comparison_role": result.get("comparison_role", comparison.get("block_source")),
                   "numeric_margin_diagnostic": _optional_number(result.get("margin")),
                   "exact_margin": result.get("margin_exact"), "reason": result.get("reason")}
            tables["block_criterion_rows"].append(row)
        auto = methods["degree_median"]["result"]
        exact = methods["degree_median_forced_exact"]["result"]
        independent = methods["degree_median_independent_exact"]["result"]
        if exact.get("certified") and independent.get("available", True):
            _require(independent.get("certified") and exact.get("strict") == independent.get("strict"), "Forced core exact acceptance contradicts independent exact reference")
        tables["auto_exact_comparison_rows"].append({**context, "panel": panel, "block": block, "block_size": len(block),
            "auto_status": auto["verification_status"], "auto_certified": auto["certified"], "auto_strict": auto["strict"],
            "forced_exact_status": exact["verification_status"], "forced_exact_certified": exact["certified"],
            "forced_exact_strict": exact["strict"], "independent_exact_certified": independent.get("certified"),
            "independent_exact_status": independent.get("verification_status", independent.get("status")),
            "exact_accepts_auto_rejects": exact["certified"] and not auto["certified"],
            "auto_accepts_exact_rejects": auto["certified"] and not exact["certified"]})
        if "c_subinstance" in comparison:
            oracle = comparison["c_subinstance"]
            tables["c_subinstance_rows"].append(_oracle_row(oracle, context, panel, block))
            for attempt_index, attempt in enumerate(oracle["attempts"]):
                result = attempt["result"]
                _require(result.get("certified") == (result["status"] == "exact_match"), "C-subinstance attempt certification/status mismatch")
                tables["c_subinstance_attempt_rows"].append({**context, "panel": panel, "block": block,
                    "block_size": len(block), "attempt_index": attempt_index, "arithmetic": attempt["arithmetic"],
                    "status": result["status"], "certified": result["certified"],
                    "active_vertices": len(result["active_vertices"]) if result.get("active_vertices") else None,
                    "active_vertex_limit": result.get("metadata", {}).get("active_vertex_limit"),
                    "message": result.get("message"), "solver_status": (result.get("oracle") or {}).get("status")})


def _selected_native(native: dict, context: dict, n: int, tables: dict[str, list], *, new_groups=None) -> None:
    _require(native.get("full_kapoce_solver") is not True, "Selected preprocessing labeled as full KaPoCE solver")
    records = native.get("records", [])
    if not records:
        tables["selected_native_rows"].append({**context, "routine": "weighted_recursive", "status": native.get("status", "unavailable"), "reason": native.get("reason", native.get("verification_status")), "full_solver": False})
        return
    _require(len(records) == 1 and records[0]["routine"] == "weighted_recursive", "Unexpected selected-native routine grid")
    for record in records:
        status = record["status"]
        result = record.get("result") or {}
        groups, removed = expanded_native_groups(n, result) if status == "completed" else ([], None)
        row = {**context, "routine": record["routine"], "status": status,
            "full_solver": False, "reason": record.get("stderr", native.get("reason")),
            "original_vertices": n, "expanded_remaining_groups": len(groups) if status == "completed" else None,
            "structural_identifications": removed, "expanded_groups": groups,
            "residual_vertices": result.get("remaining_vertices"), "solved_groups": result.get("solved_groups"),
            "cliques_stop": result.get("cliques_stop"), "forbidden_pairs": result.get("forbidden_pairs"),
            "completed_native_kernel_seconds": result.get("elapsed_ms", 0) / 1000 if status == "completed" else None,
            "observed_child_wall_seconds": record.get("elapsed_wall_seconds"),
            "completed_runner_wall_seconds": native.get("runner_wall_seconds") if status == "completed" else None,
            "censored_timeout_seconds": record.get("timeout_seconds") if status == "timeout" else None,
            "native_process_peak_RSS_bytes": result.get("native_process_peak_rss_bytes"),
            "native_memory_semantics": native.get("memory_semantics"),
            "incumbent_role": native.get("incumbent_role"), "comparison_role": native.get("comparison_role")}
        if status == "completed" and new_groups is not None:
            joined = identifications(n, [*new_groups, *groups])
            row["new_structural_identifications_beyond_selected_preprocessing"] = joined - removed
            row["selected_structural_identifications_beyond_new"] = joined - identifications(n, new_groups)
            row["structural_comparison_scope"] = "equivalence ranks only; native cannot-link residual is not composed with the new quotient"
        tables["selected_native_rows"].append(row)


def _full_original_feasible_Q(raw: dict) -> dict[str, Fraction]:
    """Only source-backed exact evaluations under the full original objective.

    C-subinstance scores/optima are local objectives and have no full-original
    lifted labels in this schema, so they cannot supply this integrity check.
    No floating optimizer bound is interpreted as an exact feasible value.
    """
    result = {}
    primary = raw.get("production_independent_bank", {})
    if primary.get("status") == "completed":
        original, quotient = primary.get("modularity_discovery_exact"), primary.get("modularity_discovery_quotient_exact")
        _require(original is not None and Fraction(original) == Fraction(quotient), "Unvalidated exact discovery feasible Q")
        result["discovery"] = Fraction(original)
    numerical = raw.get("numerical_modularity_milp") or {}
    for arm, record in numerical.get("paired_arms", {}).items():
        exact, lifted = record.get("feasible_Q_exact"), record.get("lifted_original_Q_exact")
        if exact is not None or lifted is not None:
            _require(exact is not None and lifted is not None and Fraction(exact) == Fraction(lifted), "Numerical feasible exact Q/lift mismatch")
            result[f"numerical_milp_{arm}"] = Fraction(lifted)
    return result


def _full_native(native: dict, context: dict, requested: bool, tables: dict[str, list], *, known_failure=None,
                 exact_feasible_Q: dict[str, Fraction] | None = None) -> None:
    pair = native.get("paired_arms")
    row = {**context, "requested": requested, "pair_completed": False, "native_only_completed_pair": False,
           "analytic_one_node_pair": False, "completion_time_speedup": None, "matched_pipeline_speedup": None}
    if not pair:
        _require(not requested, "A predeclared full-native pair is missing")
        row.update(pair_status=native.get("status", "unavailable"), reason=native.get("reason", native.get("verification_status")))
        tables["full_native_pair_rows"].append(row)
        return
    _require(requested and set(pair) == {"unreduced", "reduced"}, "Full-native paired-arm identity mismatch")
    incumbent = Fraction(native["same_feasible_incumbent_Q_exact"])
    for arm, record in pair.items():
        status = record["status"]
        incident = status == "failed" and known_failure is not None and known_failure(record)
        _require(status not in BAD_STATUSES or incident, "An unreviewed native failure cannot enter a recovered report")
        _require(Fraction(record["incumbent_Q_original_exact"]) == incumbent, "Different retained full-solver incumbents")
        completed = status in FULL_COMPLETED and record.get("optimality_proved") is True
        if status in FULL_COMPLETED:
            _require(completed and Fraction(record["solution"]["Q"]) == Fraction(record["lifted_Q_original_exact"]), "Unvalidated native optimal result")
            optimal_Q = Fraction(record["lifted_Q_original_exact"])
            _require(optimal_Q >= incumbent, "Native claimed optimum is below its exact feasible supplied incumbent")
            for source, feasible_Q in (exact_feasible_Q or {}).items():
                _require(optimal_Q >= feasible_Q, f"Native claimed optimum is below exact full-original feasible Q from {source}")
        if status == "optimal":
            _require(record.get("full_solver_entry_called") is True and record.get("full_kapoce_solver") is True, "Native optimality without full solver entry")
        if status == "optimal_trivial":
            _require(record.get("full_solver_entry_called") is False, "Analytic one-node result mislabeled native solve")
        bounds = {} if incident else record.get("bounds", {})
        lower = Fraction(bounds["Q_lower_bound"]) if "Q_lower_bound" in bounds else None
        upper = Fraction(bounds["Q_upper_bound"]) if "Q_upper_bound" in bounds else None
        if lower is not None:
            _require(lower >= incumbent and (upper is None or lower <= upper), "Invalid exact native modularity bound")
        row[f"{arm}_status"] = status
        row[f"{arm}_completed"] = completed
        row[f"{arm}_completed_runner_seconds"] = _time(record, "runner_wall_seconds") if completed else None
        row[f"{arm}_completed_pipeline_seconds"] = _number(native["matched_pipeline_seconds"][arm], "matched_pipeline_seconds", nonnegative=True) if completed else None
        if incident:
            _require(record.get("incumbent", {}).get("verified_independently") is True and Fraction(record["incumbent"]["Q"]) == incumbent, "Known failed arm lacks independently verified feasible incumbent")
        row[f"{arm}_Q_exact"] = record.get("lifted_Q_original_exact") if completed else record.get("incumbent", {}).get("Q", str(incumbent))
        row[f"{arm}_Q_lower_bound_exact"] = None if incident else str(lower) if lower is not None else record.get("solution", {}).get("Q")
        row[f"{arm}_Q_upper_bound_exact"] = None if incident else str(upper) if upper is not None else record.get("solution", {}).get("Q")
        armrow = {**context, "arm": arm, "status": status, "completed": completed,
            "native_full_entry_called": record.get("full_solver_entry_called", False),
            "analytic_one_node": status == "optimal_trivial", "incumbent_Q_exact": str(incumbent),
            "exact_feasible_integrity_check_count": 1 + len(exact_feasible_Q or {}) if completed else 0,
            "exact_feasible_integrity_sources": ["supplied_incumbent", *sorted(exact_feasible_Q or {})] if completed else [],
            "validated_Q_exact": None if incident else record.get("lifted_Q_original_exact"),
            "known_native_failure": incident, "native_failure_incident": "davis-gamma2-star-bound-assertion-518" if incident else None,
            "failed_observed_runner_seconds": record.get("runner_wall_seconds") if incident else None,
            "failed_observed_native_seconds": record.get("native_process_wall_seconds") if incident else None,
            "Q_lower_bound_exact": row[f"{arm}_Q_lower_bound_exact"], "Q_upper_bound_exact": row[f"{arm}_Q_upper_bound_exact"],
            "completed_runner_seconds": row[f"{arm}_completed_runner_seconds"],
            "completed_native_process_seconds": record.get("native_process_wall_seconds") if status == "optimal" else None,
            "completed_pipeline_seconds": row[f"{arm}_completed_pipeline_seconds"],
            "censored_observed_runner_seconds": record.get("runner_wall_seconds") if status == "timeout" else None,
            "censored_observed_native_seconds": record.get("native_process_wall_seconds") if status == "timeout" else None,
            "timeout_limit_seconds": record.get("timeout_seconds") if status == "timeout" else None,
            "timeout_stage": record.get("timeout_stage"), "reason": record.get("reason"),
            "native_process_peak_RSS_bytes": record.get("native_result", {}).get("peak_native_rss_bytes"),
            "bound_scope": "suppressed after reviewed failed native search; feasible incumbent only" if incident else record.get("initial_lower_bound_source"), "pipeline_scope": native.get("pipeline_scope")}
        tables["full_native_arm_rows"].append(armrow)
    completed = all(row[f"{arm}_completed"] for arm in ("unreduced", "reduced"))
    row.update(pair_completed=completed,
               native_only_completed_pair=completed and all(pair[arm]["status"] == "optimal" for arm in pair),
               analytic_one_node_pair=completed and any(pair[arm]["status"] == "optimal_trivial" for arm in pair),
               same_feasible_incumbent_Q_exact=str(incumbent), execution_order=native["execution_order"])
    row["known_native_failure"] = any(record["status"] == "failed" for record in pair.values())
    if completed:
        _require(Fraction(row["unreduced_Q_exact"]) == Fraction(row["reduced_Q_exact"]), "Completed original/quotient exact optimal Q disagree")
        row["completion_time_speedup"] = _ratio(row["unreduced_completed_runner_seconds"], row["reduced_completed_runner_seconds"])
        row["matched_pipeline_speedup"] = _ratio(row["unreduced_completed_pipeline_seconds"], row["reduced_completed_pipeline_seconds"])
        row["pair_status"] = "completed_analytic_one_node" if row["analytic_one_node_pair"] else "completed_native_only"
    else:
        row["pair_status"] = " | ".join(f"{arm}:{pair[arm]['status']}" for arm in ("unreduced", "reduced"))
    tables["full_native_pair_rows"].append(row)


def _numerical(numerical: dict | None, context: dict, tables: dict[str, list]) -> None:
    if numerical is None:
        return
    _require(set(numerical["paired_arms"]) == {"unreduced", "reduced"}, "Missing numerical development MILP arm")
    for arm, record in numerical["paired_arms"].items():
        _require(record.get("certified") is not True and record.get("global_optimum_certified") is not True, "Numerical optimization incorrectly certified")
        exact = record.get("feasible_Q_exact")
        lifted = record.get("lifted_original_Q_exact")
        if exact is not None:
            _require(Fraction(exact) == Fraction(lifted), "Numerical feasible exact Q/lift mismatch")
        tables["numerical_milp_rows"].append({**context, "arm": arm, "status": record.get("status"),
            "available": record.get("available", False), "global_optimum_certified": False,
            "feasible_Q_exact": exact, "lifted_original_Q_exact": lifted,
            "numeric_upper_bound": record.get("upper_bound"), "numeric_mip_gap": record.get("mip_gap"),
            "solver_seconds_observed": record.get("solver_seconds"), "runner_wall_seconds_observed": record.get("runner_wall_seconds"),
            "message": record.get("message", record.get("reason")), "bound_arithmetic": record.get("upper_bound_arithmetic")})


def _controls(suite: AuditedSuite, job: Job, tables: dict[str, list]) -> None:
    started = suite.load(f"{job.prefix}-started.json")
    suite.provenance(started, job.prefix)
    _require(started.get("stratum") == job.stratum and started.get("case_id") == job.identifier, "Controlled/development started identity mismatch")
    input_record = suite.load(f"{job.prefix}-input.json.gz")
    suite.provenance(input_record["provenance"], job.prefix)
    _require(input_record["provenance"] == started, "Case/input provenance differs")
    spec = started["specification"]
    if job.stratum == "controlled":
        expected_spec = next(item for item in suite.config["controlled_cases"] if item["case_id"] == job.identifier)
        _require(spec == expected_spec and input_record["dataset"]["family"] == spec["family"], "Controlled frozen specification mismatch")
        _require(input_record["dataset"]["generation_parameters"] == spec["parameters"], "Controlled generator parameters mismatch")
    bank = input_record["candidate_bank"]
    skipped = bank is None
    _require(skipped == (job.stratum == "controlled" and spec.get("candidate_bank_evaluation") is False), "Undeclared independent bank exclusion")
    if not skipped:
        _require(bank["seed"] == job.seed and input_record["bank_sha256"] == _bank_identity(bank["blocks"]), "Controlled/development independent bank mismatch")
    for index, gamma in enumerate(job.gamma):
        filename = f"{job.prefix}-gamma{index}.json.gz"
        raw = suite.load(filename)
        _no_failures(raw, filename, allowed_failure=suite.known_native_failure if filename == "development-davis-gamma2.json.gz" else None)
        suite.provenance(raw["provenance"], filename)
        _require(raw["provenance"] == started and raw.get("status") == "completed" and Fraction(raw["gamma_exact"]) == Fraction(gamma), "Controlled gamma/status/provenance mismatch")
        _require(raw["dataset"] == input_record["dataset"] and raw["graph_fingerprint"] == input_record["graph_fingerprint"] and raw["bank_sha256"] == input_record["bank_sha256"], "Controlled gamma graph/bank mismatch")
        dataset = raw["dataset"]
        context = {"stratum": job.stratum, "case_id": job.identifier, "family": dataset.get("family", job.identifier),
                   "role": spec["role"], "gamma": str(Fraction(gamma)), "proposal_seed": job.seed,
                   "source": filename, "graph_fingerprint": raw["graph_fingerprint"], "bank_sha256": raw["bank_sha256"]}
        primary = raw["production_independent_bank"]
        row = {**context, "bank_status": input_record["bank_status"], "status": primary["status"],
               "graph_loading_seconds": input_record["graph_loading_seconds"],
               "graph_preparation_seconds": input_record["graph_preparation_seconds"],
               **input_record["baseline_preparation"], "gamma_compute_seconds": raw["gamma_compute_seconds"],
               "peak_case_process_RSS_bytes": raw["peak_case_process_RSS_bytes"], "performance_scope": raw["performance_scope"]}
        if not skipped:
            _require(primary["status"] == "completed", "Independent bank production failed")
            _require(Fraction(primary["modularity_discovery_exact"]) == Fraction(primary["modularity_discovery_quotient_exact"]), "Exact discovery incumbent not preserved")
            row.update(_coverage(primary["reduction"], dataset))
            row.update(_certificate_counts(primary["candidate_certificates"], bank["blocks"], primary["certification_status_counts"]))
            row.update(_production_size_mechanism(primary["candidate_certificates"], dataset["n"], primary["reduction"]))
            row.update(checker_seconds=_time(primary, "checker_seconds"), quotient_seconds=_time(primary, "quotient_seconds"),
                       proposal_seconds=bank["proposal_seconds"], refinement_seconds=bank["refinement_seconds"], discovery_Q_exact=primary["modularity_discovery_exact"])
            _require([item["block"] for item in raw["same_bank_criterion_comparison"]] == bank["blocks"], "Same-bank comparison is incomplete/reordered")
        else:
            _require(primary.get("certified") is not True and not raw["same_bank_criterion_comparison"], "Computation-only case substituted candidate results")
        tables["control_production_rows"].append(row)
        expected_baselines = set(suite.config["global_baselines"]) | ({"recursive_cheap"} if not skipped else set())
        _require(set(raw["global_baselines"]) == expected_baselines, "Controlled/development global baseline omission")
        tables["baseline_seed_rows"].extend(_baseline_rows(raw["global_baselines"], primary, context, dataset))
        _block_rows(raw["same_bank_criterion_comparison"], context, "independent_bank", suite, tables)
        supplied = raw["controlled_supplied_block_comparison"]
        _require([item["block"] for item in supplied] == input_record["supplied_blocks"], "Supplied mathematical comparison omitted reference blocks")
        _block_rows(supplied, context, "controlled_supplied", suite, tables)
        selected = raw["native_weighted_preprocessing"]
        if "native_binary_sha256" in selected:
            _require(selected["native_binary_sha256"] == suite.freeze["runtime_source_sha256"]["research/baselines/build/kapoce_selected"], "Selected-native binary differs from freeze")
        _selected_native(selected, context, dataset["n"], tables,
                         new_groups=primary["reduction"]["merge_groups"] if not skipped else None)
        full = raw["native_full_solver"]
        if "paired_arms" in full:
            _close(full["shared_graph_preparation_seconds"], _time(input_record, "graph_preparation_seconds"), "full_native_shared_preparation")
            _close(full["shared_discovery_seconds"], _time(bank, "proposal_seconds"), "full_native_shared_discovery")
            additional = sum(_time(record, key) for record, key in ((bank, "refinement_seconds"), (primary, "checker_seconds"), (primary, "quotient_seconds"), (full, "quotient_incumbent_alignment_seconds")))
            _close(full["reduced_additional_preprocessing_seconds"], additional, "full_native_reduced_preprocessing")
            for arm, native_record in full["paired_arms"].items():
                if "binary_sha256" in native_record:
                    _require(native_record["binary_sha256"] == suite.freeze["runtime_source_sha256"]["research/full_kapoce/build/kapoce_full"], "Full-native binary differs from freeze")
                expected_pipeline = (_time(input_record, "graph_preparation_seconds") + _time(bank, "proposal_seconds")
                    + _time(native_record, "runner_wall_seconds") + _time(full, "original_incumbent_evaluation_seconds")
                    + (additional if arm == "reduced" else 0))
                _close(full["matched_pipeline_seconds"][arm], expected_pipeline, "full_native_matched_pipeline")
        _full_native(full, context, spec["native_preprocessing"], tables,
                     known_failure=suite.known_native_failure if filename == "development-davis-gamma2.json.gz" else None,
                     exact_feasible_Q=_full_original_feasible_Q(raw))
        _numerical(raw["numerical_modularity_milp"], context, tables)
    completed = suite.load(f"{job.prefix}-completed.json")
    _require(completed.get("status") == "completed" and completed["provenance"] == started, "Controlled/development completion mismatch")


def _scaling(suite: AuditedSuite, job: Job, tables: dict[str, list]) -> None:
    filename = f"{job.name}.json.gz"
    raw = suite.load(filename)
    _no_failures(raw, filename)
    suite.provenance(raw["provenance"], filename)
    for key, expected in (("status", "completed"), ("case_id", job.identifier), ("method", job.method),
                           ("measurement", job.measurement), ("replicate", job.replicate), ("gamma", "1")):
        _require(raw.get(key) == expected, f"Scaling {key} mismatch")
    spec = next(case for case in suite.config["controlled_cases"] if case["case_id"] == job.identifier)
    _require(raw["dataset"]["family"] == "profile_scaling" and raw["dataset"]["generation_parameters"] == spec["parameters"], "Scaling family/parameters mismatch")
    result = raw["checker_result"]
    metadata = result.get("metadata", {})
    if job.method == "dense_exterior_diagnostic":
        _require(result.get("certified") is False, "Dense assembly diagnostic incorrectly certified")
    if job.measurement == "timing":
        _require(raw["checker_traced_peak_bytes"] is None and raw["checker_traced_current_bytes"] is None, "Performance repetition was memory-profiled")
    component_fields = dict.fromkeys(SCALING_COMPONENTS)
    if job.method == "degree_median":
        for source_key in ("exterior_assembly_seconds", "dense_eigensolve_seconds", "exact_verification_seconds"):
            component_fields[f"production_{source_key}"] = _optional_number(metadata.get(source_key))
    elif job.method == "degree_full_pair":
        for source_key in ("assembly_seconds", "verification_seconds"):
            component_fields[f"reference_{source_key}"] = _optional_number(metadata.get(source_key))
    else:
        component_fields["dense_diagnostic_assembly_seconds"] = _optional_number(result.get("assembly_seconds"))
        component_fields["dense_diagnostic_dense_exterior_assembly_seconds"] = _optional_number(metadata.get("dense_exterior_assembly_seconds"))
        if all(component_fields[key] is not None for key in ("dense_diagnostic_assembly_seconds", "dense_diagnostic_dense_exterior_assembly_seconds")):
            _close(component_fields["dense_diagnostic_assembly_seconds"], component_fields["dense_diagnostic_dense_exterior_assembly_seconds"], "dense_assembly_alias")
    _require(all(value is None or value >= 0 for value in component_fields.values()), "Negative scaling component time")
    tables["scaling_raw_rows"].append({"case_id": job.identifier, "family": "profile_scaling", "method": job.method,
        "measurement": job.measurement, "replicate": job.replicate, "source": filename,
        "original_vertices": raw["dataset"]["n"], "original_edges": raw["dataset"]["m"], **spec["parameters"],
        "checker_seconds": _time(raw, "checker_seconds"), "preparation_seconds": _time(raw, "preparation_seconds"),
        "loading_seconds": _time(raw, "loading_seconds"), "certified": result.get("certified"),
        **component_fields, "component_timing_scope": SCALING_COMPONENT_SCOPES[job.method],
        "exterior_incidences": metadata.get("exterior_incidences"),
        "pair_union_coordinate_visits": metadata.get("pair_union_coordinate_visits"),
        "touched_exterior_columns": metadata.get("touched_exterior_columns"),
        "nonzero_center_columns": metadata.get("nonzero_center_columns"),
        "dense_exterior_shape": metadata.get("dense_exterior_shape"),
        "dense_exterior_payload_bytes_shape_derived": metadata.get("dense_exterior_payload_bytes"),
        "strict": result.get("strict"), "verification_status": result.get("verification_status", result.get("status")),
        "process_peak_RSS_bytes": raw["process_peak_RSS_bytes"],
        "process_peak_RSS_before_checker_bytes": raw["process_peak_RSS_before_checker_bytes"],
        "checker_traced_peak_bytes": raw["checker_traced_peak_bytes"],
        "timing_semantics": raw["timing_semantics"], "memory_semantics": raw["memory_semantics"]})


def _aggregate(rows: list[dict], keys: tuple[str, ...], metrics: tuple[str, ...]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(key) for key in keys)].append(row)
    results = []
    for identity, values in sorted(groups.items(), key=lambda item: tuple(str(x) for x in item[0])):
        result = dict(zip(keys, identity))
        result["observations"] = len(values)
        result["source_rows"] = [row["source"] for row in values]
        for metric in metrics:
            result.update(_flatten_stats((row.get(metric) for row in values), metric))
        results.append(result)
    return results


def _summary(suite: AuditedSuite, tables: dict[str, list]) -> dict:
    public_metrics = ("removed_vertices", "removed_fraction_all", "removed_fraction_positive_degree",
                      "removed_fraction_lcc_under_original_objective", "checker_seconds", "preprocessing_seconds",
                      "accepted_strict_blocks", "accepted_weak_blocks", "cap_exclusions", "peak_case_process_RSS_bytes",
                      "accepted_pair_blocks", "accepted_collective_blocks", "pair_only_removed_vertices",
                      "collective_only_removed_vertices", "collective_additions_beyond_accepted_production_pairs")
    tables["public_aggregate_rows"] = _aggregate(tables["public_seed_rows"], ("dataset", "gamma"), public_metrics)
    for row in tables["public_aggregate_rows"]:
        _require(row["observations"] == len(suite.config["proposal"]["seeds"]), "Public discovery-seed denominator incomplete")
    tables["public_baseline_aggregate_rows"] = _aggregate(
        [row for row in tables["baseline_seed_rows"] if row["stratum"] == "public"], ("dataset", "gamma", "method"),
        ("removed_vertices", "removed_fraction_all", "removed_fraction_positive_degree", "removed_fraction_lcc_under_original_objective",
         "new_structural_identifications_beyond_baseline", "baseline_structural_identifications_beyond_new",
         "checker_seconds", "checker_plus_reporting_quotient_seconds"))
    tables["public_workload_aggregate_rows"] = _aggregate(tables["public_workload_rows"], ("dataset", "gamma", "solves"),
        ("cold_unreduced_seconds", "discovery_plus_unreduced_seconds", "full_reduced_seconds", "speedup_vs_cold_unreduced",
         "speedup_vs_discovery_control", "unreduced_bestQ_over_workload_and_discovery", "reduced_bestQ_over_workload_and_discovery", "paired_bestQ_difference"))
    scaling = defaultdict(list)
    for row in tables["scaling_raw_rows"]:
        scaling[(row["case_id"], row["method"])].append(row)
    for (case, method), rows in sorted(scaling.items()):
        timing = sorted((row for row in rows if row["measurement"] == "timing"), key=lambda row: row["replicate"])
        memory = sorted((row for row in rows if row["measurement"] == "memory"), key=lambda row: row["replicate"])
        _require([row["replicate"] for row in timing] == list(range(suite.config["scaling"]["replicate_count"])), "Missing scaling timing repetition")
        _require([row["replicate"] for row in memory] == list(range(suite.config["scaling"]["memory_replicate_count"])), "Missing separate scaling memory repetition")
        _require(len(memory) == 1, "This analysis schema requires the predeclared single memory repetition")
        tables["scaling_aggregate_rows"].append({"case_id": case, "method": method,
            "original_vertices": timing[0]["original_vertices"], "original_edges": timing[0]["original_edges"],
            "k": timing[0]["k"], "outside_vertices": timing[0]["outside_vertices"],
            **_flatten_stats((row["checker_seconds"] for row in timing), "unprofiled_checker_seconds"),
            **_flatten_stats((row["preparation_seconds"] + row["checker_seconds"] for row in timing), "unprofiled_prepare_plus_checker_seconds"),
            **{key: value for component in SCALING_COMPONENTS for key, value in
               _flatten_stats((row[component] for row in timing), f"unprofiled_{component}").items()},
            "component_timing_scope": SCALING_COMPONENT_SCOPES[method],
            "memory_source": memory[0]["source"], "process_peak_RSS_bytes_memory_rep": memory[0]["process_peak_RSS_bytes"],
            "process_peak_RSS_before_checker_bytes_memory_rep": memory[0]["process_peak_RSS_before_checker_bytes"],
            "checker_traced_peak_bytes_memory_rep": memory[0]["checker_traced_peak_bytes"],
            "certified_timing_repetitions": sum(row["certified"] is True for row in timing),
            "algorithm_role": "uncertified dense assembly diagnostic" if method == "dense_exterior_diagnostic" else "capped implemented checker",
            "timing_sources": [row["source"] for row in timing], "memory_semantics": memory[0]["memory_semantics"]})
    native_pairs = [row for row in tables["full_native_pair_rows"] if row["requested"]]
    native_only = [row for row in native_pairs if row["native_only_completed_pair"]]
    analytic = [row for row in native_pairs if row["analytic_one_node_pair"]]
    known_failures = sum(row.get("known_native_failure", False) for row in tables["full_native_arm_rows"])
    if suite.collection:
        _require(known_failures == suite.collection["incident"]["selected_failed_native_arms"], "Reviewed selected native failure denominator does not reconcile")
    native_denominators = []
    for stratum in ("controlled", "development"):
        rows = [row for row in native_pairs if row["stratum"] == stratum]
        arm_rows = [row for row in tables["full_native_arm_rows"] if row["stratum"] == stratum]
        native_denominators.append({"stratum": stratum, "predeclared_pair_denominator": len(rows),
            "completed_native_only_pairs": sum(row["native_only_completed_pair"] for row in rows),
            "completed_analytic_one_node_pairs": sum(row["analytic_one_node_pair"] for row in rows),
            "unresolved_or_excluded_pairs": sum(not row["pair_completed"] for row in rows),
            "pair_status_counts": dict(sorted(Counter(row["pair_status"] for row in rows).items())),
            "arm_status_counts": {arm: dict(sorted(Counter(row["status"] for row in arm_rows if row["arm"] == arm).items())) for arm in ("unreduced", "reduced")},
            "native_only_completed_pipeline_speedup": _stats(row["matched_pipeline_speedup"] for row in rows if row["native_only_completed_pair"]),
            "analytic_one_node_pipeline_speedup_separate": _stats(row["matched_pipeline_speedup"] for row in rows if row["analytic_one_node_pair"])})
    block_groups = defaultdict(list)
    for row in tables["block_criterion_rows"]:
        block_groups[(row["stratum"], row["role"], row["family"], row["gamma"], row["panel"], row["method"])].append(row)
    block_counts = []
    for identity, rows in sorted(block_groups.items()):
        block_counts.append({**dict(zip(("stratum", "role", "family", "gamma", "panel", "method"), identity)),
            "supplied_block_denominator": len(rows), "available": sum(row["available"] for row in rows),
            "certified": sum(row["certified"] for row in rows),
            "certified_strict": sum(row["certified"] and row["strict"] for row in rows),
            "certified_weak": sum(row["certified"] and not row["strict"] for row in rows),
            "status_counts": dict(sorted(Counter(row["verification_status"] for row in rows).items()))})
    tables["block_aggregate_rows"] = block_counts
    auto_groups = defaultdict(list)
    for row in tables["auto_exact_comparison_rows"]:
        auto_groups[(row["stratum"], row["role"], row["family"], row["gamma"], row["panel"])].append(row)
    tables["auto_exact_aggregate_rows"] = [
        {**dict(zip(("stratum", "role", "family", "gamma", "panel"), identity)),
         "block_denominator": len(rows), "auto_certified": sum(row["auto_certified"] for row in rows),
         "auto_certified_strict": sum(row["auto_certified"] and row["auto_strict"] for row in rows),
         "forced_exact_certified": sum(row["forced_exact_certified"] for row in rows),
         "forced_exact_certified_strict": sum(row["forced_exact_certified"] and row["forced_exact_strict"] for row in rows),
         "exact_accepts_auto_rejects": sum(row["exact_accepts_auto_rejects"] for row in rows),
         "auto_accepts_exact_rejects": sum(row["auto_accepts_exact_rejects"] for row in rows)}
        for identity, rows in sorted(auto_groups.items())]
    oracle_groups = defaultdict(list)
    for row in tables["c_subinstance_rows"]:
        oracle_groups[(row["stratum"], row["role"], row["family"], row["gamma"], row["panel"], row["arithmetic"])].append(row)
    tables["c_subinstance_aggregate_rows"] = [
        {**dict(zip(("stratum", "role", "family", "gamma", "panel", "arithmetic"), identity)),
         "block_denominator": len(rows), "available": sum(row["available"] for row in rows),
         "certified_exact_match": sum(row["certified"] for row in rows),
         "status_counts": dict(sorted(Counter(row["status"] for row in rows).items()))}
        for identity, rows in sorted(oracle_groups.items())]
    return {"schema_version": SCHEMA_VERSION, "status": suite.collection["status"] if suite.collection else "complete_validated_suite",
        "run_kind": "derived_recovered_collection" if suite.collection else "original_frozen_run",
        "run_id": suite.run_dir.name, "expected_processes": len(suite.jobs), "completed_processes": len(suite.completion["outcomes"]),
        "logical_completion_is_native_solver_success": False,
        "recovered_collection": None if not suite.collection else {
            "original_v1_status": "halted_for_repair", "logical_jobs": suite.collection["logical_job_count"],
            "actual_source_orchestration_attempts": suite.collection["source_attempt_count"],
            "original_failed_orchestration_attempts": suite.collection["original_failed_attempts_retained"],
            "selected_native_failed_arms": known_failures, "all_source_native_failed_arms": suite.collection["incident"]["all_source_failed_native_arms"],
            "selection_policy": suite.collection["selection_policy"], "source_runs": suite.collection["source_runs"],
            "recovery_freeze_sha256": suite.collection["recovery_freeze_sha256"],
            "recovery_review_sha256": suite.collection["recovery_freeze"]["review_sha256"],
            "collection_analysis_source_sha256": suite.collection["recovery_freeze"]["collection_analysis_source_sha256"],
            "selection_plan_sha256": suite.collection["selection_plan_sha256"], "incident": suite.collection["incident"]},
        "config_sha256": suite.manifest["config_sha256"], "freeze_sha256": suite.manifest["freeze_sha256"],
        "runtime_source_sha256": suite.freeze["runtime_source_sha256"], "source_commit": suite.freeze.get("source_commit"),
        "source_contracts": SOURCE_CONTRACTS, "interpretation_limits": INTERPRETATION_LIMITS,
        "post_freeze_descriptive_size_mechanism": {
            "endpoint_role": "post-freeze descriptive mechanism summaries; not new predeclared primary endpoints",
            "pair_definition": "accepted production certificate block of size two",
            "collective_definition": "accepted production certificate block of size greater than two",
            "rank_definition": "original-vertex count minus equivalence classes of the selected accepted block union",
            "collective_additions_definition": "all accepted production identifications minus pair-only identifications",
            "overlap_policy": "pair-only and collective-only ranks can overlap and are not added",
            "baseline_scope": "no implemented/executed exact Bocker Rule5 comparison",
            "coverage_policy": "immutable raw all-certificate production coverage unchanged"},
        "raw_artifact_sha256": dict(sorted(suite.raw_hashes.items())),
        "table_rows": {name: len(rows) for name, rows in sorted(tables.items())},
        "public": {"seed_gamma_rows": len(tables["public_seed_rows"]), "discovery_seeds": suite.config["proposal"]["seeds"],
            "coverage_by_dataset_gamma": tables["public_aggregate_rows"], "structural_baseline_comparisons": tables["public_baseline_aggregate_rows"],
            "paired_workloads": tables["public_workload_aggregate_rows"]},
        "controls": {"production_status_counts": dict(sorted(Counter(row["status"] for row in tables["control_production_rows"]).items())),
            "block_comparisons": block_counts,
            "auto_vs_forced_exact": {"block_denominator": len(tables["auto_exact_comparison_rows"]),
                 "exact_accepts_auto_rejects": sum(row["exact_accepts_auto_rejects"] for row in tables["auto_exact_comparison_rows"]),
                 "auto_accepts_exact_rejects": sum(row["auto_accepts_exact_rejects"] for row in tables["auto_exact_comparison_rows"])},
            "c_subinstance_status_counts_by_arithmetic": {arithmetic: dict(sorted(Counter(row["status"] for row in tables["c_subinstance_rows"] if row["arithmetic"] == arithmetic).items())) for arithmetic in ("exact", "numerical")},
            "c_subinstance_attempt_status_counts_by_arithmetic": {arithmetic: dict(sorted(Counter(row["status"] for row in tables["c_subinstance_attempt_rows"] if row["arithmetic"] == arithmetic).items())) for arithmetic in ("exact", "numerical")},
            "numerical_milp_status_counts": dict(sorted(Counter(str(row["status"]) for row in tables["numerical_milp_rows"]).items()))},
        "selected_native": {"status_counts": dict(sorted(Counter(row["status"] for row in tables["selected_native_rows"]).items())),
            "scope": "recursive weighted preprocessing only; expanded groups, not residual disappearance"},
        "full_native": {"predeclared_pair_denominator": len(native_pairs), "not_predeclared_rows": len(tables["full_native_pair_rows"]) - len(native_pairs),
            "known_selected_native_failed_arms": known_failures,
            "completed_native_only_pairs": len(native_only), "completed_analytic_one_node_pairs": len(analytic),
            "by_stratum": native_denominators,
            "native_only_completed_runner_speedup": _stats(row["completion_time_speedup"] for row in native_only),
            "native_only_completed_pipeline_speedup": _stats(row["matched_pipeline_speedup"] for row in native_only),
            "analytic_one_node_pipeline_speedup_separate": _stats(row["matched_pipeline_speedup"] for row in analytic)},
        "scaling": tables["scaling_aggregate_rows"]}


def _format(value: Any, digits: int = 4) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.{digits}g}" if isinstance(value, float) else str(value)


def _markdown(summary: dict, tables: dict[str, list]) -> str:
    lead = (f"Derived recovered collection covers {summary['completed_processes']} logical jobs from {summary['recovered_collection']['actual_source_orchestration_attempts']} actual source orchestration attempts. Original v1 remains halted. Whole recovery Davis is the fixed primary; its reviewed failed native arms remain failed and are excluded from optimality, bound/gap and completed solve-time inferences."
            if summary.get("recovered_collection") else
            f"All {summary['completed_processes']} / {summary['expected_processes']} predeclared processes completed and their immutable artifacts passed the source/configuration identity checks.")
    lines = [f"# Frozen suite {summary['run_id']}", "",
        lead, "",
        f"Configuration SHA-256: `{summary['config_sha256']}`. Freeze SHA-256: `{summary['freeze_sha256']}`.", "",
        "The following tables are descriptive aggregations. Parent research interpretation and manuscript claims require separate review.", "",
        "## Public production coverage", "",
        "Medians and [minimum, maximum] span the three certificate-independent discovery seeds. Positive-degree coverage uses n minus the raw isolate count. LCC coverage retains the original full-graph objective and is not a re-solved component objective.", "",
        "| Dataset | γ | Removed vertices | All vertices | Positive degree | Original LCC | Checker seconds | Preprocessing seconds |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    def triplet(row, metric, percent=False):
        factor = 100 if percent else 1
        suffix = "%" if percent else ""
        vals = [row.get(f"{metric}_{key}") for key in ("median", "min", "max")]
        if any(x is None for x in vals):
            return "unavailable"
        return f"{_format(vals[0]*factor)} [{_format(vals[1]*factor)}, {_format(vals[2]*factor)}]{suffix}"
    for row in tables["public_aggregate_rows"]:
        lines.append(f"| {row['dataset']} | {row['gamma']} | {triplet(row,'removed_vertices')} | {triplet(row,'removed_fraction_all',True)} | {triplet(row,'removed_fraction_positive_degree',True)} | {triplet(row,'removed_fraction_lcc_under_original_objective',True)} | {triplet(row,'checker_seconds')} | {triplet(row,'preprocessing_seconds')} |")
    lines.extend(["", "## Post-freeze descriptive acceptance-size mechanism", "",
        "These are supplemental descriptive mechanism summaries added after configuration freeze, not new predeclared primary endpoints. Pair-only means accepted production size-two certificates, not an implemented exact Böcker Rule5 baseline. Collective means accepted production blocks of size greater than two. Pair-only and collective-only ranks may overlap; collective additions equal the unchanged all-certificate rank minus pair-only rank within the accepted production family.", "",
        "| Dataset | γ | Accepted pair blocks | Accepted collective blocks | Pair-only identifications | Collective-only identifications | Collective additions beyond production pairs |",
        "| --- | --- | --- | --- | --- | --- | --- |"])
    for row in tables["public_aggregate_rows"]:
        lines.append(f"| {row['dataset']} | {row['gamma']} | {triplet(row,'accepted_pair_blocks')} | {triplet(row,'accepted_collective_blocks')} | {triplet(row,'pair_only_removed_vertices')} | {triplet(row,'collective_only_removed_vertices')} | {triplet(row,'collective_additions_beyond_accepted_production_pairs')} |")
    lines.extend(["", "Controlled and development production rows preserve the same size-specific fields in `control_production_rows.csv`. Predeclared computation-only cases without an independent bank remain unavailable and receive no fabricated zero counts."])
    lines.extend(["", "## Structural comparisons with named baseline criteria", "",
        "Additional identifications are the rank added to the join of two separately reported equivalence relations. The join is a structural comparison only, with no joint-safety or domination claim. Baseline strict/weak scope and all per-seed costs are retained in the CSV files.", "",
        "| Dataset | γ | Baseline | Baseline removed | New structural additions | Baseline structural additions |",
        "| --- | --- | --- | --- | --- | --- |"])
    for row in tables["public_baseline_aggregate_rows"]:
        lines.append(f"| {row['dataset']} | {row['gamma']} | {row['method']} | {triplet(row,'removed_vertices')} | {triplet(row,'new_structural_identifications_beyond_baseline')} | {triplet(row,'baseline_structural_identifications_beyond_new')} |")
    lines.extend(["", "## Paired Louvain workloads", "",
        "Both arms retain the discovery incumbent. Speedup is discovery plus unreduced time divided by the complete reduced pipeline time; values below one indicate an end-to-end cost increase. Reported Q is the best across the specified workload and the same discovery incumbent. The cold-unreduced reference is separately retained in CSV/JSON.", "",
        "| Dataset | γ | Solves | Speedup vs discovery control | Control best Q | Reduced best Q | Paired Q difference |",
        "| --- | --- | --- | --- | --- | --- | --- |"])
    for row in tables["public_workload_aggregate_rows"]:
        lines.append(f"| {row['dataset']} | {row['gamma']} | {row['solves']} | {triplet(row,'speedup_vs_discovery_control')} | {triplet(row,'unreduced_bestQ_over_workload_and_discovery')} | {triplet(row,'reduced_bestQ_over_workload_and_discovery')} | {triplet(row,'paired_bestQ_difference')} |")
    lines.extend(["", "## Controlled and development diagnostics", "",
        "Independent seed0 bank coverage, supplied reference blocks, AUTO acceptance, forced EXACT acceptance, and independent exact ablations remain separate tables. Exploratory stress cases retain their recorded role. Numerical matches and numerical optimization never receive certified status.", "",
        "```json", json.dumps(summary["controls"], ensure_ascii=False, sort_keys=True, indent=2) if not tables["block_aggregate_rows"] else json.dumps({k:v for k,v in summary["controls"].items() if k != "block_comparisons"}, ensure_ascii=False, sort_keys=True, indent=2), "```", "",
        "Full per-family/panel/method acceptance and exclusion denominators are in `block_aggregate_rows.csv`; individual failed/unavailable criteria remain in `block_criterion_rows.csv`.", "",
        "## Complete native solver eligibility", "",
        "Only completed matched pairs enter solve-time ratios. One-node analytic quotient pairs are separately labeled. Timeouts retain censored observation duration, the supplied feasible Q, and available exact Q bounds; no timeout limit is used as a solved time. Independently scaled integer editing costs are never compared across arms.", "",
        "For the reviewed Davis assertion, both native statuses remain failed. Raw emitted native bounds remain archived but are suppressed from these tables, along with native optimum, gap and completed ratios. Observed failed-call duration is a separately named failure observation; independently verified feasible supplied Q is retained.", "",
        "```json", json.dumps(summary["full_native"], ensure_ascii=False, sort_keys=True, indent=2), "```", "",
        "Selected native preprocessing is a separate weighted-rules baseline. Its remaining equivalence classes include every expanded solved group. Residual n=0 does not imply all original vertices were removed.", "",
        "## Isolated scaling", "",
        "The median and range use only the three unprofiled timing repetitions. RSS and traced allocation come from the single separate memory repetition. RSS includes input/preparation; dense exterior assembly is an uncertified diagnostic. Full checker measurements include O(n) CSR column-slicing workspace.", "",
        "Whole checker and preparation plus checker are the primary timing measures. Component timings are recorded separately with unequal scopes: production exterior assembly is sparse dispersion; reference assembly includes rational matrix/projected-basis construction; dense assembly includes the table/float contrast matrix. They must not be presented as the same kernel.", "",
        "| Case | Method | n | k | Unprofiled checker seconds | Memory process RSS bytes | Traced checker peak bytes |",
        "| --- | --- | --- | --- | --- | --- | --- |"])
    for row in tables["scaling_aggregate_rows"]:
        lines.append(f"| {row['case_id']} | {row['method']} | {row['original_vertices']} | {row['k']} | {triplet(row,'unprofiled_checker_seconds')} | {row['process_peak_RSS_bytes_memory_rep']} | {row['checker_traced_peak_bytes_memory_rep']} |")
    lines.extend(["", "## Provenance and interpretation limits", "",
        "`summary.json` records each consumed raw artifact SHA-256, every frozen runtime-source identity, and the field-contract source paths. `analysis-provenance.json` identifies this analysis implementation and output hashes. No raw measurement is modified.", ""])
    for text in INTERPRETATION_LIMITS:
        lines.append(f"- {text}")
    lines.append("")
    return "\n".join(lines)


def _csv(rows: list[dict]) -> bytes:
    keys = sorted({key for row in rows for key in row})
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=keys, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                         if isinstance(value, (dict, list, tuple)) else value for key, value in row.items()})
    return stream.getvalue().encode("utf-8")


def analyze(run_dir: Path | str, *, project_root: Path | str = ".", expected_job_count: int | None = None,
            config_path: str = "experiments/config.json", freeze_path: str = "experiments/freeze.json") -> tuple[dict, dict[str, list]]:
    """Validate the entire complete suite and return deterministic JSON records."""
    suite = audit_suite(run_dir, project_root=project_root, config_path=config_path, freeze_path=freeze_path,
                        expected_job_count=expected_job_count)
    names = ("public_seed_rows", "baseline_seed_rows", "public_downstream_rows", "public_workload_rows",
             "control_production_rows", "block_criterion_rows", "auto_exact_comparison_rows", "c_subinstance_rows", "c_subinstance_attempt_rows",
             "selected_native_rows", "full_native_pair_rows", "full_native_arm_rows", "numerical_milp_rows",
             "scaling_raw_rows", "scaling_aggregate_rows")
    tables = {name: [] for name in names}
    try:
        for job in suite.jobs:
            if job.stratum == "public":
                _public(suite, job, tables)
            elif job.stratum == "scaling":
                _scaling(suite, job, tables)
            else:
                _controls(suite, job, tables)
        summary = _summary(suite, tables)
    except AnalysisError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError) as error:
        raise AnalysisError(f"Raw record does not satisfy the frozen field contract: {error}") from error
    return summary, tables


def generate_report(run_dir: Path | str, output_dir: Path | str, *, project_root: Path | str = ".",
                    expected_job_count: int | None = None, config_path: str = "experiments/config.json",
                    freeze_path: str = "experiments/freeze.json") -> dict:
    """Write canonical analysis artifacts only after all validation succeeds."""
    output_dir = Path(output_dir).resolve()
    run_dir = Path(run_dir).resolve()
    _require(output_dir != run_dir and run_dir not in output_dir.parents, "Analysis output must not alter immutable raw run files")
    summary, tables = analyze(run_dir, project_root=project_root, expected_job_count=expected_job_count,
                              config_path=config_path, freeze_path=freeze_path)
    artifacts = {"summary.json": _canonical(summary), "tables.json": _canonical(tables),
                 "report.md": _markdown(summary, tables).encode("utf-8")}
    artifacts.update({f"{name}.csv": _csv(rows) for name, rows in sorted(tables.items())})
    script = Path(__file__).resolve()
    provenance = {"schema_version": SCHEMA_VERSION, "analysis_source": "analysis/report.py",
        "analysis_source_sha256": sha256(script), "run_id": summary["run_id"],
        "config_sha256": summary["config_sha256"], "freeze_sha256": summary["freeze_sha256"],
        "determinism": "canonical sorted JSON, fixed frozen job/row order, UTF-8 CSV, no analysis wall-clock timestamp",
        "artifact_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(artifacts.items())}}
    novelty_audit = Path(project_root).resolve() / "reviews/novelty-strength-audit.md"
    if novelty_audit.is_file():
        provenance["post_freeze_descriptive_mechanism_basis"] = {
            "path": "reviews/novelty-strength-audit.md", "sha256": sha256(novelty_audit)}
    artifacts["analysis-provenance.json"] = _canonical(provenance)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, raw in sorted(artifacts.items()):
        temporary = output_dir / f".{name}.tmp"
        temporary.write_bytes(raw)
        temporary.replace(output_dir / name)
    return {"status": summary["status"], "output_dir": str(output_dir),
            "completed_processes": summary["completed_processes"], "artifacts": sorted(artifacts)}


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--config", default="experiments/config.json")
    parser.add_argument("--freeze", default="experiments/freeze.json")
    parser.add_argument("--expected-jobs", type=int, default=139)
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        result = generate_report(args.run_dir, args.output_dir, project_root=args.project_root,
            expected_job_count=args.expected_jobs, config_path=args.config, freeze_path=args.freeze)
    except AnalysisError as error:
        print(json.dumps({"status": "analysis_refused", "error_type": type(error).__name__, "reason": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.modules.setdefault("analysis.report", sys.modules[__name__])
    raise SystemExit(main())
