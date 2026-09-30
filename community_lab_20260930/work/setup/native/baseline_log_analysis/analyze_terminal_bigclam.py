#!/usr/bin/env python3
"""Only read BigCLAM directories having authoritative terminal result.json."""
from __future__ import annotations
import argparse, csv, hashlib, importlib.util, json, math, statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PARSER = ROOT / 'work/setup/native/parse_bigclam_logs.py'
sp = importlib.util.spec_from_file_location('bigclam_log_parser', PARSER)
mod = importlib.util.module_from_spec(sp)
sp.loader.exec_module(mod)
TERMINAL = {'COMPLETED', 'TIMEOUT', 'MEMORY_LIMIT', 'ERROR', 'LAUNCH_ERROR',
            'INVALID_OUTPUT', 'LOG_LIMIT', 'INTERRUPTED', 'BLOCKED', 'NOT_RUN_BUDGET'}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def grid(cli):
    if cli.get('c') != -1:
        return []
    lo, hi, trials = int(cli['mc']), int(cli['xc']), int(cli['nc'])
    gap = math.exp(math.log(hi / lo) / trials)
    ks = [lo]
    while len(ks) < trials:
        nxt = int(ks[-1] * gap)
        ks.append(nxt if nxt != ks[-1] else nxt + 1)
    if ks[-1] < hi:
        ks.append(hi)
    return ks

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-root', default='work/baseline73_v2')
    ap.add_argument('--output', default='work/setup/native/baseline_log_analysis')
    args = ap.parse_args()
    runroot, out = ROOT / args.run_root, ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    # Snapshot identities once. A directory or runner state alone is not proof
    # of terminal state. Do not open any outputs without terminal result.json.
    candidates = sorted(runroot.glob('*/result.json'))
    terminal, rows, details = [], [], []
    for rp in candidates:
        result_bytes = rp.read_bytes()
        rec = json.loads(result_bytes)
        if rec.get('status') not in TERMINAL:
            continue
        terminal.append(rp)
        if rec.get('method') not in {'bigclam_native', 'bigclam_oracleK'}:
            continue
        directory = rp.parent
        logpath = directory / 'stdout.log'
        logbytes = logpath.read_bytes() if logpath.exists() else b''
        parsed = mod.parse_bytes(logbytes)
        spec = json.loads((directory / 'spec.json').read_text())
        graphpath = Path(spec['graph'])
        ngraph = json.loads(graphpath.read_text())['n'] if graphpath.exists() else None
        lines = [s.strip() for s in logbytes.decode('utf-8', errors='replace').replace('\r', '\n').splitlines() if s.strip()]
        last = parsed['mle_runs'][-1] if parsed['mle_runs'] else None
        cv = [run for run in parsed['mle_runs'] if run['phase'] == 'cv']
        final = [run for run in parsed['mle_runs'] if run['phase'] == 'final_fit']
        native_cover = directory / 'native_cmtyvv.txt'
        checkpoint = directory / 'checkpoint.json'
        coveraudit = None
        if native_cover.exists():
            try:
                raw = native_cover.read_bytes()
                groups = [[int(x) for x in line.split()] for line in raw.decode().splitlines() if line.strip() and not line.lstrip().startswith('#')]
                coveraudit = {'syntax_and_id_range_valid': all(0 <= v < ngraph for group in groups for v in group),
                              'groups': len(groups), 'memberships': sum(map(len, groups)),
                              'sha256': digest(native_cover), 'ends_newline': not raw or raw.endswith(b'\n'),
                              'completion_evidence': 'COMPLETED prediction metadata' if rec.get('status') == 'COMPLETED' and rec.get('prediction_kind') == 'completed' else 'not_proven_by_file_existence'}
            except Exception as exc:
                coveraudit = {'syntax_and_id_range_valid': False, 'error': str(exc), 'sha256': digest(native_cover)}
        counts = Counter(run['k'] for run in cv if run['completed'])
        byk = [{'k': k, 'completed_mle_calls': counts[k], 'observed_mle_calls': sum(run['k'] == k for run in cv)} for k in parsed['cv_candidates_observed']]
        lastprogress = last['progress'][-1] if last and last['progress'] else None
        row = dict(job_id=rec['job_id'], case_id=rec.get('case_id'), method=rec['method'],
                   status=rec['status'], information_policy=rec.get('information_policy'),
                   n_graph=ngraph, n_loaded=(parsed.get('graph') or {}).get('n_loaded'),
                   m_loaded=(parsed.get('graph') or {}).get('m_loaded'),
                   pipeline_seconds=rec.get('pipeline_seconds'), budget_seconds=rec.get('budget_seconds'),
                   peak_tree_rss_bytes=rec.get('peak_tree_rss_bytes'),
                   cli_c=parsed['accepted_cli'].get('c'), cli_min_k=parsed['accepted_cli'].get('mc'),
                   cli_max_k=parsed['accepted_cli'].get('xc'), cli_k_trials=parsed['accepted_cli'].get('nc'),
                   expected_grid=grid(parsed['accepted_cli']), observed_grid=parsed['cv_candidates_observed'],
                   last_observed_k=parsed['cv_candidates_observed'][-1] if parsed['cv_candidates_observed'] else None,
                   cv_complete_mle_calls=sum(run['completed'] for run in cv), cv_observed_mle_calls=len(cv),
                   final_fit_observed=bool(final), final_fit_completed=any(run['completed'] for run in final),
                   selected_k_from_native_cv=parsed.get('selected_k_from_cv_scores'),
                   last_observed_phase=last['phase'] if last else 'no_MLE_observed',
                   last_observed_mle_completed=last['completed'] if last else None,
                   last_vertex_update_attempts=lastprogress.get('vertex_update_attempts') if lastprogress else last.get('vertex_update_attempts') if last else None,
                   last_mle_local_wall_seconds_integer=lastprogress.get('local_wall_seconds_integer') if lastprogress else None,
                   cv_completed_cpu_seconds_sum_rounded=parsed['completed_cv_mle_cpu_seconds_sum_rounded'],
                   final_completed_cpu_seconds_sum_rounded=parsed['completed_final_mle_cpu_seconds_sum_rounded'],
                   conductance_cpu_seconds_sum_rounded=sum(event.get('cpu_seconds_rounded') or 0 for event in parsed['conductance_observations']),
                   native_total_cpu_seconds_rounded=parsed['native_cpu_seconds'],
                   native_exit_banner_seen=parsed['native_exit_banner_seen'], native_cover_exists=native_cover.exists(),
                   native_cover_valid_syntax=coveraudit.get('syntax_and_id_range_valid') if coveraudit else None,
                   runner_checkpoint_exists=checkpoint.exists(), runner_prediction_kind=rec.get('prediction_kind'),
                   runner_prediction_exists=bool(rec.get('prediction')),
                   usable_partial_checkpoint=bool(rec.get('prediction_kind') == 'partial_checkpoint' and rec.get('prediction') and Path(rec['prediction']).exists()),
                   last_log_record=lines[-1] if lines else None,
                   result_sha256=hashlib.sha256(result_bytes).hexdigest(),
                   stdout_sha256=hashlib.sha256(logbytes).hexdigest() if logpath.exists() else None)
        if rp.read_bytes() != result_bytes:
            raise RuntimeError('Terminal result changed during analysis: ' + str(rp))
        rows.append(row)
        details.append({'row': row, 'accepted_cli': parsed['accepted_cli'], 'mle_counts_by_k': byk,
                        'parsed_native_log': parsed, 'native_cover_audit': coveraudit,
                        'original_command': rec.get('command'), 'source_hashes': rec.get('source_hashes'),
                        'graph_sha256': rec.get('graph_sha256'), 'config_sha256': rec.get('config_sha256'),
                        'result_path': str(rp.relative_to(ROOT)), 'result_sha256': row['result_sha256']})
    captured = datetime.now(timezone.utc).isoformat()
    payload = {'captured_at_utc': captured, 'run_root': args.run_root,
               'terminal_job_count_snapshot': len(terminal), 'bigclam_terminal_job_count_snapshot': len(rows),
               'analyzer_sha256': digest(Path(__file__)), 'parser_sha256': digest(PARSER),
               'analysis_scope': 'Only directories with authoritative terminal result.json; no active outputs or labels read.',
               'rows': rows, 'details': details}
    (out / 'bigclam-terminal-jobs.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')
    if rows:
        with (out / 'bigclam-terminal-jobs.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    status = Counter((row['method'], row['status']) for row in rows)
    sections = ['# BigCLAM 终态日志的实际阶段证据\n',
                f'快照 UTC：{captured}。本轮计划尚在运行；当时共有 {len(terminal)} 项终态，其中 BigCLAM {len(rows)} 项。只读权威 result.json 已终态目录；未读活跃输出、真标签或质量分数，未跑测量、未改冻结源码/配置。\n',
                '## 状态与阶段\n', '| 方法 | 状态 | 终态项数 |', '|---|---|---:|']
    for (method, state), count in sorted(status.items()):
        sections.append(f'| {method} | {state} | {count} |')
    sections += ['', 'TIMEOUT 是预算内未完成，pipeline_seconds 为实际停止花费，不能当完成时间。下面的完成条件统计只描述此快照已完成子集，不能推广到未跑或超时项。\n']
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['method'], row['n_graph'])].append(row)
    sections += ['| 方法/n | 完成/终态 | 完成条件 pipeline 中位秒 | timeout 阶段 |', '|---|---:|---:|---|']
    for (method, n), subset in sorted(grouped.items()):
        complete = [row['pipeline_seconds'] for row in subset if row['status'] == 'COMPLETED']
        stalled = Counter(row['last_observed_phase'] for row in subset if row['status'] == 'TIMEOUT')
        median = f'{statistics.median(complete):.6f}' if complete else 'NA'
        sections.append(f'| {method}/{n} | {len(complete)}/{len(subset)} | {median} | {dict(stalled)} |')
    sections += ['', '## 超时的可复放 trace\n',
                 '| job | 最后 K | 已完成 CV MLE | 最后阶段 | 最后更新尝试 | 本次 MLE 整秒 wall | usable checkpoint |',
                 '|---|---:|---:|---|---:|---:|---|']
    for row in rows:
        if row['status'] in {'TIMEOUT', 'MEMORY_LIMIT', 'ERROR', 'INVALID_OUTPUT'}:
            sections.append(f"| {row['job_id']} | {row['last_observed_k']} | {row['cv_complete_mle_calls']} | {row['last_observed_phase']} | {row['last_vertex_update_attempts']} | {row['last_mle_local_wall_seconds_integer']} | {row['usable_partial_checkpoint']} |")
    auto = [row for row in rows if row['method'] == 'bigclam_native' and row['status'] == 'COMPLETED']
    ratios = [row['cv_completed_cpu_seconds_sum_rounded'] / row['native_total_cpu_seconds_rounded'] for row in auto if row.get('native_total_cpu_seconds_rounded')]
    cpu_note = f'完成 CV 的累计 CPU 时间占原生总 CPU 时间比例中位数 {statistics.median(ratios):.6f}，范围 [{min(ratios):.6f},{max(ratios):.6f}]。' if ratios else '暂缺可分摊的完成日志。'
    timeouts = sum(row['status'] == 'TIMEOUT' for row in rows if row['method'] == 'bigclam_native')
    sections += ['', '## 可支持与不可支持的耗时诊断\n',
                 f'- 原生 autoK 已完成子集 {len(auto)} 项；{cpu_note}各 routine 的时间均已舍入，且是 CPU 时间，非完整 wall 阶段表。',
                 f'- 超时原生 autoK 共 {timeouts} 项，逐项上表列出最后观测阶段。训练阶段不保存 F，若无 runner checkpoint 则保留质量未知。',
                 '- -nc:10 通常产生11个K格点，每个3次CV MLE。实际尝试网格、接受CLI与每K已完成次数见 JSON/CSV；缺失候选表示未走到该处，不是算法主动舍弃。',
                 '- MLE completion、conductance 与 native run time 来自 clock() process CPU。日志进度的 [N sec] 来自 time(NULL)，整秒且每次MLE归零。不能当作外层单调clock的精确阶段wall。',
                 '- 串行 iterations 是vertex-update attempts，包含跳过，非实际梯度次数。printed likelihood初始化0且会陈旧，不能从日志中0推质量失败。',
                 '- 原生 completion 不给停止理由，不证明global convergence；未完成MLE的duration不插补。',
                 '- 完成cover按result身份记录；native cmtyvv语法有效不证明中途文件已完整，本分析未抢救或改变任何状态。',
                 '- 未计时的holdout构建、I/O与初始化其他步骤不能通过CPU余额精确归因；完整阶段wall需要另做一致instrumentation的研发profile。\n',
                 '## 后续公平同预算控制（未登记算法候选）\n',
                 '1. 主面板保留原 graph-only autoK 的发现+CV+最终fit+输出完整成本。增加120/300秒预算必须建立独立arm，保留原超时并记录新增预算；不能将超时预算当完成时间。',
                 '2. 模型选择政策比较须对双方依同一graph-only可观测输入冻结K网格/评分/终止，不读标签或真实overlap。更少K尝试属于搜索政策与容量变化，需要同样少试验的简单控制。',
                 '3. oracle-K只作同信息面板下的最终fit诊断，可展示已知K减去模型选择负担，但不能作为graph-only的免费快捷版或跨面板赢家。',
                 '4. BigCLAM内部seed固定10，73/74/75只是重复计时，不是独立随机算法seed。新进程、同binary/hash/线程分别报告计时散布；新增checkpoint或profile应对照两arm一致。',
                 '5. 用原生holdout likelihood选最终K，不用offline真质量择候选/epoch；quality-cost仅用真实保存cover/checkpoint，不插值time-to-quality。',
                 '6. 没有阶段wall证据之前，不能宣称耗时已精确分摊；本快照仅支持CV MLE的CPU占比与超时所处阶段。\n',
                 '完整逐job轨迹与哈希见 bigclam-terminal-jobs.json；平表见 bigclam-terminal-jobs.csv。可重跑本离线脚本更新同一派生分析文件，原始终态结果与日志不修改。']
    (out / 'BIGCLAM_TERMINAL_LOG_REPORT_ZH.md').write_text('\n'.join(sections) + '\n')
    print(json.dumps({'captured_at_utc': captured, 'terminal_jobs': len(terminal), 'bigclam_jobs': len(rows),
                      'statuses': {str(k): v for k, v in status.items()},
                      'report': str((out / 'BIGCLAM_TERMINAL_LOG_REPORT_ZH.md').relative_to(ROOT))}, ensure_ascii=False))

if __name__ == '__main__':
    main()
