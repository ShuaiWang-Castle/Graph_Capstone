"""Exhaustive finite engineering checks, independent direct binomial oracle."""
from fractions import Fraction as F
from math import comb
from pathlib import Path
import hashlib
import json
import random
import sys
import time
import argparse
import numpy as np
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT));sys.path.insert(0,str(PROJECT/'tests/m1_independent'))
from zrhfd.hyper import Hypergraph,cut_with_unary,mm_refine,regional_certificate,solve_hypergraph
from zrhfd.hyper.pipeline import level_sweep,capped_region
from exact_claim_checks import Claims,enc,lower_hull
from hyper_diffusion_checks import prepare,solve


def vertices(S,n):return [u for u in range(n) if S >> u & 1]
def mask(S):return sum(1 << int(u) for u in S)
def direct(h,S):
    vs=set(vertices(S,h.n));degree=[sum((theta for e,theta,w in h.edges if u in e),F(0)) for u in range(h.n)];v=sum((degree[u] for u in vs),F(0));M=sum(degree);cut=sum((theta*w[len(vs.intersection(e))] for e,theta,w in h.edges),F(0));p=v/M
    psi=sum((theta*sum((F(comb(len(e),j))*w[j]*p**j*(1-p)**(len(e)-j) for j in range(len(e)+1)),F(0)) for e,theta,w in h.edges),F(0));G=v-psi
    return v,cut,G,(cut+G)/v if v else None


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check-existing',action='store_true');parser.add_argument('--output',type=Path);args=parser.parse_args()
    start=time.perf_counter();rng=random.Random(271829);checks=Claims();raw=[]
    for kind in ['all_or_nothing','cardinality_min']:
        for n in [5,8]:
            edges=[tuple([u,u+1]) for u in range(n-1)]+[tuple(sorted(rng.sample(range(n),rng.randrange(3,min(5,n)+1)))) for _ in range(n)]
            h=Hypergraph.from_edges(n,edges,kind);oracle={S:direct(h,S) for S in range(1 << n)};record={'n':n,'splitting':kind,'edges':h.edges,'seeded_subsets':1 << (n-1),'cuts':[],'MM':[],'diffusion':[]}
            for S in range(1 << n):
                v,c,g,z=oracle[S];vs=vertices(S,n)
                checks.check('hyper-volume',h.volume(vs)==v);checks.check('hyper-cut',h.cut(vs)==c);checks.check('hyper-G-polynomial',h.G(v)==g)
                if S:checks.check('hyper-Z',h.z_exact(vs)==z)
            for R in [((1 << n)-1),7,1]:
                candidates=[S for S in range(1,1 << n,2) if S & ~R==0];Rv=vertices(R,n)
                for repeat in range(6):
                    unary={u:F(rng.randrange(-9,10),rng.randrange(1,6)) for u in Rv};values={S:oracle[S][1]+sum((unary[u] for u in vertices(S,n)),F(0)) for S in candidates};selected,value,meta=cut_with_unary(h,Rv,0,unary)
                    checks.check('hyper-mincut-optimum',value==min(values.values()),{'n':n,'kind':kind,'R':R,'unary':unary,'selected':selected,'value':value,'expected':min(values.values())});checks.check('hyper-mincut-full-boundary',values[mask(selected)]==value)
                    record['cuts'].append({'R':R,'unary':unary,'selected':selected,'value':value,'telemetry':meta})
                certificate=regional_certificate(h,0,Rv);expected=lower_hull([(oracle[S][0],oracle[S][1],S) for S in candidates]);coordinates=[(F(p['volume_exact']),F(p['cut_exact'])) for p in certificate['hull_vertices']]
                checks.check('hyper-exact-hull',coordinates==[(v,c) for v,c,S in expected],{'n':n,'kind':kind,'R':R,'actual':coordinates,'expected':expected});optimum=min(oracle[S][3] for S in candidates)
                checks.check('hyper-LB-range',certificate['LB_R']<=float(optimum)+1e-9 and optimum<=F(certificate['hull_best_Z_exact']),{'certificate':certificate,'optimum':optimum})
                score=np.array([float(u%3) for u in range(n)]);starts=candidates if n==5 else [1,R,candidates[len(candidates)//2]]
                for initial in starts:
                    selected,trace=mm_refine(h,0,Rv,vertices(initial,n),score);S=initial
                    for row in trace:
                        order=sorted(Rv,key=lambda u:(0 if u==0 else(1 if S >> u & 1 else 2),-score[u],u));D=F(0);unary={}
                        for u in order:
                            prev=D;D+=h.degree_exact[u]
                            # Direct binomial G at prefix volumes, without polynomial method.
                            def dg(v):
                                p=v/h.total_exact
                                return v-sum((theta*sum((F(comb(len(e),j))*w[j]*p**j*(1-p)**(len(e)-j) for j in range(len(e)+1)),F(0)) for e,theta,w in h.edges),F(0))
                            unary[u]=dg(D)-dg(prev)-oracle[S][3]*h.degree_exact[u]
                        values={T:oracle[T][1]+sum((unary[u] for u in vertices(T,n)),F(0)) for T in candidates};T=mask(row['vertices']);value=F(row['mincut_objective_exact'])
                        checks.check('hyper-MM-step',row['order']==order and value==min(values.values()) and values[T]==value);checks.check('hyper-MM-exact-acceptance',row['accepted']==(oracle[T][3]<oracle[S][3]));checks.check('hyper-MM-zero',values[S]==0)
                        if row['accepted']:S=T
                    checks.check('hyper-MM-stationary',mask(selected)==S and F(trace[-1]['mincut_objective_exact'])==0);record['MM'].append({'R':R,'initial':initial,'selected':selected,'trace':trace})
            score=np.array([float(3-u//2) if u<6 else 0 for u in range(n)]);selected,value,trace=level_sweep(h,score,0);levels=[mask(np.flatnonzero(score>=t)) for t in sorted(set(score)) if t>0]
            checks.check('hyper-sweep-ties',mask(selected) in levels and value==min(oracle[S][3] for S in levels))
            for theta in [F(1,4),F(1,2),F(1)]:
                allowed=[0]+[S for S in levels if oracle[S & ~1][0]<=theta*oracle[1][0]];expected=1|max(allowed,key=lambda S:oracle[S][0]);checks.check('hyper-cap-ties',mask(capped_region(h,[0],score,theta))==expected)
            if n==5:
                # Independent full-permutation epigraph against different sum-largest encoding.
                from exact_claim_checks import Hypergraph as IndependentHypergraph
                independent=IndependentHypergraph(n,h.edges,'independent');prepared=prepare(independent,1e-4)
                for mass in [3*h.degree[0],h.total/2,h.total]:
                    score,telemetry=solve_hypergraph(h,0,mass,tolerance=1e-12);reference=solve(independent,prepared,F(str(mass)),1e-4);difference=float(np.max(np.abs(score-np.array(reference['x']))));tol=1e-6*max(1,float(score.max()))
                    checks.check('hyper-diffusion-independent-encoding',difference<=tol,{'kind':kind,'mass':mass,'difference':difference,'tol':tol});checks.check('hyper-diffusion-objective',abs(telemetry['objective']-reference['objective'])<=1e-7*max(1,abs(reference['objective'])));checks.check('hyper-diffusion-mass-balance',telemetry['scaled_mass_balance_residual']<1e-6);record['diffusion'].append({'mass':mass,'difference':difference,'telemetry':telemetry,'independent':reference})
            raw.append(record);print(kind,n,'complete',flush=True)
    h=Hypergraph.from_edges(5,[(0,1,2,3,4)]);unary={u:F((-1)**u,(1 << 150)+33) for u in range(5)};selected,value,meta=cut_with_unary(h,list(range(5)),0,unary);expected=min(h.cut(vertices(S,5))+sum((unary[u] for u in vertices(S,5)),F(0)) for S in range(1,32,2));checks.check('hyper-bigint-exact-fallback',value==expected and meta['backend']=='NetworkX_exact_arbitrary_integer_preflow_push',{'value':value,'expected':expected,'telemetry':meta})
    graph_h=Hypergraph.from_edges(4,[(0,1),(1,2),(2,3),(0,3)])
    for S in range(1,16):checks.check('hyper-ordinary-two-edge-reduction',graph_h.G(graph_h.volume(vertices(S,4)))==graph_h.volume(vertices(S,4))**2/graph_h.total_exact)
    result={'schema_version':1,'scope':'Exhaustive all seeded subsets on each finite n=5,8 hypergraph; direct per-edge Fraction binomial oracle; all-none Lawler/cardinality-min capped gadget exact cuts; numerical high-accuracy small diffusion and LB; no timing claims','encoding_history':{'initial_raw':'results/m5_core/core_checks.json','reason':'Sum-largest engineering CVXPY encoding returned optimal_inaccurate on small cases. Frozen objective unchanged; small-rank encoding replaced with explicit linear permutation constraints; initial failed measurements retained.'},'claims':checks.data,'raw':raw,'bigint_case':{'unary':unary,'selected':selected,'value':value,'telemetry':meta},'metadata':{'elapsed_seconds':time.perf_counter()-start,'timing_claim':False,'source_SHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    p=args.output or PROJECT/'results/m5_core/core_checks_linear_epigraph.json';p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():
        if args.check_existing:
            previous=json.loads(p.read_text());assert {k:(v['checks'],v['violations']) for k,v in previous['claims'].items()}=={k:(v['checks'],v['violations']) for k,v in checks.data.items()};print('CHECK_EXISTING_PASS');return
        raise RuntimeError('Preserve immutable raw measurement')
    p.write_text(json.dumps(enc(result),indent=2)+'\n');print(json.dumps({k:{'checks':v['checks'],'violations':v['violations']} for k,v in checks.data.items()},indent=2))


if __name__=='__main__':main()
