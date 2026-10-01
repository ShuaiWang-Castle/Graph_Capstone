"""Explicit reconstruction of the missing historical full-graph pipeline.

Use the provided theory implementation for Z-sweep/MM and kernels-derived
flow_cd. This is a new run of a documented reconstruction, not a claim that the
absent original core.py was executed. The s11 attractor queries/grid are exactly
those specified by review_round1; the s12 queries are new matched diagnostics.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

sys.dont_write_bytecode = True

import igraph as ig
import leidenalg as la
import networkx as nx
import numpy as np

from core import flow_cd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "inputs/local_hfd/theory"))
from zr_pipeline import Zof, csr, f1, mm, zsweep

GRID = [50, 100, 200, 400, 800, 1600, 3200, 6400]
OUT = ROOT / "results/m0_reference/legacy_reconstruction"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stats(A, d, M, S):
    mask = np.zeros(len(d), bool)
    mask[S] = True
    volume = float(d[mask].sum())
    cut = float(A[mask][:, ~mask].sum())
    return {"volume": volume, "cut": cut, "Z": cut/volume+volume/M,
            "conductance": cut/min(volume,M-volume) if min(volume,M-volume)>0 else None}


def run_query(A, d, M, ptr, idx, seed, C, far_clique):
    start = time.perf_counter()
    best = (np.inf, None, None)
    flow_trace = []
    for v in GRID:
        begin = time.perf_counter()
        x, updates, changes, drained, max_queue = flow_cd(ptr, idx, d, seed, 3.*v)
        S, z = None, None
        z, S = zsweep(A, d, M, x)
        grad = (1+1e-4)*d*x-A@x+d
        grad[seed] -= 3.*v
        res = np.where(x>0, np.abs(grad), np.maximum(-grad,0))/np.maximum(d,1)
        flow_trace.append({"mass":3.*v, "updates":int(updates), "queue_drained":bool(drained), "max_queue":int(max_queue),
                           "support_size":int((x>0).sum()), "scaled_kkt_inf":float(res.max()), "Z_sweep":float(z),
                           "sweep":S.tolist(), "seconds":time.perf_counter()-begin})
        if z < best[0]:
            best = (z, S, x)
    cut_trace = []
    original_cut = nx.minimum_cut

    def logged_cut(*a, **kw):
        value, part = original_cut(*a, **kw)
        candidate = sorted(u for u in part[0] if u != "S")
        cut_trace.append({"raw_nx_value":float(value), "candidate":candidate,
                          "candidate_stats":stats(A,d,M,candidate)})
        return value,part

    nx.minimum_cut = logged_cut
    try:
        out, steps = mm(A,d,M,seed,list(range(len(d))),list(best[1]),best[2])
    finally:
        nx.minimum_cut = original_cut
    stC = stats(A,d,M,C)
    stCK = stats(A,d,M,list(C)+far_clique)
    stO = stats(A,d,M,out)
    return {"seed":seed, "S0":best[1].tolist(), "out":out, "F1":f1(out,C), "MM_steps":steps,
            "contains_far_clique":bool(set(out)&set(far_clique)), "Z_out":stO["Z"], "Z_C":stC["Z"],
            "Z_C_union_K":stCK["Z"], "phi_C":stC["cut"]/stC["volume"], "threshold":stCK["volume"]/M,
            "out_stats":stO, "flow_trace":flow_trace, "mincut_trace":cut_trace, "seconds":time.perf_counter()-start}


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/"raw.json").exists():
        raise RuntimeError("Refuse to overwrite raw legacy-reconstruction run")
    query_catalog=json.loads((ROOT/"data/dev/lfr_reference_queries.json").read_text())
    raw={"reference_status":"reconstructed missing core; original historical per-query baseline unavailable", "base":{}, "attractor":{}}
    begin=time.perf_counter()
    for case in ["lfr_n1000_o00_m50_s11","lfr_n1000_o00_m50_s12"]:
        gp=ROOT/"inputs/local_hfd/graphs"/f"{case}.graph.json"
        tp=ROOT/"inputs/local_hfd/graphs"/f"{case}.truth.json"
        graph=json.loads(gp.read_text())
        truth=json.loads(tp.read_text())["communities"]
        A0=np.zeros((graph["n"],graph["n"]))
        for u,v in graph["edges"]:
            A0[u,v]=A0[v,u]=1.
        ptr,idx,d=csr(A0)
        M=d.sum()
        G=ig.Graph(n=len(d),edges=[tuple(e) for e in graph["edges"]])
        membership=np.asarray(la.find_partition(G,la.ModularityVertexPartition,seed=0).membership)
        rows=[]
        for qi,query in enumerate(query_catalog["cases"][case]["queries"]):
            ci,s=query["community_index"],query["seed"]
            row=run_query(A0,d,M,ptr,idx,s,truth[ci],[])
            row.update({"query_index":qi,"community_index":ci,"Leiden_F1":f1(np.flatnonzero(membership==membership[s]),truth[ci])})
            rows.append(row)
            print(json.dumps({"case":case,"query_index":qi,"F1":row["F1"],"Leiden_F1":row["Leiden_F1"]}),flush=True)
        raw["base"][case]={"graph_sha256":sha(gp),"truth_sha256":sha(tp),"rows":rows}
        if case.endswith("s11"):
            for place in ["clique_low_ids","clique_high_ids"]:
                shift=30 if place=="clique_low_ids" else 0
                K=list(range(30)) if shift else list(range(len(A0),len(A0)+30))
                A=np.zeros((len(A0)+30,len(A0)+30))
                A[shift:shift+len(A0),shift:shift+len(A0)]=A0
                for u in K:
                    for v in K:
                        if u!=v:A[u,v]=1.
                ptr,idx,d=csr(A);M=d.sum();rows=[]
                for qi,query in enumerate(query_catalog["cases"][case]["queries"]):
                    ci,s=query["community_index"],query["seed"]
                    row=run_query(A,d,M,ptr,idx,s+shift,[u+shift for u in truth[ci]],K)
                    row.update({"query_index":qi,"community_index":ci,"seed_original":s})
                    rows.append(row)
                    print(json.dumps({"place":place,"query_index":qi,"F1":row["F1"],"contains_far_clique":row["contains_far_clique"]}),flush=True)
                raw["attractor"][place]=rows
    metadata={"python":sys.version,"platform":platform.platform(),"numpy":np.__version__,"networkx":nx.__version__,"igraph":ig.__version__,"leidenalg":la.__version__,
              "seconds":time.perf_counter()-begin,"grid":GRID,"mass_multiplier":3.,"sigma":1e-4,"tol":1e-12,"max_updates":400_000_000,
              "source_sha256":{p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),Path(__file__).with_name("core.py"),ROOT/"inputs/local_hfd/theory/zr_pipeline.py",ROOT/"inputs/local_hfd/review_round1/attractor_and_leiden.py"]},
              "differences_from_missing_historical_core":["Graph/CSR loaded directly from supplied JSON; neighbors sorted ascending", "flow_cd reconstructed from included kernels; original default parameters unavailable", "Z-sweep/MM taken from supplied theory/zr_pipeline.py rather than absent best_sweep/ratio_refine", "s12 original query seeds absent; a new rng5 query set is explicit"]}
    (OUT/"raw.json").write_text(json.dumps(raw,indent=1))
    (OUT/"run_metadata.json").write_text(json.dumps(metadata,indent=1))
    summary={"base":{case:{"median_F1":float(np.median([r["F1"] for r in data["rows"]])),"mean_F1":float(np.mean([r["F1"] for r in data["rows"]])),"median_Leiden_F1":float(np.median([r["Leiden_F1"] for r in data["rows"]]))} for case,data in raw["base"].items()},
             "attractor":{place:{"far_clique_count":sum(r["contains_far_clique"] for r in rows),"median_F1":float(np.median([r["F1"] for r in rows]))} for place,rows in raw["attractor"].items()}}
    (OUT/"summary.json").write_text(json.dumps(summary,indent=1));print(json.dumps(summary,indent=1),flush=True)


if __name__=="__main__":main()
