#!/usr/bin/env python3
from __future__ import annotations
import argparse,sys,csv,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.io import read_json,write_json,graph,cover,sha256
from lab.metrics import score

def main():
    p=argparse.ArgumentParser();p.add_argument('--catalog',required=True);p.add_argument('--plan',required=True)
    p.add_argument('--run-root',default=str(ROOT/'work/runs'));p.add_argument('--output',default=str(ROOT/'work/analysis'))
    p.add_argument('--plot',action='store_true');a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    plan=read_json(a.plan)
    if plan.get('catalog_sha256') and sha256(a.catalog)!=plan['catalog_sha256']:
        raise ValueError('Catalog changed after the job-plan freeze')
    cat={r['case_id']:r for r in read_json(a.catalog)};rows=[]
    for j in plan['jobs']:
        f=Path(a.run_root)/j['job_id']/'result.json'
        r=read_json(f) if f.exists() else {'status':'NOT_RUN','pipeline_seconds':None}
        row={k:j.get(k) for k in ['job_id','case_id','method','information_policy','device','threads','seed']}
        row.update({k:r.get(k) for k in ['status','pipeline_seconds','peak_tree_rss_bytes','prediction_kind']})
        row.update(matched_macro_f1=None,matched_membership_micro_f1=None,overlap_f1=None,extra_membership_recall=None,predicted_groups=None,metric_status='NO_PREDICTION')
        c=cat[j['case_id']]
        if r.get('prediction') and r.get('prediction_kind')!='invalid' and c.get('truth'):
            t0=time.perf_counter()
            try:
                for path,digest,kind in [(c['graph'],j.get('graph_sha256'),'graph'),(c['truth'],c.get('truth_sha256'),'truth'),(r['prediction'],r.get('prediction_sha256'),'prediction')]:
                    if not digest:raise ValueError('Missing frozen '+kind+' SHA-256; cannot score unverifiable input')
                    if sha256(path)!=digest:raise ValueError(kind+' changed after measurement/freeze')
                if read_json(c['truth']).get('labels_complete') is not True:raise ValueError('PARTIAL_LABELS_NOT_SCORABLE_BY_THIS_PROTOCOL')
                n,_=graph(c['graph']);t,_=cover(c['truth'],n);pred,audit=cover(r['prediction'],n);s=score(t,pred,n)
                write_json(out/'per_job'/(j['job_id']+'.json'),{'metrics':s,'normalization':audit,
                    'evaluation_provenance':{'graph_sha256':sha256(c['graph']),'truth_sha256':sha256(c['truth']),
                    'prediction_sha256':sha256(r['prediction']),'metrics_source_sha256':sha256(ROOT/'lab/metrics.py'),
                    'summarize_source_sha256':sha256(Path(__file__))}})
                row.update(matched_macro_f1=s['matched_macro_f1'],matched_membership_micro_f1=s['matched_membership_micro']['f1'],
                           overlap_f1=s['overlap_node']['f1'],extra_membership_recall=s['extra_membership_after_first']['recall'],
                           predicted_groups=s['predicted_groups'],metric_status='SCORED')
            except Exception as e:
                row.update(metric_status='SCORING_ERROR',metric_error=str(e))
                write_json(out/'per_job'/(j['job_id']+'.json'),{'metric_status':'SCORING_ERROR','metric_error':str(e)})
            row['evaluation_seconds']=time.perf_counter()-t0
        rows.append(row)
    write_json(out/'results.json',rows)
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with open(out/'results.csv','w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
    lines=['# Baseline status report','', 'All planned jobs are retained. Timeouts are not completed times; partial checkpoint quality is labeled separately.', '', '| Method / policy / device | Planned | Completed | Other statuses |', '|---|---:|---:|---|']
    from collections import Counter,defaultdict
    groups=defaultdict(list)
    for r in rows:groups[(r['method'],r['information_policy'],r['device'])].append(r)
    for key,rs in sorted(groups.items()):
        counts=Counter(x['status'] for x in rs);done=counts.pop('COMPLETED',0)
        lines.append(f'| {" / ".join(map(str,key))} | {len(rs)} | {done} | {dict(counts)} |')
    lines+=['','No grand average treats graph seeds, hyperparameters or algorithms as independent datasets.','Per-case quality/cost tables and stage traces are the inputs to the next diagnosis, not a proof of novelty.']
    (out/'STATUS_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    if a.plot:
        import matplotlib;matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        # One figure for each comparable information/resource panel. No interpolation from partial results.
        panels=defaultdict(list)
        for r in rows:
            if r['metric_status']=='SCORED' and r['pipeline_seconds'] is not None:panels[(r['information_policy'],r['device'])].append(r)
        for panel,rs in panels.items():
            fig,ax=plt.subplots(figsize=(8,5))
            for method in sorted({r['method'] for r in rs}):
                subset=[r for r in rs if r['method']==method and r['status']=='COMPLETED']
                if subset:ax.scatter([r['pipeline_seconds'] for r in subset],[r['matched_macro_f1'] for r in subset],label=method,alpha=.75)
            ax.set_xscale('log');ax.set_xlabel('Complete adapter pipeline time (s)');ax.set_ylabel('One-to-one matched cover macro F1')
            ax.set_title('Completed development runs: '+str(panel));ax.legend(fontsize=8);fig.tight_layout()
            fig.savefig(out/('quality_cost_'+str(panel[0])+'_'+str(panel[1])+'.png'),dpi=160);plt.close(fig)
    print(out/'results.csv')
if __name__=='__main__':main()
