"""Cross-process command contract: this caught a real controls argv mismatch."""
import importlib
import json
from pathlib import Path

from experiments.run_all import jobs


def test_every_predeclared_job_is_accepted_by_its_actual_cli_parser():
    config = json.loads(Path("experiments/config.json").read_text())
    counts = {}
    for name, command in jobs(config, Path("unused-test-run"), "experiments/config.json", "experiments/freeze.json", ["public", "controls", "scaling"]):
        assert command[0] == "-m"
        module = importlib.import_module(command[1])
        parsed = module.make_parser().parse_args(command[2:])
        assert parsed.run_dir == "unused-test-run"
        counts[command[1]] = counts.get(command[1], 0) + 1
    assert counts["experiments.run_public"] == len(config["public_datasets"]) * len(config["proposal"]["seeds"])
    assert counts["experiments.run_controls"] == len(config["controlled_cases"]) + len(config["development_datasets"])
    scaling_cases = sum(case["family"] == "profile_scaling" for case in config["controlled_cases"])
    assert counts["experiments.run_scaling"] == scaling_cases * len(config["scaling"]["methods"]) * (config["scaling"]["replicate_count"] + config["scaling"]["memory_replicate_count"])
