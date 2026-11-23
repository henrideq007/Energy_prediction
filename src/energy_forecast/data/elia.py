"""Elia Open Data (Opendatasoft API v2.1) — Belgian TSO wind & solar estimates and forecasts.

DP-027 (solar) and DP-028 (wind). Each dataset carries several forecast RUNS, which matters
for leakage (decision D-16):
    weekaheadforecast    issued about a week before delivery  -> safely known at D-1 11:00
    dayahead11hforecast  issued on D-1 at 11:00               -> same-time feature per D-29, pending the D-16 check (T52)
    dayaheadforecast     latest day-ahead run (D-1 evening)   -> after our issue time
    measured             estimated actual production          -> lag-only
Columns are prefixed `elia_` so features.py ignores them until Phase 3 decides (D-15, D-24).

Datasets (checked 3 Nov 2026 on opendata.elia.be):
    ods031  wind, historical, 15-min, from 2015, 5 rows per timestamp (offshore + region x grid) -> summed
    ods032  solar, historical, 15-min, Oct 2020 -> 25 Oct 2026, region 'Belgium'
    ods209  solar, successor of ods032 from 26 Oct 2026, region 'Belgium', gridconnectiontype 'Total'
"""

from __future__ import annotations

import logging

import pandas as pd
import requests

from energy_forecast.config import Config
from energy_forecast.data.utils import to_hourly_utc

log = logging.getLogger(__name__)
UA = {"User-Agent": "energy-forecast-research/0.1"}

FIELDS = ["measured", "weekaheadforecast", "dayahead11hforecast", "dayaheadforecast"]

DATASETS = {
    # name: (dataset id, where filter, fields mapping {api field: our field})
    "wind": [("ods031", None, {f: f for f in FIELDS})],
    "solar": [
        ("ods032", "region='Belgium'", {**{f: f for f in FIELDS},
                                        "dayahead11hconfidence10": "dayahead11h_p10",
                                        "dayahead11hconfidence90": "dayahead11h_p90"}),
        ("ods209", "region='Belgium' and gridconnectiontype='Total'",
         {"measured_upscaled": "measured",  # no week-ahead run in this dataset
          "dayahead11hforecast": "dayahead11hforecast", "dayaheadforecast": "dayaheadforecast",
          "dayahead11hconfidence10": "dayahead11h_p10", "dayahead11hconfidence90": "dayahead11h_p90"}),
    ],
}


def _export_year(base_url: str, ds: str, where: str | None, fields: dict, y_start: pd.Timestamp,
                 y_end: pd.Timestamp) -> pd.DataFrame:
    sel = ", ".join(f"sum({api}) as {ours}" for api, ours in fields.items())
    w = f"datetime >= '{y_start:%Y-%m-%dT%H:%M:%S}Z' and datetime < '{y_end:%Y-%m-%dT%H:%M:%S}Z'"
    if where:
        w += f" and {where}"
    r = requests.get(f"{base_url}/{ds}/exports/json", headers=UA, timeout=300,
                     params={"select": f"datetime, {sel}", "where": w, "group_by": "datetime", "timezone": "UTC"})
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    if df.empty:
        return df
    df.index = pd.to_datetime(df.pop("datetime"), utc=True)
    return df.apply(pd.to_numeric, errors="coerce").sort_index()


def fetch_elia(cfg: Config, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    ecfg = cfg["elia"]
    if not ecfg.get("enabled"):
        return pd.DataFrame()
    cache = cfg.path("raw_dir") / "elia"
    cache.mkdir(parents=True, exist_ok=True)
    this_year = pd.Timestamp.now(tz="UTC").year
    out = []
    for tech in ecfg.get("technologies", ["wind", "solar"]):
        parts = []
        for ds, where, fields in DATASETS[tech]:
            for y in range(start.year, end.year + 1):
                f = cache / f"{tech}_{ds}_{y}.parquet"
                if f.exists() and y < this_year:
                    parts.append(pd.read_parquet(f))
                    continue
                a = max(start, pd.Timestamp(f"{y}-01-01", tz="UTC"))
                b = min(end, pd.Timestamp(f"{y + 1}-01-01", tz="UTC"))
                try:
                    log.info("Elia %s %s %s", tech, ds, y)
                    df = _export_year(ecfg["base_url"], ds, where, fields, a, b)
                except Exception as exc:
                    log.warning("Elia %s %s %s failed: %s", tech, ds, y, exc)
                    continue
                df.to_parquet(f)
                if not df.empty:
                    parts.append(df)
        if not parts:
            continue
        d = pd.concat(parts)
        d = d[~d.index.duplicated(keep="last")]
        out.append(to_hourly_utc(d).add_prefix(f"elia_{tech}_"))
    if not out:
        return pd.DataFrame()
    df = pd.concat(out, axis=1)
    return df.loc[(df.index >= start) & (df.index < end)]
