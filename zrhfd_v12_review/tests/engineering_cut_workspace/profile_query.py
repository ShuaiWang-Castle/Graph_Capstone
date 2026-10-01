"""Explicit matched topology/query profile in a separate engineering subprocess.

Never loads labels or updates formal source/manifests. Run literal and prepared
on the same --request with separate output directories after CPU-slot approval.
"""
from pathlib import Path
from dataclasses import asdict
import argparse
import hashlib
import json
import runpy
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, allow_nan=False)
        stream.write('\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--backend', choices=('literal', 'prepared'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compare-to', type=Path)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if not output.resolve().is_relative_to((ROOT / 'reviews/performance_cut_workspace').resolve()):
        raise ValueError('Engineering output must remain in reviews/performance_cut_workspace')
    output.mkdir(parents=True, exist_ok=False)
    request = json.loads(args.request.read_text())
    write_new(output / 'execution_request.json', {'actual_command': [sys.executable, *sys.argv],
        'request_sha256': digest(args.request), 'backend': args.backend,
        'role': 'matched_engineering_profile_not_formal_quality_or_cost',
        'prototype_sha256': digest(ROOT / 'zrhfd/experimental_cut_workspace.py'),
        'reference_source_sha256': {p: digest(ROOT / p) for p in ('zrhfd/mincut.py', 'zrhfd/certificate.py', 'zrhfd/pipeline.py', 'work/bin/mincut128')},
        'truth_policy': 'request offline fields never loaded or evaluated'})
    sys.path.insert(0, str(ROOT / 'experiments/m6'))
    worker = runpy.run_path(str(ROOT / 'experiments/m6/worker.py'), run_name='engineering_m6_warmup')
    from zrhfd.pipeline import Config, run
    from zrhfd.storage import load_csr
    from zrhfd.experimental_cut_workspace import installed_workspace
    cfg = Config(**{**request['method_config'], 'fixed_grid': tuple(request['method_config']['fixed_grid'])})
    if json.loads(json.dumps(asdict(Config()))) != request['method_config']:
        raise RuntimeError('This profile accepts only the exact frozen main Config')
    def checkpoint(event):
        with (output / 'progress.jsonl').open('a') as stream:
            stream.write(json.dumps(event, allow_nan=False) + '\n')
    try:
        # Signature-matched unlabeled warmup exactly as in the frozen M6 worker.
        _, warm = worker['warmup'](output / 'toy_csr', cfg, checkpoint)
        query = request['query']
        metadata = ROOT / query['csr_path'] / 'csr_metadata.json'
        if digest(metadata) != query['csr_metadata_sha256']:
            raise RuntimeError('Authorized real-query CSR metadata changed')
        loaded = time.perf_counter()
        graph = load_csr(metadata, verify_hashes=False)
        input_seconds = time.perf_counter() - loaded
        started = time.perf_counter()
        if args.backend == 'prepared':
            with installed_workspace() as dispatcher:
                result = run(graph, query['seed'], cfg, progress=checkpoint)
                workspace = dispatcher.summary()
        else:
            result = run(graph, query['seed'], cfg, progress=checkpoint)
            workspace = []
        elapsed = time.perf_counter() - started
        comparison = None
        if args.compare_to:
            old = json.loads(args.compare_to.read_text())
            reference = old['raw_output']
            keys = ('vertices', 'S0', 'region_vertices', 'j_act', 'j_star', 'mass_sequence', 'stop_reason')
            mismatches = [k for k in keys if reference[k] != result[k]]
            certificate_keys = ('LB_R', 'LB_R_upper', 'LB_R_lower_decimal', 'LB_R_upper_decimal', 'hull_vertices', 'hull_best', 'hull_best_Z_exact', 'gap', 'mincut_calls')
            mismatches.extend('certificate.' + k for k in certificate_keys if reference['certificate'][k] != result['certificate'][k])
            old_steps = [(s['Z_before_exact'], s['Z_proposed_exact'], s['mincut_objective_exact'], s['vertices'], s['accepted']) for s in reference['mm_trace']]
            new_steps = [(s['Z_before_exact'], s['Z_proposed_exact'], s['mincut_objective_exact'], s['vertices'], s['accepted']) for s in result['mm_trace']]
            if old_steps != new_steps:
                mismatches.append('mm_exact_trajectory')
            comparison = {'same_query_id': old['query_id'] == request['query_id'], 'mismatches': mismatches,
                          'passed': old['query_id'] == request['query_id'] and not mismatches}
            if not comparison['passed']:
                raise RuntimeError('Matched prototype changed frozen semantics: ' + str(comparison))
        write_new(output / 'result.json', {'status': 'COMPLETED',
            'role': 'matched_engineering_profile_not_formal_quality_or_cost',
            'query_id': request['query_id'], 'seed': query['seed'], 'backend': args.backend,
            'method_hot_wall_seconds_engineering_only': elapsed, 'input_load_seconds': input_seconds,
            'warmup': warm, 'workspaces': workspace, 'comparison': comparison, 'raw_output': result})
        print(json.dumps({'backend': args.backend, 'query_id': request['query_id'], 'engineering_wall_seconds': elapsed, 'comparison': comparison}))
    except BaseException:
        write_new(output / 'error.json', {'status': 'FAILED', 'traceback': traceback.format_exc()})
        raise


if __name__ == '__main__':
    main()
