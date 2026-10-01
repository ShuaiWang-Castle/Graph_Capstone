"""Budgeted rational enclosure of the continuous objective on an exact hull.

The existing float certificate remains available and is not overwritten.
The enclosure uses exact Fraction tangents after checking nonnegative
Bernstein coefficients of G'' over [0,M]. No new theory is asserted.
"""
from fractions import Fraction as F
from math import comb
import math
import hashlib
import heapq
import json
from pathlib import Path
import time


def _polynomial(coefficients, value):
    result=F(0)
    for coefficient in reversed(coefficients):result=result*value+coefficient
    return result


def _convexity_check(h, objective):
    if objective=='ZH-prov':coefficients=[F(0),F(0),1/h.total_exact]
    elif objective=='ZH':coefficients=list(h.G_coefficients)
    else:raise ValueError('Unknown explicit objective')
    # Transform G(M*p)'' to the Bernstein basis on p in [0,1].
    power=[coefficients[k]*h.total_exact**k*k*(k-1) for k in range(2,len(coefficients))]
    # Retain the natural rank-2 degree even when the top power coefficient is
    # zero: reducing Bernstein degree can lose a nonnegative sign witness.
    if not power:power=[F(0)]
    degree=len(power)-1
    bernstein=[sum((power[k]*F(comb(i,k),comb(degree,k)) for k in range(i+1)),F(0)) for i in range(degree+1)]
    result={'status':'PASS' if min(bernstein)>=0 else 'UNVERIFIED','method':'exact Bernstein coefficient nonnegativity of second derivative of G(M*p) on [0,1]','degree':degree,'minimum_coefficient_exact':str(min(bernstein)),'maximum_coefficient_exact':str(max(bernstein)),'coefficients_sha256':hashlib.sha256(json.dumps(list(map(str,bernstein)),separators=(',',':')).encode()).hexdigest(),'uses_float_sign_decisions':False}
    return coefficients,result


