#!/usr/bin/env python3
"""Descriptive same-case comparisons, retaining failures and incomplete jobs.

No confidence intervals treat related LFR cases as independent datasets. These
pairwise deltas are observations, not repeatability or novelty claims.
"""
from pathlib import Path
from itertools import combinations
import argparse, csv, statistics, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.io import read_json, write_json, sha256


def median(values):
    values = [x for x in values if x is not None]
    return statistics.median(values) if values else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--results', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    source = read_json(a.results)
    panels = sorted({(r['information_policy'], r['device'], r['threads'], r['seed']) for r in source})
    rows, summaries = [], []
    quality_fields = ['matched_macro_f1', 'matched_membership_micro_f1',
                      'at_least_two_correct_recall', 'small_group_mean_matched_f1',
                      'onmi', 'pred_node_coverage']
    for policy, device, threads, seed in panels:
        subset = [r for r in source if (r['information_policy'], r['device'], r['threads'], r['seed']) == (policy, device, threads, seed)]
        methods = sorted({r['method'] for r in subset})
        cases = sorted({r['case_id'] for r in subset})
        index = {(r['method'], r['case_id']): r for r in subset}
        if len(index) != len(subset):
            raise ValueError('Repeated method/case within one panel; distinguish attempts before comparing')
        for reference, comparison in combinations(methods, 2):
            local = []
            for case in cases:
                left, right = index.get((reference, case)), index.get((comparison, case))
                row = {'case_id': case, 'information_policy': policy, 'device': device,
                       'threads': threads, 'seed': seed, 'reference_method': reference,
                       'comparison_method': comparison,
                       'reference_status': left['status'] if left else 'NOT_PLANNED',
                       'comparison_status': right['status'] if right else 'NOT_PLANNED',
                       'reference_job_id': left['job_id'] if left else None,
                       'comparison_job_id': right['job_id'] if right else None,
                       'comparison_basis': 'not_both_completed_and_scored'}
                if left and right and all(r['status'] == 'COMPLETED' and r['metric_status'] == 'SCORED' for r in [left, right]):
                    row.update(comparison_basis='both_completed_and_scored',
                               reference_complete_pipeline_seconds=left['pipeline_seconds'],
                               comparison_complete_pipeline_seconds=right['pipeline_seconds'],
                               complete_pipeline_time_ratio_comparison_over_reference=right['pipeline_seconds'] / left['pipeline_seconds'])
                    for field in quality_fields:
                        if left.get(field) is not None and right.get(field) is not None:
                            row[field + '_difference_comparison_minus_reference'] = right[field] - left[field]
                        else:
                            row[field + '_difference_comparison_minus_reference'] = None
                    qdelta = row['matched_macro_f1_difference_comparison_minus_reference']
                    time_ratio = row['complete_pipeline_time_ratio_comparison_over_reference']
                    row['observed_macro_quality_at_least_equal_and_faster'] = qdelta >= 0 and time_ratio < 1
                    row['observed_macro_quality_higher_and_time_at_most_equal'] = qdelta > 0 and time_ratio <= 1
                    row['observation_is_not_a_repeatability_claim'] = True
                local.append(row)
            scored = [r for r in local if r['comparison_basis'] == 'both_completed_and_scored']
            summaries.append({
                'information_policy': policy, 'device': device, 'threads': threads, 'seed': seed,
                'reference_method': reference, 'comparison_method': comparison,
                'all_case_denominator': len(local), 'both_completed_scored': len(scored),
                'other_or_missing_count': len(local) - len(scored),
                'median_time_ratio_completed_pairs_only': median([r['complete_pipeline_time_ratio_comparison_over_reference'] for r in scored]),
                'descriptive_only_no_IID_CI_or_grand_winner': True,
                **{f'median_{field}_difference_completed_pairs_only': median([r.get(field + '_difference_comparison_minus_reference') for r in scored]) for field in quality_fields}})
            rows.extend(local)
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=True)
    for name, data in [('paired_cases', rows), ('pair_summary', summaries)]:
        write_json(output / (name + '.json'), data)
        keys = list(dict.fromkeys(k for r in data for k in r))
        with (output / (name + '.csv')).open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(data)
    write_json(output / 'manifest.json', {
        'results_sha256': sha256(a.results), 'tool_sha256': sha256(__file__),
        'rows': len(rows), 'summaries': len(summaries),
        'direction': 'comparison minus reference for quality; comparison / reference for complete time',
        'timeout_policy': 'No completed-time ratio or imputed quality for failed/incomplete pairs; all rows retained',
        'interpretation': 'Only same case, policy, device, threads and requested algorithm seed paired; language/backend differences remain disclosed in method identities. Seed is not independent RNG for deterministic/fixed-seed native arms.'})
    print(f'{len(rows)} paired case rows; {len(summaries)} descriptive summaries')


if __name__ == '__main__':
    main()
