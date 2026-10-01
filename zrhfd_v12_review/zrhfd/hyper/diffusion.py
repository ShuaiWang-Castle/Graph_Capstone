"""Small-instance CPU reference diffusion; native adapters may replace this solver."""
import time
import numpy as np
from collections import Counter


class HyperScores(np.ndarray):
    pass


def capped_coefficients(w):
    half=(len(w)-1)//2;slopes=[w[j]-w[j-1] for j in range(1,half+1)]+[0]
    return [(j,slopes[j-1]-slopes[j]) for j in range(1,half+1) if slopes[j-1]-slopes[j]]


def solve_hypergraph(hypergraph,seed,mass,sigma=1e-4,tolerance=1e-10,support_tolerance=1e-7):
    import cvxpy as cp
    h=hypergraph
    if h.degree[seed]<=0:raise ValueError('Positive-degree seed required')
    start=time.perf_counter();x=cp.Variable(h.n);t=cp.Variable(len(h.edges));positive=x>=0;tp=t>=0;constraints=[positive,tp]
    rows=[];cols=[];data=[];owners=[]
    def permutations_multiset(values):
        counts=Counter(values);keys=sorted(counts);prefix=[]
        def visit():
            if len(prefix)==len(values):yield tuple(prefix);return
            for value in keys:
                if counts[value]:
                    counts[value]-=1;prefix.append(value);yield from visit();prefix.pop();counts[value]+=1
        yield from visit()
    linear=all(len(e)<=8 for e,theta,w in h.edges)
    if linear:
        from scipy.sparse import coo_matrix
        for k,(e,theta,w) in enumerate(h.edges):
            slopes=[w[j+1]-w[j] for j in range(len(e))]
            for coefficients in permutations_multiset(slopes):
                row=len(owners);owners.append(k)
                for u,c in zip(e,coefficients):
                    if c:rows.append(row);cols.append(u);data.append(float(c))
        B=coo_matrix((data,(rows,cols)),shape=(len(owners),h.n)).tocsr();owners=np.array(owners);epi=B@x<=t[owners];constraints.append(epi)
    else:
        for k,(e,theta,w) in enumerate(h.edges):
            xe=x[list(e)];fe=0
            for b,a in capped_coefficients(w):fe+=float(a)*(cp.sum_largest(xe,b)+cp.sum_largest(-xe,b))
            constraints.append(fe<=t[k])
    zero=np.flatnonzero(h.degree==0)
    if len(zero):constraints.append(x[zero]==0)
    injection=np.zeros(h.n);injection[seed]=mass
    weights=np.array([float(theta) for e,theta,w in h.edges])
    objective=.5*cp.sum(cp.multiply(weights,cp.square(t)))+.5*sigma*cp.sum(cp.multiply(h.degree,cp.square(x)))-(injection-h.degree)@x
    problem=cp.Problem(cp.Minimize(objective),constraints)
    value=problem.solve(solver='CLARABEL',tol_gap_abs=tolerance,tol_gap_rel=tolerance,tol_feas=tolerance,max_iter=500)
    if x.value is None or problem.status not in ['optimal','optimal_inaccurate']:raise RuntimeError(f'Hyper diffusion failed: {problem.status}')
    raw=np.maximum(x.value,0);threshold=support_tolerance*max(1,float(raw.max()));raw[raw<=threshold]=0
    score=raw.view(HyperScores);score.support=np.flatnonzero(raw>0);U=set(map(int,score.support));rhs=0.0
    square_sum=0.0
    for e,theta,w in h.edges:
        sorted_x=sorted((score[u] for u in e),reverse=True);fe=sum(float(w[j])*(sorted_x[j-1]-sorted_x[j]) for j in range(1,len(e)))
        rhs+=float(theta)*fe*float(w[len(U.intersection(e))]);square_sum+=float(theta)*fe*fe
    rhs+=sigma*float(h.degree@score);residual=float(mass)-float(h.volume(U))-rhs
    actual_objective=.5*square_sum+.5*sigma*float(h.degree@(score*score))-float((injection-h.degree)@score)
    telemetry={'mass':float(mass),'solver':'CVXPY_CLARABEL_GLOBAL_SMALL_INSTANCE_REFERENCE','epigraph_encoding':'exact_linear_permutation' if linear else 'convex_sum_largest','solver_status':problem.status,'objective':actual_objective,'solver_epigraph_objective':float(value),'runtime_seconds':time.perf_counter()-start,'support_size':len(U),'support_volume':float(h.volume(U)),'mass_balance_residual':residual,'scaled_mass_balance_residual':abs(residual)/max(1,float(mass)),'seed_is_max':bool(score[seed]>=score.max()-10*threshold),'support_components':len(h.components(U)),'support_contains_seed':seed in U,'support_threshold':threshold,'precision_mode':'float64_high_accuracy_approximate','actual_solver_input_vertices':h.n,'actual_solver_input_hyperedges':len(h.edges),'actual_solver_input_volume':h.total,'locality_claim':False}
    if linear:
        nu=np.asarray(epi.dual_value);rx=sigma*h.degree*np.asarray(x.value)-(injection-h.degree)+B.T@nu-np.asarray(positive.dual_value);rt=weights*np.asarray(t.value)-np.bincount(owners,weights=nu,minlength=len(weights))-np.asarray(tp.dual_value)
        telemetry['scaled_stationarity']=max(float(np.max(np.abs(rx))),float(np.max(np.abs(rt))))/max(1,float(mass))
        telemetry['scaled_complementarity']=max(float(np.max(np.abs(nu*(B@x.value-t.value[owners])))),float(np.max(np.abs(np.asarray(positive.dual_value)*x.value))))/max(1,float(mass))
    return score,telemetry


def native_author_diffusion(hypergraph,seed,mass,sigma=1e-4,tolerance=1e-10,support_tolerance=1e-7):
    from ..baselines.hfd import solve_hyper
    h=hypergraph
    if any(any(w[j]!=1 for j in range(1,len(w)-1)) for e,theta,w in h.edges):raise ValueError('Author native adapter verified for unit all-or-nothing only')
    raw,telemetry=solve_hyper(h,seed,mass,sigma=sigma,tolerance=tolerance,support_tolerance=support_tolerance,artifact_directory='reviews/m5_core/native_logs')
    if telemetry.get('status')!='COMPLETED':raise RuntimeError('Native author diffusion did not complete; do not score timeout as converged')
    raw=np.maximum(np.asarray(raw,dtype=float),0);threshold=support_tolerance*max(1,float(raw.max()));raw[raw<=threshold]=0;score=raw.view(HyperScores);score.support=np.flatnonzero(raw>0)
    telemetry=dict(telemetry);telemetry.update(mass=float(mass),support_threshold=threshold,support_size=len(score.support),support_volume=float(h.volume(score.support)),native_adapter_score_contract='author dual x from excess/degree/sigma; see author adapter telemetry',precision_mode='author_finite_iteration_approximate',locality_claim=False)
    return score,telemetry
