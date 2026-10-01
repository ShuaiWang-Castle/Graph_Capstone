"""One isolated CPU task: compute first, then offline label evaluation."""
from pathlib import Path
import argparse,gzip,json,os,sys,time,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dataclasses import asdict
from zrhfd.graph import Graph
from zrhfd.pipeline import Config,run
from experiments.common import evaluate,measured,sha,stamp

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);args=parser.parse_args()
    job=json.loads((ROOT/args.job).read_text());task=job['task'];dest=ROOT/job['result_path']
    if dest.exists():raise RuntimeError('Raw task already exists')
    entry=job['query'];load_start=time.perf_counter();g=Graph.load(ROOT/entry['graph_path']);input_load_seconds=time.perf_counter()-load_start;seed=int(entry['seed'])
    cfg=dict(job['configuration']);method=job['method'];oracle=None
    workspace=[None]
    def checkpoint(value):
        checkpoint_path=ROOT/job.get('progress_path',job['result_path']+'.checkpoint.json')
        checkpoint_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=checkpoint_path.with_suffix('.tmp')
        payload={'task':task,'updated_utc':stamp(),'partial_not_convergence':True,'source_sha256':job['source_sha256'],'checkpoint':value}
        if workspace[0] is not None:payload['exact_cut_workspace']=workspace[0].summary()
        temporary.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False))
        os.replace(temporary,checkpoint_path)
    if job.get('setting')=='oracle':oracle=g.stats(entry['truth_vertices'])['volume']
    if method=='zrhfd_ablation':
        from experiments.ablations import run_variant
        variant=cfg['variant'];algorithm_cfg={k:v for k,v in cfg.items() if k!='variant'}
        algorithm=lambda:run_variant(g,seed,variant,Config(**algorithm_cfg),progress=checkpoint)
    elif method=='zrhfd':
        if 'fixed_grid' in cfg:cfg['fixed_grid']=tuple(cfg['fixed_grid'])
        algorithm=lambda:run(g,seed,Config(**cfg),progress=checkpoint)
    else:
        module=__import__('zrhfd.baselines.'+method,fromlist=['run'])
        algorithm=lambda:module.run(g,seed,cfg,oracle_volume=oracle)
    backend=job.get('implementation_exact_cut_backend','original_exact')
    if method in ('zrhfd','zrhfd_ablation') and backend=='prepared_region_workspace':
        original_algorithm=algorithm
        def algorithm():
            from zrhfd.experimental_cut_workspace import installed_workspace
            with installed_workspace() as dispatcher:
                workspace[0]=dispatcher
                result=original_algorithm()
                result['exact_cut_workspace']=dispatcher.summary()
                return result
    elif backend not in ('prepared_region_workspace','original_exact'):
        raise ValueError('Unknown exact cut implementation '+backend)
    record=measured(algorithm)
    record.update(task=task,method=method,setting=job.get('setting','no_volume'),seed=seed,
           input={k:v for k,v in entry.items() if k not in ('truth_vertices','communities')},
           configuration=cfg,input_load_seconds=input_load_seconds,command=['.venv/bin/python','experiments/worker.py','--job',args.job],
           protocol_sha256=job['protocol_sha256'],source_sha256=job['source_sha256'],
           implementation_exact_cut_backend=backend,
           oracle_volume=oracle,truth_in_method_path=oracle is not None,
           measurement_role=job.get('measurement_role','formal_cpu_serial'))
    if record['result'] is not None:
        a=record['result'];record['evaluation']=evaluate(g,a['vertices'],entry['truth_vertices'],a.get('region_vertices'))
        record['output_stats']=g.stats(a['vertices']);record['components']=len(g.components(a['vertices']))
        record['output_contains_seed']=seed in a['vertices']
        touched=a.get('touched_vertices')
        record['touched_volume']=float(g.degree[touched].sum()) if isinstance(touched,list) else None
        if 'certificate' in a:
            record['hull_best_evaluation']=evaluate(g,a['certificate']['hull_best'],entry['truth_vertices'])
            R=set(a['region_vertices']);C=set(entry['truth_vertices'])
            record['evaluation']['rho_hat']=max((len(R&set(other))/len(other) for ci,other in enumerate(entry['communities']) if ci!=entry['community_index']),default=0.)
        metadata=a.get('metadata',{})
        stops=[t.get('stop') for t in metadata.get('trials',[])]
        if (metadata.get('stop') in ('query_budget','TIMEOUT') or
            str(metadata.get('status','')).startswith('PARTIAL') or
            metadata.get('mass_grid_complete') is False or
            any(s in ('time_budget','max_updates','update_budget') for s in stops)):
            record['status']='PARTIAL_BUDGET'
        record['completion_claim']=record['status']=='COMPLETED'
        record['completion_semantics']='requested algorithm budget finished; not a convergence proof'
    dest.parent.mkdir(parents=True,exist_ok=True)
    encoded=(json.dumps(record,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode()
    with dest.open('xb') as out:
        with gzip.GzipFile(filename='',mode='wb',fileobj=out,mtime=0) as f:f.write(encoded)
    print(task,record['status'],record.get('evaluation',{}).get('F1'),flush=True)

if __name__=='__main__':main()
