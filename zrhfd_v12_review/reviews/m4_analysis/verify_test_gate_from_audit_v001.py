"""Recheck G-E2 from an actual sealed full test audit; no mechanism diagnosis."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import statistics
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
AUDITOR = Path(__file__).with_name('audit_actual_ordinary_v001.py')
AUDITOR_SHA = 'd987e0f7d9f655adf80ce96f197022838025e94fc9cbf9f99d3d1f6882a7f80c'
RUN = 'results/m4/test_main_v12_002'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if digest(AUDITOR) != AUDITOR_SHA:
        raise RuntimeError('Reviewed independent auditor source changed')
    from audit_actual_ordinary_v001 import verify_audit_receipt
    audit_path = (ROOT / args.audit).resolve()
    output = (ROOT / args.output).resolve()
    boundary = (ROOT / 'reviews/m4_analysis').resolve()
    if not audit_path.is_relative_to(boundary) or not output.is_relative_to(boundary) or output.exists():
        raise RuntimeError('Require project review input and a new immutable review output')
    verified = verify_audit_receipt(audit_path, root=ROOT, run_name=RUN, verify_files=False)
    receipt = json.loads(audit_path.read_text())
    if receipt['auditor_source_sha256'] != AUDITOR_SHA:
        raise RuntimeError('Actual receipt was not produced by the reviewed auditor source')
    summary_name = RUN + '/summary.json'
    summary_path = ROOT / summary_name
    if receipt['validated_files'].get(summary_name) != digest(summary_path):
        raise RuntimeError('Derived summary changed since the actual audit')
    rows = receipt['query_records']
    if len(rows) != 5184 or len({row['task'] for row in rows}) != 5184:
        raise RuntimeError('Not the full frozen 5184 task test audit')
    lookup = {}
    for row in rows:
        key = (row['case_id'], row['query_index'], row['method'], row['setting'])
        if key in lookup:
            raise RuntimeError('Duplicate query/method setting')
        lookup[key] = row
    mains = [row for row in rows if (row['method'], row['setting']) == ('zrhfd', 'no_volume')]
    if len(mains) != 432 or len({(row['case_id'], row['query_index']) for row in mains}) != 432:
        raise RuntimeError('Main test query census differs')
    pairs = []
    for row in mains:
        hfd = lookup[(row['case_id'], row['query_index'], 'hfd', 'no_volume')]
        leiden = lookup[(row['case_id'], row['query_index'], 'leiden', 'global')]
        triple = (row, hfd, leiden)
        if all(item['status'] == 'COMPLETED' and item['completion_claim'] is True for item in triple):
            for item in triple:
                if not isinstance(item['F1'], (int, float)) or not math.isfinite(item['F1']):
                    raise RuntimeError('Invalid independently audited primary quality')
                if item['seed'] != row['seed'] or item['truth_phi'] != row['truth_phi']:
                    raise RuntimeError('Triple input/stratification differs')
            pairs.append(triple)
    low = [triple for triple in pairs if triple[0]['truth_phi'] <= .5]
    high = [triple for triple in pairs if .4 <= triple[0]['truth_phi'] <= .5]
    def med(group, index):
        return statistics.median(triple[index]['F1'] for triple in group) if group else None
    first = bool(low) and med(low, 0) >= med(low, 2) - .03
    second = bool(high) and med(high, 0) >= med(high, 1) + .10
    gate = {'status': ('PASS' if first and second else 'FAIL') if len(pairs) == 432 else 'NOT RUN',
            'complete_test_query_triples': len(pairs), 'required': 432,
            'truth_phi_le_point5_queries': len(low), 'truth_phi_point4_to_point5_queries': len(high),
            'main_median_low': med(low, 0), 'leiden_median_low': med(low, 2),
            'main_median_high': med(high, 0), 'hfd_no_volume_median_high': med(high, 1),
            'Leiden_margin_condition': first, 'HFD_gain_condition': second}
    recorded = json.loads(summary_path.read_text())['G_E2']
    for key, value in gate.items():
        if recorded.get(key) != value:
            raise RuntimeError('G-E2 differs from independently audited primary rows: ' + key)
    result = {'status': 'PASS', 'G_E2': gate,
              'created_utc': datetime.now(timezone.utc).isoformat(),
              'source_sha256': digest(Path(__file__)), 'actual_argv': [sys.executable, *sys.argv],
              'actual_audit_verification': verified, 'audit_sha256': digest(audit_path),
              'summary_sha256': digest(summary_path), 'auditor_source_sha256': AUDITOR_SHA,
              'analysis_scope': 'Primary F1 and measured truth conductance only; independent sealed full test audit',
              'raw_rehashed_in_this_step': False, 'test_mechanism_diagnostics': False,
              'algorithms_executed': False, 'bootstrap_recomputed': False,
              'gate_admission_authorized_by_this_helper': False,
              'admission_owner': 'experiments/diagnostics/gated_m4.py checks its own frozen full-cohort contract'}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'audit_recheck': 'PASS', 'G_E2': gate, 'receipt': str(output.relative_to(ROOT))}))

if __name__ == '__main__':
    main()
