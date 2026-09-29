"""Unique source/configuration gate and failed-controller preservation fixtures.

These are synthetic engineering checks, never public measurement or actual
independent source approval. The four numerical/interface groups are independently
owned in test_independent.py.
"""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import freeze, run_all
from .contracts import SCHEMA, read_json, sha256, write_once
from .schedule import expected_ledger


class SourceAndFailureGates(unittest.TestCase):
    def test_actual_closeout_and_config_mutations_fail_closed(self):
        config = read_json(freeze.CONFIG_PATH)
        prerequisites = freeze.validate_prerequisites(config)
        self.assertEqual(len(prerequisites["archived_bank_identity"]), 18)
        self.assertEqual(expected_ledger(config)["counts"]["executions"], 1944)
        for kind in ("unknown", "bool_seed", "degree", "recursive", "rd", "fallback", "phase"):
            changed = copy.deepcopy(config)
            if kind == "unknown":
                changed["unlisted_endpoint"] = True
            elif kind == "bool_seed":
                changed["discovery_seeds"][1] = True
            elif kind == "degree":
                changed["degree_policy"]["dense_max_size"] = 256
            elif kind == "recursive":
                changed["recursive_policy"]["include_round_decisions"] = True
            elif kind == "rd":
                changed["rd_policy"]["fresh_independent_recursive_prefix"] = False
            elif kind == "fallback":
                changed["incumbent_policy"]["initial_partition_supplied_to_louvain"] = True
            else:
                changed["phase_policy"]["primary_names"].pop()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                freeze.validate_config(changed)
        sources = freeze.runtime_sources()
        self.assertTrue(set(freeze.UPSTREAM_FILES).issubset(sources))
        self.assertIn("experiments/extensions/public_pipelines_v2/run_all.py", sources)
        self.assertIn("experiments/extensions/public_pipelines_v2/collect.py", sources)
        self.assertFalse(any("test_" in path or "kapoce" in path for path in sources))
        # A missing actual approval must stop before writing any freeze.
        with tempfile.TemporaryDirectory() as directory:
            review, validation, output = (Path(directory) / name for name in ("review.json", "validation.json", "freeze.json"))
            write_once(review, {"status": "pending_engineering_fixture_only"})
            write_once(validation, {"status": "passed", "engineering_only": True})
            with self.assertRaises(ValueError):
                freeze.create_freeze(freeze.CONFIG_PATH, review, validation, output)
            self.assertFalse(output.exists())

    def test_controller_keeps_failed_setup_and_complete_blocked_denominator(self):
        config = read_json(freeze.CONFIG_PATH)
        ledger = expected_ledger(config)
        synthetic_freeze = {"expected_ledger": ledger, "runtime_source_sha256": freeze.runtime_sources(),
                            "expected_ledger_sha256": "synthetic-ledger-fixture", "versions": {"fixture": "synthetic"},
                            "hardware": {"fixture": "synthetic"}}
        def fail_setup(case, config_arg, freeze_arg, identity, run_dir, *, progress):
            progress["phase"] = "candidate_discovery_and_fixed_bank_validation"
            progress["raw_setup_record"] = {"schema_version": SCHEMA, "setup_key": case.setup_key,
                                             "status": "started", "synthetic_engineering_fixture": True,
                                             "fixed_bank_attempt": {"blocks": [[0, 1]], "discovery_labels": [0, 0]},
                                             **identity}
            raise ArithmeticError("synthetic archived-bank mismatch")
        with tempfile.TemporaryDirectory() as directory:
            fake_path = Path(directory) / "synthetic-freeze.json"
            write_once(fake_path, {"engineering_fixture_only": True})
            output = Path(directory) / "run"
            with patch.object(run_all, "validate_freeze", return_value=(config, synthetic_freeze)), \
                    patch.object(run_all, "prepare_setup", side_effect=fail_setup):
                with self.assertRaisesRegex(ArithmeticError, "synthetic archived-bank mismatch"):
                    run_all.execute(freeze.CONFIG_PATH, fake_path, output)
            failure = read_json(output / "run-failed.json")
            self.assertEqual(failure["status"], "halted_for_recorded_source_repair")
            self.assertEqual(len(failure["blocked_case_keys"]), 54)
            self.assertEqual(failure["expected_counts"]["executions"], 1944)
            partial = read_json(failure["partial_setup_record"]["path"])
            self.assertEqual(partial["fixed_bank_attempt"]["blocks"], [[0, 1]])
            self.assertEqual(partial["status"], "failed")
            self.assertEqual(sha256(failure["partial_setup_record"]["path"]), failure["partial_setup_record"]["sha256"])
            self.assertFalse((output / "run-completed.json").exists())
            before = sha256(output / "run-failed.json")
            with patch.object(run_all, "validate_freeze", return_value=(config, synthetic_freeze)):
                with self.assertRaises(FileExistsError):
                    run_all.execute(freeze.CONFIG_PATH, fake_path, output)
            self.assertEqual(sha256(output / "run-failed.json"), before)


if __name__ == "__main__":
    unittest.main()
