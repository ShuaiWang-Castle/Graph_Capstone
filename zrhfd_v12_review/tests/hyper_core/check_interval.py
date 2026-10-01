"""Small rational-enclosure check; no theory proof or formal timing claim."""
from pathlib import Path
from fractions import Fraction as F
import argparse
import json
import sys
import mpmath as mp
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from zrhfd.hyper import Hypergraph
from zrhfd.hyper.interval_certificate import enclose_lower_bound
from experiments.m5.inputs import immutable_json,digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='results/m5/interval_small_v12_001.json');args=parser.parse_args();mp.mp.dps=70
    rows=[];violations=[]
    for rank,splitting in [(2,'all_or_nothing'),(3,'all_or_nothing'),(4,'all_or_nothing'),(7,'all_or_nothing'),(4,'cardinality_min')]:
        h=Hypergraph.from_edges(rank,[tuple(range(rank))],splitting);certificate={'certificate_status':'CONTROLLED_EXACT_SINGLE_EDGE_HULL','hull_vertices':[{'volume_exact':'1','cut_exact':'1'},{'volume_exact':str(rank),'cut_exact':'0'}]}
        out=enclose_lower_bound(h,certificate,max_nodes=256,wall_seconds=2.)
        if out['convexity']['status']!='PASS' or not out.get('rigorous_arithmetic'):violations.append((rank,splitting,'no enclosure'))
        a=F(-1,rank-1);b=F(rank,rank-1)
        def value(v):return a+(b+h.G(v))/v
        low=F(out['lower_exact']);up=F(out['upper_exact']);v=F(out['upper_volume_exact'])
        if value(v)!=up:violations.append((rank,splitting,'upper witness'))
        if F.from_float(out['lower_float'])>low or F.from_float(out['upper_float'])<up:violations.append((rank,splitting,'outward floats'))
        if any(value(F(1)+F(k,200)*(rank-1))<low for k in range(201)):violations.append((rank,splitting,'grid below lower'))
        # Independent high-precision bisection of the derivative numerator.
        def mf(v):return mp.mpf(v.numerator)/v.denominator
        coefficients=list(map(mf,h.G_coefficients));aa=mf(a);bb=mf(b)
        def horner(cs,x):
            answer=mp.mpf(0)
            for c in reversed(cs):answer=answer*x+c
            return answer
        prime=[k*coefficients[k] for k in range(1,len(coefficients))]
        stationary=lambda x:x*horner(prime,x)-horner(coefficients,x)-bb
        l=mp.mpf(1);r=mp.mpf(rank)
        if stationary(l)>=0:star=l
        elif stationary(r)<=0:star=r
        else:
            for _ in range(220):
                m=(l+r)/2
                if stationary(m)<0:l=m
                else:r=m
            star=(l+r)/2
        minimum=aa+(bb+horner(coefficients,star))/star
        if not mf(low)<=minimum+mp.mpf('1e-65')<=mf(up)+mp.mpf('1e-65'):violations.append((rank,splitting,'highprecision minimum outside'))
        rows.append({'rank':rank,'splitting':splitting,'enclosure':out,'highprecision_minimum':str(minimum),'highprecision_minimizer':str(star),'grid_points':201})
    h=Hypergraph.from_edges(4,[(0,1,2,3)]);cert={'hull_vertices':[{'volume_exact':'1','cut_exact':'1'},{'volume_exact':'2','cut_exact':'1'},{'volume_exact':'4','cut_exact':'0'}]}
    coarse=enclose_lower_bound(h,cert,max_nodes=1,wall_seconds=2.)
    if coarse['lower_exact']!='0' or coarse['stop_reason']!='initial_coverage_budget':violations.append('initial budget fallback')
    out={'schema_version':1,'status':'PASS' if not violations else 'FAIL','violations':violations,'small_domain_cases':rows,'coarse_initial_budget':coarse,'scope':'only controlled tiny convex unit/concave inputs; not generic frozen cardinality verification','formal_measurement':False,'source_sha256':digest('tests/hyper_core/check_interval.py')}
    immutable_json(PROJECT/args.output,out);print(json.dumps({'status':out['status'],'violations':violations,'small_cases':len(rows)}))
    if violations:raise SystemExit(1)


if __name__=='__main__':main()
