"""Experimental prepared topology for the unchanged exact seeded cut network.

Opt-in only. Frozen mincut/certificate sources and the integer backend are never
edited. A workspace requires graph topology/weights to stay immutable throughout
its lifetime. Capacity text and order match mincut.cut_with_unary exactly.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
from math import gcd, lcm
import subprocess
import time
from .mincut import BINARY


@dataclass(frozen=True)
class EncodedCut:
    text: str
    denominator: int
    constant: int
    force: int
    arc_count: int
    arcs: tuple | None


class PreparedRegionWorkspace:
    def __init__(self, graph, region, seed):
        started = time.perf_counter()
        self.graph, self.seed = graph, int(seed)
        self.region = tuple(sorted(set(map(int, region))))
        if self.seed not in self.region:
            raise ValueError('Seed absent from region')
        if any(u < 0 or u >= graph.n for u in self.region):
            raise ValueError('Invalid prepared region vertex')
        self.local = {u: i for i, u in enumerate(self.region)}
        self.source, self.sink = len(self.region), len(self.region) + 1
        boundary = {u: Fraction(0) for u in self.region}
        inner = []
        weights = {}
        scanned = 0
        for u in self.region:
            lo, hi = graph.indptr[u:u + 2]
            for j in range(lo, hi):
                scanned += 1
                v, raw = int(graph.indices[j]), float(graph.weights[j])
                if raw not in weights:
                    weights[raw] = Fraction(str(raw))
                w = weights[raw]
                if v not in self.local:
                    boundary[u] += w
                elif u < v:
                    inner.append((self.local[u], self.local[v], w.numerator, w.denominator))
        self.boundary = tuple(boundary[u] for u in self.region)
        self.inner = tuple(inner)
        self.integer_degree = tuple(int(round(graph.degree[u])) for u in self.region)
        self.degree_integer_scope = bool(graph.integer_weights)
        self.static_denominator = 1
        for _, _, _, denominator in self.inner:
            self.static_denominator = lcm(self.static_denominator, denominator)
        self.inner_capacity_sum = sum((Fraction(n, d) * 2 for _, _, n, d in self.inner), Fraction(0))
        self.inner_text_prefixes = tuple((f'{u} {v} ', f'{v} {u} ', n, d) for u, v, n, d in self.inner)
        self.graph_array_identity = tuple(getattr(graph, k) for k in ('indptr', 'indices', 'weights', 'degree'))
        self.preparation_seconds = time.perf_counter() - started
        self.scanned_adjacency_entries = scanned
        self.calls = 0
        self.assembly_seconds = self.native_seconds = self.validation_seconds = 0.0

    def encode(self, unary, include_arcs=False):
        """Retain exact reduction, LCM, zero arcs, force and original arc order."""
        pairs = []
        denominator = self.static_denominator
        for u, boundary in zip(self.region, self.boundary):
            value = Fraction(unary[u])
            if boundary.denominator == 1:
                # Adding an integer preserves the reduced unary denominator.
                n, d = value.numerator + boundary.numerator * value.denominator, value.denominator
            else:
                d = lcm(value.denominator, boundary.denominator)
                n = value.numerator * (d // value.denominator) + boundary.numerator * (d // boundary.denominator)
                common = gcd(n, d)
                n, d = n // common, d // common
            pairs.append((n, d))
            denominator = lcm(denominator, d)
        lines, arcs = [], [] if include_arcs else None
        constant = unary_capacity_sum = 0
        for local, (n, d) in enumerate(pairs):
            integer = n * (denominator // d)
            if integer >= 0:
                u, v, capacity = local, self.sink, integer
            else:
                u, v, capacity = self.source, local, -integer
                constant += integer
            unary_capacity_sum += capacity
            lines.append(f'{u} {v} {capacity}\n')
            if arcs is not None:
                arcs.append((u, v, capacity))
        capacity_strings = {}
        for i, (forward, backward, n, d) in enumerate(self.inner_text_prefixes):
            key = (n, d)
            if key not in capacity_strings:
                integer = n * (denominator // d)
                capacity_strings[key] = (integer, str(integer) + '\n')
            integer, ending = capacity_strings[key]
            lines.extend((forward + ending, backward + ending))
            if arcs is not None:
                u, v, _, _ = self.inner[i]
                arcs.extend(((u, v, integer), (v, u, integer)))
        force = unary_capacity_sum + self.inner_capacity_sum.numerator * (denominator // self.inner_capacity_sum.denominator) + 1
        if force >= (1 << 124):
            raise OverflowError('Exact cut exceeds 128-bit engineering backend; no floating fallback')
        forced = (self.source, self.local[self.seed], force)
        lines.append(f'{forced[0]} {forced[1]} {force}\n')
        if arcs is not None:
            arcs.append(forced)
        arc_count = len(self.region) + 2 * len(self.inner) + 1
        text = f'{len(self.region) + 2} {arc_count} {self.source} {self.sink}\n' + ''.join(lines)
        return EncodedCut(text, denominator, constant, force, arc_count, tuple(arcs) if arcs is not None else None)

    def solve(self, unary):
        if any(getattr(self.graph, k) is not old for k, old in zip(('indptr', 'indices', 'weights', 'degree'), self.graph_array_identity)):
            raise RuntimeError('Prepared workspace graph arrays were replaced')
        call_started = time.perf_counter()
        encoded = self.encode(unary)
        assembled = time.perf_counter()
        result = subprocess.run([str(BINARY)], input=encoded.text, text=True, capture_output=True, check=True)
        native_finished = time.perf_counter()
        lines = result.stdout.splitlines()
        value = int(lines[0])
        reachable = set(map(int, lines[1].split()))
        selected = [u for u, local in self.local.items() if local in reachable]
        if self.seed not in selected:
            raise RuntimeError('Exact seeded cut failed force constraint')
        objective = Fraction(value + encoded.constant, encoded.denominator)
        # Keep the frozen implementation's independent original-graph check.
        actual = Fraction(self.graph.stats(selected)['cut']) + sum(Fraction(unary[u]) for u in selected)
        if objective != actual:
            raise RuntimeError('Cut encoding/return objective disagreement')
        finished = time.perf_counter()
        self.calls += 1
        self.assembly_seconds += assembled - call_started
        self.native_seconds += native_finished - assembled
        self.validation_seconds += finished - native_finished
        return selected, objective, {'flow_integer': str(value), 'constant_integer': str(encoded.constant),
            'capacity_denominator': str(encoded.denominator), 'arcs': encoded.arc_count,
            'vertices': len(self.region), 'runtime_seconds': finished - assembled,
            'backend': 'Dinic_exact_int128', 'experimental_workspace': True,
            'assembly_seconds': assembled - call_started,
            'native_subprocess_seconds': native_finished - assembled,
            'objective_validation_seconds': finished - native_finished}

    def summary(self):
        return {'region_vertices': len(self.region), 'inner_edges': len(self.inner),
            'scanned_adjacency_entries_at_preparation': self.scanned_adjacency_entries,
            'preparation_seconds': self.preparation_seconds, 'calls': self.calls,
            'assembly_seconds': self.assembly_seconds, 'native_subprocess_seconds': self.native_seconds,
            'objective_validation_seconds': self.validation_seconds,
            'integer_degree_scope': self.degree_integer_scope,
            'static_edge_capacity_denominator': str(self.static_denominator)}


class WorkspaceDispatcher:
    def __init__(self):
        self.workspaces = {}
        self.region_objects = {}

    def __call__(self, graph, region, seed, unary):
        identity = id(region)
        previous = self.region_objects.get(identity)
        if previous is not None and previous[0] is region:
            canonical = previous[1]
        else:
            canonical = tuple(sorted(set(map(int, region))))
            # Keep a strong reference to prevent object-ID reuse. Input region
            # lists are immutable throughout the frozen MM/certificate calls.
            self.region_objects[identity] = (region, canonical)
        key = (id(graph), canonical, int(seed))
        if key not in self.workspaces:
            self.workspaces[key] = PreparedRegionWorkspace(graph, canonical, seed)
        return self.workspaces[key].solve(unary)

    def summary(self):
        return [workspace.summary() for workspace in self.workspaces.values()]


@contextmanager
def installed_workspace():
    """Opt-in process-local replacement, including certificate's imported alias."""
    from . import mincut, certificate
    dispatcher = WorkspaceDispatcher()
    original_cut, original_certificate_cut = mincut.cut_with_unary, certificate.cut_with_unary
    mincut.cut_with_unary = certificate.cut_with_unary = dispatcher
    try:
        yield dispatcher
    finally:
        mincut.cut_with_unary, certificate.cut_with_unary = original_cut, original_certificate_cut
