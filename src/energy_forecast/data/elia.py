"""Optional: Elia Open Data (Opendatasoft API v2.1).

ENTSO-E already covers the Belgian zone, so this is disabled by default.
Enable it in config.yaml (elia.enabled) and list dataset IDs, e.g. {solar_elia: ods032}.
Check the IDs and field names on https://opendata.elia.be before use — they change over time.
"""

from __future__ import annotations

import logging

import pandas as pd
import requests

from energy_forecast.config import Config
from energy_forecast.data.utils import to_hourly_utc

log = logging.getLogger(__name__)


def fetch_dataset(cfg: Config, dataset_id: str, start: pd.Timestamp, end: pd.Timestamp,
                  time_field: str = "datetime", value_field: str = "mostrecentforecast") -> pd.Series:
    url = f"{cfg['elia']['base_url']}/{dataset_id}/exports/json"
    params = {
        "where": f"{time_field} >= '{start:%Y-%m-%dT%H:%M:%S}' and {time_field} < '{end:%Y-%m-%dT%H:%M:%S}'",
        "select": f"{time_field},{value_field}",
        "timezone": "UTC",
    }
    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    if df.empty:
        return pd.Series(dtype=float)
    s = df.set_index(pd.to_datetime(df[time_field], utc=True))[value_field].astype(float)
    return to_hourly_utc(s.groupby(level=0).sum())


def fetch_elia(cfg: Config, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if not cfg["elia"].get("enabled"):
        return pd.DataFrame()
    cols = {}
    for name, ds in cfg["elia"]["datasets"].items():
        try:
            cols[name] = fetch_dataset(cfg, ds, start, end)
        except Exception as exc:
            log.warning("Elia dataset %s failed: %s", ds, exc)
    return pd.DataFrame(cols)
