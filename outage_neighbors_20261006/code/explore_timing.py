"""Do neighbours recover when a county was hit, even where they miss how badly?

For hidden counties whose outage share reached 10% ("severe"), the reconstruction is compared with the truth on
    peak_ratio            reconstructed peak / true peak (median over counties; 1 = recovered, < 1 = flattened)
    shape_corr            correlation between the reconstructed and the true hourly curve (median)
    peak_time_err         absolute difference of the peak hours (median, hours)
    onset_err             absolute difference of the first hour at half of the own peak (median, hours)
    above_all_neighbours  share of severe counties whose peak exceeds that of every visible spatial neighbour

Two passes, as in run_pilot.py: all counties without weather graphs, then counties with weather values with them.
"""
import warnings

import numpy as np
import pandas as pd

from data import WEATHER_COLS, event_ids, load_event
from recon import block_mask, build_graphs, fill_time, harmonic, idw, knn_graph, random_mask, weather_features

warnings.filterwarnings("ignore")
K, FRAC, REPS, MIN_COUNTIES = 8, 0.2, 10, 100


def weather_variants(x):
    ci = {c: WEATHER_COLS.index(c) for c in WEATHER_COLS}
    wind = weather_features(x[:, :, [ci["gust"], ci["wind_speed"]]])
    summ = np.column_stack([x[:, :, ci["gust"]].max(1), x[:, :, ci["wind_speed"]].max(1), x[:, :, ci["precip"]].sum(1),
                            x[:, :, ci["snowfall"]].sum(1), x[:, :, ci["t2m_c"]].min(1), x[:, :, ci["pressure"]].min(1),
                            x[:, :, ci["gust"]].argmax(1)])
    return {"weather (wind only)": knn_graph(wind, K),
            "weather (storm summary)": knn_graph((summ - summ.mean(0)) / (summ.std(0) + 1e-12), K)}


def run(with_weather):
    rows = []
    for e in event_ids():
        ev = load_event(e, require_weather=with_weather)
        if len(ev["fips"]) < MIN_COUNTIES:
            continue
        graphs, dist = build_graphs(ev, K, with_weather)
        if with_weather:
            graphs.update(weather_variants(ev["X"]))
        y, o = fill_time(ev["Y"], ev["O"]), ev["O"]
        rng = np.random.default_rng(1)
        for kind in ("random", "block"):
            for rep in range(REPS):
                hid = random_mask(len(y), FRAC, rng) if kind == "random" else block_mask(dist, FRAC, rng)
                known = ~hid
                yk, yt = y[known], y[hid]
                tp = yt.max(1)
                sev = tp >= 0.10
                preds = {"distance-weighted": idw(dist, known, yk)}
                for g, w in graphs.items():
                    preds[g + ": harmonic"] = harmonic(w, known, yk)
                wsp = graphs["spatial"][hid][:, known]
                nb_peak = np.array([yk[wsp[i].indices].max() if wsp[i].nnz else np.nan for i in range(hid.sum())])
                for name, p in preds.items():
                    r = dict(event=e, mask=kind, rep=rep, method=name, mae=np.abs(p - yt)[o[hid]].mean(), n_severe=int(sev.sum()))
                    if sev.sum() >= 3:
                        ps, ys = p[sev], yt[sev]
                        cor = [np.corrcoef(a, b)[0, 1] for a, b in zip(ps, ys) if a.std() > 0]
                        half = lambda c: (c >= 0.5 * c.max(1, keepdims=True)).argmax(1)
                        r.update(peak_ratio=float(np.median(ps.max(1) / ys.max(1))),
                                 shape_corr=float(np.median(cor)) if cor else np.nan,
                                 peak_time_err=float(np.median(np.abs(ps.argmax(1) - ys.argmax(1)))),
                                 onset_err=float(np.median(np.abs(half(ps) - half(ys)))),
                                 above_all_neighbours=float(np.nanmean(tp[sev] > nb_peak[sev])))
                    rows.append(r)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    cols = ["mae", "peak_ratio", "shape_corr", "peak_time_err", "onset_err", "above_all_neighbours"]
    for with_weather, tag in ((False, "all_counties"), (True, "weather_subset")):
        df = run(with_weather)
        df.to_csv(f"../results/pilot_timing_k{K}_{tag}.csv", index=False)
        print(f"\n##### {tag}: {df.event.nunique()} storm windows")
        for kind in ("random", "block"):
            d = df[df["mask"] == kind].groupby(["event", "method"]).mean(numeric_only=True).reset_index()
            print(f"\n=== {kind} hiding, severe hidden counties, averages over windows")
            print(d.groupby("method")[cols].mean().sort_values("mae").round(3).to_string())
