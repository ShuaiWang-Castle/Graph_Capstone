#!/usr/bin/env python3
"""Offline development diagnosis. Labels never enter the measured adapter.

Use the saved checkpoint covers, not interpolated embeddings or label-selected
output. Checkpoint clocks start at the adapter entry, not the outer process.
"""
from pathlib import Path
import argparse, csv, json, sys, time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.io import read_json, write_json, graph, cover, sha256
from lab.metrics import score


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--run-root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--plot', action='store_true')
    args = parser.parse_args()
    plan = read_json(args.plan)
    if sha256(args.catalog) != plan['catalog_sha256']:
        raise ValueError('Catalog changed after freeze')
    catalog = {c['case_id']: c for c in read_json(args.catalog)}
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    rows, summaries, artifacts, errors = [], [], [], []
    levels = read_json(ROOT / 'configs/protocol.json')['target_macro_f1_levels_for_time_to_quality']
    begin = time.perf_counter()
    for job in plan['jobs']:
        if job['method'] != 'nocd_graph_oracleK':
            continue
        directory = Path(args.run_root) / job['job_id']
        result_path = directory / 'result.json'
        if not result_path.exists():
            summaries.append({'job_id': job['job_id'], 'status': 'NOT_RUN', 'checkpoints_evaluated': 0})
            continue  # Do not read active checkpoints.
        result = read_json(result_path)
        case = catalog[job['case_id']]
        local = []
        try:
            for path, digest in [(case['graph'], job['graph_sha256']),
                                 (case['truth'], case['truth_sha256']),
                                 (job['config'], job['config_sha256'])]:
                if sha256(path) != digest:
                    raise ValueError('Input/config hash changed: ' + str(path))
            if read_json(case['truth']).get('labels_complete') is not True:
                raise ValueError('Labels are not complete')
            n, _ = graph(case['graph'])
            truth, _ = cover(case['truth'], n)
            cfg = read_json(job['config'])
            if cfg['k'] != len(truth):
                raise ValueError('Oracle scalar K disagrees with frozen truth')
            for checkpoint in sorted((directory / 'checkpoints').glob('epoch_*.json')):
                digest_before = sha256(checkpoint)
                saved = read_json(checkpoint)
                if saved['metadata']['kind'] != 'measured_evaluation_checkpoint':
                    raise ValueError('Unexpected checkpoint kind')
                pred, _ = cover(checkpoint, n)
                metrics = score(truth, pred, n)
                event = saved['trace'][-1]
                row = {'job_id': job['job_id'], 'case_id': job['case_id'],
                       'information_policy': job['information_policy'], 'device': job['device'],
                       'seed': job['seed'], 'run_status': result['status'],
                       'epoch': event['epoch'], 'checkpoint_path': str(checkpoint),
                       'checkpoint_sha256': digest_before,
                       'observation_elapsed_from_adapter_entry_seconds': event['elapsed_seconds'],
                       'snapshot_creation_elapsed_from_adapter_entry_seconds': saved['stage_seconds']['elapsed'],
                       'training_reconstruction_loss': event['training_reconstruction_loss'],
                       'matched_macro_f1': metrics['matched_macro_f1'],
                       'matched_membership_micro_f1': metrics['matched_membership_micro']['f1'],
                       'at_least_two_correct_recall': metrics['at_least_two_correct_recall'],
                       'small_group_mean_matched_f1': metrics['small_group_mean_matched_f1'],
                       'predicted_groups': metrics['predicted_groups'],
                       'pred_node_coverage': metrics['pred_node_coverage']}
                if sha256(checkpoint) != digest_before:
                    raise ValueError('Checkpoint changed during offline evaluation')
                local.append(row)
                artifacts.append({'path': str(checkpoint), 'sha256': digest_before})
            summary = {'job_id': job['job_id'], 'case_id': job['case_id'],
                       'status': result['status'], 'checkpoints_evaluated': len(local),
                       'outer_pipeline_seconds': result['pipeline_seconds'],
                       'output_selection': 'minimum full training loss; never label selected',
                       'clock_scope': 'adapter entry to observation, excluding process bootstrap and not including subsequent checkpoint write',
                       'first_observed_crossings': {}}
            if local:
                selected = min(local, key=lambda r: r['training_reconstruction_loss'])
                summary['training_loss_selected_epoch'] = selected['epoch']
                summary['training_loss_selected_macro_f1'] = selected['matched_macro_f1']
                # Development posthoc diagnostics are never promoted to algorithm output.
                best_quality = max(local, key=lambda r: r['matched_macro_f1'])
                summary['posthoc_label_best_epoch_DIAGNOSTIC_ONLY'] = best_quality['epoch']
                summary['posthoc_label_best_macro_f1_DIAGNOSTIC_ONLY'] = best_quality['matched_macro_f1']
                summary['posthoc_label_best_is_not_a_returned_method'] = True
                if result.get('prediction'):
                    if sha256(result['prediction']) != result['prediction_sha256']:
                        raise ValueError('Final prediction hash changed')
                    final_cover, _ = cover(result['prediction'], n)
                    selected_cover, _ = cover(selected['checkpoint_path'], n)
                    summary['returned_cover_equals_training_loss_selected_cover'] = final_cover == selected_cover
                    if not summary['returned_cover_equals_training_loss_selected_cover']:
                        raise ValueError('Returned cover does not match declared training-loss selection')
                for level in levels:
                    crossed = next((r for r in local if r['matched_macro_f1'] >= level), None)
                    summary['first_observed_crossings'][str(level)] = ({
                        'epoch': crossed['epoch'],
                        'observation_elapsed_from_adapter_entry_seconds': crossed['observation_elapsed_from_adapter_entry_seconds'],
                        'checkpoint_sha256': crossed['checkpoint_sha256'],
                        'discrete_saved_checkpoint_only_no_interpolation': True
                    } if crossed else None)
            summaries.append(summary)
            rows.extend(local)
        except Exception as exc:
            errors.append({'job_id': job['job_id'], 'error': repr(exc)})
            summaries.append({'job_id': job['job_id'], 'status': 'DIAGNOSTIC_ERROR', 'error': repr(exc)})
    write_json(output / 'checkpoint_quality.json', rows)
    write_csv(output / 'checkpoint_quality.csv', rows)
    write_json(output / 'job_summary.json', summaries)
    write_json(output / 'manifest.json', {
        'purpose': 'OFFLINE_DEVELOPMENT_DIAGNOSIS_NOT_AN_ALGORITHM_OR_LABEL_SELECTED_METHOD',
        'plan_sha256': sha256(args.plan), 'catalog_sha256': sha256(args.catalog),
        'metrics_source_sha256': sha256(ROOT / 'lab/metrics.py'),
        'analysis_source_sha256': sha256(__file__), 'artifacts': artifacts,
        'offline_evaluation_seconds': time.perf_counter() - begin,
        'errors': errors, 'summary_count': len(summaries), 'checkpoint_count': len(rows),
        'clock_limitation': 'No process-bootstrap clock offset was measured; do not call checkpoint elapsed outer pipeline time-to-quality.'})
    if args.plot and rows:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        for size in [1000, 5000]:
            cases = [s for s in summaries if s.get('case_id') and catalog[s['case_id']]['n'] == size and s.get('checkpoints_evaluated', 0)]
            if not cases:
                continue
            ncols = min(4, len(cases))
            nrows = (len(cases) + ncols - 1) // ncols
            fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows), squeeze=False)
            for ax, summary in zip(axes.flat, sorted(cases, key=lambda r: r['case_id'])):
                curve = [r for r in rows if r['job_id'] == summary['job_id']]
                x = [r['observation_elapsed_from_adapter_entry_seconds'] for r in curve]
                ax.plot(x, [r['matched_macro_f1'] for r in curve], '-o', markersize=2, label='Saved cover macro F1')
                chosen = next(r for r in curve if r['epoch'] == summary['training_loss_selected_epoch'])
                ax.scatter([chosen['observation_elapsed_from_adapter_entry_seconds']], [chosen['matched_macro_f1']], marker='x', color='red', label='Training-loss selected')
                ax.set_ylim(0, 1)
                ax.set_title(summary['case_id'], fontsize=8)
                ax.set_xlabel('Observed seconds from adapter entry', fontsize=7)
                ax.set_ylabel('Matched macro F1', fontsize=7)
                ax.legend(fontsize=6)
            for ax in list(axes.flat)[len(cases):]:
                ax.set_visible(False)
            fig.suptitle('NOCD-G oracle K / CPU: offline saved-checkpoint diagnostics; no interpolation')
            fig.tight_layout()
            fig.savefig(output / f'saved_checkpoint_quality_n{size}.png', dpi=140)
            plt.close(fig)
    print(json.dumps({'summaries': len(summaries), 'checkpoints': len(rows), 'errors': errors}))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
