#!/usr/bin/env python3
"""Portable immutable-record index, compact materialization and offline scoring.

Build/materialize/verify use the standard library. Evaluate additionally requires
the recorded NumPy/SciPy runtime and hash-pinned original lab scorer. This tool
never trains or invokes a graph community algorithm.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile

SCHEMA = 'community_portable_replay_index_v1'
TERMINAL = {'COMPLETED', 'TIMEOUT', 'MEMORY_LIMIT', 'ERROR', 'LAUNCH_ERROR', 'LOG_LIMIT', 'INTERRUPTED', 'INVALID_OUTPUT', 'BLOCKED', 'NOT_RUN_BUDGET'}
SIMPLE_ID = re.compile(r'^[A-Za-z0-9_.-]+$')
THREAD_VARIABLES = ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS']
SUMMARY_METRICS = {
    'matched_macro_f1': 'matched_macro_f1',
    'matched_membership_micro_f1': 'matched_membership_micro.f1',
    'overlap_f1': 'overlap_node.f1',
    'extra_membership_recall': 'extra_membership_after_first.recall',
    'predicted_groups': 'predicted_groups',
    'at_least_two_correct_recall': 'at_least_two_correct_recall',
    'small_group_mean_matched_f1': 'small_group_mean_matched_f1',
    'small_group_size_cutoff': 'small_group_size_cutoff',
    'pred_node_coverage': 'pred_node_coverage',
}
for _kind in ['overlap_node', 'extra_membership_after_first']:
    for _stat in ['precision', 'recall', 'f1']:
        SUMMARY_METRICS[_kind + '_' + _stat] = _kind + '.' + _stat


class IntegrityError(ValueError):
    pass


def safe_relative(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or '\x00' in value:
        raise IntegrityError('Invalid portable path: ' + repr(value))
    parts = value.split('/')
    if value.startswith('/') or any(p in ('', '.', '..') for p in parts):
        raise IntegrityError('Traversal/noncanonical path rejected: ' + repr(value))
    return str(PurePosixPath(value))


def under(root, value):
    relative = safe_relative(value)
    root = Path(root).resolve()
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        path.resolve().relative_to(root)
    except ValueError:
        raise IntegrityError('Symlink escapes extracted root: ' + relative)
    return path


def source_relative(root, value):
    root = Path(root).resolve()
    path = Path(value)
    if path.is_absolute():
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            raise IntegrityError('Original absolute path outside source root: ' + str(path))
    else:
        relative = safe_relative(str(value))
    under(root, relative)
    return safe_relative(relative)


def hash_file(path):
    path = Path(path)
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise IntegrityError('File changed during read: ' + str(path))
    return h.hexdigest(), after.st_size


def read_json(path):
    with Path(path).open(encoding='utf-8') as f:
        return json.load(f, parse_constant=lambda s: (_ for _ in ()).throw(IntegrityError('Nonfinite JSON value: ' + s)))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def digest_valid(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def nested(obj, path):
    for part in path.split('.'):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def compare(expected, actual, tolerance=1e-12, at=''):
    """Compare saved score tree, including fixed Hungarian matching and None."""
    differences = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(expected) != set(actual):
            differences.append({'field': at, 'kind': 'key_set', 'expected': sorted(expected), 'actual': sorted(actual)})
        for key in sorted(set(expected) & set(actual)):
            differences.extend(compare(expected[key], actual[key], tolerance, at + '.' + key))
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            differences.append({'field': at, 'kind': 'length', 'expected': len(expected), 'actual': len(actual)})
        for i, (x, y) in enumerate(zip(expected, actual)):
            differences.extend(compare(x, y, tolerance, at + '[' + str(i) + ']'))
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
        if not math.isfinite(expected) or not math.isfinite(actual) or abs(expected - actual) > tolerance:
            differences.append({'field': at, 'kind': 'number', 'expected': expected, 'actual': actual})
    elif expected != actual:
        differences.append({'field': at, 'kind': 'value', 'expected': expected, 'actual': actual})
    return differences


class IndexBuilder:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.files = {}
        self.missing_files = {}

    def bind(self, value, expected=None, required_hash=False):
        if value is None:
            return None
        relative = source_relative(self.root, value)
        if required_hash and not digest_valid(expected):
            raise IntegrityError('Missing/invalid frozen hash: ' + relative)
        path = under(self.root, relative)
        if not path.is_file():
            self.missing_files[relative] = {'expected_sha256': expected, 'status': 'MISSING_AT_BUILD'}
            return None
        if relative not in self.files:
            digest, size = hash_file(path)
            self.files[relative] = {'sha256': digest, 'size_bytes': size}
        if expected is not None and self.files[relative]['sha256'] != expected:
            raise IntegrityError('Frozen hash mismatch: ' + relative)
        return relative

    def load_bound(self, value, **kwargs):
        relative = self.bind(value, **kwargs)
        return relative, None if relative is None else read_json(under(self.root, relative))

    def group(self, group):
        name = group['name']
        if not isinstance(name, str) or not SIMPLE_ID.fullmatch(name):
            raise IntegrityError('Invalid group name')
        plan_ref, plan = self.load_bound(group['plan'])
        if plan is None:
            raise IntegrityError('Missing group plan: ' + str(group['plan']))
        catalog_ref, cat = self.load_bound(group['catalog'], expected=plan.get('catalog_sha256'), required_hash=True)
        if cat is None:
            raise IntegrityError('Missing catalog')
        catalog = {c['case_id']: c for c in cat}
        if len(catalog) != len(cat):
            raise IntegrityError('Duplicate catalog case_id')
        analysis = source_relative(self.root, group['analysis'])
        run = source_relative(self.root, group['run_root'])
        results_ref, summary = self.load_bound(analysis + '/results.json')
        summary = summary or []
        by_id = {r['job_id']: r for r in summary}
        if len(by_id) != len(summary):
            raise IntegrityError('Duplicate summary job_id')
        ids = [j['job_id'] for j in plan['jobs']]
        if len(set(ids)) != len(ids):
            raise IntegrityError('Duplicate planned job_id')
        if any(not isinstance(x, str) or not SIMPLE_ID.fullmatch(x) for x in ids):
            raise IntegrityError('Invalid job_id path component')
        if set(by_id) - set(ids):
            raise IntegrityError('Summary contains unplanned jobs')
        csv_ref = self.bind(analysis + '/results.csv')
        csv_issues = []
        if csv_ref:
            with under(self.root, csv_ref).open(newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                csv_rows = list(reader)
                fields = reader.fieldnames
            if [r['job_id'] for r in csv_rows] != [r['job_id'] for r in summary] or any(any(c.get(k, '') != ('' if r.get(k) is None else str(r.get(k))) for k in fields) for c, r in zip(csv_rows, summary)):
                raise IntegrityError('Summary CSV/JSON disagree')
        else:
            csv_issues.append('MISSING_SUMMARY_CSV')
        stage_ref = self.bind(analysis + '/stage_records.json')
        output = {'name': name, 'plan': plan_ref, 'catalog': catalog_ref, 'summary_json': results_ref, 'summary_csv': csv_ref, 'stage_records': stage_ref, 'planned_jobs': len(ids), 'planned_case_ids': sorted({j['case_id'] for j in plan['jobs']}), 'issues': csv_issues, 'rows': []}
        for job in plan['jobs']:
            row = {'job_id': job['job_id'], 'case_id': job['case_id'], 'method': job['method'], 'information_policy': job.get('information_policy'), 'device': job.get('device'), 'threads': job.get('threads'), 'seed': job.get('seed'), 'original_summary': by_id.get(job['job_id']), 'measurement_status': None, 'prediction_kind': None, 'cost': {}, 'references': {}, 'issues': [], 'replay_eligibility': 'UNKNOWN'}
            refs = row['references']
            try:
                catalog_row = catalog[job['case_id']]
                directory = run + '/' + job['job_id']
                refs['spec'], spec = self.load_bound(directory + '/spec.json')
                refs['result'], result = self.load_bound(directory + '/result.json')
                refs['graph'] = self.bind(job['graph'], expected=job.get('graph_sha256'), required_hash=True)
                refs['truth'] = self.bind(catalog_row.get('truth'), expected=catalog_row.get('truth_sha256'), required_hash=True)
                refs['config'] = self.bind(job['config'], expected=job.get('config_sha256'), required_hash=True)
                refs['offline_details'], details = self.load_bound(analysis + '/per_job/' + job['job_id'] + '.json')
                refs['source_files'] = {source_relative(self.root, p): self.bind(p, expected=d, required_hash=True) for p, d in job.get('source_hashes', {}).items()}
                if any(v is None for v in refs['source_files'].values()):
                    row['issues'].append('MISSING_DECLARED_ALGORITHM_SOURCE')
                if spec is None:
                    row['issues'].append('MISSING_SPEC')
                elif spec != job:
                    raise IntegrityError('Immutable spec does not equal frozen plan')
                if result is None:
                    row['issues'].append('MISSING_RESULT')
                else:
                    row['measurement_status'] = result.get('status')
                    row['prediction_kind'] = result.get('prediction_kind')
                    row['cost'] = {k: result.get(k) for k in ['pipeline_seconds', 'monitor_elapsed_seconds', 'peak_tree_rss_bytes', 'sampled_tree_cpu_seconds', 'budget_seconds', 'original_timeout_s', 'returncode', 'timing_definition', 'resource_measurement']}
                    for k in ['job_id', 'case_id', 'method', 'information_policy', 'device', 'threads', 'seed']:
                        if k in result and result[k] != job.get(k):
                            raise IntegrityError('Raw result identity differs: ' + k)
                    for k in ['graph_sha256', 'config_sha256']:
                        if k in result and result[k] != job.get(k):
                            raise IntegrityError('Raw result frozen hash differs: ' + k)
                    if result.get('source_hashes') is not None and result['source_hashes'] != job.get('source_hashes', {}):
                        raise IntegrityError('Raw result source hashes differ')
                    refs['prediction'] = self.bind(result.get('prediction'), expected=result.get('prediction_sha256'), required_hash=bool(result.get('prediction')))
                    if row['measurement_status'] not in TERMINAL:
                        row['issues'].append('NONTERMINAL_OR_UNKNOWN_RESULT_STATUS')
                original = row['original_summary']
                if original is None:
                    row['issues'].append('MISSING_SUMMARY_ROW')
                elif result is not None:
                    for k in ['status', 'pipeline_seconds', 'peak_tree_rss_bytes', 'prediction_kind']:
                        if original.get(k) != result.get(k):
                            raise IntegrityError('Summary differs from raw measurement: ' + k)
                if details and 'metrics' in details:
                    provenance = details.get('evaluation_provenance', {})
                    bindings = [('graph_sha256', job.get('graph_sha256')), ('truth_sha256', catalog_row.get('truth_sha256'))]
                    if result is not None:
                        bindings.append(('prediction_sha256', result.get('prediction_sha256')))
                    else:
                        row['issues'].append('MISSING_RESULT_CANNOT_BIND_SAVED_EVALUATION')
                    for k, expected in bindings:
                        if provenance.get(k) != expected:
                            raise IntegrityError('Offline evaluator input provenance differs: ' + k)
                    if not digest_valid(provenance.get('metrics_source_sha256')):
                        raise IntegrityError('Offline evaluator source hash missing')
                    refs['metrics_source'] = self.bind('lab/metrics.py', expected=provenance['metrics_source_sha256'], required_hash=True)
                    if original:
                        for k, path in SUMMARY_METRICS.items():
                            if k in original and original[k] != nested(details['metrics'], path):
                                raise IntegrityError('Saved evaluator differs from summary: ' + k)
                    row['expected_metrics'] = details['metrics']
                    row['onmi_reference'] = details.get('onmi_supplement')
                    onmi = row['onmi_reference']
                    if onmi and onmi.get('implementation_source_sha256'):
                        refs['onmi_implementation'] = self.bind('lab/metrics_onmi_sparse.py', expected=onmi['implementation_source_sha256'], required_hash=True)
                        refs['onmi_author_source'] = self.bind(onmi['source_relative_path'], expected=onmi['source_sha256_observed'], required_hash=True)
                        if original and (original.get('onmi') != onmi.get('onmi') or original.get('onmi_status') != onmi.get('onmi_status')):
                            raise IntegrityError('Saved ONMI differs from summary')
                refs['io_source'] = self.bind('lab/io.py')
                for kind in ['graph', 'truth', 'config', 'io_source']:
                    if refs.get(kind) is None:
                        row['issues'].append('MISSING_' + kind.upper())
                if result and result.get('prediction') and refs.get('prediction') is None:
                    row['issues'].append('MISSING_DECLARED_PREDICTION')
                if result and result.get('status') == 'COMPLETED' and result.get('prediction_kind') != 'completed':
                    raise IntegrityError('COMPLETED lacks final cover identity')
                if result and result.get('status') != 'COMPLETED' and result.get('prediction_kind') == 'completed':
                    raise IntegrityError('Noncompleted result incorrectly claims completed cover')
                if result and not result.get('prediction') and original and any(original.get(k) is not None for k in SUMMARY_METRICS):
                    raise IntegrityError('Missing prediction has fabricated quality')
                required = ['spec', 'result', 'graph', 'truth', 'config', 'prediction', 'offline_details', 'metrics_source', 'io_source']
                if result and result.get('status') in TERMINAL and all(refs.get(k) for k in required) and not row['issues']:
                    row['replay_eligibility'] = 'READY_FINAL_COVER' if result['status'] == 'COMPLETED' else 'READY_PARTIAL_CHECKPOINT'
                elif result and not result.get('prediction'):
                    row['replay_eligibility'] = 'NO_COVER_QUALITY_UNKNOWN'
            except IntegrityError as exc:
                row['issues'].append('INTEGRITY_ERROR: ' + str(exc))
                row['replay_eligibility'] = 'INTEGRITY_ERROR'
            output['rows'].append(row)
        output['status_counts'] = dict(Counter(r['measurement_status'] or 'MISSING_RESULT' for r in output['rows']))
        output['eligibility_counts'] = dict(Counter(r['replay_eligibility'] for r in output['rows']))
        return output


def build_index(root, groups):
    builder = IndexBuilder(root)
    names = [g['name'] for g in groups]
    if len(names) != len(set(names)):
        raise IntegrityError('Duplicate group name')
    output_groups = [builder.group(g) for g in groups]
    tool = source_relative(builder.root, Path(__file__).resolve())
    builder.bind(tool)
    index = {'schema': SCHEMA, 'created_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'path_policy': 'POSIX relative paths rooted at extracted LAB; no .., absolute paths, backslashes, colon or escaping symlinks; original raw bytes are never rewritten.', 'source_root_recorded_for_provenance_only': str(builder.root), 'labels_policy': 'Ground-truth cover is consumed only by offline evaluate, never by graph algorithms. build hashes truth bytes without parsing memberships.', 'tool': tool, 'groups': output_groups, 'files': dict(sorted(builder.files.items())), 'missing_files': dict(sorted(builder.missing_files.items())), 'onmi_policy': 'Saved ONMI retained with pinned implementation/author-source hashes; ONMI is NOT recomputed by this tool.', 'cost_policy': 'Original measured status/cost retained; no new inference timing, timeout is not completed time, unscored/missing cover quality remains unknown.'}
    return index


def validate_index(index, root, verify_hashes=True):
    if index.get('schema') != SCHEMA or not isinstance(index.get('files'), dict):
        raise IntegrityError('Unsupported replay index schema')
    files = index['files']
    for path, entry in index.get('missing_files', {}).items():
        under(root, path)
        if path in files or entry.get('status') != 'MISSING_AT_BUILD' or entry.get('expected_sha256') is not None and not digest_valid(entry['expected_sha256']):
            raise IntegrityError('Invalid missing-file record: ' + str(path))
    for path, entry in files.items():
        target = under(root, path)
        if not isinstance(entry, dict) or not digest_valid(entry.get('sha256')) or type(entry.get('size_bytes')) is not int or entry['size_bytes'] < 0:
            raise IntegrityError('Missing/invalid indexed hash/size: ' + str(path))
        if verify_hashes:
            if not target.is_file():
                raise IntegrityError('Missing indexed file: ' + path)
            digest, size = hash_file(target)
            if digest != entry['sha256'] or size != entry['size_bytes']:
                raise IntegrityError('Indexed file changed: ' + path)
    names = []
    keys = set()
    for group in index.get('groups', []):
        name = group.get('name')
        if not isinstance(name, str) or not SIMPLE_ID.fullmatch(name) or name in names:
            raise IntegrityError('Invalid/duplicate indexed group')
        names.append(name)
        for field in ['plan', 'catalog', 'summary_json', 'summary_csv', 'stage_records']:
            path = group.get(field)
            if path is not None and (safe_relative(path) not in files):
                raise IntegrityError('Group reference absent from file manifest: ' + field)
        for row in group.get('rows', []):
            key = (name, row.get('job_id'))
            if key in keys or not isinstance(key[1], str) or not SIMPLE_ID.fullmatch(key[1]):
                raise IntegrityError('Invalid/duplicate indexed job')
            keys.add(key)
            for kind, value in row.get('references', {}).items():
                values = value.values() if isinstance(value, dict) else [value]
                for path in values:
                    if path is not None and safe_relative(path) not in files:
                        raise IntegrityError('Row reference absent from file manifest: ' + str(kind))
    if index.get('tool') not in files:
        raise IntegrityError('Indexed tool missing')
    if verify_hashes:
        validate_record_bindings(index, root)
    return True


def recorded_relative(index, value):
    """Lexical old-path mapping; never stat/open the old source root."""
    if not isinstance(value, str):
        raise IntegrityError('Missing raw-record path')
    prefix = index['source_root_recorded_for_provenance_only'].rstrip('/') + '/'
    if value.startswith(prefix):
        return safe_relative(value[len(prefix):])
    if value.startswith('/'):
        raise IntegrityError('Raw path outside recorded source root')
    return safe_relative(value)


def validate_record_bindings(index, root):
    """Bind generated fields back to hash-verified unchanged raw JSON bytes."""
    for group in index['groups']:
        plan = read_json(under(root, group['plan']))
        if index['files'][group['catalog']]['sha256'] != plan.get('catalog_sha256'):
            raise IntegrityError('Indexed catalog differs from immutable plan freeze')
        catalog_rows = read_json(under(root, group['catalog']))
        catalog = {c['case_id']: c for c in catalog_rows}
        jobs = {j['job_id']: j for j in plan['jobs']}
        original_rows = read_json(under(root, group['summary_json'])) if group.get('summary_json') else []
        summary = {r['job_id']: r for r in original_rows}
        if len(jobs) != len(plan['jobs']) or len(catalog) != len(catalog_rows) or len(summary) != len(original_rows):
            raise IntegrityError('Duplicate raw-record identity')
        if [r['job_id'] for r in group['rows']] != [j['job_id'] for j in plan['jobs']]:
            raise IntegrityError('Index row coverage/order differs from immutable plan')
        if group.get('planned_jobs') != len(plan['jobs']) or group.get('planned_case_ids') != sorted({j['case_id'] for j in plan['jobs']}):
            raise IntegrityError('Indexed plan counts differ')
        for row in group['rows']:
            job = jobs[row['job_id']]
            refs = row['references']
            if row.get('original_summary') != summary.get(row['job_id']):
                raise IntegrityError('Indexed quality/status summary differs from raw summary')
            for key in ['job_id', 'case_id', 'method', 'information_policy', 'device', 'threads', 'seed']:
                if row.get(key) != job.get(key):
                    raise IntegrityError('Indexed row identity differs from immutable plan: ' + key)
            raw = read_json(under(root, refs['result'])) if refs.get('result') else None
            expected_cost = {} if raw is None else {k: raw.get(k) for k in ['pipeline_seconds', 'monitor_elapsed_seconds', 'peak_tree_rss_bytes', 'sampled_tree_cpu_seconds', 'budget_seconds', 'original_timeout_s', 'returncode', 'timing_definition', 'resource_measurement']}
            if row.get('measurement_status') != (raw.get('status') if raw else None) or row.get('prediction_kind') != (raw.get('prediction_kind') if raw else None) or row.get('cost') != expected_cost:
                raise IntegrityError('Indexed status/cost differs from immutable raw result')
            # Build intentionally retains known corrupt rows instead of dropping them.
            # These are never eligible for scoring and keep their recorded issue.
            if row.get('replay_eligibility') == 'INTEGRITY_ERROR':
                if not any(s.startswith('INTEGRITY_ERROR: ') for s in row.get('issues', [])):
                    raise IntegrityError('Integrity-error row has no recorded reason')
                continue
            if refs.get('spec') and read_json(under(root, refs['spec'])) != job:
                raise IntegrityError('Spec differs from immutable plan')
            for kind, value, expected in [('graph', job['graph'], job.get('graph_sha256')), ('config', job['config'], job.get('config_sha256')), ('truth', catalog[job['case_id']].get('truth'), catalog[job['case_id']].get('truth_sha256'))]:
                path = refs.get(kind)
                if path and (path != recorded_relative(index, value) or index['files'][path]['sha256'] != expected):
                    raise IntegrityError('Indexed mapped input/hash differs: ' + kind)
            if raw and refs.get('prediction'):
                path = refs['prediction']
                if path != recorded_relative(index, raw['prediction']) or index['files'][path]['sha256'] != raw.get('prediction_sha256'):
                    raise IntegrityError('Indexed prediction map/hash differs from raw result')
            if refs.get('offline_details'):
                details = read_json(under(root, refs['offline_details']))
                if row.get('expected_metrics') != details.get('metrics') or row.get('onmi_reference') != details.get('onmi_supplement'):
                    raise IntegrityError('Indexed expected metrics differ from raw offline details')
                if details.get('metrics') and refs.get('metrics_source'):
                    if index['files'][refs['metrics_source']]['sha256'] != details.get('evaluation_provenance', {}).get('metrics_source_sha256'):
                        raise IntegrityError('Mapped scorer source hash differs from original evaluation')
            if row.get('replay_eligibility', '').startswith('READY_'):
                required = ['spec', 'result', 'graph', 'truth', 'config', 'prediction', 'offline_details', 'metrics_source', 'io_source']
                if row.get('issues') or not all(refs.get(k) for k in required) or not raw or raw.get('status') not in TERMINAL:
                    raise IntegrityError('READY row lacks required complete bindings')
                expected = 'READY_FINAL_COVER' if raw['status'] == 'COMPLETED' else 'READY_PARTIAL_CHECKPOINT'
                if row['replay_eligibility'] != expected:
                    raise IntegrityError('READY final/partial identity differs from original status')


def reject_indexed_output(index, root, output, index_file=None):
    destination = Path(output).resolve()
    if index_file is not None and destination == Path(index_file).resolve():
        raise IntegrityError('Output would overwrite replay index')
    if any(destination == under(root, path).resolve() for path in index['files']):
        raise IntegrityError('Output would overwrite an immutable indexed payload')


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forbid_original_input_opens(index):
    """Optional diagnostic guard; dependencies are allowed, original payload opens are not.

    This is an audit-hook test of the trusted scorer path, not a general sandbox.
    Only lexical original file names in the immutable payload manifest are denied.
    """
    old_root = index['source_root_recorded_for_provenance_only']
    denied = {os.path.normcase(os.path.abspath(os.path.join(old_root, *PurePosixPath(p).parts))) for p in index['files']}
    observation = {'enabled': True, 'original_indexed_input_paths_denied': len(denied), 'blocked_open_attempts': []}
    def hook(event, args):
        if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = os.path.normcase(os.path.abspath(os.fsdecode(args[0])))
            if path in denied:
                observation['blocked_open_attempts'].append(path)
                raise IntegrityError('Original input open denied by replay diagnostic guard: ' + path)
    sys.addaudithook(hook)
    return observation


def evaluate_index(index, root, tolerance=1e-12, selected_groups=None):
    if not math.isfinite(tolerance) or not 0 <= tolerance <= 1e-8:
        raise IntegrityError('Tolerance must be finite and between 0 and 1e-8')
    validate_index(index, root)
    if selected_groups and set(selected_groups) - {g['name'] for g in index['groups']}:
        raise IntegrityError('Unknown selected group')
    for name in THREAD_VARIABLES:
        os.environ[name] = '1'
    scorer_cache = {}
    io_cache = {}
    outputs = []
    for group in index['groups']:
        if selected_groups and group['name'] not in selected_groups:
            continue
        for original in group['rows']:
            onmi_verified = original.get('onmi_reference') is not None and original.get('references', {}).get('onmi_implementation') and original.get('references', {}).get('onmi_author_source')
            row = {'group': group['name'], 'job_id': original['job_id'], 'case_id': original['case_id'], 'measurement_status': original['measurement_status'], 'prediction_kind': original['prediction_kind'], 'original_cost': original['cost'], 'replay_status': 'QUALITY_UNKNOWN', 'quality': None, 'matches_saved_core_metrics': None, 'matches_saved_summary_fields': None, 'issues': list(original['issues']), 'onmi_status': 'NOT_RECOMPUTED_SOURCE_VERIFIED' if onmi_verified else 'NOT_AVAILABLE_OR_SOURCE_UNVERIFIED', 'onmi_saved': original.get('onmi_reference')}
            if original['replay_eligibility'].startswith('READY_'):
                refs = original['references']
                try:
                    io_ref = refs['io_source']
                    metric_ref = refs['metrics_source']
                    if io_ref not in io_cache:
                        io_cache[io_ref] = load_module(under(root, io_ref), '_portable_replay_io_' + str(len(io_cache)))
                    if metric_ref not in scorer_cache:
                        scorer_cache[metric_ref] = load_module(under(root, metric_ref), '_portable_replay_metrics_' + str(len(scorer_cache)))
                    io = io_cache[io_ref]
                    truth_path = under(root, refs['truth'])
                    truth_json = io.read_json(truth_path)
                    if truth_json.get('labels_complete') is not True:
                        raise IntegrityError('Partial labels cannot be scored by strict recovery protocol')
                    n, _ = io.graph(under(root, refs['graph']))
                    truth, _ = io.cover(truth_path, n)
                    pred, audit = io.cover(under(root, refs['prediction']), n)
                    score = scorer_cache[metric_ref].score(truth, pred, n)
                    differences = compare(original.get('expected_metrics'), score, tolerance, 'metrics')
                    saved_summary = original.get('original_summary') or {}
                    summary_differences = []
                    for key, path in SUMMARY_METRICS.items():
                        if key in saved_summary:
                            summary_differences.extend(compare(saved_summary[key], nested(score, path), tolerance, key))
                    row.update(quality=score, normalization=audit, matches_saved_core_metrics=not differences, matches_saved_summary_fields=not summary_differences, differences=differences + summary_differences, replay_status='RECOMPUTED_MATCH' if not differences and not summary_differences else 'RECOMPUTED_MISMATCH')
                except Exception as exc:
                    row['replay_status'] = 'SCORING_ERROR'
                    row['issues'].append(type(exc).__name__ + ': ' + str(exc))
            elif original['replay_eligibility'] == 'INTEGRITY_ERROR':
                row['replay_status'] = 'INTEGRITY_ERROR'
            outputs.append(row)
    import numpy
    import scipy
    return {'schema': 'community_portable_replay_scores_v1', 'evaluated_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'index_created_at_utc': index['created_at_utc'], 'original_source_files_accessed_by_scorer': False, 'lexical_old_root_mapping_used_for_record_verification': True, 'inference_executed': False, 'tolerance_absolute': tolerance, 'runtime': {'numpy': numpy.__version__, 'scipy': scipy.__version__, 'python': sys.version, 'thread_environment': {k: os.environ[k] for k in THREAD_VARIABLES}}, 'row_count': len(outputs), 'status_counts': dict(Counter(r['replay_status'] for r in outputs)), 'original_status_counts': dict(Counter(r['measurement_status'] or 'MISSING_RESULT' for r in outputs)), 'rows': outputs, 'limitations': ['Offline score equality is conditional on original valid cover and complete truth, scorer source and numerical runtime; Hungarian ties can differ across SciPy implementations.', 'ONMI saved values/source hashes verified only, not recomputed.', 'Inference cost is original recorded wall/RSS; offline reevaluation has no new algorithm timing and does not reset the research deadline.']}


def materialize(index, source_root, destination, index_file):
    validate_index(index, source_root)
    destination = Path(destination).resolve()
    source_root = Path(source_root).resolve()
    if destination == source_root or source_root in destination.parents:
        raise IntegrityError('Compact copy must be outside original source root')
    if destination.exists():
        raise IntegrityError('Destination must not exist; do not overwrite old replay evidence')
    destination.mkdir(parents=True)
    for path in index['files']:
        target = under(destination, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(under(source_root, path), target)
    target_index = destination / 'replay_index.json'
    if target_index.exists():
        raise IntegrityError('Reserved replay_index.json conflicts with payload')
    shutil.copyfile(index_file, target_index)
    validate_index(index, destination)
    return destination


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    build = sub.add_parser('build')
    build.add_argument('--source-root', type=Path, default=Path.cwd())
    build.add_argument('--groups', type=Path, required=True, help='JSON {groups:[{name,plan,catalog,analysis,run_root}]}')
    build.add_argument('--output', type=Path, required=True)
    build.add_argument('--expected-jobs', type=int)
    build.add_argument('--expected-cases', type=int)
    verify = sub.add_parser('verify')
    verify.add_argument('--root', type=Path, required=True)
    verify.add_argument('--index', type=Path, required=True)
    ev = sub.add_parser('evaluate')
    ev.add_argument('--root', type=Path, required=True)
    ev.add_argument('--index', type=Path, required=True)
    ev.add_argument('--output', type=Path, required=True)
    ev.add_argument('--group', action='append')
    ev.add_argument('--tolerance', type=float, default=1e-12)
    ev.add_argument('--forbid-original-input-opens', action='store_true', help='Diagnostic audit hook rejects original indexed payload paths; use with a materialized/extracted copy, never original root.')
    copy = sub.add_parser('materialize')
    copy.add_argument('--source-root', type=Path, required=True)
    copy.add_argument('--index', type=Path, required=True)
    copy.add_argument('--destination', type=Path, required=True)
    a = p.parse_args(argv)
    try:
        if a.command == 'build':
            groups = read_json(a.groups)['groups']
            index = build_index(a.source_root, groups)
            row_count = sum(len(g['rows']) for g in index['groups'])
            cases = {r['case_id'] for g in index['groups'] for r in g['rows']}
            if a.expected_jobs is not None and row_count != a.expected_jobs:
                raise IntegrityError('Expected job count differs: ' + str(row_count))
            if a.expected_cases is not None and len(cases) != a.expected_cases:
                raise IntegrityError('Expected case count differs: ' + str(len(cases)))
            reject_indexed_output(index, a.source_root, a.output)
            write_json(a.output, index)
            integrity_rows = [r for g in index['groups'] for r in g['rows'] if r['replay_eligibility'] == 'INTEGRITY_ERROR']
            print(json.dumps({'index': str(a.output), 'rows': row_count, 'cases': len(cases), 'file_count': len(index['files']), 'integrity_error_rows': len(integrity_rows), 'groups': {g['name']: g['eligibility_counts'] for g in index['groups']}}))
            return 2 if integrity_rows else 0
        index = read_json(a.index)
        if a.command == 'verify':
            validate_index(index, a.root)
            print(json.dumps({'verification': 'PASS', 'file_count': len(index['files'])}))
        elif a.command == 'materialize':
            destination = materialize(index, a.source_root, a.destination, a.index)
            print(json.dumps({'copied_to': str(destination), 'file_count': len(index['files']), 'model_or_embedding_suffixes_copied': [s for s in index['files'] if Path(s).suffix in ('.pt', '.pth', '.npy')]}))
        elif a.command == 'evaluate':
            reject_indexed_output(index, a.root, a.output, a.index)
            guard = None
            if a.forbid_original_input_opens:
                if Path(a.root).resolve() == Path(index['source_root_recorded_for_provenance_only']).resolve():
                    raise IntegrityError('Original-open guard requires a distinct extracted root')
                guard = forbid_original_input_opens(index)
            report = evaluate_index(index, a.root, a.tolerance, a.group)
            report['original_input_open_guard'] = guard
            report['index_sha256'] = hash_file(a.index)[0]
            write_json(a.output, report)
            print(json.dumps({'output': str(a.output), 'rows': report['row_count'], 'status_counts': report['status_counts'], 'original_status_counts': report['original_status_counts']}))
            return 2 if any(k in report['status_counts'] for k in ['RECOMPUTED_MISMATCH', 'SCORING_ERROR', 'INTEGRITY_ERROR']) else 0
    except (IntegrityError, KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({'status': 'INTEGRITY_ERROR', 'error': type(exc).__name__ + ': ' + str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
