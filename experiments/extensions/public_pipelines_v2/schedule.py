"""Fixed full grid and balanced deterministic orders, independent of outcomes."""
from fractions import Fraction

from .contracts import ARMS, CaseKey

DATASETS = ("ca-GrQc", "ca-HepTh", "email-Eu-core", "facebook_combined", "ca-CondMat", "p2p-Gnutella08")
DISCOVERY_SEEDS = (0, 1, 2)
GAMMAS = ("1/2", "1", "2")
DOWNSTREAM_SEEDS = tuple(range(10, 19))
PREFIXES = (1, 3, 9)


def enumerate_cases(config):
    if any(type(value) is not int for key in ("discovery_seeds", "downstream_seeds", "prefixes") for value in config[key]):
        raise ValueError("seed/prefix grid values must be integers, never booleans")
    if (tuple(config["datasets"]) != DATASETS or tuple(config["discovery_seeds"]) != DISCOVERY_SEEDS
            or tuple(config["gamma"]) != GAMMAS or tuple(config["arms"]) != ARMS
            or tuple(config["downstream_seeds"]) != DOWNSTREAM_SEEDS or tuple(config["prefixes"]) != PREFIXES):
        raise ValueError("configuration differs from the prospectively fixed complete grid")
    result = []
    for dataset in DATASETS:
        for discovery in DISCOVERY_SEEDS:
            for text in GAMMAS:
                result.append(CaseKey(dataset, discovery, Fraction(text), len(result)))
    return tuple(result)


def preprocessing_order(ordinal):
    j = ordinal % 4
    return ARMS[j:] + ARMS[:j]


def seed_arm_order(ordinal, seed_index):
    if ordinal < 0 or not 0 <= seed_index < 9:
        raise ValueError("invalid scheduled ordinal/seed index")
    j = (ordinal + seed_index) % 4
    order = ARMS[j:] + ARMS[:j]
    return tuple(reversed(order)) if (ordinal // 4) % 2 else order


def expected_ledger(config):
    cases = enumerate_cases(config)
    case_rows, executions, prefixes = [], [], []
    for case in cases:
        row = case.record()
        row["preprocessing_order"] = list(preprocessing_order(case.ordinal))
        row["downstream_order"] = [{"seed": seed, "arms": list(seed_arm_order(case.ordinal, r))}
                                   for r, seed in enumerate(DOWNSTREAM_SEEDS)]
        case_rows.append(row)
        for seed in DOWNSTREAM_SEEDS:
            for arm in ARMS:
                executions.append({"execution_key": f"{case.key}/{arm}/seed{seed}",
                                   "case_key": case.key, "arm": arm, "seed": seed})
        for arm in ARMS:
            for k in PREFIXES:
                prefixes.append({"prefix_key": f"{case.key}/{arm}/prefix{k}",
                                 "case_key": case.key, "arm": arm, "prefix": k})
    return {"setups": [{"setup_key": f"{d}-discovery{s}", "dataset": d, "discovery_seed": s}
                       for d in DATASETS for s in DISCOVERY_SEEDS],
            "cases": case_rows, "executions": executions, "prefixes": prefixes,
            "counts": {"setups": 18, "cases": 54, "arm_states": 216, "executions": 1944, "prefixes": 648}}
