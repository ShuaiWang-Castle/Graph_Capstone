"""Exact seeded parametric cuts and a numerically evaluated regional lower bound."""
from fractions import Fraction
import math
from decimal import Decimal,localcontext,ROUND_FLOOR,ROUND_CEILING
from .mincut import cut_with_unary


def _fraction_interval(value):
    with localcontext() as c:
        c.prec=80;c.rounding=ROUND_FLOOR
        lo=Decimal(value.numerator)/Decimal(value.denominator)
        c.rounding=ROUND_CEILING
        hi=Decimal(value.numerator)/Decimal(value.denominator)
    return lo,hi


def _stationary_interval(slope,intercept,M):
    slo,shi=_fraction_interval(slope);blo,bhi=_fraction_interval(intercept/M)
    with localcontext() as c:
        c.prec=80
        # Decimal sqrt is correctly rounded; adjacent representable values
        # enclose the exact root. Propagate outward rounding through addition.
        rootlo=blo.sqrt().next_minus();roothi=bhi.sqrt().next_plus()
        c.rounding=ROUND_FLOOR;lo=slo+Decimal(2)*rootlo
        c.rounding=ROUND_CEILING;hi=shi+Decimal(2)*roothi
    return lo,hi


def regional_certificate(graph, seed, region):
    R=sorted(set(region));M=int(round(graph.total))
    def point(S):
        st=graph.stats(S)
        return (int(st['volume']),int(st['cut']),tuple(sorted(S)))
    left,right=point([seed]),point(R)
    cache={};oracle_trace=[]
    def recurse(a,b):
        if a[0]==b[0]:return [min(a,b,key=lambda p:p[1])]
        slope=Fraction(b[1]-a[1],b[0]-a[0])
        if slope not in cache:
            unary={u:-slope*int(round(graph.degree[u])) for u in R}
            S,value,meta=cut_with_unary(graph,R,seed,unary)
            cache[slope]=point(S),value
            oracle_trace.append({'slope_exact':str(slope),'objective_exact':str(value),
                'point':{'volume':cache[slope][0][0],'cut':cache[slope][0][1],
                         'vertices':list(cache[slope][0][2])},'telemetry':meta})
        p,value=cache[slope]
        line=Fraction(a[1])-slope*a[0]
        if value==line:return [a,b]
        if value>line or not a[0]<p[0]<b[0]:
            raise RuntimeError('Exact parametric lower hull oracle contradiction')
        return recurse(a,p)[:-1]+recurse(p,b)
    hull=recurse(left,right)
    candidates=[];width_bound=Fraction(0)
    for i,p in enumerate(hull):
        v,c,_=p
        lo,hi=_fraction_interval(Fraction(c,v)+Fraction(v,M))
        candidates.append({'volume':float(v),'value':float(Fraction(c,v)+Fraction(v,M)),
                           'lower_decimal':str(lo),'upper_decimal':str(hi),
                           'kind':'vertex','vertex_index':i})
    for a,b in zip(hull,hull[1:]):
        va,ca,_=a;vb,cb,_=b
        slope=Fraction(cb-ca,vb-va);intercept=Fraction(ca)-slope*va
        width_bound=max(width_bound,Fraction((vb-va)**2,4*M*va))
        if intercept>0:
            stationary=math.sqrt(float(intercept*M))
            if va*va<intercept*M<vb*vb:
                lo,hi=_stationary_interval(slope,intercept,M)
                candidates.append({'volume':stationary,
                    'value':float(slope)+2*math.sqrt(float(intercept)/M),
                    'lower_decimal':str(lo),'upper_decimal':str(hi),
                    'kind':'segment_stationary','slope_exact':str(slope),
                    'intercept_exact':str(intercept)})
    lb=min(candidates,key=lambda c:c['value'])
    lower=min(Decimal(c['lower_decimal']) for c in candidates)
    upper=min(Decimal(c['upper_decimal']) for c in candidates)
    best=min(hull,key=lambda p:Fraction(p[1],p[0])+Fraction(p[0],M))
    return {'LB_R':math.nextafter(float(lower),-math.inf),'LB_R_upper':math.nextafter(float(upper),math.inf),
        'LB_R_lower_decimal':str(lower),'LB_R_upper_decimal':str(upper),
        'LB_evaluation':'exact rational hull; 80-digit Decimal outward-rounded analytic stationary intervals; reported lower float rounded down',
        'LB_minimizer':lb,'hull_vertices':[{'volume':p[0],'cut':p[1],'vertices':list(p[2])} for p in hull],
        'hull_best':list(best[2]),'hull_best_Z_exact':str(Fraction(best[1],best[0])+Fraction(best[0],M)),
        'gap_bound_telemetry':float(width_bound),'gap_bound_exact':str(width_bound),
        'mincut_calls':len(oracle_trace),'oracle_trace':oracle_trace,
        'certificate_status':'EXACT_HULL_WITH_OUTWARD_ROUNDED_LB_INTERVAL'}
