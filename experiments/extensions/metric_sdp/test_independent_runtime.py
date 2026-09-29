"""Independent engineering fixtures only; explicit mathematical order <=4.

No study input generator, sentinel worker, pilot, or benchmark is invoked.
All subprocess actors and retained files are inside independent-runtime.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction as F
import itertools
import json
import os
from pathlib import Path
import signal
import sys
import time
import unittest
from unittest.mock import patch
import uuid

import cvxpy as cp
import networkx as nx
import numpy as np
import psutil
from scipy import sparse

from . import freeze, numerical, runtime
from .rational import interval_from_payload, verify_interval
from .run_pilot import pilot_schedule, select_backend, supervise


HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "independent-runtime" / "fixtures"
CONFIG = json.loads((HERE / "config.json").read_text())
POLICY = CONFIG["solver"]


def directory(name):
    path = FIXTURES / (name + "-" + uuid.uuid4().hex[:10])
    path.mkdir(parents=True, exist_ok=False)
    freeze.write_once(path / "engineering-scope.json", {
        "scientific_measurement": False, "scope": "explicit n<=4 or process-only engineering",
        "name": name,
    })
    return path


def fractions(matrix):
    return [[F(int(x), matrix.denominator) for x in row]
            for row in matrix.numerators]


def determinant(matrix):
    n = len(matrix)
    if not n:
        return F(1)
    return sum(((-1) ** j) * matrix[0][j] * determinant(
        [row[:j] + row[j + 1:] for row in matrix[1:]]) for j in range(n))


class IndependentRuntime(unittest.TestCase):
    def assert_psd(self, matrix):
        # All principal minors, an exact independent order<=4 PSD criterion.
        for r in range(1, len(matrix) + 1):
            for ids in itertools.combinations(range(len(matrix)), r):
                minor = [[matrix[i][j] for j in ids] for i in ids]
                self.assertGreaterEqual(determinant(minor), 0)

    def assert_interval(self, c, result, optimum):
        self.assertEqual(result["status"], "verified_target")
        proof = result["interval"]
        y = fractions(proof.primal.matrix)
        n = len(c)
        self.assert_psd(y)
        for i in range(n):
            self.assertEqual(y[i][i], 1)
            for j in range(n):
                self.assertEqual(y[i][j], y[j][i])
                self.assertGreaterEqual(y[i][j], 0)
                self.assertLessEqual(y[i][j], 1)
        for i, j, k in itertools.permutations(range(n), 3):
            self.assertLessEqual(y[i][j] + y[j][k] - y[i][k], 1)
        lower = sum((c[i][j] * y[i][j] for i in range(n)
                     for j in range(n)), F())
        self.assertEqual(lower, proof.lower)
        dual = proof.dual
        multipliers = [F(x, dual.denominator) for x in dual.lambda_numerators]
        diagonal = [F(x, dual.denominator) for x in dual.y_numerators]
        model = [[-c[i][j] for j in range(n)] for i in range(n)]
        rhs = F()
        for i in range(n):
            model[i][i] += diagonal[i]
        for record, value in zip(dual.inequalities, multipliers):
            self.assertGreaterEqual(value, 0)
            # Independent literal inequalities, not record.terms().
            if record.kind == "lower":
                terms, bound = [(record.i, record.j, -1)], 0
            elif record.kind == "upper":
                terms, bound = [(record.i, record.j, 1)], 1
            else:
                terms, bound = [(record.i, record.j, 1), (record.j, record.k, 1),
                                (record.i, record.k, -1)], 1
            rhs += value * bound
            for i, j, sign in terms:
                model[i][j] += value * sign / 2
                model[j][i] += value * sign / 2
        self.assertEqual(model, fractions(dual.model))
        slack = [row[:] for row in model]
        for i in range(n):
            slack[i][i] += dual.tau
        self.assertEqual(slack, fractions(dual.slack))
        self.assert_psd(slack)
        self.assertEqual(sum(diagonal, F()) + rhs + n * dual.tau, proof.upper)
        self.assertLessEqual(proof.lower, optimum)
        self.assertGreaterEqual(proof.upper, optimum)
        self.assertEqual(proof.width, proof.upper - proof.lower)
        payload = json.loads(json.dumps(proof.to_dict(), allow_nan=False))
        decoded = interval_from_payload(payload)
        self.assertTrue(verify_interval(c, decoded))
        self.assertEqual(decoded.lower, proof.lower)
        broken = deepcopy(payload)
        broken["dual"]["lambda_numerators"][0] = -1
        with self.assertRaises((ArithmeticError, ValueError)):
            verify_interval(c, interval_from_payload(broken))

    def solve(self, c, backend, target=F(1, 10000)):
        path = directory("exact-" + backend + "-n" + str(len(c)))
        ledger = runtime.Ledger()
        def progress(index, proposal, metrics):
            if proposal is not None:
                with (path / f"raw-{index:02d}.npz").open("xb") as handle:
                    np.savez_compressed(handle, H=proposal["matrix"],
                                        y=proposal["diagonal_dual"],
                                        lambdas=proposal["inequality_dual"],
                                        slack=proposal["psd_dual_slack"])
            if metrics is not None:
                freeze.write_once(path / f"metrics-{index:02d}.json", metrics)
        result = numerical.solve_component(c, backend=backend, width_target=target,
                                          deadline=time.perf_counter() + 30,
                                          stage=ledger.measure, policy=POLICY, progress=progress)
        freeze.write_once(path / "outcome.json", {
            "status": result["status"], "rounds": result["rounds"],
            "stages": dict(ledger.seconds), "proof": result["interval"].to_dict(),
        })
        self.assertGreater(ledger.seconds["checkpoint"], 0)
        self.assertIn("rational_repair_and_exact_validation", ledger.seconds)
        self.assertNotIn("exact_interval_validation", ledger.seconds)
        return result

    def test_n2_full_trace_nonzero_and_negative_optima_both_backends(self):
        for off, optimum in ((F(1, 7), F(3, 35)), (-F(1, 7), -F(1, 5))):
            c = ((F(1, 5), off), (off, -F(2, 5)))
            for backend in ("direct", "indirect"):
                result = self.solve(c, backend)
                self.assert_interval(c, result, optimum)

    def test_n4_fractional_metric_optimum_and_x_only_warm_starts(self):
        # Sum of the three hub-centered triangles gives hub_sum<=3/2+leaf_sum/2.
        # F=hub_sum-2 leaf_sum<=3/2. diag1, hub=.5, leaves0 is PSD and metric.
        c = tuple(tuple(F() if i == j else F(1, 2) if i == 0 or j == 0
                        else -F(1) for j in range(4)) for i in range(4))
        real_scs = numerical.scs.SCS
        for backend in ("direct", "indirect"):
            calls = []
            class Tracked:
                def __init__(self, data, cone, **kwargs):
                    self.data = data
                    calls.append({"linear_solver": kwargs["linear_solver"],
                                  "n": len(data["c"]), "rows": len(data["b"]),
                                  "time_limit": kwargs["time_limit_secs"]})
                    self.native = real_scs(data, cone, **kwargs)
                def solve(self, **kwargs):
                    self_outer.assertEqual(set(kwargs), {"warm_start", "x"})
                    self_outer.assertIs(type(kwargs["warm_start"]), bool)
                    if kwargs["warm_start"]:
                        self_outer.assertEqual(len(kwargs["x"]), len(self.data["c"]))
                    calls[-1]["warm_start"] = kwargs["warm_start"]
                    return self.native.solve(**kwargs)
            self_outer = self
            with patch.object(numerical.scs, "SCS", Tracked):
                result = self.solve(c, backend)
            self.assert_interval(c, result, F(3, 2))
            self.assertTrue(any(row["active_triangles"] for row in result["rounds"]))
            self.assertFalse(calls[0]["warm_start"])
            self.assertTrue(any(x["warm_start"] for x in calls[1:]))
            self.assertEqual({x["n"] for x in calls}, {10})
            self.assertGreater(max(x["rows"] for x in calls), calls[0]["rows"])
            self.assertEqual({x["linear_solver"] for x in calls},
                             {"qdldl" if backend == "direct" else "cpu_indirect"})
            self.assertTrue(all(x["time_limit"] > 0 for x in calls))

    def test_triangle_orientation_limits_and_already_active(self):
        y = np.eye(4)
        y[0, 1:] = y[1:, 0] = 1
        answer = numerical.separate_triangles(y, limit=2)
        self.assertEqual(answer["add"], [(1, 0, 2), (1, 0, 3)])
        self.assertEqual(answer["new_violations_above_threshold"], 3)
        self.assertEqual(answer["maximum_raw_violation"], 1)
        self.assertEqual(numerical.separate_triangles(y, active={(1, 0, 2)}, limit=2)["add"],
                         [(1, 0, 3), (2, 0, 3)])
        for n in (1, 2):
            self.assertEqual(numerical.separate_triangles(np.eye(n))["add"], [])

    def test_no_native_proposal_preserves_nonfinite_info_and_checkpoint(self):
        c = ((F(), F(1)), (F(1), F()))
        records = []
        class NoProposal:
            def __init__(self, data, cone, **settings):
                self.data = data
            def solve(self, **kwargs):
                return {"x": np.full(len(self.data["c"]), np.nan),
                        "y": np.full(len(self.data["b"]), np.nan),
                        "s": np.full(len(self.data["b"]), np.nan),
                        "info": {"status_val": -7, "status": "infeasible_inaccurate",
                                 "iter": 1, "pobj": np.float64(float("inf")),
                                 "solve_time": 0.0, "setup_time": 0.0}}
        with patch.object(numerical.scs, "SCS", NoProposal):
            result = numerical.solve_component(c, backend="direct", width_target=F(1, 1000),
                deadline=time.perf_counter() + 10, stage=runtime.Ledger().measure,
                policy=POLICY, progress=lambda i, p, m: records.append((i, p, m)))
        self.assertEqual(result["status"], "no_finite_solver_proposal")
        self.assertIsNone(result["interval"])
        self.assertIsNone(records[0][1])
        info = records[0][2]["solver_info"]
        self.assertEqual(info["pobj"], {"diagnostic_type": "nonfinite_float", "value": "inf"})
        json.dumps(info, allow_nan=False)

    def test_nonfinite_native_matrix_is_archived_before_unresolved_return(self):
        c = ((F(), F(1)), (F(1), F()))
        original_build = numerical.build_problem
        records = []
        def build(*args, **kwargs):
            built = list(original_build(*args, **kwargs))
            real_problem, variable = built[0], args[1]
            class Wrapper:
                def get_problem_data(self, solver):
                    return real_problem.get_problem_data(solver)
                def unpack_results(self, *values):
                    real_problem.unpack_results(*values)
                    variable._value = np.full((2, 2), np.nan)
            built[0] = Wrapper()
            return built
        with patch.object(numerical, "build_problem", build):
            result = numerical.solve_component(c, backend="direct", width_target=F(1, 1000),
                deadline=time.perf_counter() + 10, stage=runtime.Ledger().measure,
                policy=POLICY, progress=lambda i, p, m: records.append((i, p, m)))
        self.assertEqual(result["status"], "nonfinite_solver_proposal")
        self.assertTrue(np.isnan(records[0][1]["matrix"]).all())
        self.assertEqual(records[0][2]["nonfinite_proposal"], True)
        self.assertEqual(len(result["raw"]), 1)

    def test_runtime_exact_components_quotient_lift_and_common_cost(self):
        graph = nx.Graph()
        graph.add_nodes_from(range(4))
        graph.add_edge(0, 1, weight=2)
        graph.add_edge(2, 3, weight=1)
        case = {"case_id": "engineering-four-node", "gamma": "1/2"}
        for arm in ("U", "D"):
            path = directory("runtime-" + arm)
            actual_bank = runtime.candidate_bank
            with patch.object(runtime, "candidate_bank", wraps=actual_bank) as bank:
                record, results = runtime.run_arm(graph, case, arm, "direct", CONFIG, path,
                                                  wall_seconds=30, started_at=time.perf_counter())
            self.assertEqual(bank.call_count, 1)
            self.assertEqual(record["status"], "verified_target")
            self.assertLessEqual(F(record["lower_exact"]), F(13, 18))
            self.assertGreaterEqual(F(record["upper_exact"]), F(13, 18))
            self.assertEqual(F(record["S_exact"]), 6)
            self.assertEqual(sum(map(F, record["component_width_targets"]), F()), F(1, 1000))
            self.assertEqual(record["lift_validation"]["original_lifted_trace_exact"],
                             record["lower_exact"])
            self.assertGreater(record["stage_seconds"]["common_discovery_and_bank"], 0)
            self.assertGreater(record["stage_seconds"]["checkpoint"], 0)
            self.assertGreaterEqual(record["unassigned_compute_seconds"], 0)
            prep = json.loads((path / "preprocessing.json").read_text())
            self.assertEqual(prep["bank_sha256"], record["bank_sha256"])
            self.assertEqual(prep["membership"], record["membership"])
            self.assertEqual(prep["S_exact"], "6")
            self.assertEqual(prep["components"], [])
            if arm == "U":
                self.assertTrue(all(not x["analytic"] for x in results))
            else:
                self.assertEqual(record["quotient_n"], 2)
                self.assertTrue(all(x["analytic"] for x in results))
                self.assertNotIn("solver", record["stage_seconds"])
            freeze.write_once(path / "completed-engineering-record.json", record)

    def test_runtime_terminal_status_preservation_and_no_false_bounds(self):
        graph = nx.Graph()
        graph.add_edge(0, 1, weight=1)
        path = directory("terminal-native")
        info = {"status": "diagnostic-only", "pobj": {"diagnostic_type": "nonfinite_float", "value": "nan"}}
        def missing(c, *, progress, **kwargs):
            self.assertTrue((path / "preprocessing.json").exists())
            progress(0, None, {"status": "no_finite_solver_proposal", "solver_info": info})
            return {"status": "no_finite_solver_proposal", "raw": [], "rounds": [],
                    "interval": None, "solver_info": info, "unpack_error": "fixture diagnostic"}
        with patch.object(runtime, "solve_component", missing):
            record, _ = runtime.run_arm(graph, {"case_id": "engineering-no-proposal", "gamma": "1/2"},
                                        "U", "direct", CONFIG, path,
                                        wall_seconds=10, started_at=time.perf_counter())
        self.assertEqual(record["status"], "incomplete_component_bounds")
        self.assertNotIn("upper_exact", record)
        self.assertEqual(record["components"][0]["terminal_solver_info"], info)
        self.assertEqual(record["components"][0]["terminal_unpack_error"], "fixture diagnostic")
        self.assertTrue((path / "component-000-round-000-metrics.json").exists())

    def test_exact_original_loops_and_invalid_quotient_rejected(self):
        a = sparse.csr_matrix([[3, 2, 0], [2, 1, 1], [0, 1, 4]])
        _, c, d, total = runtime.coefficient_matrix(a, F(2, 3))
        self.assertEqual(d, (F(5), F(4), F(5)))
        self.assertEqual(total, 14)
        quotient = sparse.csr_matrix([[8, 1], [1, 4]])
        _, cq, dq, tq = runtime.coefficient_matrix(quotient, F(2, 3))
        runtime.validate_quotient(c, cq, [0, 0, 1], d, dq, total, tq)
        bad = [list(row) for row in cq]
        bad[0][0] += F(1, 100)
        with self.assertRaises(ArithmeticError):
            runtime.validate_quotient(c, bad, [0, 0, 1], d, dq, total, tq)
        with self.assertRaises(ArithmeticError):
            runtime.validate_quotient(c, cq, [1, 1, 0], d, dq, total, tq)

    def test_deadline_prevents_native_call(self):
        with patch.object(numerical.scs, "SCS") as solver:
            with self.assertRaises(numerical.BudgetExpired):
                numerical.solve_component(((F(), F(1)), (F(1), F())), backend="direct",
                    width_target=F(1, 1000), deadline=time.perf_counter() - 1,
                    stage=runtime.Ledger().measure, policy=POLICY)
            solver.assert_not_called()

    def test_exclusive_atomic_json_preserves_first_and_failed_partial(self):
        path = directory("exclusive-json") / "marker.json"
        freeze.write_once(path, {"first": 1})
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            freeze.write_once(path, {"second": 2})
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(json.loads(path.with_name(path.name + ".partial").read_text()), {"second": 2})

    def watchdog(self, actor, *, wall=0.15, rss=2 ** 30, init=0.3):
        path = directory("watchdog")
        script = path / "actor.py"
        script.write_text(actor)
        config = {"pilot": {"rss_bytes": rss, "wall_seconds": wall},
                  "watchdog": {"initialization_limit_seconds": init,
                               "terminate_then_kill_seconds": 0.2, "sampling_seconds": 0.02}}
        leader = None
        try:
            with (path / "actor.log").open("xb") as log:
                result = supervise([sys.executable, "-B", str(script), str(path)], path, config, log)
            if (path / "leader.json").exists():
                leader = json.loads((path / "leader.json").read_text())["pid"]
            if (path / "descendant.json").exists():
                pid = json.loads((path / "descendant.json").read_text())["pid"]
                running = False
                for _ in range(50):
                    try:
                        descendant = psutil.Process(pid)
                        running = descendant.is_running() and descendant.status() != psutil.STATUS_ZOMBIE
                    except psutil.NoSuchProcess:
                        running = False
                    if not running:
                        break
                    time.sleep(0.01)
                # Capture BEFORE the fixture's finally cleanup, or the test
                # could conceal a broken supervisor by doing its work for it.
                result["descendant_running_before_fixture_cleanup"] = running
            freeze.write_once(path / "monitoring.json", result)
            self.assertLess(result["process_wall_seconds_including_import_input_output"], 3)
            self.assertGreater(result["monitored_peak_RSS_bytes"], 0)
            return path, result
        finally:
            if leader is None and (path / "leader.json").exists():
                leader = json.loads((path / "leader.json").read_text())["pid"]
            if leader is not None:
                try:
                    os.killpg(leader, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_watchdog_kills_descendant_when_leader_exits_on_sigterm(self):
        actor = """import json,os,pathlib,subprocess,sys,time
