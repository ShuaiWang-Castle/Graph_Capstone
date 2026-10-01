"""Expected-cut null model, grouped exact polynomial, and topology input."""
from fractions import Fraction as F
from functools import lru_cache
from math import comb
import numpy as np


def fraction(value):
    return value if isinstance(value,F) else F(str(value))


class Hypergraph:
    def __init__(self,n,edges,splitting):
        self.n=int(n);self.splitting=splitting;self.edges=edges
        self.degree_exact=[F(0)]*n;self.incidence=[[] for _ in range(n)];groups={}
        for k,(e,theta,w) in enumerate(edges):
            for u in e:self.degree_exact[u]+=theta;self.incidence[u].append(k)
            key=(len(e),w);groups[key]=groups.get(key,F(0))+theta
        self.total_exact=sum(self.degree_exact);self.total=float(self.total_exact)
        if not self.total_exact:raise ValueError('Nonzero hypergraph volume required')
        self.degree=np.array(list(map(float,self.degree_exact)));self.groups=groups
        self.integer_degrees=all(d.denominator==1 for d in self.degree_exact)
        maximum=max(r for r,w in groups);psi=[F(0)]*(maximum+1)
        for (r,w),theta in groups.items():
            if all(value==1 for value in w[1:-1]):
                # Evaluate established binomial all-or-nothing expression in O(r).
                for k in range(1,r+1):psi[k]-=theta*((-1)**k)*comb(r,k)
                psi[r]-=theta
                continue
            for j in range(r+1):
                if not w[j]:continue
                for k in range(j,r+1):psi[k]+=theta*w[j]*comb(r,j)*comb(r-j,k-j)*((-1)**(k-j))
        self.G_coefficients=[-coefficient/self.total_exact**k for k,coefficient in enumerate(psi)]
        self.G_coefficients[1]+=1
    @classmethod
    def from_edges(cls,n,edges,splitting='all_or_nothing'):
        if splitting not in ['all_or_nothing','cardinality_min','custom_concave']:raise ValueError('Unknown explicitly named splitting')
        normalized=[]
        for raw in edges:
            if len(raw) in [2,3] and isinstance(raw[0],(list,tuple,set,np.ndarray)):
                e=tuple(sorted(set(map(int,raw[0]))));theta=fraction(raw[1]);custom=raw[2] if len(raw)==3 else None
            else:e=tuple(sorted(set(map(int,raw))));theta=F(1);custom=None
            if len(e)<2 or not all(0<=u<n for u in e) or theta<=0:raise ValueError('Require positive hyperedges with at least two distinct valid vertices')
            r=len(e)
            if custom is not None:w=tuple(fraction(v) for v in custom)
            elif splitting=='all_or_nothing':w=tuple([F(0)]+[F(1)]*(r-1)+[F(0)])
            elif splitting=='cardinality_min':w=tuple(F(min(j,r-j)) for j in range(r+1))
            else:raise ValueError('Custom splitting values required')
            if len(w)!=r+1 or w[0] or w[-1] or any(v<0 for v in w) or w!=w[::-1]:raise ValueError('Require nonnegative symmetric splitting with zero endpoints')
            if any(w[j]>min(j,r-j) for j in range(r+1)):raise ValueError('Normalize splitting before input; no silent normalization')
            slopes=[w[j+1]-w[j] for j in range(r)]
            if any(slopes[j]<slopes[j+1] for j in range(r-1)):raise ValueError('Nonconcave splitting blocked by frozen T-b scope issue')
            normalized.append((e,theta,w))
        return cls(n,normalized,splitting)
    @lru_cache(maxsize=4096)
    def G(self,volume):
        v=fraction(volume);result=F(0)
        for coefficient in reversed(self.G_coefficients):result=result*v+coefficient
        return result
    def G_float(self,volume):
        from scipy.stats import binom
        p=float(volume)/self.total;p=min(1,max(0,p));psi=0.0
        for (r,w),theta in self.groups.items():
            if all(value==1 for value in w[1:-1]):expectation=1-(1-p)**r-p**r
            else:expectation=float(np.dot(np.array(list(map(float,w))),binom.pmf(np.arange(r+1),r,p)))
            psi+=float(theta)*expectation
        return float(volume)-psi
    def volume(self,vertices):return sum((self.degree_exact[int(u)] for u in set(vertices)),F(0))
    def cut(self,vertices):
        S=set(map(int,vertices));incident=set(k for u in S for k in self.incidence[u])
        return sum((self.edges[k][1]*self.edges[k][2][len(S.intersection(self.edges[k][0]))] for k in incident),F(0))
    def z_exact(self,vertices,objective='ZH'):
        v=self.volume(vertices)
        if not v:raise ValueError('Zero-volume objective undefined')
        null=self.G(v) if objective=='ZH' else v*v/self.total_exact
        return (self.cut(vertices)+null)/v
    def stats(self,vertices):
        S=set(vertices);v=self.volume(S);c=self.cut(S);z=self.z_exact(S)
        return {'volume':float(v),'volume_exact':str(v),'cut':float(c),'cut_exact':str(c),'Z':float(z),'Z_exact':str(z),'Z_H':float(z),'Z_H_prov':float(self.z_exact(S,'ZH-prov')),'size':len(S)}
    def components(self,vertices):
        todo=set(map(int,vertices));sizes=[]
        while todo:
            start=todo.pop();stack=[start];size=0
            while stack:
                u=stack.pop();size+=1
                for k in self.incidence[u]:
                    for v in self.edges[k][0]:
                        if v in todo:todo.remove(v);stack.append(v)
            sizes.append(size)
        return sizes
