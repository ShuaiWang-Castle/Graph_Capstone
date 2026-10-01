"""Render the frozen prepared M6 cohort without imputing censored runtimes."""
from pathlib import Path
import argparse,collections,csv,hashlib,json,math,statistics,sys

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'results/m6_prepared'

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
    return h.hexdigest()

def load():
    summary=json.loads((RUN/'summary.json').read_text())
    manifest=json.loads((RUN/'manifest.json').read_text())
    config=json.loads((ROOT/'experiments/m6_prepared/config.json').read_text())
    rows=list(csv.DictReader((RUN/'query_summary.csv').open()))
    expected={q['query_id']:q for q in manifest['schedule']}
    if len(rows)!=108 or len({r['query_id'] for r in rows})!=108 or set(expected)!={r['query_id'] for r in rows}:
        raise RuntimeError('The plot requires all 108 planned query rows, including missing and failed outcomes')
    if summary['manifest_sha256']!=sha(RUN/'manifest.json') or summary['legacy_measurements_imported'] or manifest['legacy_measurements_imported']:
        raise RuntimeError('M6 cohort or version provenance differs')
    if manifest['config_sha256']!=sha(ROOT/'experiments/m6_prepared/config.json') or manifest['configuration']!=config:
        raise RuntimeError('M6 configuration snapshot differs')
    if summary['implementation_version']!=manifest['implementation_version'] or manifest['implementation_version']!=config['implementation_version']:
        raise RuntimeError('Summary, manifest and current configuration versions differ')
    for r in rows:
        r['n']=int(r['n'])
        if r['n']!=expected[r['query_id']]['n'] or r['case_id']!=expected[r['query_id']]['case_id'] or r['implementation_version']!=config['implementation_version']:
            raise RuntimeError('Mixed input or implementation versions are forbidden')
    if collections.Counter(r['status'] for r in rows)!=collections.Counter(summary['status_counts']):
        raise RuntimeError('CSV and summary status denominators differ')
    by_n={str(n):dict(collections.Counter(r['status'] for r in rows if r['n']==n)) for n in (10000,100000,1000000)}
    if by_n!=summary['status_counts_by_n'] or any(sum(counts.values())!=36 for counts in by_n.values()):
        raise RuntimeError('Each scale requires all 36 planned rows and matching status counts')
    if len({r['case_id'] for r in rows})!=9 or any(collections.Counter(r['case_id'] for r in rows)[r['case_id']]!=12 for r in rows):
        raise RuntimeError('The fixed nine graphs require 12 planned queries each')
    done=[r for r in rows if r['status']=='completed']
    if summary['scheduled_queries']!=108 or summary['completed_queries']!=len(done) or type(summary['all_queries_completed']) is not bool or summary['all_queries_completed']!=(len(done)==108):
        raise RuntimeError('Completion claims or totals differ')
    for r in done:
        for field in ('method_hot_wall_seconds','parent_process_wall_seconds','touched_over_output_volume','target_volume','touched_volume'):
            value=number(r,field)
            if value is None or value<=0:raise RuntimeError('Missing or invalid completed numeric field: '+field)
        value=number(r,'F1')
        if value is None or not 0<=value<=1:raise RuntimeError('Invalid completed F1')
    grouped=collections.defaultdict(list)
    for r in done:grouped[r['case_id']].append(r)
    graphs=summary['graph_summaries']
    if len(graphs)!=len(grouped) or {g['case_id'] for g in graphs}!=set(grouped):
        raise RuntimeError('Every completed graph requires exactly one matching graph summary')
    for g in graphs:
        actual=grouped[g['case_id']]
        if g['n']!=actual[0]['n'] or g['completed_queries']!=len(actual):raise RuntimeError('Graph summary denominator differs')
        for field in ('method_hot_wall_seconds','parent_process_wall_seconds','target_volume','touched_volume','touched_over_output_volume'):
            estimate=g['median_'+field]
            target=statistics.median(number(r,field) for r in actual)
            if not isinstance(estimate,(float,int)) or not math.isfinite(estimate) or not math.isclose(estimate,target,rel_tol=1e-12,abs_tol=1e-12):
                raise RuntimeError('Graph median differs from its actual completed queries: '+field)
    return summary,rows