p=pathlib.Path(sys.argv[1])
(p/'leader.json').write_text(json.dumps({'pid':os.getpid()}))
child=p/'descendant.py'
child.write_text('import json,os,pathlib,signal,sys,time\\np=pathlib.Path(sys.argv[1])\\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\\n(p/\"descendant.json\").write_text(json.dumps({\"pid\":os.getpid()}))\\ntime.sleep(30)\\n')
subprocess.Popen([sys.executable,'-B',str(child),str(p)])
while not (p/'descendant.json').exists(): time.sleep(.005)
(p/'timer-start.json').write_text(json.dumps({'perf_counter':time.perf_counter()}))
print('engineering descendant ready',flush=True)
time.sleep(30)
"""
        path, result = self.watchdog(actor)
        self.assertEqual(result["limit_reason"], "full_wall_limit")
        self.assertFalse(result["descendant_running_before_fixture_cleanup"],
                         "live descendant survived process-group hard kill")
        self.assertIn("engineering descendant ready", (path / "actor.log").read_text())

    def test_watchdog_initialization_rss_and_final_serialization_limits(self):
        preamble = "import json,os,pathlib,sys,time\np=pathlib.Path(sys.argv[1])\n(p/'leader.json').write_text(json.dumps({'pid':os.getpid()}))\n"
        _, result = self.watchdog(preamble + "time.sleep(30)\n", init=0.1)
        self.assertEqual(result["limit_reason"], "initialization_limit")
        _, result = self.watchdog(preamble + "time.sleep(30)\n", rss=1)
        self.assertEqual(result["limit_reason"], "rss_limit")
        finish = "(p/'timer-start.json').write_text(json.dumps({'perf_counter':time.perf_counter()}))\n(p/'compute-finished.json').write_text(json.dumps({'perf_counter':time.perf_counter()-61}))\ntime.sleep(30)\n"
        _, result = self.watchdog(preamble + finish)
        self.assertEqual(result["limit_reason"], "final_serialization_limit")

    def test_fixed_six_jobs_eligibility_penalties_tie_and_failure_gate(self):
        jobs = pilot_schedule(CONFIG)
        self.assertEqual(len(jobs), 6)
        self.assertEqual({row["arm"] for row in jobs}, {"U"})
        self.assertEqual([row["backend"] for row in jobs],
                         ["direct", "indirect", "indirect", "direct", "direct", "indirect"])
        entries = [{**job, "credited_verified_target": True, "full_compute_seconds": 1}
                   for job in jobs]
        winner, _ = select_backend(entries, CONFIG)
        self.assertEqual(winner, "direct")
        entries[-2]["credited_verified_target"] = False
        entries[-2]["full_compute_seconds"] = None
        winner, sums = select_backend(entries, CONFIG)
        self.assertEqual(winner, "indirect")
        self.assertEqual(sums["direct"]["selection_cost_with_unresolved_penalty"], 182)
        entries[-1]["credited_verified_target"] = False
        self.assertIsNone(select_backend(entries, CONFIG)[0])

    def test_hash_environment_gate_rejects_drift(self):
        path = directory("synthetic-freeze-contract")
        config_path = path / "config.json"
        frozen_path = path / "fixture-freeze.json"
        freeze.write_once(config_path, CONFIG)
        frozen = {"status": "frozen_for_six_bounded_U_only_pilot_jobs",
                  "config_sha256": freeze.sha256(config_path),
                  "runtime_source_sha256": freeze.runtime_sources(),
                  "environment": freeze.environment(),
                  "required_artifact_sha256": {str(Path(__file__).resolve().relative_to(freeze.ROOT)):
                                                freeze.sha256(__file__)}}
        freeze.write_once(frozen_path, frozen)
        freeze.validate(config_path, frozen_path)
        for field in ("status", "config_sha256", "runtime_source_sha256", "environment",
                      "required_artifact_sha256"):
            altered = deepcopy(frozen)
            if field in ("status", "config_sha256"):
                altered[field] = "engineering-corruption"
            elif field == "runtime_source_sha256":
                altered[field][next(iter(altered[field]))] = "0" * 64
            elif field == "environment":
                altered[field]["versions"]["scs"] = "wrong"
            else:
                altered[field][next(iter(altered[field]))] = "0" * 64
            tamper = path / (field + ".json")
            freeze.write_once(tamper, altered)
            with self.assertRaises(ValueError):
                freeze.validate(config_path, tamper)
        with patch.dict(os.environ, {"OMP_NUM_THREADS": "2"}):
            with self.assertRaises(ValueError):
                freeze.validate(config_path, frozen_path)
        with patch.object(sys.modules["experiments.pipeline"], "__file__", __file__):
            with self.assertRaisesRegex(ValueError, "actual imported source differs"):
                freeze.validate(config_path, frozen_path)
        changed_config = deepcopy(CONFIG)
        changed_config["solver"]["backend"] = "direct"
        changed_path = path / "preselected-backend-config.json"
        freeze.write_once(changed_path, changed_config)
        changed_freeze = deepcopy(frozen)
        changed_freeze["config_sha256"] = freeze.sha256(changed_path)
        changed_freeze_path = path / "preselected-backend-freeze.json"
        freeze.write_once(changed_freeze_path, changed_freeze)
        with self.assertRaisesRegex(ValueError, "cannot silently choose"):
            freeze.validate(changed_path, changed_freeze_path)


if __name__ == "__main__":
    unittest.main()
