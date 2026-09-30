#!/usr/bin/env python3
"""Freeze separate diagnostic jobs without editing the initial measurement plan."""
from pathlib import Path
import argparse, copy, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.io import read_json, write_json, sha256


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline-plan', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    base = read_json(a.baseline_plan)
    jobs_by_id = {j['job_id']: j for j in base['jobs']}
    output = Path(a.output).resolve()
    cfg_dir = output.parent / 'job_configs'
    jobs = []
    small = 'lfr_n1000_o40_m50_s12'
    large = 'lfr_n5000_o40_m50_s11'
    for case in [small, large]:
        for method, tool, extra in [
            ('highway_python', 'highway_trace_runner.py', ['--profile']),
            ('nocd_graph_oracleK', 'nocd_kernel_profile_runner.py', [])]:
            original_id = f'{case}__{method}__s73'
            job = copy.deepcopy(jobs_by_id[original_id])
            job['job_id'] += '__diagnostic_v1'
            job['diagnostic_only'] = True
            job['method'] += '__diagnostic_profile'
            tool_path = ROOT / 'work/setup/trace_tools' / tool
            job['source_hashes'][str(tool_path)] = sha256(tool_path)
            job['command'] = ['{python}', str(tool_path), '--plan', str(Path(a.baseline_plan).resolve()),
                              '--job-id', original_id]
            if method == 'highway_python':
                job['command'] += ['--output-dir', '{run_dir}/trace', '--prediction-output', '{output}'] + extra
            else:
                job['command'] += ['--output', '{output}']
            jobs.append(job)
    for method in ['ego_karateclub', 'ego_karateclub_loopless_fix']:
        original_id = f'{small}__{method}__s73'
        job = copy.deepcopy(jobs_by_id[original_id])
        job['job_id'] += '__diagnostic_v1'
        job['method'] += '__diagnostic_trace'
        job['diagnostic_only'] = True
        cfg = read_json(job['config'])
        cfg['detailed_trace'] = True
        config_path = cfg_dir / (job['job_id'] + '.json')
        if config_path.exists() and read_json(config_path) != cfg:
            raise ValueError('Refuse to edit a diagnostic config')
        write_json(config_path, cfg)
        job['config'] = str(config_path)
        job['config_sha256'] = sha256(config_path)
        jobs.append(job)
    plan = {
        'purpose': 'DIAGNOSTIC_ONLY_NOT_FORMAL_SPEED_COMPARISON_NOT_A_CANDIDATE',
        'baseline_plan_sha256': sha256(a.baseline_plan),
        'catalog_sha256': base['catalog_sha256'], 'jobs': jobs,
        'measurement_gate': 'Run only after every initial baseline job has a terminal result and initial runner is no longer live.',
        'selection_reason': 'Prespecified two sizes of overlapping mu=.5 development graphs; detailed inspection of existing failures, not a confirmation set.',
        'profile_cost_policy': 'All diagnostic process costs count in round wall budget; never replace baseline latency.'}
    if output.exists() and read_json(output) != plan:
        raise ValueError('Use a new version rather than changing a frozen diagnostic plan')
    write_json(output, plan)
    print(f'{len(jobs)} diagnostic jobs frozen; no algorithms executed')


if __name__ == '__main__':
    main()
