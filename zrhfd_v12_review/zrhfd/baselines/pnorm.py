from ._native import run_native


def run(graph, seed, config, oracle_volume=None):
    return run_native("pnorm", graph, seed, config, oracle_volume)
