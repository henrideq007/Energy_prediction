"""JAO Core Publication Tool — flow-based domain limits for Belgium (DP-040, candidate).

`fb_BE_min_np` / `fb_BE_max_np` = the most negative (max import) and most positive (max export)
net position Belgium can reach inside the final Core flow-based domain, per MTU (MW).
History starts with Core flow-based go-live (delivery day 9 Jun 2022). Fetched via `jao-py`,
one request per delivery day, cached per month in data/raw/jao.

Publication: Core final FB parameters are published on D-1 in the morning — the exact time vs
our 10:00 issue time is still to verify (open question in the inventory). Prefix `fb_` is
ignored by features.py until the ablation test (D-15, D-24).
"""

from __future__ import annotations

import logging
import time

import pandas as pd

from energy_forecast.config import Config
from energy_forecast.data.utils import to_hourly_utc

log = logging.getLogger(__name__)
CORE_FB_START = pd.Timestamp("2022-06-09")


def fetch_jao(cfg: Config, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    jcfg = cfg.get("jao") or {}
    if not jcfg.get("enabled", False):
        return pd.DataFrame()
    try:
        from jao import JaoPublicationToolPandasClient
    except ImportError:
        log.warning("jao-py not installed — DP-040 skipped (pip install jao-py)")
        return pd.DataFrame()
    client = JaoPublicationToolPandasClient()
    zone = jcfg.get("zone", "BE")
    cache = cfg.path("raw_dir") / "jao"
    cache.mkdir(parents=True, exist_ok=True)
    first = max(start.tz_localize(None).normalize(), CORE_FB_START)
    last = min(end.tz_localize(None).normalize(), pd.Timestamp.now().normalize() + pd.Timedelta(days=1))
    this_month = pd.Timestamp.now().to_period("M")
    parts = []
    for month in pd.period_range(first, last, freq="M"):
        f = cache / f"minmax_np_{zone}_{month}.parquet"
        if f.exists() and month < this_month:
            parts.append(pd.read_parquet(f))
            continue
        rows = []
        for day in pd.date_range(max(first, month.start_time), min(last, month.end_time.normalize()), freq="D"):
            try:
                x = client.query_minmax_np(pd.Timestamp(day, tz="Europe/Brussels"))
            except Exception as exc:  # missing days / API hiccups: skip the day
                log.debug("JAO %s failed: %s", day.date(), exc)
                continue
            if x is None or x.empty or f"min{zone}" not in x:
                continue
            idx = pd.DatetimeIndex(x["mtu"]) if "mtu" in x else pd.DatetimeIndex(x.index)
            rows.append(pd.DataFrame({f"fb_{zone}_min_np": pd.to_numeric(x[f"min{zone}"]).to_numpy(),
                                      f"fb_{zone}_max_np": pd.to_numeric(x[f"max{zone}"]).to_numpy()},
                                     index=idx.tz_convert("UTC")))
            time.sleep(jcfg.get("request_sleep_s", 0.2))
        log.info("JAO %s: %s days", month, len(rows))
        if rows:
            m = pd.concat(rows)
            m.to_parquet(f)
            parts.append(m)
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts)
    out = to_hourly_utc(out[~out.index.duplicated(keep="last")])
    return out.loc[(out.index >= start) & (out.index < end)]
