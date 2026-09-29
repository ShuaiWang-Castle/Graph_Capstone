"""Portable identities, state contracts and disjoint outer compute intervals."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
import gzip
import hashlib
import json
import math
from numbers import Integral
from pathlib import Path
import time
from typing import Any

ARMS = ("U", "D", "R", "RD")
COMMON_PHASES = ("common_original_prepare", "common_discovery", "common_discovery_evaluate")
ARM_PHASES = ("recursive_prefix", "recursive_csr_reconstruct_validate", "mapped_bank_prepare",
              "degree_prepare_check", "degree_contract_validate", "r_prefix_cross_arm_validate",
              "arm_solver_prepare")
SEED_PHASES = ("seed_solve_and_float_validate", "seed_lift_exact_validate", "seed_select_materialize")
PHASES = COMMON_PHASES + ("fixed_bank_refinement",) + ARM_PHASES + SEED_PHASES + ("prefix_finalize",)
SCHEMA = "public-pipelines-v2.1"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def content_hash(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_once(path, value):
    """An exclusive raw write never replaces a failed/partial previous attempt."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json_bytes(value)
    if path.suffix == ".gz":
        payload = gzip.compress(payload, mtime=0)
    with path.open("xb") as target:
        target.write(payload)
    return sha256(path)


def read_json(path):
    path = Path(path)
    payload = path.read_bytes()
    if path.suffix == ".gz":
        payload = gzip.decompress(payload)
    return json.loads(payload.decode("utf-8"))


def integer_labels(labels, n=None):
    result = tuple(labels)
    if n is not None and len(result) != n:
        raise ValueError("labels must cover every vertex")
    if any(isinstance(v, bool) or not isinstance(v, Integral) for v in result):
        raise ValueError("labels must be integers")
    return tuple(int(v) for v in result)


def canonical_partition(labels):
    labels = integer_labels(labels)
    order = {}
    return tuple(order.setdefault(v, len(order)) for v in labels)


def groups_from_membership(membership, n_current=None):
    membership = integer_labels(membership)
    if not membership or min(membership) < 0:
        raise ValueError("membership must be nonempty and nonnegative")
    count = max(membership) + 1 if n_current is None else int(n_current)
    groups = [[] for _ in range(count)]
    for u, v in enumerate(membership):
        if v >= count:
            raise ValueError("membership exceeds current graph")
        groups[v].append(u)
    if any(not group for group in groups):
        raise ValueError("membership must cover every current vertex")
    return tuple(tuple(group) for group in groups)


def compose_membership(first, second):
    first, second = integer_labels(first), integer_labels(second)
    if any(v < 0 or v >= len(second) for v in first):
        raise ValueError("membership composition has invalid intermediate IDs")
    result = tuple(second[v] for v in first)
    groups_from_membership(result)
    return result


def rational_record(value):
    value = Fraction(value)
    return {"numerator": int(value.numerator), "denominator": int(value.denominator)}


def rational_value(record):
    if set(record) != {"numerator", "denominator"}:
        raise ValueError("rational fields must have exactly numerator and denominator")
    n, d = record["numerator"], record["denominator"]
    if isinstance(n, bool) or isinstance(d, bool) or not isinstance(n, int) or not isinstance(d, int) or d <= 0:
        raise ValueError("invalid portable rational")
    value = Fraction(n, d)
    if value.numerator != n or value.denominator != d:
        raise ValueError("rational fields must be reduced")
    return value


@dataclass(frozen=True)
class CaseKey:
    dataset: str
    discovery_seed: int
    gamma: Fraction
    ordinal: int

    @property
    def setup_key(self):
        return f"{self.dataset}-discovery{self.discovery_seed}"

    @property
    def key(self):
        return f"{self.setup_key}-gamma{self.gamma.numerator}over{self.gamma.denominator}"

    def record(self):
        return {"case_key": self.key, "dataset": self.dataset, "discovery_seed": self.discovery_seed,
                "gamma": rational_record(self.gamma), "case_ordinal": self.ordinal, "setup_key": self.setup_key}


@dataclass(frozen=True)
class IntegerObjectiveCache:
    adjacency: Any
    rows: tuple[tuple[tuple[int, int], ...], ...]
    weights: tuple[int, ...]
    degrees: tuple[int, ...]
    total: int
    content_sha256: str

    @property
    def n(self):
        return len(self.degrees)


@dataclass(frozen=True)
class OriginalContext:
    graph: Any
    adjacency: Any
    objective: IntegerObjectiveCache
    metadata: dict
    largest_component: tuple[int, ...]
    vertex_order: tuple[int, ...]


