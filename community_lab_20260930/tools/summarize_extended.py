#!/usr/bin/env python3
"""Offline supplementary metrics and stage records; never passed to adapters."""
from pathlib import Path
import sys,json,argparse,csv,re,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.io import read_json,write_json,cover,graph,sha256
from lab.metrics_onmi_sparse import compute_onmi_sparse as compute_onmi

def main():
 p=argparse.ArgumentParser();p.add_argument('--catalog',required=True);p.add_argument('--plan',required=True);p.add_argument('--run-root',required=True);p.add_argument('--analysis',required=True);a=p.parse_args()
 catalog={c['case_id']:c for c in read_json(a.catalog)};plan=read_json(a.plan);out=Path(a.analysis)
 if sha256(a.catalog)!=plan['catalog_sha256']:raise ValueError('catalog hash changed')
 rows=read_json(out/'results.json');stages=[]
 for row in rows:
  job=row['job_id'];d=Path(a.run_root)/job;rfile=d/'result.json'
  if not rfile.exists():continue
  r=read_json(rfile);c=catalog[row['case_id']]
  if row.get('metric_status')=='SCORED':
   pred=r['prediction'];n,_=graph(c['graph'])
   if sha256(pred)!=r['prediction_sha256'] or sha256(c['truth'])!=c['truth_sha256']:raise ValueError('frozen output/truth changed')
   t,_=cover(c['truth'],n);pr,_=cover(pred,n)
   pf=out/'per_job'/(job+'.json');details=read_json(pf);m=details['metrics']
   if 'onmi_supplement' not in details:
    begin=time.perf_counter();details['onmi_supplement']=compute_onmi(t,pr,n);details['onmi_evaluation_seconds']=time.perf_counter()-begin;write_json(pf,details)
   onmi=details['onmi_supplement'];row.update(onmi=onmi['onmi'],onmi_status=onmi['onmi_status'],at_least_two_correct_recall=m['at_least_two_correct_recall'],small_group_mean_matched_f1=m['small_group_mean_matched_f1'],small_group_size_cutoff=m['small_group_size_cutoff'],pred_node_coverage=m['pred_node_coverage'])
   for name in ['overlap_node','extra_membership_after_first']:
    for k in ['precision','recall','f1']:row[name+'_'+k]=m[name][k]
   prediction=read_json(pred);stage={'job_id':job,'case_id':row['case_id'],'method':row['method'],'pipeline_seconds':row['pipeline_seconds'],'status':row['status'],'stage_seconds':prediction.get('stage_seconds',{}),'metadata':prediction.get('metadata',{})}
   logfile=d/'stdout.log'
   if row['method'].startswith('highway_native') and logfile.exists():
    log=logfile.read_text(errors='replace');stage['native_stage_seconds']={k:float(v) for k,v in re.findall(r'^\s+(\w+) = ([0-9.]+)s$',log,re.M)}
    stage['native_summary']={k:v for k,v in re.findall(r'^\s+(\w+)=([0-9.]+)$',log,re.M)}
   stages.append(stage)
 write_json(out/'results.json',rows);keys=list(dict.fromkeys(k for r in rows for k in r))
 with open(out/'results.csv','w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
 write_json(out/'stage_records.json',stages)
 print(str(out/'results.csv'))
if __name__=='__main__':main()
