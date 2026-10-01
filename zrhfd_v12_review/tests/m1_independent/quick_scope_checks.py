"""Exact numerical probes of frozen v1.2, without modifying its claims."""
from fractions import Fraction as F
from math import comb
import json
import platform
import time
from pathlib import Path
import argparse


def expectation(k, w, p):
    return sum((F(comb(k, j)) * p**j * (1-p)**(k-j) * w[j]
                for j in range(k+1)), F(0))


def g_single(k, w, v):
    return v-expectation(k, w, v/F(k))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-existing", action="store_true")
    args = parser.parse_args()
    start = time.perf_counter()
    equality_cases = []
    for k in (2, 3):
        w = [F(0)] + [F(1, 2)]*(k-1) + [F(0)]
        v = F(1)
        actual, claimed = g_single(k, w, v), v*v/F(k)
        equality_cases.append({"n": k, "hyperedges": [{"vertices": list(range(k)),
            "theta": "1", "w": [str(t) for t in w]}], "M": str(k), "v": str(v),
            "G_actual": str(actual), "G_claimed_v2_over_M": str(claimed),
            "normalized_bound_satisfied": True, "symmetric": True,
            "cardinality_concave": True, "violation": actual != claimed})
    k, w = 4, [F(0), F(0), F(1), F(0), F(0)]
    left, midpoint, right = F(0), F(1, 2), F(1)
    midpoint_value = g_single(k, w, midpoint)
    chord_value = (g_single(k, w, left)+g_single(k, w, right))/2
    result = {"schema_version": 1, "scope": "Literal frozen symmetric cardinality splitting functions; exact Fraction arithmetic",
        "claims": {"T-b-small-edge-equality": {"status": "FAIL", "cases": equality_cases},
            "T-b-convexity-without-concavity-assumption": {"status": "FAIL", "n": k,
                "hyperedges": [{"vertices": list(range(k)), "theta": "1", "w": [str(t) for t in w]}],
                "M": str(k), "v_left": str(left), "v_mid": str(midpoint), "v_right": str(right),
                "G_mid": str(midpoint_value), "chord_mid": str(chord_value),
                "excess": str(midpoint_value-chord_value), "normalized_bound_satisfied": True,
                "symmetric": True, "cardinality_concave": False,
                "scope_note": "Frozen v1.2 does not state discrete concavity. This case needs theoretical admissibility judgment."}},
        "metadata": {"python": platform.python_version(), "platform": platform.platform(),
                     "elapsed_seconds": time.perf_counter()-start}}
    root = Path(__file__).resolve().parents[2]
    output = args.output or root / "results" / "m1_independent" / "scope_counterexamples.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if args.check_existing:
            existing = json.loads(output.read_text())
            assert existing["claims"] == result["claims"], "Independent recomputation differs"
            print(json.dumps({"check_existing": "PASS", "output": str(output), "elapsed_seconds": time.perf_counter()-start}))
            return
        raise RuntimeError("Preserve immutable raw output: use --check-existing or a fresh --output")
    output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
