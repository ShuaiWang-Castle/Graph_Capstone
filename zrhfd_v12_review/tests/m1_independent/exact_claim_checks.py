"""Independent exact finite checks of frozen ZR-HFD v1.2 claim statements.

All subsets containing vertex 0 are enumerated for each specified n<=14 graph.
This does not enumerate all graphs on those sizes. No theory proofs are supplied.
"""
from fractions import Fraction as F
from itertools import combinations, product
from math import comb, sqrt
from pathlib import Path
import hashlib
import json
import platform
import random
import time
import argparse


def popcount(S):
    return bin(S).count("1")


def enc(x):
    if isinstance(x, F): return str(x)
    if isinstance(x, dict): return {str(k): enc(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)): return [enc(v) for v in x]
    return x


class Claims:
    def __init__(self): self.data = {}; self.current = None
    def check(self, name, ok, context=None):
        r = self.data.setdefault(name, {"checks": 0, "violations": 0, "examples": []})
        r["checks"] += 1
        if not ok:
            r["violations"] += 1
            if len(r["examples"]) < 3: r["examples"].append(enc(context))
    def note(self, name, **kwargs):
        self.data.setdefault(name, {"checks": 0, "violations": 0, "examples": []}).update(kwargs)


class Graph:
    def __init__(self, n, edges, name):
        self.n, self.name = n, name
        self.edges = [(u, v, F(w)) for u, v, w in edges]
        self.d = [F(0)]*n
        self.adj = [[F(0)]*n for _ in range(n)]
        for u, v, w in self.edges:
            self.d[u] += w; self.d[v] += w; self.adj[u][v] += w; self.adj[v][u] += w
        assert all(self.d), "No zero-degree vertices in the finite suite."
        self.M = sum(self.d)
        self.full = (1 << n)-1
        self.vol = [F(0)]*(1 << n)
        self.cut = [F(0)]*(1 << n)
        self.z = [None]*(1 << n)
        for S in range(1, 1 << n):
            b = S & -S; v = b.bit_length()-1; T = S ^ b
            self.vol[S] = self.vol[T]+self.d[v]
            self.cut[S] = self.cut[T]+self.d[v]-2*sum((self.adj[v][u] for u in range(n) if T >> u & 1), F(0))
            self.z[S] = self.cut[S]/self.vol[S]+self.vol[S]/self.M
        self.seeded = list(range(1, 1 << n, 2))
    def phi(self, S):
        v = self.vol[S]
        return self.cut[S]/min(v, self.M-v) if v < self.M else None
    def cross(self, A, B):
        return sum((w for u, v, w in self.edges if ((A >> u & 1) and (B >> v & 1)) or ((A >> v & 1) and (B >> u & 1))), F(0))
    def description(self): return {"name": self.name, "n": self.n, "edges": self.edges, "M": self.M}


class Hypergraph(Graph):
    def __init__(self, n, hyperedges, name):
        self.n, self.name, self.hyperedges = n, name, [(tuple(e), F(t), tuple(F(v) for v in w)) for e, t, w in hyperedges]
        self.d = [F(0)]*n
        for e, t, w in self.hyperedges:
            for u in e: self.d[u] += t
        assert all(self.d)
        self.M = sum(self.d); self.full = (1 << n)-1
        self.vol = [F(0)]*(1 << n); self.cut = [F(0)]*(1 << n); self.z = [None]*(1 << n)
        for S in range(1, 1 << n):
            b=S & -S; self.vol[S]=self.vol[S^b]+self.d[b.bit_length()-1]
            self.cut[S]=sum((t*w[sum(S >> u & 1 for u in e)] for e,t,w in self.hyperedges),F(0))
            self.z[S]=(self.cut[S]+self.G(self.vol[S]))/self.vol[S]
        self.seeded=list(range(1,1 << n,2))
    def G(self,v):
        p=v/self.M
        psi=sum((t*sum((F(comb(len(e),j))*p**j*(1-p)**(len(e)-j)*w[j] for j in range(len(e)+1)),F(0)) for e,t,w in self.hyperedges),F(0))
        return v-psi
    def description(self): return {"name":self.name,"n":self.n,"hyperedges":self.hyperedges,"M":self.M}


