"""Serial resumable task executor with wall/memory limits and immutable failures."""
from pathlib import Path
import argparse,gzip,json,os,signal,subprocess,sys,time
import psutil,yaml
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dataclasses import asdict,replace
from zrhfd.pipeline import Config
from experiments.catalog import make_dev,inventory
from experiments.common import sha,source_hashes,stamp,write_new

def configurations(protocol,phase):
    base=Config(**protocol['main'])
    if phase=='region':return [('main','zrhfd','no_volume',asdict(base)),('cap05','zrhfd','no_volume',asdict(replace(base,region='R-cap')))]
    if phase=='main':
        configs=[('main','zrhfd','no_volume',asdict(base))]
        for method in ['hfd','hfd_cd','tlhfd','acl','pnorm']:
            for setting in ['no_volume','oracle']:
                cfg={**protocol['mass_grid'],**protocol['baseline_configs'][method],
                     'budget_seconds':protocol['resources']['local_method_query_seconds']}
                configs.append((method+'_'+setting,method,setting,cfg))
        configs.append(('leiden','leiden','global',protocol['baseline_configs']['leiden']))
        return configs
    if phase=='ablations':
        from experiments.ablations import NAMES
        return [(name,'zrhfd_ablation','no_volume',{**asdict(base),'variant':name}) for name in NAMES]
    raise ValueError('Unknown phase')

def prepare(phase,output,catalog,limit=None):
    protocol=yaml.safe_load((ROOT/'experiments/protocol_v12.yaml').read_text());folder=ROOT/output
    folder.mkdir(parents=True,exist_ok=True);manifest=folder/'manifest.json'
    if manifest.exists():return json.loads(manifest.read_text())
    queries=list(inventory(catalog));jobs=[]
    if phase=='ablations':queries=[q for q in queries if q['query_index']<2]
    sources={p:d for p,d in source_hashes().items() if
       (p in ['experiments/catalog.py','experiments/common.py','experiments/schedule.py','experiments/worker.py','experiments/protocol_v12.yaml','experiments/ablations.py']) or
       (p.startswith('zrhfd/') and p.count('/')==1 and p!='zrhfd/storage.py') or
       (phase in ('main','ablations') and p.startswith('zrhfd/baselines/') and not p.split('/')[-1].startswith('hyper'))}
    for entry in queries:
        for label,method,setting,cfg in configurations(protocol,phase):
            task=f"{entry['case_id']}_q{entry['query_index']:02d}_{label}"
            artifact=f'{output}/artifacts/{task}';configuration=dict(cfg)
            if method not in ['zrhfd','zrhfd_ablation']:configuration['artifact_directory']=artifact
            job={'task':task,'method':method,'setting':setting,'configuration':configuration,'query':entry,
                 'implementation_exact_cut_backend':protocol.get('implementation',{}).get('exact_cut_backend','original_exact'),
                 'result_path':f'{output}/raw/{task}.json.gz','source_sha256':sources,
                 'protocol_sha256':sha(ROOT/'experiments/protocol_v12.yaml'),'measurement_role':
                    'formal_cpu_serial'}
            path=f'{output}/jobs/{task}.json';write_new(ROOT/path,job);jobs.append(path)
            if limit is not None and len(jobs)>=limit:break
        if limit is not None and len(jobs)>=limit:break
    m={'created_utc':stamp(),'phase':phase,'jobs':jobs,'source_sha256':sources,
       'catalog_sha256':sha(ROOT/catalog) if isinstance(catalog,str) else sha(ROOT/'data/dev/catalog_v12.json'),
       'protocol_sha256':sha(ROOT/'experiments/protocol_v12.yaml'),
       'dependency_versions_sha256':sha(ROOT/'provenance/dependency_versions.txt'),
       'runtime_sha256':{'work/bin/mincut128':sha(ROOT/'work/bin/mincut128')},
       'implementation':protocol.get('implementation',{'exact_cut_backend':'original_exact'}),
       'resources':protocol['resources'],'command':['.venv/bin/python','experiments/schedule.py','--phase',phase,'--output',output]}
    write_new(manifest,m);return m

