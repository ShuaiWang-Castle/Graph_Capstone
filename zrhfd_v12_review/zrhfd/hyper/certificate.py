"""Exact parametric seeded hull with explicitly numerical continuous LB."""
from fractions import Fraction as F
from scipy.optimize import minimize_scalar
from .mincut import cut_with_unary


def regional_certificate(hypergraph,seed,region,objective='ZH'):
    h=hypergraph;R=sorted(set(region));cache={};trace=[]
    def point(S):return h.volume(S),h.cut(S),tuple(sorted(S))
    def recurse(a,b):
        if a[0]==b[0]:return [min(a,b,key=lambda p:p[1])]
        slope=(b[1]-a[1])/(b[0]-a[0])
        if slope not in cache:
            S,value,meta=cut_with_unary(h,R,seed,{u:-slope*h.degree_exact[u] for u in R});p=point(S);cache[slope]=(p,value)
            trace.append({'slope_exact':str(slope),'objective_exact':str(value),'point':{'volume_exact':str(p[0]),'cut_exact':str(p[1]),'vertices':list(p[2])},'telemetry':meta})
        p,value=cache[slope];line=a[1]-slope*a[0]
        if value==line:return [a,b]
        if value>line or not a[0]<p[0]<b[0]:raise RuntimeError('Hyper parametric hull contradiction')
        return recurse(a,p)[:-1]+recurse(p,b)
    hull=recurse(point([seed]),point(R));best=min(hull,key=lambda p:h.z_exact(p[2],objective));candidates=[]
    null=h.G_float if objective=='ZH' else lambda v:v*v/h.total
    for v,c,S in hull:candidates.append({'volume':float(v),'value':float(h.z_exact(S,objective)),'kind':'vertex'})
    for a,b in zip(hull,hull[1:]):
        slope=(b[1]-a[1])/(b[0]-a[0]);intercept=a[1]-slope*a[0]
        function=lambda v:float(slope)+float(intercept)/v+null(v)/v
        result=minimize_scalar(function,bounds=(float(a[0]),float(b[0])),method='bounded',options={'xatol':1e-11})
        candidates.append({'volume':float(result.x),'value':float(result.fun),'kind':'numeric_segment_minimum','optimizer_success':bool(result.success),'slope_exact':str(slope),'intercept_exact':str(intercept)})
    lb=min(candidates,key=lambda p:p['value'])
    return {'LB_R':lb['value'],'LB_minimizer':lb,'LB_evaluation':'numeric continuous minimization and stable binomial expectation over exact Fraction hull; no directed-rounding guarantee','hull_vertices':[{'volume_exact':str(v),'cut_exact':str(c),'vertices':list(S)} for v,c,S in hull],'hull_best':list(best[2]),'hull_best_Z_exact':str(h.z_exact(best[2],objective)),'mincut_calls':len(trace),'oracle_trace':trace,'certificate_status':'EXACT_HULL_WITH_NUMERIC_LB_EVALUATION'}
