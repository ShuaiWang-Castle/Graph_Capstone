"""M2 engineering regression: same12 and both placements of the remote clique."""
from pathlib import Path
import argparse, csv, hashlib, itertools, json, os, sys, time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dataclasses import asdict
from zrhfd.graph import Graph
from zrhfd.pipeline import Config,run
from experiments.common import evaluate,measured,sha,source_hashes,stamp,write_new

def tasks():
    catalog=json.loads((ROOT/'data/dev/same12/catalog.json').read_text())
    entries=catalog.get('cases',catalog.get('graphs',catalog.get('instances')))
    if entries is None:raise ValueError('Unknown same12 catalog schema')
    for index,entry in enumerate(entries):
        path=ROOT/entry.get('graph',entry.get('graph_path'));truthpath=ROOT/entry.get('truth',entry.get('truth_path'))
        truth=json.loads(truthpath.read_text())['communities'][0]
        seed=entry.get('seed',entry.get('query_seed'))
        for variant,cfg in [('main',Config()),('cap05',Config(region='R-cap')),
                             ('P2',Config(patience=2)),('budgetM',Config(mass_budget_fraction=1.))]:
            yield f'same12_{index:02d}_{variant}',Graph.load(path),seed,truth,cfg,{
                'graph_path':str(path.relative_to(ROOT)),'graph_sha256':sha(path),'truth_sha256':sha(truthpath),
                'input_role':'dev','placement':'base','variant':variant}
    queries=json.loads((ROOT/'data/dev/lfr_reference_queries.json').read_text())['cases']
    for case,entry in queries.items():
        path=ROOT/'inputs/local_hfd/graphs'/f'{case}.graph.json'
        truthpath=path.with_name(f'{case}.truth.json');g=Graph.load(path)
        communities=json.loads(truthpath.read_text())['communities']
        placements=['base','low','high'] if case.endswith('s11') else ['base']
        for placement in placements:
            shift=30 if placement=='low' else 0
            if placement=='base':h=g;clique=[]
            else:
                clique=list(range(30)) if placement=='low' else list(range(g.n,g.n+30))
                edges=[(u+shift,v+shift,w) for u,v,w in g.edges]+list(itertools.combinations(clique,2))
                h=Graph.from_edges(g.n+30,edges)
            topology_hash=hashlib.sha256(json.dumps([h.n,h.edges],separators=(',',':')).encode()).hexdigest()
            for qi,q in enumerate(entry['queries']):
                seed=q['seed']+shift;C=[u+shift for u in communities[q['community_index']]]
                for variant,cfg in [('main',Config()),('cap05',Config(region='R-cap'))]:
                    yield f'{case}_{placement}_q{qi:02d}_{variant}',h,seed,C,cfg,{
                        'graph_path':str(path.relative_to(ROOT)),'graph_sha256':sha(path),'derived_topology_sha256':topology_hash,
                        'truth_sha256':sha(truthpath),'input_role':'dev','placement':placement,
                        'variant':variant,'clique_vertices':clique,'query_index':qi,'case':case}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',default='results/m2/run_v12_001');ap.add_argument('--limit',type=int);args=ap.parse_args()
    output=ROOT/args.output;output.mkdir(parents=True,exist_ok=True)
    manifest=output/'manifest.json'
    if not manifest.exists():write_new(manifest,{'created_utc':stamp(),'command':['.venv/bin/python','experiments/run_m2.py','--output',args.output],
        'source_sha256':source_hashes(),'threads':{k:os.environ.get(k) for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS']},
        'measurement_role':'engineering regression; other agents may run verification, not formal headline time',
        'specification_sha256':sha(ROOT/'provenance/goal-objective.md')})
    expected=json.loads(manifest.read_text())['source_sha256']
    # New baseline wrappers may be independently added. Root graph core is frozen within this run.
    for p,digest in expected.items():
        if p.startswith('zrhfd/') and '/baselines/' not in p and sha(ROOT/p)!=digest:raise RuntimeError('Run core changed: '+p)
    for i,(name,g,seed,C,cfg,meta) in enumerate(tasks()):
        if args.limit is not None and i>=args.limit:break
        dest=output/(name+'.json')
        if dest.exists():continue
        record=measured(lambda:run(g,seed,cfg))
        record.update(task=name,seed=seed,configuration=asdict(cfg),input=meta,truth_vertices=C)
        if record['result'] is not None:
            record['evaluation']=evaluate(g,record['result']['vertices'],C,record['result']['region_vertices'])
            record['far_clique_incorporated']=bool(set(meta.get('clique_vertices',()))&set(record['result']['vertices']))
        write_new(dest,record)
        r=record.get('evaluation',{})
        print(name,record['status'],'F1',r.get('F1'),'outer_s',round(record['outer_wall_seconds'],3),flush=True)
    rows=[]
    for p in sorted(output.glob('*.json')):
        if p.name=='manifest.json':continue
        r=json.loads(p.read_text());a=r.get('result') or {};ev=r.get('evaluation') or {};cert=a.get('certificate',{})
        rows.append({'task':r['task'],'status':r['status'],'F1':ev.get('F1'),'exact_recovery':ev.get('exact_recovery'),
         'truth_covered':ev.get('truth_covered'),'failure_class':ev.get('failure_class'),'j_act':a.get('j_act'),
         'j_star':a.get('j_star'),'m_act':a.get('m_act'),'output_size':len(a.get('vertices',())),
         'region_volume':a.get('region_volume'),'Z':a.get('stats',{}).get('Z'),'LB_R':cert.get('LB_R'),
         'gap':cert.get('gap'),'far_clique':r.get('far_clique_incorporated'),'outer_wall_seconds':r['outer_wall_seconds'],
         'peak_rss_bytes':r['peak_rss_bytes_sampled_process_and_children']})
    with (output/'summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

if __name__=='__main__':main()
