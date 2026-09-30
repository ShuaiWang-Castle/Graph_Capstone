#!/usr/bin/env python3
"""Persist a non-resetting research-round deadline. Resume does not grant more time."""
from __future__ import annotations
import argparse,sys,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.io import read_json,write_json

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['start','status','phase'])
    p.add_argument('--hours',type=float,default=24);p.add_argument('--name',default='setup');p.add_argument('--next-command',default='')
    a=p.parse_args();f=ROOT/'work/state.json';now=datetime.now(timezone.utc)
    if a.action=='start' and not f.exists():
        if not 0<a.hours<=24:raise ValueError('This round allows at most 24h without new user authorization')
        write_json(f,{'started_at':now.isoformat(),'deadline':(now+timedelta(hours=a.hours)).isoformat(),
                      'phase':'setup','next_command':'python tools/lab.py doctor','status':'ACTIVE'})
    if not f.exists():raise FileNotFoundError('Run session.py start first')
    d=read_json(f);remaining=(datetime.fromisoformat(d['deadline'])-now).total_seconds()
    if a.action=='phase':
        d['phase']=a.name;d['next_command']=a.next_command;d['updated_at']=now.isoformat();write_json(f,d)
    print(json.dumps({**d,'remaining_seconds':max(0,remaining),'deadline_expired':remaining<=0},ensure_ascii=False,indent=2))
    if remaining<=0:sys.exit(2)
if __name__=='__main__':main()
