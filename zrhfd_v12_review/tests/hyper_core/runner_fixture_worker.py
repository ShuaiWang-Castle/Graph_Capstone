"""Actual processes for storage/timeout/memory guards; no clustering output claims."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from experiments.m5.inputs import immutable_json
parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);args=parser.parse_args()
request=json.loads(Path(args.request).read_text());task=request['task'];directory=Path(args.request).parent
kind=task['fixture'];progress=directory/'progress';progress.mkdir()
immutable_json(progress/'00000.json',{'event':'baseline_progress','payload':{'stage':'trial_finished','vertices':[0,1],'completed_trial_count':1,'status':'PARTIAL_GRID_CHECKPOINT','truth_used':False,'controlled_fixture':True}})
result={'task':task,'status':'COMPLETED','output':{'vertices':[0,1],'runtime_seconds':.01},'offline_metrics':{'F1':.5},'worker_wall_seconds':.02,'input_load_seconds':0.,'formal_measurement':False,'controlled_fixture':True}
if kind=='timeout':
    child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'])
    immutable_json(directory/'fixture_child.json',{'pid':child.pid});time.sleep(20)
elif kind=='memory':
    resident=bytearray(64*1024*1024);time.sleep(20)
elif kind=='malformed_progress':
    (progress/'00001.json').write_text('{"event":')
    immutable_json(directory/'worker_result.json',result)
elif kind=='malformed_result':(directory/'worker_result.json').write_text('{"status":')
else:
    immutable_json(directory/'worker_result.json',result)
    if kind=='nonzero':raise SystemExit(7)