def enclose_lower_bound(h, certificate, objective='ZH', absolute_tolerance=F(1,10**8), max_nodes=512, wall_seconds=5.):
    """Return exact rational lower/upper bounds, preserving an explicit budget.

    Bounds enclose the minimum of (exact hull cut interpolant+G(v))/v.
    Hull validity is delegated to the original exact parametric cut engine.
    A budget stop preserves valid bounds and does not claim target precision.
    """
    started=time.perf_counter();tolerance=F(str(absolute_tolerance));max_nodes=int(max_nodes)
    if tolerance<0 or max_nodes<1 or wall_seconds<=0:raise ValueError('Invalid explicit enclosure budget')
    points=[(F(p['volume_exact']),F(p['cut_exact'])) for p in certificate['hull_vertices']]
    if not points or any(v<=0 for v,c in points):raise ValueError('Positive-volume exact hull required')
    if any(points[i][0]>=points[i+1][0] for i in range(len(points)-1)):raise ValueError('Hull volumes must strictly increase')
    coefficients,convexity=_convexity_check(h,objective)
    base={'scope':'continuous exact-hull objective enclosure; not an exact minimizer, theorem proof, or general-cardinality gate clearance','hull_status':certificate.get('certificate_status'),'convexity':convexity,'budget':{'absolute_tolerance_exact':str(tolerance),'max_nodes':max_nodes,'wall_seconds':wall_seconds},'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'float_certificate_retained':{'LB_R':certificate.get('LB_R'),'status':certificate.get('certificate_status')}}
    if convexity['status']!='PASS':
        return dict(base,status='NO_ENCLOSURE_CONVEXITY_UNVERIFIED',runtime_seconds=time.perf_counter()-started)
    prime=[k*coefficients[k] for k in range(1,len(coefficients))]
    def null(v):return _polynomial(coefficients,v)
    def value(v,a,b):return a+(b+null(v))/v
    heap=[];events=[];counter=0;upper=None;upper_point=None
    def add(lo,hi,a,b,parent_lower=None):
        nonlocal counter,upper,upper_point
        middle=(lo+hi)/2;gm=null(middle);slope=_polynomial(prime,middle)
        constant=b+gm-middle*slope
        lower=min(a+slope+constant/lo,a+slope+constant/hi)
        if parent_lower is not None:lower=max(lower,parent_lower)
        candidates=[(value(v,a,b),v) for v in [lo,middle,hi]];ub,point=min(candidates)
        if lower>ub:raise RuntimeError('Rational enclosure contradiction')
        if upper is None or ub<upper:upper=ub;upper_point=point
        node=(lower,counter,lo,hi,a,b,ub);heapq.heappush(heap,node)
        events.append({'node':counter,'lo_exact':str(lo),'hi_exact':str(hi),'lower_exact':str(lower),'upper_exact':str(ub),'parent_lower_exact':str(parent_lower) if parent_lower is not None else None});counter+=1
    if len(points)==1:
        v,c=points[0];exact=(c+null(v))/v
        return dict(base,status='EXACT_SINGLE_HULL_VERTEX',lower_exact=str(exact),upper_exact=str(exact),width_exact='0',lower_float=math.nextafter(float(exact),-math.inf),upper_float=math.nextafter(float(exact),math.inf),upper_volume_exact=str(v),nodes_evaluated=0,stop_reason='singleton_domain',runtime_seconds=time.perf_counter()-started,branch_trace=[],rigorous_arithmetic=True,exact_hull_assumption=True)
    def incomplete_initialization():
        # Coarse nonnegative-objective enclosure when full initial coverage is over budget.
        if coefficients[0]<0 or len(coefficients)>1 and coefficients[1]<0 or min(c for v,c in points)<0:
            return dict(base,status='NO_ENCLOSURE_INITIAL_BUDGET',nodes_evaluated=counter,stop_reason='initial_coverage_budget',runtime_seconds=time.perf_counter()-started,branch_trace=events)
        ub,point=min(((c+null(v))/v,v) for v,c in points)
        return dict(base,status='RATIONAL_ENCLOSURE_BUDGET_STOP',lower_exact='0',upper_exact=str(ub),width_exact=str(ub),lower_float=math.nextafter(0.,-math.inf),upper_float=math.nextafter(float(ub),math.inf),upper_volume_exact=str(point),nodes_evaluated=counter,stop_reason='initial_coverage_budget',runtime_seconds=time.perf_counter()-started,branch_trace=events,rigorous_arithmetic=True,exact_hull_assumption=True,coarse_fallback='nonnegative exact cut and certified convex G with nonnegative G(0),Gprime(0)')
    for (lo,cl),(hi,ch) in zip(points,points[1:]):
        if counter>=max_nodes or time.perf_counter()-started>=wall_seconds:return incomplete_initialization()
        a=(ch-cl)/(hi-lo);b=cl-a*lo;add(lo,hi,a,b)
    while True:
        while heap and heap[0][0]>=upper:heapq.heappop(heap)
        lower=min(upper,heap[0][0]) if heap else upper
        if upper-lower<=tolerance:stop='target_width';break
        if counter+2>max_nodes:stop='max_nodes';break
        if time.perf_counter()-started>=wall_seconds:stop='wall_budget';break
        lb,identity,lo,hi,a,b,ub=heapq.heappop(heap);middle=(lo+hi)/2
        add(lo,middle,a,b,lb);add(middle,hi,a,b,lb)
    status='RATIONAL_ENCLOSURE_TARGET_MET' if stop=='target_width' else 'RATIONAL_ENCLOSURE_BUDGET_STOP'
    return dict(base,status=status,lower_exact=str(lower),upper_exact=str(upper),width_exact=str(upper-lower),lower_float=math.nextafter(float(lower),-math.inf),upper_float=math.nextafter(float(upper),math.inf),upper_volume_exact=str(upper_point),nodes_evaluated=counter,stop_reason=stop,runtime_seconds=time.perf_counter()-started,branch_trace=events,rigorous_arithmetic=True,exact_hull_assumption=True)
