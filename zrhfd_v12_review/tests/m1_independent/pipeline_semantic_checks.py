"""Independent control-flow audit of frozen graph pipeline, using labelled stubs."""
from pathlib import Path
from fractions import Fraction as F
from unittest.mock import patch
import hashlib
import json
import platform
import sys
import time
import numpy as np
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from zrhfd.graph import Graph
from zrhfd.diffusion import Scores
from zrhfd.pipeline import run,Config


def case(n,activation,improving):
    g=Graph.from_edges(n,[(u,u+1) for u in range(n-1)]);calls=[]
    def solve(graph,seed,mass,*args):
        calls.append(mass);x=np.zeros(graph.n).view(Scores);x[seed]=mass
        if mass>=activation:x[1]=mass/2
        x.support=np.flatnonzero(x>0)
        return x,{"mass":mass,"queue_pending":0,"support_size":len(x.support)}
    def sweep(graph,x,seed,objective):
        value=F(2)-F(len(calls),10) if improving else F(2)
        return [seed],value,[{"score":float(x[seed]),"value":float(value)}]
    with patch('zrhfd.pipeline.solve_graph',solve),patch('zrhfd.pipeline.level_sweep',sweep):
        result=run(g,0,Config(refine=False))
    return {"calls":calls,"output":result}


def main():
    start=time.perf_counter();a=case(250,48,False);b=case(20,6,True)
    checks={"no_patience_before_activation":a['calls'][:5]==[3,6,12,24,48],
        "activation_index":a['output']['j_act']==4,
        "patience_counts_from_activation_inclusive_reference_semantics":a['output']['stop_reason']=='post_activation_patience' and a['calls']==[3,6,12,24,48,96,192],
        "region_next_mass_beyond_budget":b['calls']==[3,6,12,24] and b['output']['j_star']==2 and b['output']['diffusion_trace'][-1].get('supplement_for_region') is True,
        "region_contains_seed_initial":set(b['output']['S0'])<=set(b['output']['region_vertices']) and 0 in b['output']['region_vertices']}
    result={"scope":"Control-flow audit with explicitly stubbed diffusion/sweep. Actual numerical diffusion and MM tested separately; stubs are not claimed to solve frozen objectives.","checks":checks,"failures":sum(not v for v in checks.values()),"actual_issues":[],"notes":["Patience starts inclusively at j_act, matching supplied checks_g3b.py lines9-14. Frozen text interpretation remains theory-owned.","R-supp supplements j_star+1 even above M/2.","Core tie blocks and exact Fraction acceptance were separately crosschecked.","Approximate score ties are literal equal stored float values; root solver metadata explicitly records approximate precision."],"raw":[a,b],"metadata":{"elapsed_seconds":time.perf_counter()-start,"platform":platform.platform(),"python":platform.python_version(),"pipeline_SHA256":hashlib.sha256((PROJECT/'zrhfd/pipeline.py').read_bytes()).hexdigest()}}
    p=PROJECT/'results/m1_independent/pipeline_semantic_checks.json'
    if p.exists():raise RuntimeError('Immutable raw output exists')
    p.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(checks,indent=2))


if __name__=='__main__':main()