def penalty(g,T,C,R):
    return 2*(g.vol[C&T]*g.vol[T & ~C]+g.vol[C & ~T]*g.vol[R & ~C])/(g.M*g.vol[C])


def mm_values(g,S,R,order=None):
    if order is None: order=[0]+[v for v in range(1,g.n) if S >> v & 1]+[v for v in range(1,g.n) if (R & ~S) >> v & 1]
    D=F(0); u=[F(0)]*g.n
    for v in order:
        prev=D; D+=g.d[v]
        upper=(g.G(D)-g.G(prev)) if isinstance(g,Hypergraph) else (D*D-prev*prev)/g.M
        u[v]=upper-g.z[S]*g.d[v]
    candidates=[T for T in g.seeded if T & ~R == 0]
    vals={T:g.cut[T]+sum((u[v] for v in range(g.n) if T >> v & 1),F(0)) for T in candidates}
    return order, vals


def mm_and_fp(g,claims):
    R=g.full
    starts=g.seeded if g.n <= 6 else sorted(set([1,R,g.seeded[len(g.seeded)//3],min(g.seeded,key=lambda T:g.z[T])]))
    fixed={}; steps=[]
    for start in starts:
        S=start
        for k in range(2*len(g.seeded)):
            order,vals=mm_values(g,S,R)
            T=min(vals,key=lambda T:(vals[T],g.vol[T],T)); minimum=vals[T]
            claims.check("P5-zero",vals[S]==0,{"graph":g.name,"S":S,"value":vals[S]})
            claims.check("P5-negative-implies-decrease",minimum >= 0 or g.z[T] < g.z[S],{"graph":g.name,"S":S,"T":T,"subproblem":minimum,"old_Z":g.z[S],"new_Z":g.z[T]})
            if g.z[T] < g.z[S]:
                claims.check("P5-descent",True); S=T
            else:
                claims.check("P7-stationary",minimum==0,{"graph":g.name,"S":S,"minimum":minimum})
                claims.check("P7-region",S & ~R == 0)
                fixed[S]=order; steps.append({"start":start,"final":S,"steps":k,"minimum":minimum}); break
        else: raise RuntimeError("Unexpected finite MM loop")
    for S,order in fixed.items():
        for C in g.seeded:
            if isinstance(g,Hypergraph): continue # FP formula frozen for ordinary graph only.
            prefix=0; numerator=F(0)
            for v in order:
                prefix |= 1 << v
                if C >> v & 1: numerator += 2*g.d[v]*g.vol[prefix & ~C]
            bound=numerator/(g.M*g.vol[C]); pen=penalty(g,S,C,R); last=2*g.vol[R & ~C]/g.M
            ctx={"graph":g.name,"S":S,"C":C,"order":order,"difference":g.z[S]-g.z[C],"prefix_bound":bound,"penalty":pen,"last_bound":last}
            claims.check("FP-first",g.z[S]-g.z[C]<=bound,ctx)
            claims.check("FP-second",bound<=pen,ctx)
            claims.check("FP-third",pen<=last,ctx)
    qualifying=[]
    if not isinstance(g,Hypergraph):
        for C in g.seeded:
            valid=True
            for T in g.seeded:
                if T != C and not g.z[T]-g.z[C] > penalty(g,T,C,R): valid=False; break
            claims.check("MM-exact-hypothesis-enumerated",True)
            if valid:
                qualifying.append(C)
                for S in fixed: claims.check("MM-exact",S==C,{"graph":g.name,"C":C,"fixed":S})
    return {"graph":g.name,"seeded_subsets":len(g.seeded),"starts":len(starts),"fixedpoints":list(fixed),"qualifying_MM_exact_targets":qualifying,"runs":steps}


def identities(g,claims,rng):
    for A in g.seeded:
        for u in range(1,g.n):
            if A >> u & 1: continue
            B=1 << u; e=g.cross(A,B); d=g.d[u]; a=g.vol[A]
            rhs=d/2*(1-g.z[A])+d*a/g.M+d*d/(2*g.M)
            claims.check("P3-add",(g.z[A|B]<g.z[A])==(e>rhs),{"graph":g.name,"A":A,"u":u})
            claims.check("P3-delete",(g.z[A]<g.z[A|B])==(e<rhs),{"graph":g.name,"A":A,"u":u})
        if g.n<=7:
            complement=g.full ^ A; B=complement
            choices=[]
            while B: choices.append(B); B=(B-1)&complement
        else:
            choices=list(set([(g.full^A),1 << ((rng.randrange(g.n-1))+1)]))
            choices=[B & ~A for B in choices if B & ~A]
        for B in choices:
            a,b=g.vol[A],g.vol[B]; e=g.cross(A,B)
            expected=(a*g.z[A]+b*g.z[B]-2*(e-a*b/g.M))/(a+b)
            claims.check("P2",g.z[A|B]==expected,{"graph":g.name,"A":A,"B":B})
            if a+b <= g.M/2:
                expected_phi=(a*g.phi(A)+b*g.phi(B)-2*e)/(a+b)
                claims.check("P1",g.phi(A|B)==expected_phi,{"graph":g.name,"A":A,"B":B})
            if e==0:
                claims.check("P6",(g.z[A|B]<g.z[A])==(g.cut[A]/a-g.cut[B]/b>(a+b)/g.M),{"graph":g.name,"A":A,"B":B})
    optimum=min(g.z[S] for S in g.seeded)
    # Finite nonnegative vectors with seed maximum, with ties respected.
    vectors=list(product(range(3),repeat=g.n)) if g.n<=5 else [tuple([2]+[rng.randrange(3) for _ in range(g.n-1)]) for _ in range(64)]
    for vector in vectors:
        if not vector[0] or vector[0] != max(vector): continue
        x=list(map(F,vector)); denominator=sum((g.d[v]*x[v] for v in range(g.n)),F(0))
        order=sorted(range(g.n),key=lambda v:(-x[v],v)); D=F(0); H=F(0)
        for v in order: previous=D; D+=g.d[v]; H+=x[v]*(D*D-previous*previous)
        tv=sum((w*abs(x[u]-x[v]) for u,v,w in g.edges),F(0)); ratio=(tv+H/g.M)/denominator
        levels=[sum(1 << v for v in range(g.n) if x[v]>=t) for t in sorted(set(x)) if t>0]
        best=min(g.z[S] for S in levels)
        claims.check("P4-sweep",best<=ratio,{"graph":g.name,"x":x,"best":best,"ratio":ratio})
        claims.check("P4-global-lower",optimum<=ratio)
    for S in g.seeded:
        # Indicator vectors provide exact objective witnesses; no proof claim.
        claims.check("P4-indicator-witness",(g.cut[S]+g.vol[S]*g.vol[S]/g.M)/g.vol[S]==g.z[S])


def lower_hull(points):
    hull=[]
    for x,y,S in sorted(points):
        if hull and x==hull[-1][0]: continue
        while len(hull)>=2:
            a,b=hull[-2],hull[-1]
            if (b[1]-a[1])*(x-b[0]) >= (y-b[1])*(b[0]-a[0]): hull.pop()
            else: break
        hull.append((x,y,S))
    return hull


def certificate(g,claims):
    # Enumerated cut values define an independent lower convex hull oracle.
    hull=lower_hull([(g.vol[S],g.cut[S],S) for S in g.seeded])
    best=min(g.z[S] for _,_,S in hull); optimum=min(g.z[S] for S in g.seeded)
    if isinstance(g,Hypergraph):
        # Exact grid upper witnesses plus high precision scalar minimum: record numeric scope.
        from scipy.optimize import minimize_scalar
        lb=float(best)
        for (a,ca,_),(b,cb,_) in zip(hull,hull[1:]):
            alpha=(cb-ca)/(b-a); beta=ca-alpha*a
            fn=lambda v: float(alpha)+float(beta)/v+float(g.G(F(v))) / v
            found=minimize_scalar(fn,bounds=(float(a),float(b)),method="bounded",options={"xatol":1e-11})
            lb=min(lb,float(found.fun),fn(float(a)),fn(float(b)))
        claims.check("T-c-hypergraph-numeric",lb <= float(optimum)+1e-9 and optimum<=best,{"graph":g.name,"LB":lb,"optimum":optimum,"hull_best":best})
        return {"hull":hull,"LB_numeric":lb,"optimum":optimum,"hull_best":best}
    lb=float(best)
    bound=F(0)
    for (a,ca,_),(b,cb,_) in zip(hull,hull[1:]):
        alpha=(cb-ca)/(b-a); beta=ca-alpha*a
        points=[float(a),float(b)]
        if beta>0:
            candidate=sqrt(float(beta*g.M))
            if float(a)<=candidate<=float(b): points.append(candidate)
        lb=min(lb,*(float(alpha)+float(beta)/v+v/float(g.M) for v in points))
        bound=max(bound,(b-a)**2/(4*g.M*a))
    claims.check("T-c",lb<=float(optimum)+1e-12 and optimum<=best,{"graph":g.name,"LB":lb,"optimum":optimum,"hull_best":best})
    claims.check("T-c-prime",lb+1e-12>=float(best-bound),{"graph":g.name,"LB":lb,"hull_best":best,"bound":bound})
    return {"hull":hull,"LB_numeric":lb,"optimum":optimum,"hull_best":best,"bound":bound}


def linear_solve(A,b):
    rows=[list(row)+[bi] for row,bi in zip(A,b)]; n=len(rows)
    for k in range(n):
        pivot=next(j for j in range(k,n) if rows[j][k]); rows[k],rows[pivot]=rows[pivot],rows[k]
        divisor=rows[k][k]; rows[k]=[v/divisor for v in rows[k]]
        for j in range(n):
            if j!=k and rows[j][k]:
                f=rows[j][k]; rows[j]=[a-f*b for a,b in zip(rows[j],rows[k])]
    return [row[-1] for row in rows]


def graph_diffusion(g,m,sigma=F(1,10000)):
    A=[[(1+sigma)*g.d[u] if u==v else -g.adj[u][v] for v in range(g.n)] for u in range(g.n)]
    b=[(m if u==0 else F(0))-g.d[u] for u in range(g.n)]
    active={0} if m>g.d[0] else set(); x=[F(0)]*g.n
    for _ in range(g.n*4+4):
        ids=sorted(active)
        sol=linear_solve([[A[u][v] for v in ids] for u in ids],[b[u] for u in ids])
        x=[F(0)]*g.n
        for u,value in zip(ids,sol): x[u]=value
        negative=[u for u in ids if x[u]<=0]
        if negative: active.remove(min(negative,key=lambda u:x[u])); continue
        residual=[sum((A[u][v]*x[v] for v in range(g.n)),F(0))-b[u] for u in range(g.n)]
        violating=[u for u in range(g.n) if u not in active and residual[u]<0]
        if not violating:
            assert all(residual[u]==0 for u in active) and all(x[u]>=0 for u in range(g.n))
            return x,residual
        active.add(min(violating,key=lambda u:residual[u]))
    raise RuntimeError("Exact active-set solve did not converge")


def diffusion_checks(g,claims):
    sigma=F(1,10000); ds=g.d[0]
    neighbors=[v for v in range(g.n) if g.adj[0][v]]
    mact=ds+(1+sigma)*ds*min(g.d[v]/g.adj[0][v] for v in neighbors)
    masses=sorted(set([F(0),ds,ds+F(1,10000),2*ds,3*ds,4*ds,8*ds,g.M/2,g.M,2*g.M,mact,mact+F(1,10000)]))
    previous=None; raw=[]
    for m in masses:
        x,res=graph_diffusion(g,m,sigma); U=sum(1 << v for v in range(g.n) if x[v]>0)
        claims.check("V-a-graph",x[0]==max(x),{"graph":g.name,"m":m,"x":x})
        reached=set([0]) if U else set(); stack=list(reached)
        while stack:
            u=stack.pop()
            for v in range(g.n):
                if g.adj[u][v] and U >> v & 1 and v not in reached: reached.add(v);stack.append(v)
        claims.check("V-b-graph",len(reached)==popcount(U),{"graph":g.name,"m":m,"U":U})
        claims.check("V-c-volume-graph",g.vol[U]<=m,{"graph":g.name,"m":m,"U":U})
        if U:
            boundary=sum((w*(x[u] if U >> u & 1 else x[v]) for u,v,w in g.edges if bool(U >> u & 1)!=bool(U >> v & 1)),F(0))
            rhs=boundary+sigma*sum((g.d[u]*x[u] for u in range(g.n) if U >> u & 1),F(0))
            claims.check("V-c-balance-graph",m-g.vol[U]==rhs,{"graph":g.name,"m":m,"U":U,"rhs":rhs,"lhs":m-g.vol[U]})
        else:
            claims.check("V-c-balance-literal-empty",m-g.vol[U]==0,{"graph":g.name,"m":m,"U":U,"rhs":F(0),"lhs":m})
        claims.check("A",(U==1)==(ds<m<=mact),{"graph":g.name,"m":m,"m_act":mact,"U":U})
        lower=(m-ds)/((1+sigma)*ds)
        claims.check("Leak-seed",x[0]>=lower,{"graph":g.name,"m":m,"seed_value":x[0],"bound":lower})
        for v in neighbors:
            claims.check("Leak-neighbor",not(g.d[v]<g.adj[0][v]*lower) or bool(U >> v & 1),{"graph":g.name,"m":m,"v":v,"U":U})
        if previous:
            claims.check("Mono-graph",all(xv>=pv for xv,pv in zip(x,previous)),{"graph":g.name,"m":m,"x":x,"previous":previous})
        previous=x; raw.append({"m":m,"x":x,"support":U,"KKT_exact":True,"m_act":mact})
    return {"graph":g.name,"solves":raw}


def sbm_checks(claims):
    output=[]
    for K,s,p,q in [(4,2,F(1),F(1,4)),(4,3,F(3,4),F(1,8)),(6,2,F(1),F(1,8)),(4,3,F(1,2),F(1,5))]:
        g=Graph(K*s,[(u,v,p if u//s==v//s else q) for u in range(K*s) for v in range(u+1,K*s)],f"mean_sbm_K{K}_s{s}_p{p}_q{q}")
        delta=(s-1)*p+(K-1)*s*q; C=(1 << s)-1; alpha=F(1,K*s)-q/delta
        optimum=min(g.z[S] for S in g.seeded); zmin=[S for S in g.seeded if g.z[S]==optimum]
        minphi=min(g.phi(S) for S in g.seeded if S!=g.full); phimin=[S for S in g.seeded if S!=g.full and g.phi(S)==minphi]
        for S in g.seeded:
            counts=[sum(S >> u & 1 for u in range(j*s,(j+1)*s)) for j in range(K)]; t=sum(counts)
            formula=1+p/delta-(p-q)/delta*F(sum(a*a for a in counts),t)+alpha*t
            claims.check("P8-formula",g.z[S]==formula,{"graph":g.name,"S":S,"formula":formula,"actual":g.z[S]})
            if S&C==C:
                b=popcount(S)-s; diff=g.z[S]-g.z[C]
                claims.check("M-prime",diff>=alpha*b,{"graph":g.name,"S":S,"counts":counts,"difference":diff,"bound":alpha*b})
                if b<=F(s,2): claims.check("M-prime-small-b",diff>=((p-q)/(3*delta)+alpha)*b,{"graph":g.name,"S":S,"counts":counts,"difference":diff,"bound":((p-q)/(3*delta)+alpha)*b})
        assert (s-1)*p>s*q
        claims.check("P8-unique-Z-minimum",zmin==[C],{"graph":g.name,"minimizers":zmin,"C":C})
        expected=[sum(((1 << s)-1) << (j*s) for j in js) for js in combinations(range(K),K//2) if 0 in js]
        claims.check("P8-conductance-minimum",set(phimin)==set(expected),{"graph":g.name,"minimizers":phimin,"expected":expected})
        output.append({"graph":g.description(),"seeded_subsets":len(g.seeded),"Z_minimizers":zmin,"conductance_minimizers":phimin})
    return output


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path)
    parser.add_argument("--check-existing",action="store_true")
    args=parser.parse_args()
    start=time.perf_counter(); rng=random.Random(290930); claims=Claims()
    graphs=[Graph(2,[(0,1,1)],"single_edge"),Graph(3,[(0,1,1),(1,2,1)],"path3"),
        Graph(4,[(u,v,1) for u in range(4) for v in range(u+1,4)],"K4"),
        Graph(6,[(0,1,1),(1,2,1),(2,0,1),(3,4,1),(4,5,1),(5,3,1)],"two_triangles")]
    for n in [5,7,10,14]:
        edges=[(u,u+1,F(rng.randrange(1,8),rng.randrange(1,5))) for u in range(n-1)]
        edges += [(u,v,F(rng.randrange(1,8),rng.randrange(1,5))) for u in range(n) for v in range(u+2,n) if rng.random()<0.22]
        graphs.append(Graph(n,edges,f"random_weighted_n{n}"))
    records=[]
    for g in graphs:
        gstart=time.perf_counter(); identities(g,claims,rng)
        records.append({"graph":g.description(),"all_seeded_subsets_enumerated":len(g.seeded),"MM":mm_and_fp(g,claims),"certificate":certificate(g,claims),"diffusion":diffusion_checks(g,claims),"elapsed_seconds":time.perf_counter()-gstart})
        print(g.name,"complete",flush=True)
    hypergraphs=[]
    for kind in ["all_or_nothing","cardinality_min","concave_scaled"]:
        edges=[]
        for e in [(0,1,2),(1,2,3,4),(0,4,5),(2,5)]:
            r=len(e)
            w=[F(0)]+[(F(1) if kind=="all_or_nothing" else F(min(j,r-j))) for j in range(1,r)]+[F(0)]
            if kind=="concave_scaled": w=[v/2 for v in w]
            edges.append((e,F(rng.randrange(1,4),2),w))
        h=Hypergraph(6,edges,kind); hstart=time.perf_counter()
        for i in range(20):
            a=h.M*F(i,20); b=h.M*F(i+1,20); mid=(a+b)/2
            claims.check("T-b-convexity-concave",h.G(mid)<=(h.G(a)+h.G(b))/2,{"graph":kind,"a":a,"b":b})
        for A in h.seeded:
            complement=h.full ^ A; B=complement
            while B:
                a,b=h.vol[A],h.vol[B]; Rcut=h.cut[A]+h.cut[B]-h.cut[A|B]
                rhs=(a*h.z[A]+b*h.z[B]-Rcut+h.G(a+b)-h.G(a)-h.G(b))/(a+b)
                claims.check("T-b-merge",h.z[A|B]==rhs,{"graph":kind,"A":A,"B":B})
                B=(B-1)&complement
        hypergraphs.append({"graph":h.description(),"all_seeded_subsets_enumerated":len(h.seeded),"MM":mm_and_fp(h,claims),"certificate":certificate(h,claims),"elapsed_seconds":time.perf_counter()-hstart})
    sbm=sbm_checks(claims)
    result={"schema_version":1,"scope":{"random_seed":290930,"arithmetic":"fractions.Fraction for objective, algebra, MM, graph diffusion and SBM","certificate_minimum":"floating evaluation of exact hull; 1e-12 ordinary graph comparison tolerance","P1_P2_P6":"Disjoint nonempty positive-volume A,B. All seeded A; all disjoint B for n<=7, deterministic sampled B beyond.","FP":"All seeded C for every reached graph MM fixedpoint; S-first ordering.","MM-exact":"All seeded C hypotheses; all seeded T until first failed inequality. Fixedpoints from all starts n<=6; four selected starts beyond.","V":"Exact graph KKT solutions; empty-support literal domain tested separately.","P8_M_prime":"Mean SBM in the explicitly stated separation regime (s-1)p>sq.","hypergraph":"Symmetric concave normalized cuts; P5,P7,T-b,T-c tested; general T-b contradictions separate."},"claims":claims.data,"graphs":records,"hypergraphs":hypergraphs,"SBM":sbm,"metadata":{"elapsed_seconds":time.perf_counter()-start,"python":platform.python_version(),"platform":platform.platform(),"source_SHA256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    root=Path(__file__).resolve().parents[2]; output=args.output or root/"results"/"m1_independent"/"exact_claim_checks.json"
    if output.exists():
        if args.check_existing:
            existing=json.loads(output.read_text())
            assert existing["claims"]==enc(result["claims"]),"Independent recomputation differs"
            print(json.dumps({"check_existing":"PASS","output":str(output),"elapsed_seconds":time.perf_counter()-start})); return
        raise RuntimeError("Immutable raw output already exists; use --check-existing or a fresh --output")
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(enc(result),indent=2)+"\n")
    print(json.dumps({k:{"checks":v["checks"],"violations":v["violations"]} for k,v in claims.data.items()},indent=2))


if __name__=="__main__": main()