def execute(manifest,output,max_tasks=None):
    for name,digest in manifest['source_sha256'].items():
        if sha(ROOT/name)!=digest:raise RuntimeError('Source changed since run froze: '+name)
    for name,digest in manifest.get('runtime_sha256',{}).items():
        if sha(ROOT/name)!=digest:raise RuntimeError('Runtime changed since run froze: '+name)
    if sha(ROOT/'provenance/dependency_versions.txt')!=manifest['dependency_versions_sha256']:
        raise RuntimeError('Dependency lock changed since run froze')
    environment=dict(os.environ)
    environment.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMBA_NUM_THREADS='1',
       VECLIB_MAXIMUM_THREADS='1',BLIS_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',PYTHONHASHSEED='0')
    performed=0
    for jobpath in manifest['jobs']:
        job=json.loads((ROOT/jobpath).read_text());dest=ROOT/job['result_path'];failure=dest.with_suffix('.failure.json')
        if dest.exists() or failure.exists():continue
        if max_tasks is not None and performed>=max_tasks:break
        folder=ROOT/output/'logs';folder.mkdir(exist_ok=True)
        log=folder/(job['task']+'.stdout.log');err=folder/(job['task']+'.stderr.log')
        cmd=[str(ROOT/'.venv/bin/python'),'experiments/worker.py','--job',jobpath]
        started=time.perf_counter();peak=0;reason=None
        write_new(folder/(job['task']+'.started.json'),{'status':'STARTED','started_utc':stamp(),
           'task':job['task'],'actual_argv':cmd,'cwd':str(ROOT),'job_sha256':sha(ROOT/jobpath),
           'thread_environment':{k:environment[k] for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS','PYTHONHASHSEED')}})
        with log.open('x') as stdout,err.open('x') as stderr:
            process=subprocess.Popen(cmd,cwd=ROOT,stdout=stdout,stderr=stderr,env=environment,start_new_session=True)
            try:
                while process.poll() is None:
                    try:
                        parent=psutil.Process(process.pid);rss=parent.memory_info().rss
                        for child in parent.children(recursive=True):
                            try:rss+=child.memory_info().rss
                            except psutil.Error:pass
                        peak=max(peak,rss)
                    except psutil.Error:pass
                    elapsed=time.perf_counter()-started
                    if elapsed>manifest['resources']['local_method_query_seconds']:reason='TIMEOUT'
                    if peak>manifest['resources']['memory_limit_bytes']:reason='MEMORY_LIMIT'
                    if reason:
                        os.killpg(process.pid,signal.SIGTERM)
                        try:process.wait(timeout=3)
                        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                        break
                    time.sleep(.05)
            except KeyboardInterrupt:
                reason='INTERRUPTED'
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
        elapsed=time.perf_counter()-started
        if reason or process.returncode or not dest.exists():
            write_new(failure,{'task':job['task'],'status':reason or 'WORKER_ERROR','returncode':process.returncode,
               'wall_seconds_observed_not_completion':elapsed,'peak_rss_bytes':peak,'job':jobpath,
               'command':cmd,'stdout_path':str(log.relative_to(ROOT)),'stderr_path':str(err.relative_to(ROOT)),
               'finished_utc':stamp(),'partial_result_present':dest.exists(),'completion_claim':False})
        print(job['task'],reason or 'RETURNED',round(elapsed,3),flush=True);performed+=1
        if reason=='INTERRUPTED':raise KeyboardInterrupt
    return performed

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['region','main','ablations'],required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--split',choices=['dev','test'],default='dev')
    parser.add_argument('--limit',type=int);parser.add_argument('--max-tasks',type=int);parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    catalog=make_dev() if args.split=='dev' else 'data/test/calibrated_lfr/catalog.json'
    manifest=prepare(args.phase,args.output,catalog,args.limit)
    print('tasks_frozen',len(manifest['jobs']),flush=True)
    if not args.prepare_only:execute(manifest,args.output,args.max_tasks)

if __name__=='__main__':main()
