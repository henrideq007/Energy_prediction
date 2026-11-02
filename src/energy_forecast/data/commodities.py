"""Fuel & carbon prices — the marginal cost drivers of gas-fired plants that often set the BE price.

- TTF gas: Yahoo Finance front-month future via yfinance (free, daily close).
- EUA carbon: no reliable free API -> optional manual CSV (date,price) in data/external/.
Daily values are shifted by `publication_lag_days` so a forecast only uses closes
that were known at issue time, then forward-filled to hourly.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from energy_forecast.config import ROOT, Config

log = logging.getLogger(__name__)


def _daily_to_hourly(s: pd.Series, index: pd.DatetimeIndex, lag_days: int) -> pd.Series:
    s = s.copy()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.index = (s.index + pd.Timedelta(days=lag_days)).tz_localize("UTC")
    return s.reindex(s.index.union(index)).ffill().reindex(index)


def fetch_commodities(cfg: Config, index: pd.DatetimeIndex) -> pd.DataFrame:
    ccfg = cfg["commodities"]
    out = pd.DataFrame(index=index)
    if not ccfg.get("enabled", True):
        return out
    lag = ccfg["publication_lag_days"]
    try:
        import yfinance as yf

        start = (index.min() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        end = (index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        ttf = yf.download(ccfg["ttf_ticker"], start=start, end=end, progress=False, auto_adjust=False)
        if not ttf.empty:
            close = ttf["Close"]
            close = close.iloc[:, 0] if isinstance(close, pd.DataFrame) else close
            out["ttf_gas"] = _daily_to_hourly(close, index, lag)
    except Exception as exc:  # network / ticker issues should not kill the pipeline
        log.warning("TTF download failed: %s", exc)

    eua_path = ROOT / ccfg["eua_csv"]
    if Path(eua_path).exists():
        eua = pd.read_csv(eua_path, parse_dates=["date"]).set_index("date")["price"]
        out["eua_carbon"] = _daily_to_hourly(eua, index, lag)
    else:
        log.info("No EUA CSV at %s — carbon feature skipped", eua_path)
    return out
