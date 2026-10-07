"""Exploratory: what do similarity graphs of outage curves pick up in the 10 August 2020 Midwest derecho?

Two graphs are built from the same 118 counties (states IA, IL, IN and neighbours; peak outage share of 2% or more):

    rise      the first 30 hours, as the share of the county's eventual peak already reached
    recovery  the 96 hours after each county's own peak, divided by that peak

The Fiedler vector of each graph is compared with quantities that did not enter the graph: the hour of the wind
reports near the county (NOAA Storm Prediction Center, an independent source), longitude, and the time to restore.
Outage onset is derived from the same curves, so its correlation is a consistency check, not a validation.
"""
import os

import networkx as nx
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.stats import spearmanr
from sklearn.neighbors import NearestNeighbors

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "extra")
z = np.load(os.path.join(HERE, "derecho_2020-08-10.npz"))
meta = pd.read_csv(os.path.join(HERE, "derecho_2020-08-10_counties.csv"), dtype={"fips": str}).set_index("fips")
share = z["outage_share"]                                   # counties x 168 hours, from 2020-08-10 06:00 UTC


def knn_graph(x, k, metric):
    idx = NearestNeighbors(n_neighbors=k + 1, metric=metric, algorithm="brute").fit(x).kneighbors(x)[1][:, 1:]
    n = len(x)
    a = sp.csr_matrix((np.ones(idx.size), (np.repeat(np.arange(n), k), idx.ravel())), shape=(n, n))
    return ((a + a.T) > 0).astype(float)


def spectrum(a, nv=4):
    d = np.asarray(a.sum(1)).ravel()
    dm = np.diag(d ** -0.5)
    w, v = np.linalg.eigh(np.eye(len(d)) - dm @ a.toarray() @ dm)
    return w[:nv], dm @ v[:, :nv]


rise = np.maximum.accumulate(share[:, :31], axis=1)
rise = rise / rise[:, -1:]
recovery = []
for s in share:
    p = int(np.argmax(s))
    seg = s[p:p + 96]
    seg = np.pad(seg, (0, 96 - len(seg)), constant_values=seg[-1])
    recovery.append(seg / seg[0])
recovery = np.array(recovery)
ok = meta.wind_report_hour.notna().values
print(f"counties {len(meta)}; with a wind report within 40 km {int(ok.sum())}")
print("Spearman(outage onset, wind-report hour) =", round(spearmanr(meta.onset_hour[ok], meta.wind_report_hour[ok]).statistic, 3))
for tag, feats in (("rise", rise), ("recovery", recovery)):
    for k in (5, 8, 12, 20):
        a = knn_graph(feats, k, "euclidean")
        w, v = spectrum(a)
        f = v[:, 1]
        cols = (("onset_hour", slice(None)), ("wind_report_hour", ok), ("lon", slice(None)), ("peak_share", slice(None)), ("restore_hours", slice(None)))
        out = "  ".join(f"{c} {abs(spearmanr(f[m], meta[c].values[m]).statistic):.2f}" for c, m in cols)
        print(f"{tag:8} k={k:2d} components={nx.number_connected_components(nx.from_scipy_sparse_array(a))} lambda2={w[1]:.3f} | |Spearman| of the Fiedler vector: {out}")
