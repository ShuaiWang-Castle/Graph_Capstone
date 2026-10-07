"""Loader for the public storm panels in ../data (EAGLE-I outages, ERA5 weather, county statics)."""
import os

import numpy as np
import pandas as pd

DATA = os.environ.get("OUTAGE_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
STATIC_COLS = ["rucc", "log_pop_density", "log_cust_density", "coop_share", "saidi", "saifi", "n_utilities", "log_area"]
WEATHER_COLS = ["gust", "wind_speed", "precip", "snowfall", "t2m_c", "pressure", "cape", "rh"]


def event_ids():
    return list(pd.read_csv(os.path.join(DATA, "events.csv")).event)


def statics():
    return pd.read_csv(os.path.join(DATA, "county_statics.csv"), dtype={"fips": str}).set_index("fips")


def load_event(eid, min_observed=0.8, require_weather=False):
    """Hourly outage share (counties x hours), observation mask, weather (counties x hours x channels), county table.

    Counties observed in fewer than `min_observed` of the hours, or without static descriptors, are dropped.
    In 18 of the 26 windows the weather block of many counties is zero-filled (no ERA5 value was mapped to them);
    `require_weather` keeps only counties with real weather, and `has_weather` flags them otherwise.
    """
    z = np.load(os.path.join(DATA, "events", f"{eid}.npz"))
    y = z["outage_share"].astype(float)
    o = np.isfinite(y)
    fips = z["fips"].astype(str)
    st = statics().reindex(fips)
    keep = (o.mean(1) >= min_observed) & st[STATIC_COLS + ["lat", "lon"]].notna().all(1).values
    has_weather = np.abs(z["weather"]).sum((1, 2)) > 0
    if require_weather:
        keep &= has_weather
    ch = [str(c) for c in z["channels"]]
    x = z["weather"][:, :, [ch.index(c) for c in WEATHER_COLS]].astype(float)
    return dict(id=eid, Y=np.clip(np.nan_to_num(y[keep]), 0, 1), O=o[keep], X=x[keep], hours=pd.to_datetime(z["hours"]),
                fips=fips[keep], meta=st.loc[fips[keep]], customers=z["customers"][keep], has_weather=has_weather[keep])
