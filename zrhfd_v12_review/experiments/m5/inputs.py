"""Pinned M5 inputs and truth-free topology loading; no download or repair."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import math
import os
import uuid
import numpy as np

PROJECT = Path(__file__).resolve().parents[2]
CONFIG = 'experiments/m5/config_v12_001.json'


def digest(path):
    return hashlib.sha256((PROJECT/path).read_bytes()).hexdigest()


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def immutable_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_bytes(value)
    if path.exists():
        if path.read_bytes() != content:
            raise RuntimeError('Immutable artifact already exists with different content: '+str(path))
        return
    temporary=path.parent/('.'+path.name+'.partial-'+str(uuid.uuid4()))
    with temporary.open('xb') as stream:
        stream.write(content);stream.flush()
    try:
        os.link(temporary,path)  # Atomic exclusive publication; never replace an existing raw artifact.
    except FileExistsError:
        if path.read_bytes()!=content:raise RuntimeError('Concurrent immutable artifact differs: '+str(path))
    finally:temporary.unlink(missing_ok=True)


def config():
    return json.loads((PROJECT/CONFIG).read_text())


def validate_official():
    catalog = json.loads((PROJECT/config()['query_catalog']).read_text())
    receipt = json.loads((PROJECT/config()['acquisition_receipt']).read_text())
    checks = []
    for dataset in catalog['datasets']:
        for name, raw in dataset['raw_files'].items():
            actual = digest(raw['path'])
            if actual != raw['sha256']:
                raise RuntimeError('Pinned official input changed: '+raw['path'])
        path = PROJECT/dataset['raw_files']['hyperedges']['path']
        ranks = Counter(); ids = set(); degree = Counter(); edgecount = 0
        for line in path.open():
            vertices = tuple(int(v)-1 for v in line.strip().split(','))
            if len(vertices)<2 or len(set(vertices))!=len(vertices) or not all(0<=v<dataset['n'] for v in vertices):
                raise ValueError('Raw hyperedge invalid; input will not be silently repaired')
            ranks[len(vertices)] += 1; edgecount += 1; ids.update(vertices); degree.update(vertices)
        labels = [int(v) for v in (PROJECT/dataset['raw_files']['node-labels']['path']).read_text().splitlines()]
        if len(labels) != dataset['n']:
            raise ValueError('Label count mismatch')
        selected = [q for q in catalog['queries'] if q['dataset']==dataset['dataset']]
        groups = {g['code']:g for g in dataset['groups']}
        for q in selected:
            if labels[q['seed_zero_based']]!=q['source_label_id'] or q['seed_zero_based'] not in groups[q['cluster_code']]['members_zero_based']:
                raise ValueError('Query-to-target mismatch')
        if dataset['dataset']=='contact-high-school':
            if len(selected)!=327 or len({q['seed_zero_based'] for q in selected})!=327:
                raise ValueError('Contact query census mismatch')
        elif dataset['dataset']=='trivago-clicks':
            counts=Counter(q['cluster_code'] for q in selected)
            if counts!={code:100 for code in config()['datasets']['trivago-clicks']['clusters']}:
                raise ValueError('Trivago cluster query counts mismatch')
            if any(len({q['seed_zero_based'] for q in selected if q['cluster_code']==code})!=100 for code in counts):
                raise ValueError('Trivago queries sampled with repetition')
        checks.append({'dataset':dataset['dataset'],'n':dataset['n'],'hyperedges':edgecount,'volume':sum(degree.values()),'rank_histogram':dict(sorted(ranks.items())),'node_id_count':len(ids),'queries':len(selected),'raw_files':dataset['raw_files'],'status':'PASS'})
    # Receipt schemas may vary; input pinning above is authoritative, receipt is retained verbatim by hash.
    return {'catalog':catalog['catalog_id'],'catalog_sha256':digest(config()['query_catalog']),'source_protocol_sha256':digest(config()['source_protocol']),'receipt_sha256':digest(config()['acquisition_receipt']),'receipt_recorded_at':receipt.get('recorded_at'),'checks':checks}


def generate_hsbm():
    """Poisson counts plus uniform conditional edges; never reroll by quality."""
    p=config()['datasets']['hyper_synthetic']; K=p['blocks']; size=p['block_size']; n=K*size
    existing=PROJECT/'data/hyper_synthetic/catalog_v12_001.json'
    if existing.exists():
        manifest=json.loads(existing.read_text())
        for item in manifest['datasets']:
            if digest(item['path'])!=item['sha256']:raise RuntimeError('Immutable synthetic input changed')
            raw=json.loads((PROJECT/item['path']).read_text())
            if any(raw['parameters'][key]!=value for key,value in p.items()):
                raise RuntimeError('Synthetic generation parameters changed; freeze a new catalog')
        return manifest
    artifacts=[]
    for mu in p['cross_edge_fractions']:
        for seed in p['generation_seeds']:
            rng=np.random.Generator(np.random.PCG64(seed))
            edges=[]; requested={}; blocks=[np.arange(b*size,(b+1)*size) for b in range(K)]
            for rank, incidence_fraction in p['rank_incidence_fractions'].items():
                rank=int(rank); mean=n*p['expected_incidence_degree']*incidence_fraction/rank
                within=0
                for block in blocks:
                    count=int(rng.poisson(mean*(1-mu)/K));within+=count
                    edges.extend(sorted(map(int,rng.choice(block,rank,replace=False))) for _ in range(count))
                count=int(rng.poisson(mean*mu));cross=[]
                for _ in range(count):
                    while True:
                        row=sorted(map(int,rng.choice(n,rank,replace=False)))
                        if len({u//size for u in row})>1:
                            cross.append(row);break
                edges.extend(cross);requested[str(rank)]={'within':within,'cross':count,'expected_total':mean}
            name=f'hsbm_k{K}_s{size}_mu{int(mu*100):02d}_seed{seed}'
            relative='data/hyper_synthetic/'+name+'.json'
            degree=Counter(u for e in edges for u in e)
            query_rng=np.random.Generator(np.random.PCG64(seed+p['query_rng_offset']))
            groups=[];queries=[]
            for b,block in enumerate(blocks):
                code=f'block{b}';members=list(map(int,block));groups.append({'code':code,'members_zero_based':members})
                for index,s in enumerate(query_rng.choice(block,p['queries_per_block'],replace=False)):
                    queries.append({'query_id':f'{name}_{code}_{index:02d}','dataset':name,'cluster_code':code,'seed_zero_based':int(s),'within_cluster_query_index':index})
            artifact={'schema_version':1,'dataset':name,'n':n,'edges':edges,'groups':groups,'queries':queries,'parameters':dict(p,cross_edge_fraction=mu,generation_seed=seed),'realized':{'edge_counts':requested,'hyperedges':len(edges),'volume':sum(degree.values()),'isolated_vertices':sum(degree[u]==0 for u in range(n))},'generator_scope':'sparse Poisson planted multihypergraph; sampled multiplicities retained; mu is cross-edge class fraction, not a measured cut conductance','quality_selection':False}
            immutable_json(PROJECT/relative,artifact)
            artifacts.append({'dataset':name,'path':relative,'sha256':digest(relative),'queries':len(queries),'realized':artifact['realized']})
    manifest={'schema_version':1,'configuration_sha256':digest(CONFIG),'datasets':artifacts,'quality_evaluated':False,'source_sha256':digest('experiments/m5/inputs.py')}
    immutable_json(PROJECT/'data/hyper_synthetic/catalog_v12_001.json',manifest)
    return manifest


def tasks(datasets=None, methods=None, toy=False):
    c=config(); chosen=set(datasets or ['contact-high-school','trivago-clicks','hyper_synthetic']); methods=methods or c['methods']; out=[]
    if toy:
        data={'schema_version':1,'dataset':'m5_toy_interface','n':8,'edges':[[0,1],[1,2],[0,1,2,3],[4,5],[5,6],[4,5,6,7],[2,4],[3,7]],'groups':[{'code':'left','members_zero_based':[0,1,2,3]},{'code':'right','members_zero_based':[4,5,6,7]}],'queries':[{'query_id':'m5_toy_0','dataset':'m5_toy_interface','cluster_code':'left','seed_zero_based':0}]}
        path='data/hyper_synthetic/toy_interface.json';immutable_json(PROJECT/path,data)
        records=[(data,path)]
    else:
        records=[]; catalog=json.loads((PROJECT/c['query_catalog']).read_text())
        for data in catalog['datasets']:
            if data['dataset'] in chosen:
                item=dict(data,queries=[q for q in catalog['queries'] if q['dataset']==data['dataset']]);records.append((item,c['query_catalog']))
        if 'hyper_synthetic' in chosen:
            synthetic=json.loads((PROJECT/'data/hyper_synthetic/catalog_v12_001.json').read_text())
            records.extend((json.loads((PROJECT/item['path']).read_text()),item['path']) for item in synthetic['datasets'])
    for data,path in records:
        input_sha=digest(path)
        for q in data['queries']:
            for method in methods:
                if method not in c['methods']:raise ValueError('Unknown frozen method')
                out.append({'task_id':q['query_id']+'__'+method,'query':q,'method':method,'dataset':data['dataset'],'input_path':path,'input_sha256':input_sha,'toy':toy})
    return out


def load_topology(task):
    from zrhfd.hyper import Hypergraph
    data=json.loads((PROJECT/task['input_path']).read_text())
    if 'edges' in data:
        h=Hypergraph.from_edges(data['n'],data['edges']);return h,data
    dataset=next(d for d in data['datasets'] if d['dataset']==task['dataset'])
    edgepath=PROJECT/dataset['raw_files']['hyperedges']['path']
    # Input has been validated before run freeze; no sorting deduplication repairs permitted.
    edges=[tuple(int(v)-1 for v in line.strip().split(',')) for line in edgepath.open()]
    h=Hypergraph.from_edges(dataset['n'],edges);return h,dataset


def target_vertices(data, query):
    return next(g['members_zero_based'] for g in data['groups'] if g['code']==query['cluster_code'])


def metrics(h, selected, truth):
    selected=set(selected);truth=set(truth);tp=len(selected & truth)
    precision=tp/len(selected) if selected else 0;recall=tp/len(truth) if truth else 0
    volume=float(h.volume(selected));denominator=min(volume,h.total-volume);cut=float(h.cut(selected))
    return {'precision':precision,'recall':recall,'F1':2*precision*recall/(precision+recall) if precision+recall else 0,'size':len(selected),'truth_size':len(truth),'truth_volume':float(h.volume(truth)),'cut_exact':str(h.cut(selected)),'volume_exact':str(h.volume(selected)),'hypergraph_conductance':cut/denominator if denominator>0 else None,'Z_H_exact':str(h.z_exact(selected)) if volume>0 else None,'Z_H_prov_exact':str(h.z_exact(selected,'ZH-prov')) if volume>0 else None,'components':len(h.components(selected)),'evaluation_only_truth':True}
