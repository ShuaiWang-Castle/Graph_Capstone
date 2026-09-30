#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys,platform,subprocess,os,shutil,time,importlib.metadata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.io import read_json,write_json,graph,cover,sha256

def doctor(args):
    import psutil
    nv=None
    if shutil.which('nvidia-smi'):
        try:nv=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,memory.total,memory.used,utilization.gpu','--format=csv,noheader'],text=True,timeout=10).strip()
        except Exception as e:nv=str(e)
    packs={}
    for name in ['numpy','scipy','networkx','psutil','matplotlib','torch','cdlib','karateclub']:
        try:packs[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packs[name]=None
    data={'platform':platform.platform(),'python':sys.version,'cpu_logical':os.cpu_count(),
          'cpu_physical':psutil.cpu_count(logical=False),'ram_total_bytes':psutil.virtual_memory().total,
          'ram_available_bytes':psutil.virtual_memory().available,'disk_free_bytes':shutil.disk_usage(ROOT).free,
          'nvidia_smi':nv,'packages':packs,'tools':{x:bool(shutil.which(x)) for x in ['git','make','g++','clang++']},
          'notice':'This probe does not reserve CPUs or GPUs. Inspect active work before using a device.'}
    write_json(args.output,data);print(json.dumps(data,ensure_ascii=False,indent=2))

def smoke(args):
    from itertools import combinations
    base=Path(args.output);catalog=[]
    for q in [2,3,5]:
        s=5;n=1+q*s;groups=[];edges=set()
        for j in range(q):
            c=[0]+list(range(1+j*s,1+(j+1)*s));groups.append(c);edges.update(combinations(c,2))
        name=f'hub_cliques_q{q}'
        gp=base/'graphs'/f'{name}.json';tp=base/'evaluation_only'/f'{name}.json'
        write_json(gp,{'n':n,'edges':sorted(edges),'schema_version':1})
        write_json(tp,{'communities':groups,'labels_complete':True})
        catalog.append({'case_id':name,'graph':str(gp.resolve()),'truth':str(tp.resolve()),'n':n,
                        'graph_sha256':sha256(gp),'purpose':'mechanism_smoke_not_benchmark'})
    # Explicit empty / no-signal graph tests: not evidence of recovery quality.
    gp=base/'graphs'/'isolates.json';write_json(gp,{'n':4,'edges':[],'schema_version':1})
    write_json(base/'catalog.json',catalog);print(base/'catalog.json')

def evaluate(args):
    from lab.metrics import score
    n,_=graph(args.graph);t,ta=cover(args.truth,n);p,pa=cover(args.pred,n)
    td=read_json(args.truth)
    if td.get('labels_complete') is not True:
        raise ValueError('Strict scoring requires explicitly complete labels. Partial real metadata need a separate positive-only protocol.')
    result=score(t,p,n);result['normalization']={'truth':ta,'prediction':pa}
    write_json(args.output,result);print(json.dumps({k:v for k,v in result.items() if k!='matching'},indent=2))

def validate(args):
    n,edges=graph(args.graph);r={'n':n,'edges':len(edges),'graph_sha256':sha256(args.graph)}
    if args.truth:
        c,a=cover(args.truth,n);counts=[0]*n
        for g in c:
            for v in g:counts[v]+=1
        r.update({'groups':len(c),'overlap_nodes':sum(x>1 for x in counts),'uncovered_nodes':counts.count(0),'normalization':a})
    print(json.dumps(r,indent=2))

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='action',required=True)
    d=s.add_parser('doctor');d.add_argument('--output',default=str(ROOT/'work/environment.json'));d.set_defaults(fn=doctor)
    d=s.add_parser('make-smoke');d.add_argument('--output',default=str(ROOT/'work/smoke'));d.set_defaults(fn=smoke)
    d=s.add_parser('validate');d.add_argument('--graph',required=True);d.add_argument('--truth');d.set_defaults(fn=validate)
    d=s.add_parser('evaluate');d.add_argument('--graph',required=True);d.add_argument('--truth',required=True);d.add_argument('--pred',required=True);d.add_argument('--output',required=True);d.set_defaults(fn=evaluate)
    d=s.add_parser('selftest');d.set_defaults(fn=lambda a:sys.exit(subprocess.call([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'),'-v'],cwd=ROOT)))
    a=p.parse_args();a.fn(a)
if __name__=='__main__':main()
