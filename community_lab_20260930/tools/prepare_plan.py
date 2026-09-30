#!/usr/bin/env python3
"""Create an immutable baseline job plan. Ground-truth K appears ONLY in the
explicit oracle-K panel; no ground-truth member list enters an adapter command.
"""
from __future__ import annotations
import argparse,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.io import read_json,write_json,sha256

def main():
    p=argparse.ArgumentParser();p.add_argument('--catalog',required=True);p.add_argument('--output',default=str(ROOT/'work/plans/baselines.json'))
    p.add_argument('--method-configs',default=str(ROOT/'configs/methods.json'));p.add_argument('--protocol',default=str(ROOT/'configs/protocol.json'))
    p.add_argument('--alg-seed',type=int,default=73);p.add_argument('--methods',nargs='*');a=p.parse_args()
    catalog=read_json(a.catalog);methods=read_json(a.method_configs)['methods'];protocol=read_json(a.protocol)
    out=Path(a.output).resolve();jobs=[];config_dir=out.parent/'job_configs';config_dir.mkdir(parents=True,exist_ok=True)
    source_files=[ROOT/'adapters/run.py',ROOT/'adapters/nocd_graph_only.py',ROOT/'lab/io.py',ROOT/'lab/runner.py']
    for case in catalog:
        for m in methods:
            if a.methods and m['id'] not in a.methods:continue
            stem=f"{case['case_id']}__{m['id']}__s{a.alg_seed}";cfg=dict(m.get('parameters',{}))
            for k in ['binary','source_dir','module_path']:
                if k in cfg:cfg[k]=str((ROOT/cfg[k]).resolve())
            blocked=None
            if case.get('status','GENERATED')!='GENERATED':blocked='graph_generation_failed:'+case.get('status','unknown')
            if m.get('information_policy')=='oracle_K' and not blocked:
                truth=read_json(case['truth'])
                cfg['k']=len([c for c in truth['communities'] if c])
            configpath=config_dir/(stem+'.json')
            if configpath.exists() and read_json(configpath)!=cfg:raise ValueError('Existing per-job configuration changed; use a new plan directory')
            write_json(configpath,cfg)
            if not m.get('enabled',True):blocked='disabled_after_setup_audit'
            for k in ['binary','source_dir','module_path']:
                if k in cfg and not Path(cfg[k]).exists():blocked='missing_dependency:'+k+':'+cfg[k]
            sourcehashes={str(f):sha256(f) for f in source_files}
            # Additional adapters must be locked too; baseline files above keep
            # their original coverage and the frozen plans remain immutable.
            for token in m['command']:
                if token.startswith('{root}/') and token.endswith('.py'):
                    adapter_path=ROOT/token[len('{root}/'):]
                    sourcehashes[str(adapter_path)]=sha256(adapter_path)
            if 'module_path' in cfg and Path(cfg['module_path']).exists():sourcehashes[cfg['module_path']]=sha256(cfg['module_path'])
            if 'binary' in cfg and Path(cfg['binary']).is_file():sourcehashes[cfg['binary']]=sha256(cfg['binary'])
            if 'source_dir' in cfg and Path(cfg['source_dir']).exists():
                package='karateclub' if m['id'].startswith('ego_karateclub') else 'nocd'
                for f in (Path(cfg['source_dir'])/package).rglob('*.py'):sourcehashes[str(f)]=sha256(f)
            cp={'job_id':stem,'case_id':case['case_id'],'method':m['id'],'command':m['command'],
                'graph':case.get('graph',''),'config':str(configpath),'config_sha256':sha256(configpath),
                'seed':a.alg_seed,'device':cfg.get('device','cpu'),'gpu':m.get('gpu'),
                'threads':cfg.get('threads',protocol['resources']['threads_per_job']),
                'memory_mb':protocol['resources']['memory_mb_per_job'],
                'timeout_s':protocol['resources']['small_job_seconds'] if case.get('n',case.get('requested',{}).get('n',5000))<=1000 else protocol['resources']['medium_job_seconds'],
                'information_policy':m['information_policy'],'source_hashes':sourcehashes,
                'declared_implementation':m['implementation']}
            if not blocked:cp['graph_sha256']=sha256(cp['graph'])
            else:cp['blocked_reason']=blocked
            jobs.append(cp)
    # Interleave by graph and randomize method execution order reproducibly without using outcomes.
    import random
    random.Random(protocol['execution_order_seed']).shuffle(jobs)
    plan={'purpose':'BASELINE_DISCOVERY_NOT_A_NEW_METHOD_RESULT','catalog_sha256':sha256(a.catalog),
          'protocol_sha256':sha256(a.protocol),'methods_sha256':sha256(a.method_configs),'jobs':jobs}
    for filename,key in [('provenance/SOURCE_LOCK.json','source_lock_sha256'),('provenance/dependency_versions.txt','dependency_lock_sha256')]:
        if (ROOT/filename).exists():plan[key]=sha256(ROOT/filename)
    if out.exists() and read_json(out)!=plan:raise ValueError('Plan is already frozen. Use a separately named plan after a declared change.')
    write_json(out,plan);print(f'{len(jobs)} planned jobs; {sum("blocked_reason" in j for j in jobs)} blocked. {out}')
if __name__=='__main__':main()
