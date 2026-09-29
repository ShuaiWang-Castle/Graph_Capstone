"""Predeclared controlled cases; generation never depends on a certificate."""
from itertools import product


def controlled_grid():
    records = []
    def add(name, parameters, *, gamma=None, role="confirmatory_controlled", native=True):
        records.append({"case_id": f"controlled-{len(records):03d}-{name}", "family": name,
                        "parameters": parameters, "gamma": ["1/2", "1", "2"] if gamma is None else gamma,
                        "role": role, "native_preprocessing": native,
                        "candidate_bank_seed": 0, "supplied_block_comparison": True})
    for k in (3, 4, 5, 8, 16, 32, 64):
        add("matching_cliques", {"k": k})
    add("common_hub_matching", {"k": 6})
    add("uniform_advantage_counterexample", {}, gamma=["1/8"], role="derived_mechanism_negative_control")
    for seed in (201, 202, 203):
        add("weighted_planted_blocks", {"block_sizes": [4, 5, 6], "p": "4/5", "q": "1/25",
            "node_factors": [1, 2, 4], "internal_base": 3, "external_base": 1,
            "seed": seed, "relabel_seed": seed + 1000000})
    for p, q, noise, seed in product(("7/20", "13/20"), ("1/200", "1/50"),
                                    (("0", "0"), ("1/10", "1/1000")), (101, 102, 103)):
        add("noisy_planted_clusters", {"communities": 8, "block_size": 30, "p": p, "q": q,
            "deletion_probability": noise[0], "addition_probability": noise[1], "seed": seed,
            "noise_seed": seed + 100000, "relabel_seed": seed + 1000000}, native=seed == 101)
    for k, outside in product((16, 32), (100, 1000, 10000)):
        add("profile_scaling", {"k": k, "outside_vertices": outside, "hub_size": 4,
                                "core_weight": 1, "attachment_weight": 1, "outside_weight": 1}, native=False)
    for k in (3, 6, 16):
        add("hard_exterior_attachment", {"k": k, "attachment_weight": k + 2}, gamma=["1"],
            role="exploratory_proved_failure_stress", native=True)
    return records
