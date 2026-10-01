"""Fixed query inventory. Labels are exposed only to the experiment layer."""
from pathlib import Path
import json
import numpy as np
from experiments.common import ROOT,sha,write_new

def make_dev():
    destination=ROOT/'data/dev/catalog_v12.json'
    if destination.exists():return json.loads(destination.read_text())
    cases=[]
    oldqueries=json.loads((ROOT/'data/dev/lfr_reference_queries.json').read_text())['cases']
    for graph in sorted((ROOT/'inputs/local_hfd/graphs').glob('*.graph.json')):
        case=graph.name.removesuffix('.graph.json');truth=graph.with_name(case+'.truth.json')
        communities=json.loads(truth.read_text())['communities']
        if case in oldqueries:queries=oldqueries[case]['queries']
        else:
            rng=np.random.default_rng(5);queries=[]
            for ci in rng.choice(len(communities),size=min(6,len(communities)),replace=False):
                for seed in rng.choice(sorted(communities[int(ci)]),size=2,replace=False):
                    queries.append({'community_index':int(ci),'seed':int(seed)})
        qp=ROOT/'data/dev/attached_queries'/f'{case}.queries.json'
        write_new(qp,{'queries':queries,'rule':'rng5 six communities two seeds; shared exact M0 queries where available'})
        cases.append({'case_id':case,'split':'dev','graph_path':str(graph.relative_to(ROOT)),'graph_sha256':sha(graph),
                      'truth_path':str(truth.relative_to(ROOT)),'truth_sha256':sha(truth),'queries_path':str(qp.relative_to(ROOT)),
                      'queries_sha256':sha(qp),'query_count':len(queries),'source':'attached'})
    sbm=json.loads((ROOT/'data/dev/sbm_v12/catalog.json').read_text())['cases']
    cases.extend(sbm)
    catalog={'protocol':'zrhfd-v12-operational-20261001','cases':cases,
             'scope':'four attached graphs and 24 new SBM; missing historical12 not substituted'}
    write_new(destination,catalog);return catalog

def inventory(catalog):
    if isinstance(catalog,(str,Path)):catalog=json.loads((ROOT/catalog).read_text())
    for entry in catalog['cases']:
        for pathkey,hashkey in [('graph_path','graph_sha256'),('truth_path','truth_sha256'),('queries_path','queries_sha256')]:
            if sha(ROOT/entry[pathkey])!=entry[hashkey]:raise RuntimeError('Frozen input hash changed: '+entry[pathkey])
        communities=json.loads((ROOT/entry['truth_path']).read_text())['communities']
        queries=json.loads((ROOT/entry['queries_path']).read_text())['queries']
        for qi,query in enumerate(queries):
            yield {**entry,'query_index':qi,'seed':query['seed'],'community_index':query['community_index'],
                   'truth_vertices':communities[query['community_index']],'communities':communities}

if __name__=='__main__':
    c=make_dev();print(len(c['cases']),sum(x['query_count'] for x in c['cases']),sha(ROOT/'data/dev/catalog_v12.json'))
