#!/usr/bin/env python3
from __future__ import annotations
import argparse,sys,json,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.io import read_json,write_json
from lab.runner import run_job

def main():
    p=argparse.ArgumentParser();p.add_argument('--plan',required=True);p.add_argument('--run-root',default=str(ROOT/'work/runs'))
    p.add_argument('--max-job-wall-hours',type=float,default=24);a=p.parse_args()
    jobs=read_json(a.plan)['jobs'];runroot=Path(a.run_root);runroot.mkdir(parents=True,exist_ok=True)
    budget=a.max_job_wall_hours*3600
    for job in jobs:
        used=sum(read_json(f).get('pipeline_seconds',0) for f in runroot.glob('*/result.json'))
        remaining=max(0,budget-used)
        session=ROOT/'work/state.json'
        if session.exists():
            deadline=datetime.fromisoformat(read_json(session)['deadline'])
            remaining=min(remaining,max(0,(deadline-datetime.now(timezone.utc)).total_seconds()))
        try:r=run_job(job,ROOT,runroot,remaining)
        except Exception as e:
            print(json.dumps({'job_id':job['job_id'],'status':'PLAN_ERROR','error':str(e)}),flush=True)
            raise
        print(json.dumps({k:r.get(k) for k in ['job_id','status','pipeline_seconds','prediction_kind']},ensure_ascii=False),flush=True)
        if r['status']=='INTERRUPTED':break
    rows=[read_json(f) for f in sorted(runroot.glob('*/result.json'))]
    write_json(runroot/'run_records.json',rows)
if __name__=='__main__':main()
