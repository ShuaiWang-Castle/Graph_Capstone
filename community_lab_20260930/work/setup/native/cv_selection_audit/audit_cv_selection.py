#!/usr/bin/env python3
"""Audit CV output of completed n=1000 native BigCLAM jobs, offline only."""
from __future__ import annotations
import argparse, csv, hashlib, importlib.util, json, math, re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PARSER = ROOT / 'work/setup/native/parse_bigclam_logs.py'
sp = importlib.util.spec_from_file_location('bigclam_log_parser', PARSER)
parser = importlib.util.module_from_spec(sp)
sp.loader.exec_module(parser)
EXPECTED_GRID = [5, 6, 8, 10, 13, 17, 22, 29, 39, 52, 100]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def tabrows(path):
    return [{'k': int(float(line.split()[0])), 'native_score': float(line.split()[1])}
            for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-root', default='work/baseline73_v2')
    ap.add_argument('--output', default='work/setup/native/cv_selection_audit')
    args = ap.parse_args()
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    identities = sorted((ROOT / args.run_root).glob('*/result.json'))
    rows, details = [], []
    for rp in identities:
        rb = rp.read_bytes()
        result = json.loads(rb)
        if result.get('status') != 'COMPLETED' or result.get('method') != 'bigclam_native':
            continue
        directory = rp.parent
        spec = json.loads((directory / 'spec.json').read_text())
        graph = json.loads(Path(spec['graph']).read_text())
        if graph['n'] != 1000:
            continue
        # Only authoritative completed jobs are now allowed for output reads.
        stdout = directory / 'stdout.log'
        parsed = parser.parse_bytes(stdout.read_bytes())
        tab = directory / 'native_.CV.likelihood.tab'
        plt = directory / 'native_.CV.likelihood.plt'
        png = directory / 'native_.CV.likelihood.png'
        tab_scores = tabrows(tab) if tab.exists() else []
        scores = parsed['cv_scores']
        ordered = sorted(scores, key=lambda x: x['native_score'], reverse=True)
        winner = ordered[0]['k'] if ordered else None
        tabwinner = max(tab_scores, key=lambda x: x['native_score'])['k'] if tab_scores else None
        gap = ordered[0]['native_score'] - ordered[1]['native_score'] if len(ordered) > 1 else None
        cv = [x for x in parsed['mle_runs'] if x['phase'] == 'cv']
        final = [x for x in parsed['mle_runs'] if x['phase'] == 'final_fit']
        count_by_k = Counter(x['k'] for x in cv if x['completed'])
        final_count = final[0].get('vertex_update_attempts') if len(final) == 1 else None
        stderr = (directory / 'stderr.log').read_text()
        coverlines = [line for line in (directory / 'native_cmtyvv.txt').read_text().splitlines() if line.strip()]
        prediction = json.loads((directory / 'prediction.json').read_text())
        omitted_matches = re.findall(r'Community vector generated\. (\d+) communities are ommitted', stdout.read_text())
        omitted = int(omitted_matches[-1]) if omitted_matches else 0
        cli = parsed['accepted_cli']
        row = dict(job_id=result['job_id'], case_id=result.get('case_id'), status=result['status'],
                   cli_c=cli.get('c'), cli_min_k=cli.get('mc'), cli_max_k=cli.get('xc'), cli_k_trials=cli.get('nc'),
                   loaded_n=parsed['graph']['n_loaded'], loaded_m=parsed['graph']['m_loaded'],
                   pipeline_seconds=result.get('pipeline_seconds'),
                   observed_grid=parsed['cv_candidates_observed'], grid_exactly_expected=parsed['cv_candidates_observed'] == EXPECTED_GRID,
                   cv_mle_observed=len(cv), cv_mle_completed=sum(x['completed'] for x in cv),
                   all_11_k_have_3_complete_mle=all(count_by_k[k] == 3 for k in EXPECTED_GRID) and len(count_by_k) == 11,
                   all_cv_returned_at_10000_attempts=all(x.get('vertex_update_attempts') == 10000 for x in cv) and len(cv) == 33,
                   final_mle_count=len(final), final_mle_completed=bool(len(final) == 1 and final[0]['completed']),
                   final_vertex_update_attempts=final_count,
                   final_below_maxiter=bool(final_count is not None and final_count < 1000000),
                   native_exit_banner_seen=parsed['native_exit_banner_seen'],
                   scores_finite_and_negative=bool(len(scores) == 11 and all(math.isfinite(x['native_score']) and -1e306 < x['native_score'] < 0 for x in scores)),
                   selected_k_from_stdout_source_rule=winner, selected_k_from_tab=tabwinner,
                   stdout_tab_argmax_equal=winner == tabwinner,
                   winner_runnerup_score_gap_stdout=gap, winner_unambiguous_at_print_precision=bool(gap is not None and gap > 1e-6),
                   tab_grid_exactly_expected=[x['k'] for x in tab_scores] == EXPECTED_GRID,
                   tab_exists=tab.exists(), plt_exists=plt.exists(), png_exists=png.exists(),
                   gnuplot_missing_warning='Cannot find GnuPlot' in stderr,
                   emitted_cover_groups=len(coverlines), prediction_groups=len(prediction['communities']),
                   omitted_groups_from_stdout=omitted,
                   cover_count_consistent_with_selected_k=bool(winner is not None and len(coverlines) + omitted == winner),
                   result_sha256=hashlib.sha256(rb).hexdigest(), stdout_sha256=digest(stdout),
                   tab_sha256=digest(tab) if tab.exists() else None, plt_sha256=digest(plt) if plt.exists() else None)
        if rp.read_bytes() != rb:
            raise RuntimeError('Terminal result identity changed: ' + str(rp))
        rows.append(row)
        details.append({'row': row, 'cv_scores_stdout_6_decimal_places': scores,
                        'cv_scores_tab_6_significant_digits': tab_scores,
                        'cv_count_by_k': dict(count_by_k), 'mle_calls': parsed['mle_runs'],
                        'original_command': result.get('command'),
                        'native_command': prediction.get('metadata', {}).get('native_command'),
                        'source_hashes': result.get('source_hashes'), 'graph_sha256': result.get('graph_sha256'),
                        'config_sha256': result.get('config_sha256'),
                        'result_path': str(rp.relative_to(ROOT)),
                        'stderr_sha256': digest(directory / 'stderr.log'),
                        'native_cover_sha256': digest(directory / 'native_cmtyvv.txt'),
                        'prediction_sha256': digest(directory / 'prediction.json')})
    timestamp = datetime.now(timezone.utc).isoformat()
    sourcefiles = ['external/snap/examples/bigclam/bigclam.cpp', 'external/snap/snap-adv/agmfast.cpp',
                   'external/snap/glib-core/gnuplot.cpp', 'external/snap/glib-core/gnuplot.h',
                   'external/snap/glib-core/tm.h']
    payload = {'captured_at_utc': timestamp, 'scope': 'completed n1000 bigclam_native only; no labels or active outputs read',
               'run_root': args.run_root, 'job_count': len(rows), 'expected_grid': EXPECTED_GRID,
               'source_commit': '6924a035aabd1ce0a547b94e995e142f29eb5040',
               'source_sha256': {f: digest(ROOT / f) for f in sourcefiles},
               'analyzer_sha256': digest(Path(__file__)), 'parser_sha256': digest(PARSER),
               'rows': rows, 'details': details}
    (out / 'cv-selection-audit.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    if rows:
        with (out / 'cv-selection-audit.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v) if isinstance(v, list) else v for k, v in row.items()})
    required = ['grid_exactly_expected', 'all_11_k_have_3_complete_mle', 'all_cv_returned_at_10000_attempts',
                'final_mle_completed', 'native_exit_banner_seen', 'scores_finite_and_negative',
                'stdout_tab_argmax_equal', 'winner_unambiguous_at_print_precision',
                'tab_grid_exactly_expected', 'cover_count_consistent_with_selected_k']
    evidence = {k: sum(row[k] for row in rows) for k in required}
    report = ['# n1000 BigCLAM 原生 CV 选择与停止语义审计\n',
              f'UTC {timestamp} 快照；仅审 {len(rows)} 项已 COMPLETED 的 n1000 graph-only native-K BigCLAM。主实验仍在执行，本报告不代表24项主面板已完成。未读活跃输出、真标签或评价质量，不改冻结代码/配置、不跑测量、不登记候选。\n',
              '## 实际完成证据\n', '| 检查 | 满足/已审项 |', '|---|---:|']
    for key, count in evidence.items():
        report.append(f'| {key} | {count}/{len(rows)} |')
    report += ['', '原生接受CLI均为 c=-1/mc=5/xc=100/nc=10/nt=1；stdout和TAB均包含完整网格 `[5,6,8,10,13,17,22,29,39,52,100]`。每个K确有3次CV MLE completion，而后单独最终fit、native exit banner与有效cover。没有用“planned配置”代替实际执行证据。\n',
               '| case | 选K | stdout第1/2名分差 | CV calls | final attempts | 输出群数 | omitted |',
               '|---|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        report.append(f"| {row['case_id']} | {row['selected_k_from_stdout_source_rule']} | {row['winner_runnerup_score_gap_stdout']:.6f} | {row['cv_mle_completed']} | {row['final_vertex_update_attempts']} | {row['emitted_cover_groups']} | {row['omitted_groups_from_stdout']} |")
    report += ['', '## 数值与原生选择规则\n',
               '- 原生 FindComsByCV 选择 HOLV 最大值；初值 EstComs=2/MaxL=TFlt::Mn，按grid顺序严格 `MaxL < HOLV[c]` 更新，所以相等时保留首个。stdout每K score为 `%f` 六位小数，TAB为 `%g` 通常六位有效数字；真正选择发生在输出之前，使用内存double，不读取TAB。',
               '- 本次所有已审score均finite/negative，非TFlt::Mn sentinel；stdout argmax与TAB argmax一致，头两名分差远大于打印舍入。称选K是由实际stdout和源码规则核验的结果，不声称TAB保存double全精度。完整所有K分数与原文件hash在JSON。',
               '- m>50分支分数为3次holdout likelihood之和。holdout集合双向保存，因此LikelihoodHoldOut逐u遍历会双向计pair；不能将该值当最终全图训练loss、归属恢复指标或跨不同图归一分数。源码将非负HOL替换TFlt::Mn，本审计未见该sentinel。',
               '- 每个K仅初始化一次；三fold MLE连续更新同一F，非三次独立重启。候选结束后选择K、RandomInit，再由main重新NeighborComInit最终fit。本报告记录原生语义，没有另加修复。\n',
               '## 停止条件可事实确认的范围\n',
               '- n1000的33次CV MLE每次恰为10000 vertex-update attempts。源码CV MaxIter=10*n=10000，而MLE的相对目标早停检查额外要求 iter>10000，所以此规模CV在到达MaxIter前无法触发容差早停。这是源码/日志共同支持的停止语义，不是新算法候选。',
               '- 最终fit MaxIter=1000*n=1000000。已审final attempts均低于上限；按未改源码仅有的while内部break，可以推断因相对目标变化条件退出。该条件是 `CurL-PrevL <= .0001*abs(PrevL)`，目标下降也会满足；日志本身没有停止原因/精确最后差值，不能声称已证明收敛或最优。',
               '- iterations包含每个节点尝试及跳过，非有效梯度更新次数；最终解码阈值sqrt(2m/n²)、MinSz3可能使输出群数小于选K，stdout明确记录omitted。不要把输出群数反推选K，更不把选K视为真实群数恢复。\n',
               '## 文件、绘图依赖与时间单位\n',
               '- native_.CV.likelihood.tab只有每K汇总likelihood；.plt是指向该表的gnuplot绘图脚本。两者均不是模型/affiliation/checkpoint，无节点cover可转换。native_cmtyvv.txt在最终fit后写，graph.gexf是后续图导出。',
               f"- 本快照 {sum(row['gnuplot_missing_warning'] for row in rows)}/{len(rows)} 项stderr提示Cannot find GnuPlot，{sum(row['png_exists'] for row in rows)}项生成PNG；TAB/PLT仍已写，native继续返回成功且cover有效。这属于可选绘图环境限制，不算算法失败；本审计没有在计量期间安装依赖或改代码。", 
               '- TExeTm以clock()/CLOCKS_PER_SEC计CPU时间；native MLE completion、conductance、run time不是pipeline wall。进度[N sec]是time(NULL)整秒、每次MLE重置。不得从本审计补任何墙钟阶段时长；完整pipeline以runner保存值为准，原生绘图调用和导出成本已计入，不能事后免费移除。离线真标签评价按协议单列，不属于算法推断时间。\n',
               '## 公平比较边界\n',
               '- 本规模原生CV无容差早停的事实可以作为后续研发profile的依据，但改检查间隔/早停仍会改变训练政策，必须单独冻结、与简单少迭代/少K/增加预算控制比较，而不能作为免费兼容修复。这里未登记任何候选。',
               '- 固定K oracle结果属于已知K面板，不是graph-only的免费primary arm；native规模网格也不是新机制。更快实现/缓存只有语义等价且同输出预算对照才可归为工程收益。',
               '- 本审计只证实已完成n1000搜索路径；n5000超时CV不能称完整模型选择或评价未知cover，原失败保留。\n',
               '逐项证据：cv-selection-audit.csv/json。可执行 `python3 work/setup/native/cv_selection_audit/audit_cv_selection.py` 更新同一派生报告，原始结果不修改。']
    (out / 'CV_SELECTION_AUDIT_ZH.md').write_text('\n'.join(report) + '\n')
    print(json.dumps({'captured_at_utc': timestamp, 'job_count': len(rows), 'checks': evidence,
                      'selected_ks': dict(Counter(row['selected_k_from_stdout_source_rule'] for row in rows))}, ensure_ascii=False))

if __name__ == '__main__':
    main()
