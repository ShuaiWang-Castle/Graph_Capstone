#!/usr/bin/env python3
"""Fetch source code only; never execute installers or build scripts automatically."""
from __future__ import annotations
import argparse,subprocess,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.io import read_json,write_json

def git(args,cwd=None):
    return subprocess.check_output(['git',*args],cwd=cwd,text=True,stderr=subprocess.STDOUT,timeout=180).strip()
def main():
    p=argparse.ArgumentParser();p.add_argument('--registry',default=str(ROOT/'configs/sources.json'))
    p.add_argument('--only',nargs='*');p.add_argument('--dest',default=str(ROOT/'external'))
    a=p.parse_args();dest=Path(a.dest).resolve();dest.mkdir(parents=True,exist_ok=True)
    rows=[]
    for s in read_json(a.registry)['sources']:
        if a.only and s['id'] not in a.only:continue
        path=dest/s['id'];row={'id':s['id'],'url':s['git_url'],'path':str(path),'requested_ref':s.get('ref')}
        try:
            if path.exists():
                origin=git(['remote','get-url','origin'],path)
                if origin.rstrip('/').removesuffix('.git')!=s['git_url'].rstrip('/').removesuffix('.git'):
                    raise ValueError('Existing path has a different origin; not modified')
                if git(['status','--porcelain'],path):raise ValueError('Existing tree is dirty; not modified')
            else:
                git(['clone','--depth','1',s['git_url'],str(path)])
                if s.get('ref'):
                    git(['fetch','--depth','1','origin',s['ref']],path)
                    git(['checkout','--detach','FETCH_HEAD'],path)
            row['commit']=git(['rev-parse','HEAD'],path)
            if s.get('ref') and row['commit']!=s['ref']:raise ValueError('Pinned commit mismatch; existing source was not reset')
            row['status']='FETCHED_NOT_INSTALLED'
        except Exception as e:row.update(status='UNAVAILABLE',error=str(e))
        rows.append(row);print(json.dumps(row,ensure_ascii=False))
    out=dest/'SOURCE_LOCK.json'
    previous=read_json(out) if out.exists() else {'sources':[]}
    prior={r['id']:r for r in previous['sources']}
    prior.update({r['id']:r for r in rows});write_json(out,{'sources':list(prior.values()),'note':'Inspect licenses, APIs and build scripts before execution. Preserve this source lock in every freeze.'})
if __name__=='__main__':main()
