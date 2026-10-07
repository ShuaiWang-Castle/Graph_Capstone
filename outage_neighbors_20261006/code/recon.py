"""Who is a useful neighbour? Reconstruction of hidden county outage reports on three graphs.

A share of the counties of a storm window is hidden. Their hourly outage share is rebuilt from the counties that
remain visible, using one reconstructor (harmonic interpolation) on three neighbour definitions:

    spatial  nearest counties on the map
    weather  counties with the most similar weather over the window (ERA5; no outage data)
    static   counties with the most similar static profile (density, rurality, utility structure)

No graph uses outage data, so nothing about the hidden counties leaks into the neighbourhoods.
The weather graph is only defined on counties that have weather values (see data.load_event).
"""
import numpy as np
import scipy.sparse as sp
from sklearn.neighbors import NearestNeighbors

from data import STATIC_COLS


# ------------------------------------------------------------------ graphs
def _union_knn(idx, n):
    r = np.repeat(np.arange(n), idx.shape[1])
    a = sp.csr_matrix((np.ones(idx.size), (r, idx.ravel())), shape=(n, n))
    return ((a + a.T) > 0).astype(float).tocsr()


def knn_graph(z, k):
    idx = NearestNeighbors(n_neighbors=k + 1).fit(z).kneighbors(z)[1][:, 1:]
    return _union_knn(idx, len(z))


def haversine(lat, lon):
    p = np.pi / 180
    a = (np.sin((lat[:, None] - lat[None, :]) * p / 2) ** 2
         + np.cos(lat[:, None] * p) * np.cos(lat[None, :] * p) * np.sin((lon[:, None] - lon[None, :]) * p / 2) ** 2)
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def spatial_graph(dist, k):
    idx = np.argsort(dist, axis=1)[:, 1:k + 1]
    return _union_knn(idx, len(dist))


def weather_features(x):
    """Counties x (hours * channels); every channel is standardised over all counties and hours."""
    z = (x - x.mean((0, 1), keepdims=True)) / (x.std((0, 1), keepdims=True) + 1e-12)
    return z.reshape(len(x), -1)


def static_features(meta):
    s = meta[STATIC_COLS].values.astype(float)
    return (s - s.mean(0)) / (s.std(0) + 1e-12)


def build_graphs(ev, k, with_weather=True):
    meta = ev["meta"]
    dist = haversine(meta.lat.values, meta.lon.values)
    graphs = dict(spatial=spatial_graph(dist, k), static=knn_graph(static_features(meta), k))
    if with_weather:
        assert ev["has_weather"].all(), "load the event with require_weather=True before building a weather graph"
        graphs["weather"] = knn_graph(weather_features(ev["X"]), k)
    return graphs, dist


# ----------------------------------------------------------- reconstructors
def harmonic(w, known, yk):
    """Zhu-Ghahramani-Lafferty: hidden values minimise sum_ij w_ij (f_i - f_j)^2 with the visible values fixed."""
    u = ~known
    lap = sp.diags(np.asarray(w.sum(1)).ravel()) - w
    eps = 1e-8                                    # a component with no visible county falls back to the visible mean
    a = lap[u][:, u].toarray() + eps * np.eye(int(u.sum()))
    b = w[u][:, known] @ yk + eps * yk.mean(0, keepdims=True)
    return np.linalg.solve(a, b)


def local_mean(w, known, yk):
    """Average of the visible graph neighbours, no propagation."""
    wk = w[~known][:, known]
    deg = np.asarray(wk.sum(1)).ravel()
    out = np.asarray(wk @ yk) / np.maximum(deg, 1e-12)[:, None]
    out[deg == 0] = yk.mean(0)
    return out


def idw(dist, known, yk, m=8):
    d = dist[~known][:, known]
    idx = np.argsort(d, axis=1)[:, :m]
    wgt = 1.0 / np.maximum(np.take_along_axis(d, idx, 1), 1.0) ** 2
    return np.einsum("um,umt->ut", wgt, yk[idx]) / wgt.sum(1, keepdims=True)


# -------------------------------------------------------------------- masks
def random_mask(n, frac, rng):
    hid = np.zeros(n, bool)
    hid[rng.choice(n, int(round(frac * n)), replace=False)] = True
    return hid


def block_mask(dist, frac, rng):
    """A contiguous region: a random county and its nearest neighbours on the map."""
    hid = np.zeros(len(dist), bool)
    hid[np.argsort(dist[rng.integers(len(dist))])[:int(round(frac * len(dist)))]] = True
    return hid


# ----------------------------------------------------------------- one event
def fill_time(y, o):
    """Visible counties: fill the rare unobserved hours from the nearest observed hour."""
    y = np.where(o, y, np.nan)
    for i in np.where(~o.all(1))[0]:
        t = np.arange(y.shape[1])
        good = np.isfinite(y[i])
        y[i] = np.interp(t, t[good], y[i, good]) if good.any() else 0.0
    return y


def evaluate(ev, k=8, frac=0.2, reps=10, seed=0, severe=0.10, with_weather=True):
    graphs, dist = build_graphs(ev, k, with_weather)
    y, o = fill_time(ev["Y"], ev["O"]), ev["O"]
    n = len(y)
    state = ev["meta"].index.str[:2].values
    peak_hour = int(np.argmax(np.nanmean(np.where(o, y, np.nan), axis=0)))
    rng = np.random.default_rng(seed)
    rows = []
    for kind in ("random", "block"):
        for rep in range(reps):
            hid = random_mask(n, frac, rng) if kind == "random" else block_mask(dist, frac, rng)
            known = ~hid
            yk, yt, ot = y[known], y[hid], o[hid]
            pred = {"global mean": np.repeat(yk.mean(0, keepdims=True), hid.sum(), 0)}
            sm = np.stack([yk[state[known] == s].mean(0) if (state[known] == s).any() else yk.mean(0) for s in state[hid]])
            pred["state mean"] = sm
            pred["nearest county"] = yk[np.argmin(dist[hid][:, known], axis=1)]
            pred["distance-weighted"] = idw(dist, known, yk)
            for g, w in graphs.items():
                pred[f"{g}: neighbour mean"] = local_mean(w, known, yk)
                pred[f"{g}: harmonic"] = harmonic(w, known, yk)
            sev = np.nanmax(np.where(ot, yt, np.nan), axis=1) >= severe
            for name, p in pred.items():
                err = np.abs(p - yt)
                act = ot & (yt >= 0.01)
                row = dict(event=ev["id"], mask=kind, rep=rep, method=name, mae=err[ot].mean(),
                           mae_active=err[act].mean() if act.any() else np.nan,
                           mae_rise=err[:, :peak_hour + 1][ot[:, :peak_hour + 1]].mean(),
                           mae_recovery=err[:, peak_hour + 1:][ot[:, peak_hour + 1:]].mean(),
                           n_severe=int(sev.sum()))
                if sev.any():
                    tp = np.nanmax(np.where(ot[sev], yt[sev], np.nan), axis=1)
                    row["peak_ratio"] = float(np.median(p[sev].max(1) / tp))      # 1 = peak recovered, < 1 = flattened
                    row["mae_severe"] = err[sev][ot[sev]].mean()
                rows.append(row)
    return rows
