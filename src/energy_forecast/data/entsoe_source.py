"""ENTSO-E Transparency Platform — primary source for prices, load and generation.

Uses the `entsoe-py` client. Requests are split into chunks and cached as
parquet files in data/raw/entsoe so that re-runs only download what is missing.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

import pandas as pd

from energy_forecast.config import Config, entsoe_api_key
from energy_forecast.data.utils import month_chunks, snake, to_hourly_utc

log = logging.getLogger(__name__)

# Production groups used as targets / features
GEN_GROUPS = {
    "solar": ["solar"],
    "wind": ["wind_onshore", "wind_offshore"],
    "nuclear": ["nuclear"],
    "gas": ["fossil_gas"],
    "hydro": ["hydro_pumped_storage", "hydro_run_of_river_and_poundage", "hydro_water_reservoir"],
    "biomass_waste": ["biomass", "waste"],
}


def _client():
    from entsoe import EntsoePandasClient

    return EntsoePandasClient(api_key=entsoe_api_key())


def _cached_fetch(
    cfg: Config,
    name: str,
    fn: Callable[[pd.Timestamp, pd.Timestamp], pd.Series | pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Fetch [start, end) chunk by chunk, caching each chunk to parquet."""
    from entsoe.exceptions import NoMatchingDataError

    cache_dir = cfg.path("raw_dir") / "entsoe"
    cache_dir.mkdir(parents=True, exist_ok=True)
    today = pd.Timestamp.now(tz="UTC").floor("D")
    parts = []
    for s, e in month_chunks(start, end, cfg["entsoe"]["chunk_months"]):
        f: Path = cache_dir / f"{name}_{s:%Y%m%d}_{e:%Y%m%d}.parquet"
        recent = e >= today - pd.Timedelta(days=2)  # recent chunks may still be revised
        if f.exists() and not recent:
            parts.append(pd.read_parquet(f))
            continue
        log.info("ENTSO-E %s %s -> %s", name, s.date(), e.date())
        try:
            res = fn(s.tz_convert("Europe/Brussels"), e.tz_convert("Europe/Brussels"))
        except NoMatchingDataError:
            log.warning("No data for %s in %s -> %s", name, s.date(), e.date())
            continue
        df = res.to_frame(name) if isinstance(res, pd.Series) else res
        df = _flatten(df)
        df.to_parquet(f)
        parts.append(df)
        time.sleep(cfg["entsoe"]["request_sleep_s"])
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts)
    return to_hourly_utc(out[~out.index.duplicated(keep="last")])


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """Generation frames can have MultiIndex columns (type, Actual Aggregated/Consumption)."""
    if isinstance(df.columns, pd.MultiIndex):
        keep = [c for c in df.columns if c[1] in ("Actual Aggregated", "")]
        df = df[keep] if keep else df.xs(df.columns.levels[1][0], axis=1, level=1)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [snake(str(c)) for c in df.columns]
    return df


def fetch_entsoe(cfg: Config, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Download every ENTSO-E series used by the model and return one hourly UTC frame."""
    client = _client()
    zone = cfg["project"]["bidding_zone"]
    start = start or cfg.start
    end = end or cfg.end + pd.Timedelta(days=2)  # include D+1 forecasts when available
    frames: dict[str, pd.DataFrame] = {}

    # --- Prices -----------------------------------------------------------
    frames["price"] = _cached_fetch(cfg, f"price_{zone}", lambda s, e: client.query_day_ahead_prices(zone, start=s, end=e), start, end)
    frames["price"].columns = ["price_da"]
    for nb in cfg["project"]["neighbours"]:
        p = _cached_fetch(cfg, f"price_{nb}", lambda s, e, nb=nb: client.query_day_ahead_prices(nb, start=s, end=e), start, end)
        if not p.empty:
            p.columns = [f"price_da_{nb}"]
            frames[f"price_{nb}"] = p

    # --- Load -------------------------------------------------------------
    load = _cached_fetch(cfg, f"load_{zone}", lambda s, e: client.query_load(zone, start=s, end=e), start, end)
    frames["load"] = load.rename(columns={"actual_load": "load_actual"})[["load_actual"]] if not load.empty else load
    lf = _cached_fetch(cfg, f"loadfc_{zone}", lambda s, e: client.query_load_forecast(zone, start=s, end=e), start, end)
    frames["load_fc"] = lf.rename(columns={"forecasted_load": "load_forecast"})[["load_forecast"]] if not lf.empty else lf

    # --- Generation (actual, per type) -----------------------------------
    gen = _cached_fetch(cfg, f"gen_{zone}", lambda s, e: client.query_generation(zone, start=s, end=e), start, end)
    if not gen.empty:
        out = pd.DataFrame(index=gen.index)
        for group, cols in GEN_GROUPS.items():
            present = [c for c in cols if c in gen.columns]
            if present:
                out[f"gen_{group}"] = gen[present].sum(axis=1, min_count=1)
        out["gen_total"] = gen.sum(axis=1, min_count=1)
        frames["gen"] = out

    # --- Day-ahead forecasts published by the TSO (known before the auction)
    ws = _cached_fetch(cfg, f"wsfc_{zone}", lambda s, e: client.query_wind_and_solar_forecast(zone, start=s, end=e), start, end)
    if not ws.empty:
        out = pd.DataFrame(index=ws.index)
        if "solar" in ws:
            out["fc_solar"] = ws["solar"]
        wind_cols = [c for c in ("wind_onshore", "wind_offshore") if c in ws]
        if wind_cols:
            out["fc_wind"] = ws[wind_cols].sum(axis=1, min_count=1)
        frames["ws_fc"] = out
    gf = _cached_fetch(cfg, f"genfc_{zone}", lambda s, e: client.query_generation_forecast(zone, start=s, end=e), start, end)
    if not gf.empty:
        frames["gen_fc"] = gf.iloc[:, [0]].set_axis(["fc_gen_total"], axis=1)

    df = pd.concat([f for f in frames.values() if not f.empty], axis=1).sort_index()
    return df.loc[(df.index >= start) & (df.index < end)]
