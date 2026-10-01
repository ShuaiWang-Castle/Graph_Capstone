"""Read-only checks of all 12 integration records; writes only audit summaries."""
from pathlib import Path
import gzip
import json
import math
import sys
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.common import sha, stamp

FOLDER = ROOT / 'reviews/baselines/integration_v12'


def main():
    manifest = json.loads((FOLDER / 'manifest.json').read_text())
    protocol = yaml.safe_load((ROOT / 'experiments/protocol_v12.yaml').read_text())
    acquisition = json.loads((ROOT / 'provenance/baselines/acquisition.json').read_text())
    checks, details, failures = [], [], []

    def check(name, condition, evidence=None):
        row = {'check': name, 'passed': bool(condition)}
        if evidence is not None:
            row['evidence'] = evidence
        checks.append(row)
        if not condition:
            failures.append(row)

    check('exactly_12_jobs', len(manifest['jobs']) == 12)
    check('frozen_protocol_unchanged', sha(ROOT / 'experiments/protocol_v12.yaml') == manifest['protocol_sha256'])
    changed = [p for p, d in manifest['source_sha256'].items() if sha(ROOT / p) != d]
    check('all_frozen_sources_unchanged', not changed, changed)
    check('runner_unchanged', sha(ROOT / 'experiments/baseline_integration/run_smoke.py') == manifest['runner_sha256'])
    masses = []
    mass = 3 * 55.0
    while mass <= 25326.0 / 2:
        masses.append(mass)
        mass *= 2
    oracle = 6439.0
    for jobpath in manifest['jobs']:
        job = json.loads((ROOT / jobpath).read_text())
        name = job['task']
        dest = ROOT / job['result_path']
        check(name + ':raw_exists', dest.is_file())
        if not dest.is_file():
            failure = dest.with_suffix('.failure.json')
            details.append({'task': name, 'failure_record': str(failure.relative_to(ROOT)),
                            'failure': json.loads(failure.read_text()) if failure.exists() else 'MISSING'})
            continue
        r = json.loads(gzip.decompress(dest.read_bytes()))
        a = r.get('result')
        check(name + ':completed_without_error', r['status'] == 'COMPLETED' and r['error_trace'] is None
              and r.get('completion_claim') is True)
        if a is None:
            details.append({'task': name, 'error_trace': r.get('error_trace')})
            continue
        method, setting = job['method'], job['setting']
        m = a.get('metadata', {})
        expected_oracle = oracle if setting == 'oracle' else None
        check(name + ':only_explicit_oracle_scalar', r['oracle_volume'] == expected_oracle
              and r['truth_in_method_path'] == (expected_oracle is not None)
              and 'truth_vertices' not in r['input'] and 'communities' not in r['input']
              and not any(k in job['configuration'] for k in ('truth', 'truth_vertices', 'communities', 'labels')))
        check(name + ':record_identity', r['method'] == method and r['setting'] == setting
              and r['seed'] == 18 and r['source_sha256'] == manifest['source_sha256']
              and r['protocol_sha256'] == manifest['protocol_sha256']
              and r['configuration'] == job['configuration']
              and r['measurement_role'] == manifest['measurement_role'])
        check(name + ':actual_worker_command', r['command'] == ['.venv/bin/python', 'experiments/worker.py', '--job', jobpath])
        check(name + ':worker_logs_present', all((FOLDER / 'logs' / (name + suffix)).is_file()
              for suffix in ('.stdout.log', '.stderr.log')))
        check(name + ':valid_return_schema', a['vertices'] == sorted(set(a['vertices']))
              and all(type(v) is int and 0 <= v < 400 for v in a['vertices'])
              and isinstance(a['touched_vertices'], list)
              and a['touched_vertices'] == sorted(set(a['touched_vertices']))
              and all(type(v) is int and 0 <= v < 400 for v in a['touched_vertices'])
              and math.isfinite(a['runtime_seconds']) and a['runtime_seconds'] >= 0)
        check(name + ':outer_cost_finite', math.isfinite(r['outer_wall_seconds'])
              and r['outer_wall_seconds'] >= a['runtime_seconds']
              and r['peak_rss_bytes_sampled_process_and_children'] > 0)
        ts = m.get('trials', [])
        expected_masses = [3 * oracle] if setting == 'oracle' else masses
        native_logs = None
        if method in ('hfd', 'hfd_cd', 'pnorm'):
            check(name + ':complete_mass_grid', m['mass_grid'] == expected_masses
                  and [t['mass'] for t in ts] == expected_masses and m['mass_grid_complete'] is True)
        if method in ('hfd', 'pnorm'):
            execution = m['execution']
            receiptpath = ROOT / execution['logs']['execution']
            receipt = json.loads(receiptpath.read_text())
            native_logs = execution['logs']
            check(name + ':successful_native_receipt', execution['status'] == 'COMPLETED'
                  and execution['returncode'] == 0 and receipt['status'] == 'COMPLETED'
                  and receipt['returncode'] == 0 and receipt['complete_json_records'] == len(expected_masses)
                  and not receipt['json_parse_errors'])
            check(name + ':native_actual_command_and_hashes', bool(receipt['actual_command'])
                  and receipt['driver_sha256'] == sha(ROOT / 'zrhfd/baselines/native_driver.jl')
                  and len(receipt['input_edge_csv_sha256']) == 64
                  and receipt['sources'] == m['sources']
                  and receipt['stdout_sha256'] == sha(ROOT / execution['logs']['stdout'])
                  and receipt['stderr_sha256'] == sha(ROOT / execution['logs']['stderr']))
            check(name + ':native_budget_not_convergence_claim', m['max_iterations'] == 50
                  and m['mass_grid_complete'] and a['touched_vertices'] == list(range(400)))
        if 'repository' in m.get('sources', {}):
            source = m['sources']
            pinned = next(v for v in acquisition['repositories'].values() if v['url'] == source['repository'])
            check(name + ':primary_source_pin', source['commit'] == pinned['commit'] and all(
                  digest == pinned['tracked_worktree_file_sha256'][path]
                  and sha(ROOT / pinned['path'] / path) == digest for path, digest in source['files'].items()))
        if method == 'hfd_cd':
            check(name + ':independent_high_accuracy_control_identity', 'not author' in m['identity']
                  and m['objective'] == 'same frozen HFD graph quadratic dual'
                  and job['configuration']['identity'] == 'high_accuracy_same_objective_control_not_author_execution_algorithm'
                  and all(t['diffusion']['queue_pending'] == 0 for t in ts)
                  and max(t['diffusion']['scaled_kkt_residual'] for t in ts) <= 1e-8)
        if method == 'tlhfd':
            fractions = protocol['baseline_configs']['tlhfd']['fraction_grid']
            expected = [(mass, f) for mass in expected_masses for f in fractions]
            check(name + ':full_paper_fraction_and_mass_grid', m['mass_grid'] == expected_masses
                  and [(t['mass'], t['fraction']) for t in ts] == expected and m['mass_grid_complete'] is True)
            check(name + ':algorithm1_numba_request_finished', m['backend'] == 'numba'
                  and m['step_schedule'] == 'constant' and m['step_size'] == .25
                  and m['return_policy'] == 'best_dual' and not m['fastmath'] and not m['parallel']
                  and all(t['updates'] == 1000 and t['stop'] == 'fixed_iterations'
                          and len(t['trace']) == 1000 and t['selected_iteration'] < 1000 for t in ts)
                  and m['update_count'] == len(ts) * 1000)
            check(name + ':TL_source_identity', m['sources']['version'] == '2606.09340v1'
                  and 'independent Algorithm1 port' in m['sources']['implementation_identity'])
        if method == 'acl':
            scales = [oracle] if setting == 'oracle' else masses
            expected = [(alpha, 1 / scale) for alpha in protocol['baseline_configs']['acl']['alpha_grid'] for scale in scales]
            check(name + ':full_alpha_and_rho_grid', [(t['alpha'], t['rho']) for t in ts] == expected)
            check(name + ':residual_stop', all(t['stop'] == 'residual_tolerance'
                  and t['max_residual_degree_ratio'] <= t['rho'] + 1e-12
                  and t['mass_conservation_residual'] < 1e-10 for t in ts))
        if method == 'leiden':
            check(name + ':global_native_identity', setting == 'global'
                  and m['oracle_volume_used'] is False and m['iterations_requested'] == -1
                  and m['resolution'] == 1 and m['random_seed'] == 73
                  and a['touched_vertices'] == list(range(400)))
        if method == 'zrhfd':
            trace = a['diffusion_trace']
            check(name + ':main_grid_and_supplement', a['mass_sequence'] == masses + [2 * masses[-1]]
                  and a['j_act'] == 5 and a['j_star'] == 6 and a['stop_reason'] == 'mass_budget'
                  and trace[-1]['supplement_for_region'] is True
                  and all(t['queue_pending'] == 0 for t in trace))
            check(name + ':region_certificate_cover_telemetry', 'truth_covered' in r['evaluation']
                  and set(a['vertices']) <= set(a['region_vertices'])
                  and set(a['S0']) <= set(a['region_vertices']) and 18 in a['region_vertices']
                  and math.isfinite(a['certificate']['gap']) and a['certificate']['gap'] >= -1e-10
                  and all(k in a['certificate'] for k in ('LB_R', 'oracle_trace', 'hull_best', 'certificate_status')))
            check(name + ':progress_checkpoint', (ROOT / (job['result_path'] + '.checkpoint.json')).is_file())
        details.append({'task': name, 'method': method, 'setting': setting,
            'status': r['status'], 'trials': len(ts), 'output_contains_seed': r['output_contains_seed'],
            'outer_wall_seconds_engineering_only': r['outer_wall_seconds'],
            'kernel_seconds_total': m.get('kernel_seconds_total'),
            'stop': m.get('stop', a.get('stop_reason')),
            'touched_definition': m.get('touched_definition', 'frozen diffusion support union region'),
            'frozen_support_union_known': method in ('zrhfd', 'hfd_cd', 'tlhfd'),
            'native_logs': native_logs, 'raw_sha256': sha(dest),
            'max_scaled_kkt_residual': max((t.get('diffusion', {}).get('scaled_kkt_residual', 0) for t in ts), default=0)
                if method == 'hfd_cd' else None})
    check('no_outer_failures', not list((FOLDER / 'raw').glob('*.failure.json')))
    timeoutfixtures = [json.loads(line) for line in (ROOT / 'reviews/baselines/smoke_records.jsonl').read_text().splitlines()
                      if 'actual_subprocess_timeout_retention' in line]
    check('previous_actual_timeout_logs_retained', bool(timeoutfixtures) and all(
          r['passed'] and r['execution']['status'] == 'TIMEOUT'
          and all((ROOT / p).is_file() for p in r['execution']['logs'].values()) for r in timeoutfixtures))
    result = {'audited_utc': stamp(), 'measurement_role': manifest['measurement_role'],
              'manifest_sha256': sha(FOLDER / 'manifest.json'),
              'audit_source_sha256': sha(Path(__file__)), 'status': 'PASS' if not failures else 'FAIL',
              'check_count': len(checks), 'failure_count': len(failures), 'checks': checks,
              'configurations': details, 'failures': failures,
              'quality_analysis': 'none; no F1 values used or compared',
              'timeout_scope': '12 current jobs finished; previous artificial actual subprocess timeout confirms log retention; outer task kill not exercised here'}
    (FOLDER / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(result['status'], result['check_count'], 'checks', result['failure_count'], 'failures')
    for failure in failures:
        print(failure)
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