@dataclass(frozen=True)
class FixedBank:
    blocks: tuple[tuple[int, ...], ...]
    discovery_labels: tuple[int, ...]
    identity_sha256: str
    source_record: dict


@dataclass(frozen=True)
class MappedBank:
    blocks: tuple[tuple[int, ...], ...]
    entries: tuple[dict, ...]
    summary: dict


@dataclass
class ArmState:
    arm: str
    adjacency: Any
    membership: tuple[int, ...]
    graph: Any = None
    objective: IntegerObjectiveCache | None = None
    provenance: dict = field(default_factory=dict)
    recursive_partition: tuple[int, ...] | None = None
    seed_results: list[dict] = field(default_factory=list)
    prefixes: list[dict] = field(default_factory=list)


class PhaseLedger:
    """Every primary outer interval is exclusive; nested source times are separate."""
    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.origin = clock()
        self.records = []
        self.active = None

    @contextmanager
    def measure(self, name, *, arm=None, seed=None, prefix=None):
        if name not in PHASES or self.active is not None or (arm is not None and arm not in ARMS):
            raise ValueError("unknown phase/arm or nested primary measurement")
        start = self.clock()
        self.active = name
        record = {"phase": name, "arm": arm, "seed": seed, "prefix": prefix,
                  "start_offset_seconds": start - self.origin, "status": "completed",
                  "applicability": "applicable", "attribution": "measured_outer_interval"}
        try:
            yield record
        except BaseException:
            record["status"] = "failed"
            raise
        finally:
            end = self.clock()
            record.update(end_offset_seconds=end - self.origin, seconds=end - start)
            self.active = None
            self._validate(record["seconds"])
            self.records.append(record)

    @staticmethod
    def _validate(seconds):
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            raise ArithmeticError("primary elapsed interval must be finite and nonnegative")

    def attribute_candidate_call(self, outer_seconds, refinement_seconds, proposal_seconds):
        self._validate(outer_seconds)
        self._validate(refinement_seconds)
        self._validate(proposal_seconds)
        remainder = outer_seconds - refinement_seconds
        if remainder < 0 or outer_seconds - refinement_seconds - proposal_seconds < -1e-6:
            raise ArithmeticError("candidate nested intervals exceed the outer call")
        for name, seconds, formula in (("common_discovery", remainder, "B-F"),
                                       ("fixed_bank_refinement", refinement_seconds, "F")):
            self.records.append({"phase": name, "arm": None, "seed": None, "prefix": None,
                                 "start_offset_seconds": None, "end_offset_seconds": None,
                                 "seconds": seconds, "status": "completed", "applicability": "applicable",
                                 "attribution": "partition_of_candidate_outer_call", "formula": formula})
        return {"candidate_outer_seconds_B": outer_seconds, "source_refinement_seconds_F": refinement_seconds,
                "source_proposal_seconds": proposal_seconds, "B_minus_F_seconds": remainder,
                "source_residual_overhead_seconds": outer_seconds - proposal_seconds - refinement_seconds,
                "nested_source_timers_are_not_added_to_primary_totals": True}

    def not_applicable(self, name, arm):
        self.records.append({"phase": name, "arm": arm, "seed": None, "prefix": None,
                             "start_offset_seconds": None, "end_offset_seconds": None, "seconds": None,
                             "status": "not_applicable", "applicability": "not_applicable"})

    def sum(self, names, *, arm=None, seeds=None, prefix=None):
        return sum(record["seconds"] for record in self.records if record["phase"] in names
                   and record.get("arm") == arm and record["status"] == "completed"
                   and (seeds is None or record.get("seed") in seeds)
                   and (prefix is None or record.get("prefix") == prefix))


def standalone_cost(ledger, arm, prefix, seeds):
    if arm not in ARMS or prefix not in (1, 3, 9) or len(seeds) != 9:
        raise ValueError("unknown standalone workload")
    common = ledger.sum(COMMON_PHASES)
    refinement = 0.0 if arm == "U" else ledger.sum(("fixed_bank_refinement",))
    preparation = ledger.sum(ARM_PHASES, arm=arm)
    downstream = ledger.sum(SEED_PHASES, arm=arm, seeds=seeds[:prefix])
    finalization = ledger.sum(("prefix_finalize",), arm=arm, prefix=prefix)
    return {"common_seconds": common, "fixed_bank_refinement_seconds": refinement,
            "arm_preparation_seconds": preparation, "seed_compute_seconds": downstream,
            "prefix_finalize_seconds": finalization,
            "constructed_standalone_seconds": math.fsum((common, refinement, preparation, downstream, finalization)),
            "cost_scope": "constructed standalone single-resolution workload; no v1 times; no multi-gamma amortization"}
