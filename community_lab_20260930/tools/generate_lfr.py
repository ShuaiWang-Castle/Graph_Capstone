#!/usr/bin/env python3
"""Invoke the author-linked LFR generator. No substitute for overlapping LFR.
The native binary and its license/source lock must be audited on the execution host.
The seed uses time_seed.dat, not a guessed --seed argument.
"""
from __future__ import annotations
import argparse,subprocess,sys,time,json,itertools
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.io import read_json,write_json,sha256

def convert(raw,n,on,om):
    es=set();rawlines=0;loops=0
    for line in (raw/'network.dat').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):continue
        u,v=map(int,line.split()[:2]);u-=1;v-=1;rawlines+=1
        if not (0<=u<n and 0<=v<n):raise ValueError('Unexpected LFR node numbering')
        if u==v:loops+=1;continue
        es.add(tuple(sorted((u,v))))
    memberships={};bygroup={}
    for line in (raw/'community.dat').read_text(encoding='utf-8').splitlines():
        if not line.strip():continue
        vals=list(map(int,line.split()));u=vals[0]-1
        if not 0<=u<n or u in memberships:raise ValueError('Bad/duplicate LFR membership row')
        ms=set(vals[1:])
        if not ms:raise ValueError('LFR node without a membership')
        memberships[u]=ms
        for c in ms:bygroup.setdefault(c,[]).append(u)
    if len(memberships)!=n:raise ValueError('LFR did not return all n nodes')
    overlap=[u for u,ms in memberships.items() if len(ms)>1]
    if len(overlap)!=on:raise ValueError(f'Expected {on} overlap nodes, observed {len(overlap)}')
    if any(len(memberships[u])!=om for u in overlap):raise ValueError('Overlap multiplicity mismatch')
    # Definitions differ slightly from native reported mu. Keep both, never relabel target mu as observed.
    external=sum(not(memberships[u]&memberships[v]) for u,v in es)
    degrees=[0]*n
    for u,v in es:degrees[u]+=1;degrees[v]+=1
    return {'n':n,'edges':sorted(es),'schema_version':1}, {'communities':[sorted(bygroup[c]) for c in sorted(bygroup)],'labels_complete':True}, {
      'n':n,'m':len(es),'average_degree':sum(degrees)/n,'isolated_nodes':degrees.count(0),
      'overlap_nodes_observed':len(overlap),'raw_edge_rows':rawlines,'self_loops_removed':loops,
      'undirected_external_edge_fraction':external/len(es) if es else None,
      'community_sizes':sorted(map(len,bygroup.values()))}

def main():
    p=argparse.ArgumentParser();p.add_argument('--binary',required=True);p.add_argument('--protocol',default=str(ROOT/'configs/protocol.json'))
    p.add_argument('--output',default=str(ROOT/'work/dev_lfr'));p.add_argument('--split',choices=['development','confirmation'],default='development')
    p.add_argument('--timeout',type=int,default=180);p.add_argument('--limit',type=int);a=p.parse_args()
    cfg=read_json(a.protocol)['lfr'];binary=Path(a.binary).resolve()
    if not binary.is_file():raise FileNotFoundError(binary)
    seeds=cfg['dev_graph_seeds'] if a.split=='development' else cfg['confirm_graph_seeds']
    base=Path(a.output).resolve();base.mkdir(parents=True,exist_ok=True)
    spec={'split':a.split,'generator_binary_sha256':sha256(binary),'lfr':cfg,'seeds':seeds}
    frozen=base/'GENERATION_FREEZE.json'
    if frozen.exists() and read_json(frozen)!=spec:raise ValueError('Generation freeze differs; do not overwrite an existing study')
    write_json(frozen,spec)
    cases=list(itertools.product(cfg['n'],cfg['overlap_fraction'],cfg['mu'],seeds))
    if a.limit is not None:cases=cases[:a.limit]
    rows=[]
    for n,ov,mu,seed in cases:
        name=f'lfr_n{n}_o{int(ov*100):02d}_m{int(mu*100):02d}_s{seed}';raw=base/'raw'/name;raw.mkdir(parents=True,exist_ok=True)
        recfile=raw/'record.json'
        if recfile.exists():
            rows.append(read_json(recfile));continue
        session=ROOT/'work/state.json'
        if session.exists():
            remaining=(datetime.fromisoformat(read_json(session)['deadline'])-datetime.now(timezone.utc)).total_seconds()
            if remaining<=1:
                row={'case_id':name,'split':a.split,'requested':{'n':n,'overlap_fraction':ov,'mu':mu,'seed':seed},'status':'NOT_RUN_BUDGET'}
                write_json(recfile,row);rows.append(row);continue
        else:remaining=a.timeout
        on=round(n*ov);(raw/'time_seed.dat').write_text(str(seed)+'\n',encoding='utf-8')
        (raw/'time_seed.before.dat').write_bytes((raw/'time_seed.dat').read_bytes())
        argv=[str(binary),'-N',str(n),'-k',str(cfg['mean_degree']),'-maxk',str(cfg['max_degree']),
          '-mu',str(mu),'-t1',str(cfg['degree_exponent']),'-t2',str(cfg['community_exponent']),
          '-minc',str(cfg['min_community']),'-maxc',str(cfg['max_community']),'-on',str(on),'-om',str(cfg['overlap_memberships'])]
        row={'case_id':name,'split':a.split,'requested':{'n':n,'overlap_fraction':ov,'mu':mu,'seed':seed},'command':argv}
        start=time.perf_counter()
        try:
            with open(raw/'stdout.log','w',encoding='utf-8') as out:
                r=subprocess.run(argv,cwd=raw,stdout=out,stderr=subprocess.STDOUT,timeout=min(a.timeout,remaining),check=False)
            if r.returncode:raise RuntimeError(f'generator exit={r.returncode}')
            g,t,meta=convert(raw,n,on,cfg['overlap_memberships'])
            gp=base/'graphs'/f'{name}.json';tp=base/'evaluation_only'/f'{name}.json'
            write_json(gp,g);write_json(tp,t);write_json(raw/'observed_statistics.json',meta)
            row.update(status='GENERATED',graph=str(gp),truth=str(tp),n=n,graph_sha256=sha256(gp),truth_sha256=sha256(tp),statistics=meta)
        except subprocess.TimeoutExpired:row.update(status='GENERATION_TIMEOUT')
        except Exception as e:row.update(status='GENERATION_ERROR',error=str(e))
        if (raw/'time_seed.dat').exists():(raw/'time_seed.after.dat').write_bytes((raw/'time_seed.dat').read_bytes())
        row['generator_binary_sha256']=sha256(binary);row['generator_source_sha256']=sha256(Path(__file__))
        row['generation_seconds']=time.perf_counter()-start;write_json(recfile,row);rows.append(row)
        print(json.dumps({k:row[k] for k in ['case_id','status','generation_seconds']},ensure_ascii=False),flush=True)
        write_json(base/'catalog.json',rows)
    write_json(base/'catalog.json',rows)
if __name__=='__main__':main()
