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
    "hydro": ["hydro_pumped_storage", "hydro_run_of_river_and_pondage", "hydro_run_of_river_and_poundage",
              "hydro_water_reservoir"],
    "biomass_waste": ["biomass", "waste"],
    "storage": ["energy_storage"],
}

# ENTSO-E leaves these types EMPTY (not 0) in hours where they do not generate:
# - pumped storage while pumping (its consumption is in a separate column we drop)
# - offshore wind at zero output / curtailment
# Checked on BE data 2019-2026: pumped storage is "missing" in ~55% of hours, mostly at night (pumping/idle;
# average price 79 EUR/MWh vs 119 when it generates). The old typo "poundage" also dropped run-of-river.
# They are set to 0 when the rest of the generation mix is reported for that hour.
ZERO_IF_MISSING = ("hydro_pumped_storage", "wind_offshore", "energy_storage")


def fill_zero_generation(gen: pd.DataFrame) -> pd.DataFrame:
    """Replace missing values by 0 for types that ENTSO-E leaves empty when they produce nothing."""
    gen = gen.copy()
    reported = gen.notna().any(axis=1)
    for c in ZERO_IF_MISSING:
        if c in gen:
            gen.loc[reported & gen[c].isna(), c] = 0.0
    return gen


def call_with_retry(fn, label: str, tries: int = 4):
    """Call fn(); retry transient errors (5xx, 429, connection). NoMatchingDataError is re-raised at once.

    The exception text is never logged: ENTSO-E puts the security token in the request URL.
    """
    from entsoe.exceptions import NoMatchingDataError

    for attempt in range(tries):
        try:
            return fn()
        except NoMatchingDataError:
            raise
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            transient = status is None or status >= 500 or status == 429
            if not transient or attempt == tries - 1:
                raise RuntimeError(f"ENTSO-E {label} failed ({type(exc).__name__}, HTTP {status})") from None
            log.info("ENTSO-E %s: HTTP %s, retry %s", label, status, attempt + 1)
            time.sleep(5 * 2 ** attempt)


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
        res = None
        for attempt in range(4):  # transient 5xx / connection errors are common on the Transparency API
            try:
                res = fn(s.tz_convert("Europe/Brussels"), e.tz_convert("Europe/Brussels"))
                break
            except NoMatchingDataError:
                log.warning("No data for %s in %s -> %s", name, s.date(), e.date())
                break
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                transient = status is None or status >= 500 or status == 429
                if status == 400 and (e - s) > pd.Timedelta(days=32):
                    # some series (e.g. BE net position around the 2022 Core go-live) reject multi-month
                    # windows -> retry month by month and cache the result under the chunk name
                    res = _monthly_fallback(fn, s, e)
                    if res is None:
                        log.warning("ENTSO-E %s %s -> %s failed month by month too — chunk skipped",
                                    name, s.date(), e.date())
                    break
                if not transient or attempt == 3:
                    # never log the exception text: ENTSO-E puts the token in the request URL
                    log.warning("ENTSO-E %s %s -> %s failed (%s, HTTP %s) — chunk skipped",
                                name, s.date(), e.date(), type(exc).__name__, status)
                    break
                time.sleep(5 * 2 ** attempt)
        if res is None:
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


def _monthly_fallback(fn, s: pd.Timestamp, e: pd.Timestamp):
    """Call fn month by month over [s, e); return the concatenated result or None."""
    from entsoe.exceptions import NoMatchingDataError

    parts = []
    for ms, me in month_chunks(s, e, 1):
        try:
            r = call_with_retry(lambda ms=ms, me=me: fn(ms.tz_convert("Europe/Brussels"), me.tz_convert("Europe/Brussels")),
                                f"monthly fallback {ms.date()}")
        except NoMatchingDataError:
            continue
        except Exception:
            continue
        parts.append(r)
    if not parts:
        return None
    out = pd.concat(parts)
    return out[~out.index.duplicated(keep="last")]


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
        gen = fill_zero_generation(gen)
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
