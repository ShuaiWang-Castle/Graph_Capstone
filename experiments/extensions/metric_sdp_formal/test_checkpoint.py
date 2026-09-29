"""New atomic CSR engineering invariants; no graph or scientific arm is run."""
from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

import numpy as np
from scipy import sparse

from . import runtime


HERE = Path(__file__).resolve().parent


def fixture(label):
    directory = HERE / "checkpoint-author" / "fixtures" / (label + "-" + uuid.uuid4().hex[:10])
    directory.mkdir(parents=True, exist_ok=False)
    runtime.write_once(directory / "engineering-scope.json", {
        "scientific_measurement": False, "explicit_matrix_n": 4,
        "graph_generation": False, "discovery_calls": 0, "solver_calls": 0,
        "scope": "new atomic CSR path only",
    })
    return directory


def explicit_csr():
    # Loops and noncontiguous column indices survive the stored CSR representation.
    return sparse.csr_matrix(np.array([
        [13, 0, 7, 0], [0, 0, 0, 5], [7, 0, 2, 0], [0, 5, 0, 11],
    ], dtype=np.int64))


class CheckpointAuthor(unittest.TestCase):
    def test_exact_arrays_and_exclusive_final_identity(self):
        directory = fixture("roundtrip-exclusive")
        target, original = directory / "original-adjacency.npz", explicit_csr()
        runtime.write_original_csr_once(target, original)
        digest = runtime.sha256(target)
        with np.load(target, allow_pickle=False) as saved:
            for name in ("data", "indices", "indptr"):
                self.assertTrue(np.array_equal(saved[name], getattr(original, name)))
                self.assertEqual(saved[name].dtype, getattr(original, name).dtype)
            self.assertEqual(tuple(saved["shape"]), original.shape)
        self.assertFalse(target.with_name(target.name + ".partial").exists())
        with self.assertRaises(FileExistsError):
            runtime.write_original_csr_once(target, original * 2)
        self.assertEqual(runtime.sha256(target), digest)
        self.assertTrue(target.with_name(target.name + ".partial").exists())

    def test_interrupted_writer_never_publishes_incomplete_final(self):
        directory = fixture("interrupted-csr")
        target = directory / "original-adjacency.npz"
        def fail(handle, **arrays):
            handle.write(b"injected incomplete archive")
            raise OSError("explicit engineering interruption")
        with patch.object(runtime.np, "savez_compressed", side_effect=fail):
            with self.assertRaisesRegex(OSError, "explicit engineering interruption"):
                runtime.write_original_csr_once(target, explicit_csr())
        self.assertFalse(target.exists())
        partial = target.with_name(target.name + ".partial")
        self.assertEqual(partial.read_bytes(), b"injected incomplete archive")
        with self.assertRaises(FileExistsError):
            runtime.write_original_csr_once(target, explicit_csr())
        self.assertFalse(target.exists())

    def test_unchanged_run_arm_ast_except_declared_checkpoint_orchestration(self):
        def function(path):
            return next(node for node in ast.parse(path.read_text()).body
                        if isinstance(node, ast.FunctionDef) and node.name == "run_arm")
        original = function(HERE.parent / "metric_sdp/runtime.py")
        changed = deepcopy(function(HERE / "runtime.py"))
        retained = []
        removed = []
        for node in changed.body:
            if (isinstance(node, ast.With) and
                    ast.unparse(node.items[0].context_expr) == "ledger.measure('original_input_checkpoint')"):
                removed.append("original_input_checkpoint")
                continue
            if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "operation_files":
                removed.append("operation_files")
                continue
            if isinstance(node, ast.FunctionDef) and node.name == "composition_progress":
                removed.append("composition_progress")
                continue
            if (isinstance(node, ast.If) and
                    ast.unparse(node.test) == "composition is not None and len(operation_files) != len(composition.operations)"):
                removed.append("durable_operation_count_validation")
                continue
            if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and
                    ast.unparse(node.value.func) == "record.update" and
                    any(keyword.arg == "schema" for keyword in node.value.keywords)):
                removed.append("checkpoint_record_metadata")
                continue
            retained.append(node)
        changed.body = retained
        for node in ast.walk(changed):
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "run_composition":
                node.keywords = [keyword for keyword in node.keywords if keyword.arg != "progress"]
        self.assertEqual(removed, ["original_input_checkpoint", "operation_files", "composition_progress",
                                  "durable_operation_count_validation", "checkpoint_record_metadata"])
        self.assertEqual(ast.dump(original, include_attributes=False),
                         ast.dump(changed, include_attributes=False))


if __name__ == "__main__":
    unittest.main()
