import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from data import event_ids, load_event
from recon import haversine, spatial_graph, fill_time
def curve_stats(y):
    pk = y.max(1); tp = y.argmax(1)
    onset = (y >= 0.2 * pk[:, None]).argmax(1).astype(float)
    rest = np.array([np.argmax(y[i, tp[i]:] <= 0.1 * pk[i]) if (y[i, tp[i]:] <= 0.1 * pk[i]).any() else y.shape[1] - tp[i] for i in range(len(y))], float)
    return onset, pk, rest
def rayleigh(w, x):
    """Generalised Rayleigh quotient of the normalised Laplacian: 0 = constant on the graph, about 1 = unrelated to it."""
    d = np.asarray(w.sum(1)).ravel(); xc = x - (d @ x) / d.sum()
    c = w.tocoo(); return 0.5 * (c.data * (xc[c.row] - xc[c.col]) ** 2).sum() / (d @ xc ** 2)
rows = []; rng = np.random.default_rng(0)
for e in event_ids():
    ev = load_event(e); y = fill_time(ev["Y"], ev["O"]); onset, pk, rest = curve_stats(y)
    aff = pk >= 0.05
    if aff.sum() < 40: continue
    m = ev["meta"][aff]; w = spatial_graph(haversine(m.lat.values, m.lon.values), 8)
    for name, x in (("onset hour", onset[aff]), ("peak share (log)", np.log(pk[aff])), ("hours to restore (log)", np.log1p(rest[aff]))):
        r = rayleigh(w, x); null = np.array([rayleigh(w, rng.permutation(x)) for _ in range(300)])
        rows.append(dict(event=e, signal=name, n=int(aff.sum()), rayleigh=r, null=null.mean(), z=(r - null.mean()) / null.std()))
df = pd.DataFrame(rows); df.to_csv("../results/pilot_smoothness.csv", index=False)
pd.set_option("display.width", 200)
print(df.pivot(index="event", columns="signal", values="rayleigh").round(2).to_string())
g = df.groupby("signal").agg(events=("event", "count"), rayleigh=("rayleigh", "mean"), null=("null", "mean"), z=("z", "mean"))
print("\naverage over events with at least 40 affected counties (affected = peak share of 5% or more)"); print(g.round(3).to_string())
p = df.pivot(index="event", columns="signal", values="rayleigh")
print("events where the onset hour is the smoothest of the three:", int((p.idxmin(axis=1) == "onset hour").sum()), "of", len(p))
