#!/usr/bin/env python3
"""Integrate terminal group tables without rescoring, imputation or inference."""
from pathlib import Path
import argparse, collections, csv, datetime, hashlib, json, statistics
ROOT=Path(__file__).resolve().parents[1]
def load(p):return json.loads(p.read_text())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
 p=argparse.ArgumentParser();p.add_argument('--groups',required=True);p.add_argument('--output',default='analysis');p.add_argument('--plot',action='store_true');p.add_argument('--plot-only',action='store_true');a=p.parse_args()
 groups=load(ROOT/a.groups)['groups'];out=ROOT/a.output;out.mkdir(parents=True,exist_ok=True)
 if a.plot_only:
  if not a.plot:raise ValueError('--plot-only requires --plot')
  render(load(out/'results.json'),out);return
 for f in ['results.json','results.csv','integrated_manifest.json']:
  if (out/f).exists():raise FileExistsError('Preserve prior integration; use a new directory: '+str(out/f))
 rows=[];manifest=[];seen=set();summaries=[]
 for g in groups:
  planp=ROOT/g['plan'];catp=ROOT/g['catalog'];resultp=ROOT/g['analysis']/'results.json';plan=load(planp);cat={c['case_id']:c for c in load(catp)};rr=load(resultp)
  jobs={j['job_id']:j for j in plan['jobs']}
  if len(jobs)!=len(plan['jobs']) or len({r['job_id'] for r in rr})!=len(rr) or set(jobs)!={r['job_id'] for r in rr}:raise ValueError('Whole planned denominator mismatch: '+g['name'])
  for r in rr:
   if r['job_id'] in seen:raise ValueError('Duplicate job across groups: '+r['job_id'])
   seen.add(r['job_id']);j=jobs[r['job_id']];c=cat[j['case_id']]
   for k in ['case_id','method','information_policy','device','threads','seed']:
    if r.get(k)!=j.get(k):raise ValueError('Planned identity mismatch: '+k)
   recp=ROOT/g['run_root']/r['job_id']/'result.json';raw=load(recp)
   for k in ['status','pipeline_seconds','peak_tree_rss_bytes','prediction_kind']:
    if r.get(k)!=raw.get(k):raise ValueError('Raw measurement mismatch: '+k)
   n=c.get('n',c.get('requested',{}).get('n'))
   seed=c.get('seed',c.get('requested',{}).get('seed'))
   rows.append({**r,'phase_group':g['name'],'graph_n':n,'graph_seed':seed,'graph_split':c.get('split'),'graph_sha256':j.get('graph_sha256'),'group_plan':g['plan'],'group_analysis':g['analysis'],'raw_measurement_path':str(recp.relative_to(ROOT))})
  manifest.append({'group':g['name'],'planned_jobs':len(jobs),'plan':g['plan'],'plan_sha256':digest(planp),'catalog':g['catalog'],'catalog_sha256':digest(catp),'analysis':str(resultp.relative_to(ROOT)),'analysis_sha256':digest(resultp)})
 by=collections.defaultdict(list)
 for r in rows:by[(r['phase_group'],r['method'],r['information_policy'],r['device'],r['threads'],r['graph_n'])].append(r)
 for key,rs in sorted(by.items(),key=lambda x:tuple(str(v) for v in x[0])):
  done=[r for r in rs if r['status']=='COMPLETED' and r['metric_status']=='SCORED'];entry=dict(zip(['phase_group','method','information_policy','device','threads','graph_n'],key));entry.update(planned=len(rs),status_counts=dict(collections.Counter(r['status'] for r in rs)),metric_status_counts=dict(collections.Counter(r['metric_status'] for r in rs)),completed_scored=len(done))
  for k in ['pipeline_seconds','matched_macro_f1','matched_membership_micro_f1']:
   v=[r[k] for r in done if r.get(k) is not None];entry['completed_scored_median_'+k]=statistics.median(v) if v else None
  summaries.append(entry)
 write(out/'results.json',rows);keys=list(dict.fromkeys(k for r in rows for k in r))
 with (out/'results.csv').open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,keys);w.writeheader();w.writerows(rows)
 write(out/'integrated_manifest.json',{'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'groups':manifest,'planned_rows_retained':len(rows),'status_counts':dict(collections.Counter(r['status'] for r in rows)),'no_new_inference_or_score':True,'cost_definition':'Saved complete child-process pipeline; no timeout completion imputation; diagnostic costs excluded.','memory_definition':'Saved approximately0.2s sampled tree RSS; not true OS peak or hard memory guarantee.','statistical_policy':'Descriptive related parameter/graph/algorithm-seed grid, not IID trials or an aggregated Pareto frontier.','source_sha256':digest(Path(__file__)),'summary':summaries})
 if a.plot:render(rows,out)
 print(json.dumps({'planned_rows_retained':len(rows),'groups':len(groups),'output':str(out.relative_to(ROOT))}))
def render(rows,out):
 import matplotlib;matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 from matplotlib.ticker import LogLocator,NullFormatter,FuncFormatter
 panels=collections.defaultdict(list)
 for r in rows:
  if r['status']=='COMPLETED' and r['metric_status']=='SCORED' and r.get('pipeline_seconds') is not None:panels[(r['information_policy'],r['device'],r['threads'],r['graph_n'],r['graph_split'])].append(r)
 for panel,rs in panels.items():
  fig,axes=plt.subplots(1,2,figsize=(14,6));methods=sorted({r['method'] for r in rs})
  for ax,quality in zip(axes,['matched_macro_f1','matched_membership_micro_f1']):
   for i,m in enumerate(methods):
    z=[r for r in rs if r['method']==m and r.get(quality) is not None];ax.scatter([r['pipeline_seconds'] for r in z],[r[quality] for r in z],label=m,s=24,alpha=.65,color=plt.get_cmap('tab20')(i%20))
   ax.set_xscale('log');ax.xaxis.set_major_locator(LogLocator(base=10,subs=(1,2,5),numticks=7));ax.xaxis.set_major_formatter(FuncFormatter(lambda value,pos:f'{value:g}'));ax.xaxis.set_minor_formatter(NullFormatter());ax.set_xlabel('Complete child-process pipeline (seconds)');ax.set_ylabel(quality);ax.set_ylim(0,1.03);ax.grid(alpha=.15)
  axes[1].legend(loc='upper left',bbox_to_anchor=(1.02,1),fontsize=6)
  fig.suptitle(f'Completed scored runs: {panel[0]}, {panel[1]}, requested threads={panel[2]}, n={panel[3]}, split={panel[4]}')
  fig.text(.02,.02,'All planned failures/unknown qualities remain in CSV/JSON. Correlated graph/algorithm repeats; descriptive scatter, not a pooled frontier.',fontsize=8)
  fig.tight_layout(rect=(0,.06,.83,.95));name='quality_cost_'+('_'.join(str(x) for x in panel))+'.png';fig.savefig(out/name,dpi=140);plt.close(fig)
if __name__=='__main__':main()
