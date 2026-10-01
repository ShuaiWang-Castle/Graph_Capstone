"""Lightweight protocol/input checks; invokes no clustering algorithm."""
from pathlib import Path
import ast
import argparse
import hashlib
import json
import sys
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from experiments.m5.inputs import CONFIG,config,digest,immutable_json,validate_official,generate_hsbm,tasks
from experiments.m5.worker import method_settings


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='reviews/m5/static_v12_001.json');args=parser.parse_args()
    checked=[]
    for directory in ['experiments/m5','zrhfd/hyper']:
        for path in sorted((PROJECT/directory).glob('*.py')):
            ast.parse(path.read_text());checked.append(str(path.relative_to(PROJECT)))
    official=validate_official();synthetic=generate_hsbm();selected=tasks();c=config();violations=[]
    if len(selected)!=8*(1327+108):violations.append('task count')
    settings=[]
    for dataset,expected in [('contact-high-school',1000),('trivago-clicks',500)]:
        task=next(t for t in selected if t['dataset']==dataset and t['method']=='tlhfd_no_volume')
        p=method_settings(task,c)
        if p['iterations']!=expected or p['step_size']!=.25 or p['fraction_grid']!=c['datasets'][dataset]['tl_fraction_grid']:violations.append(dataset+' TL config')
        if p['mass_ratio']!=2 or p['max_mass_steps']!=128:violations.append('mass-grid keys')
        settings.append({'dataset':dataset,'config':p})
    synthetic_records=[]
    for d in synthetic['datasets']:
        item=json.loads((PROJECT/d['path']).read_text());members=set(u for g in item['groups'] for u in g['members_zero_based'])
        if len(members)!=400 or len(item['queries'])!=12 or item['quality_selection']:violations.append(d['dataset'])
        if any(len(e)!=len(set(e)) or not all(0<=u<400 for u in e) for e in item['edges']):violations.append('invalid synthetic edge')
        synthetic_records.append({'dataset':d['dataset'],'sha256':d['sha256'],'realized':d['realized']})
    evidence={'schema_version':1,'status':'PASS' if not violations else 'FAIL','violations':violations,'configuration_sha256':digest(CONFIG),'official':official,'synthetic':synthetic_records,'formal_task_count':len(selected),'method_count':len(c['methods']),'synthetic_query_count':108,'actual_tl_settings':settings,'parsed_sources':checked,'algorithms_invoked':False,'formal_measurements_started':False,'source_sha256':digest('experiments/m5/check_static.py')}
    immutable_json(PROJECT/args.output,evidence);print(json.dumps({'status':evidence['status'],'configuration_sha256':evidence['configuration_sha256'],'tasks':len(selected),'official_queries':1327,'synthetic_queries':108}))
    if violations:raise SystemExit(1)


if __name__=='__main__':main()
