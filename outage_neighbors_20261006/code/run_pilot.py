"""Reconstruction pilot. Two passes:

    all       every county; spatial and static graphs and the simple baselines (no weather graph)
    weather   only counties with weather values, only windows with at least MIN_COUNTIES of them; all three graphs

Usage: python run_pilot.py [k]
"""
import sys
import warnings

import pandas as pd

from data import event_ids, load_event
from recon import evaluate

warnings.filterwarnings("ignore")
MIN_COUNTIES = 100
k = int(sys.argv[1]) if len(sys.argv) > 1 else 8
pd.set_option("display.width", 250)


def summarise(df, title):
    print(f"\n##### {title}: {df.event.nunique()} storm windows")
    for kind in ("random", "block"):
        d = df[df["mask"] == kind]
        pe = d.groupby(["event", "method"])[["mae", "mae_active", "mae_severe", "peak_ratio", "mae_rise", "mae_recovery"]].mean().reset_index()
        base = pe[pe.method == "global mean"].set_index("event").mae
        pe["skill"] = 1 - pe.mae / pe.event.map(base)
        s = pe.groupby("method").agg(mae=("mae", "mean"), skill=("skill", "mean"), mae_active=("mae_active", "mean"),
                                     mae_severe=("mae_severe", "mean"), peak_ratio=("peak_ratio", "mean"),
                                     mae_rise=("mae_rise", "mean"), mae_recovery=("mae_recovery", "mean"))
        piv = pe.pivot(index="event", columns="method", values="mae")
        s["wins"] = piv.eq(piv.min(axis=1), axis=0).sum()
        s["mean_rank"] = piv.rank(axis=1).mean()
        print(f"\n=== hidden counties: {kind} (20% of the counties, 10 draws per window; averages over windows)")
        print(s.sort_values("mae").round(4).to_string())


rows_all, rows_w, used = [], [], []
for e in event_ids():
    rows_all += evaluate(load_event(e), k=k, with_weather=False)
    ev = load_event(e, require_weather=True)
    if len(ev["fips"]) >= MIN_COUNTIES:
        rows_w += evaluate(ev, k=k, with_weather=True)
        used.append((e, len(ev["fips"])))
a, w = pd.DataFrame(rows_all), pd.DataFrame(rows_w)
a.to_csv(f"../results/pilot_k{k}_all_counties.csv", index=False)
w.to_csv(f"../results/pilot_k{k}_weather_subset.csv", index=False)
summarise(a, f"all counties, k={k}, no weather graph")
print("\nwindows in the weather comparison (counties with weather values):", used)
summarise(w, f"counties with weather values, k={k}, three graphs")