def number(row,field):
    value=row.get(field)
    if value in ('',None):return None
    x=float(value)
    return x if math.isfinite(x) else None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='figures/m6/prepared_v001')
    parser.add_argument('--audit-receipt',default='results/m6_analysis/prepared_audit/receipt.json',
                        help='Separate verified offline raw/cohort audit; not a method-completion claim')
    args=parser.parse_args();out=(ROOT/args.output).resolve()
    if not out.is_relative_to(ROOT/'figures/m6'):parser.error('Output must remain in figures/m6')
    audit_path=(ROOT/args.audit_receipt).resolve()
    if not audit_path.is_relative_to(ROOT/'results/m6_analysis'):parser.error('Audit receipt must remain in results/m6_analysis')
    sys.path.insert(0,str(ROOT))
    from experiments.m6_analysis.audit import verify_audit_receipt
    audit=verify_audit_receipt(audit_path,run_path=RUN,verify_files=False)
    if audit.get('status')!='PASS' or audit.get('scheduled_queries')!=108:
        raise RuntimeError('A successful independent complete-plan integrity audit is required')
    summary,rows=load();out.mkdir(parents=True,exist_ok=True)
    if audit['manifest_sha256']!=summary['manifest_sha256'] or audit['summary_sha256']!=sha(RUN/'summary.json') or audit['query_csv_sha256']!=sha(RUN/'query_summary.csv') or audit['completed_queries']!=len([r for r in rows if r['status']=='completed']):
        raise RuntimeError('The integrity audit is bound to a different derived cohort view')
    completed=[r for r in rows if r['status']=='completed']
    provenance={'plot_source_sha256':sha(__file__),'summary_sha256':sha(RUN/'summary.json'),
                'query_csv_sha256':sha(RUN/'query_summary.csv'),'manifest_sha256':summary['manifest_sha256'],
                'integrity_audit':{'path':str(audit_path.relative_to(ROOT)),'receipt_sha256':sha(audit_path),
                                   'status':audit['status'],'cohort_origin':audit.get('cohort_origin'),
                                   'scheduled_queries':audit['scheduled_queries'],'completed_queries':audit['completed_queries']},
                'status_counts':summary['status_counts'],'planned_queries':108,'legacy_measurements_imported':False,
                'scope':'Completed-only hot costs and support volumes; timeout clocks never become completed hot cost; all statuses displayed'}
    if not completed:
        provenance.update(status='NOT_RUN',reason='No completed observations; no invented numeric chart')
        (out/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n');return
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'serif','font.serif':['Times New Roman','DejaVu Serif'],
                        'font.size':10,'axes.spines.top':False,'axes.spines.right':False,
                        'svg.fonttype':'none','pdf.fonttype':42})
    products=[]
    def save(fig,name):
        for suffix in ('pdf','svg','png'):
            target=out/(name+'.'+suffix);fig.savefig(target,dpi=180,bbox_inches='tight');products.append(target)
        plt.close(fig)
    ns=sorted({r['n'] for r in rows});colors=['#0072B2','#D55E00','#009E73']
    fig,axes=plt.subplots(1,2,figsize=(9,3.8))
    for n,color in zip(ns,colors):
        actual=[r for r in completed if r['n']==n]
        xs=[number(r,'method_hot_wall_seconds') for r in actual]
        ys=[number(r,'touched_over_output_volume') for r in actual]
        good=[(x,y) for x,y in zip(xs,ys) if x is not None and x>0 and y is not None and y>0]
        if good:
            axes[0].scatter([n]*len(good),[x for x,y in good],color=color,alpha=.45,s=18,
                            label=f'n={n:,}: {len(actual)}/36 completed')
            axes[1].scatter([n]*len(good),[y for x,y in good],color=color,alpha=.45,s=18)
    for graph in summary['graph_summaries']:
        axes[0].scatter(graph['n'],graph['median_method_hot_wall_seconds'],marker='D',s=34,c='black',zorder=4)
        axes[1].scatter(graph['n'],graph['median_touched_over_output_volume'],marker='D',s=34,c='black',zorder=4)
    axes[0].set(xscale='log',yscale='log',xlabel='Graph nodes n',ylabel='Completed method hot wall (s)')
    axes[1].set(xscale='log',yscale='log',xlabel='Graph nodes n',ylabel='Touched / output volume')
    axes[1].axhline(20,color='.45',ls='--',lw=1,label='Gate threshold 20')
    axes[0].legend(frameon=False,fontsize=8);axes[1].legend(frameon=False,fontsize=8)
    for ax in axes:ax.grid(alpha=.16)
    fit=summary['fits'].get('method_hot_wall_seconds_raw_logn',{})
    if fit.get('logn_slope') is not None:
        ci=fit.get('graph_cluster_bootstrap_95_ci')
        text=f"Completed-only graph-median slope: {fit['logn_slope']:.3f}"
        if ci:text+=f"; 95% CI [{ci[0]:.3f}, {ci[1]:.3f}]"
        fig.text(.5,-.025,text,ha='center',fontsize=9)
    save(fig,'scale_hot_cost_and_touched_ratio')
    fig,ax=plt.subplots(figsize=(6.3,3.5))
    for n,color in zip(ns,colors):
        good=[r for r in completed if r['n']==n and number(r,'method_hot_wall_seconds') and number(r,'F1') is not None]
        if good:ax.scatter([number(r,'method_hot_wall_seconds') for r in good],[number(r,'F1') for r in good],
                           color=color,s=25,alpha=.6,label=f'n={n:,}: {len(good)}/36 completed')
    ax.set(xscale='log',xlabel='Completed method hot wall (s)',ylabel='F1',ylim=(-.02,1.04))
    ax.grid(alpha=.16);ax.legend(frameon=False,fontsize=8);save(fig,'quality_vs_hot_cost')
    # Censoring is a separate process-clock panel. A timeout arrow at the
    # observed parent clock denotes a lower bound, not a completion time.
    fig,ax=plt.subplots(figsize=(6.3,3.5))
    for n,color in zip(ns,colors):
        done=[r for r in completed if r['n']==n and number(r,'parent_process_wall_seconds')]
        if done:ax.scatter([n]*len(done),[number(r,'parent_process_wall_seconds') for r in done],color=color,alpha=.4,s=18)
        censored=[r for r in rows if r['n']==n and r['status'] in ('timeout','memory_limit') and number(r,'parent_process_wall_seconds')]
        if censored:ax.scatter([n]*len(censored),[number(r,'parent_process_wall_seconds') for r in censored],
                               facecolors='none',edgecolors=color,marker='^',s=48,label=f'n={n:,}: {len(censored)} censored')
    ax.set(xscale='log',yscale='log',xlabel='Graph nodes n',ylabel='Observed parent process clock (s)')
    ax.grid(alpha=.16)
    if ax.get_legend_handles_labels()[0]:ax.legend(frameon=False,fontsize=8)
    save(fig,'process_clock_censoring')
    fig,ax=plt.subplots(figsize=(6.3,3.2));bottom=[0]*len(ns)
    statuses=sorted({r['status'] for r in rows});palette=plt.get_cmap('tab10')
    for index,status in enumerate(statuses):
        vals=[sum(r['n']==n and r['status']==status for r in rows) for n in ns]
        ax.bar([str(n) for n in ns],vals,bottom=bottom,label=status,color=palette(index))
        bottom=[a+b for a,b in zip(bottom,vals)]
    ax.set(xlabel='Graph nodes n',ylabel='Planned queries (36 per scale)',ylim=(0,40));ax.legend(frameon=False,fontsize=8)
    save(fig,'completion_denominators')
    caption='''# M6 图注与口径

所有图只用 `results/m6_prepared` 的固定108-query cohort，不引入旧实现结果。每档三个独立生成图、36个预定query。失败、超时、未运行均留在CSV与分母图。

`scale_hot_cost_and_touched_ratio`：完成query的实际算法hot wall与触及/输出volume；黑菱形为各图完成子集的中位数。hot包含完整扩散、sweep、MM、区域证书和checkpoint写入，不含预热/输入加载/离线真值评价。completed-only logn斜率与图级bootstrap只描述完成子集；存在删失时不据此宣布G-E3通过。横虚线20为登记关卡值。数学支撑volume不是全部内存/IO访问的计量。

`quality_vs_hot_cost`：每个完成query的实际F1与hot时间，包括快速但质量低的输出。没有将低质量快例包装为同质量加速。

`process_clock_censoring`：完成query的parent总时钟，与timeout/memory-limit的观测时钟分别绘制。空心上三角表示删失下界，包含启动/预热等；它不是hot完成时间，也不属于completed cohort。方法产物可能部分完成，也可能在完整方法证书保存后、离线评价或序列化时截断，须按原始阶段与文件另列，不能统一宣称没有证书。

`completion_denominators`：全部108任务的最新attempt状态，原中断attempt仍保留在raw目录，不重复当成独立query。

SVG/PDF是可导出的矢量图，PNG供视觉核验。若最终仍有未完成任务，所有图和斜率明确为partial/completed-only，不补造结果。
'''
    (out/'CAPTIONS_ZH.md').write_text(caption)
    provenance.update(status='COMPLETED',figure_sha256={p.name:sha(p) for p in products},
                      matplotlib_version=matplotlib.__version__,full_cohort_completed=summary['all_queries_completed'])
    (out/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps({'figures':len(products),'planned':108,'completed':len(completed)}))

if __name__=='__main__':main()
