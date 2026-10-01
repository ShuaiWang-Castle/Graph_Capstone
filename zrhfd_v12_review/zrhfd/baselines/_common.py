from pathlib import Path
import hashlib
import json
import math
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def source_record(name, files=()):
    entry = json.loads((ROOT / "provenance/baselines/acquisition.json").read_text())["repositories"][name]
    for path in files:
        current = ROOT / entry["path"] / path
        if hashlib.sha256(current.read_bytes()).hexdigest() != entry["tracked_worktree_file_sha256"][path]:
            raise RuntimeError("Frozen baseline source changed: " + name + "/" + path)
    return {"repository": entry["url"], "commit": entry["commit"], "files": {p: entry["tracked_worktree_file_sha256"][p] for p in files}}


def validate_query(graph, seed):
    if type(seed) is not int or not 0 <= seed < graph.n:
        raise ValueError("Invalid query seed")
    if not np.isfinite(graph.degree).all() or np.any(graph.degree < 0):
        raise ValueError("Invalid graph degree")
    return float(graph.degree[seed])


def neighbors(graph, vertex):
    start, stop = int(graph.indptr[vertex]), int(graph.indptr[vertex + 1])
    return zip(graph.indices[start:stop], graph.weights[start:stop])


def conductance(graph, vertices):
    selected = set(vertices)
    volume = float(sum(graph.degree[v] for v in selected))
    denominator = min(volume, float(graph.total) - volume)
    if denominator <= 0:
        return math.inf
    cut = sum(float(weight) for v in selected for u, weight in neighbors(graph, v) if int(u) not in selected)
    return cut / denominator


def sweep(graph, scores, seed, require_seed=False, keep_ties=False):
    """Conductance sweep on positive heights; explicit seed and tie policies."""
    if isinstance(scores, dict):
        values = {int(v): float(x) for v, x in scores.items() if x > 0}
    else:
        values = {int(v): float(scores[v]) for v in np.flatnonzero(np.asarray(scores) > 0)}
    if any(not math.isfinite(x) for x in values.values()):
        raise FloatingPointError("Nonfinite sweep heights")
    order = sorted(values, key=lambda v: (-values[v], v))
    selected = set()
    volume = cut = 0.0
    best_value = math.inf
    best = []
    for index, v in enumerate(order):
        for u, weight in neighbors(graph, v):
            cut += -float(weight) if int(u) in selected else float(weight)
        selected.add(v)
        volume += float(graph.degree[v])
        if keep_ties and index + 1 < len(order) and values[order[index + 1]] == values[v]:
            continue
        denominator = min(volume, float(graph.total) - volume)
        if denominator <= 0 or (require_seed and seed not in selected):
            continue
        value = max(0.0, cut) / denominator
        if value < best_value:
            best_value, best = value, sorted(selected)
    return best, best_value


def mass_grid(graph, seed, config, oracle_volume=None):
    if oracle_volume is not None:
        if not math.isfinite(float(oracle_volume)) or oracle_volume <= 0:
            raise ValueError("Invalid explicit oracle volume")
        return [float(config.get("oracle_mass_factor", 3.0)) * float(oracle_volume)], "explicit_oracle_volume"
    if "masses" in config:
        masses = [float(x) for x in config["masses"]]
        if any(not math.isfinite(x) or x <= 0 for x in masses):
            raise ValueError("Invalid fixed mass grid")
        return masses, "explicit_truth_free_mass_grid"
    mass = float(config.get("mass_start_factor", 3.0)) * float(graph.degree[seed])
    ratio = float(config.get("mass_ratio", 2.0))
    if ratio <= 1 or not math.isfinite(ratio):
        raise ValueError("Mass ratio must exceed one")
    masses = []
    for _ in range(int(config.get("max_mass_steps", 128))):
        if mass <= 0 or mass > float(config.get("mass_limit_fraction", .5)) * float(graph.total):
            break
        masses.append(mass)
        mass *= ratio
    return masses, "truth_free_doubling_to_fixed_volume_fraction"
