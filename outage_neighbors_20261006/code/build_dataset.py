"""How the files under data/ were assembled. Provenance only: it needs the source panels, which are not in this repository.

Source panels: 26 storm windows built from public data in a separate project (EAGLE-I county outage records, ERA5
single-level fields averaged over counties, county statics from Census / EIA-861 / USDA, NOAA Storm Events).
This script only reshapes them:

    outage share    15-minute values -> hourly mean of the observed, non-empty values (NaN where there is none)
    weather         kept as is: counties x 169 hours x 12 channels
    statics         kept as is, written as CSV
    storm reports   NOAA Storm Events rows of the panel counties that begin inside the window

Usage: python build_dataset.py <folder with panel_*.npz, drivers_*.npz, *.parquet> <output data folder>
"""
import json
import os
import sys

import numpy as np
import pandas as pd

src, out = sys.argv[1], sys.argv[2]
os.makedirs(os.path.join(out, "events"), exist_ok=True)
ids = json.load(open(os.path.join(src, "PANEL_MANIFEST.json")))["panels"]
statics = pd.read_parquet(os.path.join(src, "county_statics.parquet"))
statics.to_csv(os.path.join(out, "county_statics.csv"), index=False, float_format="%.12g")
days = pd.read_parquet(os.path.join(src, "event_days_stratified.parquet"))
days["day"] = days.day.astype(str).str[:10]
dominant = days.set_index("day").dominant.to_dict()
reports = pd.read_parquet(os.path.join(src, "storm_events_county.parquet"))
reports["t_begin_utc"] = pd.to_datetime(reports.t_begin_utc)

rows, kept_reports = [], []
for eid in ids:
    p = np.load(os.path.join(src, f"panel_{eid}.npz"), allow_pickle=True)
    d = np.load(os.path.join(src, f"drivers_{eid}.npz"), allow_pickle=True)
    fips = np.array([str(f) for f in p["fips"]])
    assert list(fips) == [str(f) for f in d["fips"]]
    ts, hours = pd.to_datetime(p["ts"]), pd.to_datetime(d["ts"])
    y, obs, hour_of = p["y"], p["observed"], ts.floor("h")
    share = np.full((len(fips), len(hours)), np.nan, dtype=np.float64)
    for j, h in enumerate(hours):
        m = np.asarray(hour_of == h)
        if m.any():
            ok = obs[:, m] & np.isfinite(y[:, m])          # a record can exist with an empty count: not a value
            cnt = ok.sum(1)
            tot = np.where(ok, y[:, m], 0.0).sum(1)
            share[:, j] = np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan)
    np.savez_compressed(os.path.join(out, "events", f"{eid}.npz"), fips=fips, hours=np.array([str(h) for h in hours]),
                        outage_share=share, customers=p["denominator"].astype(np.float64),
                        weather=d["X"].astype(np.float32), channels=np.array([str(c) for c in d["channels"]]))
    cust = p["denominator"]
    tot_out = np.nansum(share * cust[:, None], axis=0)
    rows.append(dict(event=eid, first_hour_utc=str(hours[0]), last_hour_utc=str(hours[-1]), counties=len(fips),
                     states=len({f[:2] for f in fips}), storm_type=dominant.get(eid, ""),
                     observed_share=round(float(np.isfinite(share).mean()), 4),
                     peak_customers_out=int(tot_out.max()), peak_hour_utc=str(hours[int(np.argmax(tot_out))])))
    r = reports[reports.fips.isin(fips) & (reports.t_begin_utc >= hours[0]) & (reports.t_begin_utc <= hours[-1])]
    kept_reports.append(r.assign(event=eid)[["event", "fips", "EVENT_TYPE", "t_begin_utc", "t_end_utc", "MAGNITUDE", "MAGNITUDE_TYPE"]])
pd.DataFrame(rows).to_csv(os.path.join(out, "events.csv"), index=False)
pd.concat(kept_reports).to_csv(os.path.join(out, "storm_reports.csv.gz"), index=False)
print(pd.DataFrame(rows).to_string(index=False))
