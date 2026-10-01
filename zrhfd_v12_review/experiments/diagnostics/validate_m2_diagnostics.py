"""Crosscheck saved diagnostic margins against direct exact objective calls."""
from fractions import Fraction as F
from pathlib import Path
import hashlib
import itertools
import json
import sys
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from zrhfd.graph import Graph
from experiments.diagnostics.graph_query import penalty


def main():
    directory=PROJECT/'results/diagnostics/m2_dev_v12_001';count=0;violations=[]
    for path in sorted(directory.glob('*_main.json')):
        payload=json.loads(path.read_text());diagnosis=payload['diagnosis'];raw=json.loads((PROJECT/payload['source_raw']).read_text());meta=raw['input'];g=Graph.load(PROJECT/meta['graph_path']);shift=30 if meta['placement']=='low' else 0
        if meta['placement']!='base':g=Graph.from_edges(g.n+30,[(u+shift,v+shift,w) for u,v,w in g.edges]+list(itertools.combinations(meta['clique_vertices'],2)))
        C=set(raw['truth_vertices']);R=set(raw['result']['region_vertices']);rows=diagnosis['single_step_margins'];indices=sorted(set([0,len(rows)//2,len(rows)-1])) if rows else []
        for index in indices:
            row=rows[index];T=C-{row['vertex']} if row['operation']=='delete' else C|{row['vertex']};gap=g.z_exact(T)-g.z_exact(C);pen=penalty(g,R,T,C);count+=1
            if gap!=F(row['Z_gap_exact']) or pen!=F(row['penalty_exact']) or gap-pen!=F(row['margin_exact']):violations.append({'file':path.name,'row':row,'actual_gap':str(gap),'actual_penalty':str(pen)})
    output=PROJECT/'results/diagnostics/m2_dev_v12_001/margin_crosscheck.json'
    if output.exists():raise RuntimeError('Immutable result already exists')
    output.write_text(json.dumps({'status':'PASS' if not violations else 'FAIL','checks':count,'violations':violations,'scope':'Independent direct core Z_exact and full penalty versus analytic one-point diagnostic arithmetic on three sampled rows per actual query','source_SHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2)+'\n');print(count,'checks',len(violations),'violations')
    if violations:raise RuntimeError('Diagnostic arithmetic disagrees')


if __name__=='__main__':main()
