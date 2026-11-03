"""Fuel & carbon prices — the marginal cost drivers of gas-fired plants that often set the BE price.

- TTF gas: Yahoo Finance front-month future via yfinance (free, daily close, unofficial).
  If Yahoo returns nothing (ticker changes, blocking), a manual CSV is used instead
  (`commodities.ttf_csv`, columns date,price). If both exist, the CSV fills the gaps.
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


def read_price_csv(path: str | Path) -> pd.Series:
    """Read a daily price CSV with columns `date,price` (extra columns are ignored).

    Accepts ISO dates (2026-10-27) or day-first dates (27/10/2026) and decimal commas ("31,25").
    """
    raw = pd.read_csv(path, dtype=str)
    cols = {c.lower().strip(): c for c in raw.columns}
    if "date" not in cols or "price" not in cols:
        raise ValueError(f"{path}: expected columns 'date,price', found {list(raw.columns)}")
    dates = raw[cols["date"]].str.strip()
    iso = dates.str.match(r"^\d{4}-\d{2}-\d{2}")
    parsed = pd.to_datetime(dates.where(iso), format="%Y-%m-%d", errors="coerce")
    parsed = parsed.fillna(pd.to_datetime(dates.where(~iso), dayfirst=True, errors="coerce"))
    price = pd.to_numeric(raw[cols["price"]].str.replace(",", ".", regex=False).str.strip(), errors="coerce")
    s = pd.Series(price.to_numpy(), index=parsed).dropna()
    s = s[s.index.notna()].sort_index()
    return s[~s.index.duplicated(keep="last")]


def _ttf_from_yahoo(ticker: str, index: pd.DatetimeIndex) -> pd.Series:
    try:
        import yfinance as yf

        start = (index.min() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        end = (index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        ttf = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    except Exception as exc:  # network / ticker issues should not kill the pipeline
        log.warning("TTF download from Yahoo failed: %s", exc)
        return pd.Series(dtype=float)
    if ttf is None or ttf.empty:
        log.warning("Yahoo returned no data for %s — use the TTF CSV fallback (commodities.ttf_csv)", ticker)
        return pd.Series(dtype=float)
    close = ttf["Close"]
    close = close.iloc[:, 0] if isinstance(close, pd.DataFrame) else close
    return close.dropna()


def fetch_commodities(cfg: Config, index: pd.DatetimeIndex) -> pd.DataFrame:
    ccfg = cfg["commodities"]
    out = pd.DataFrame(index=index)
    if not ccfg.get("enabled", True):
        return out
    lag = ccfg["publication_lag_days"]

    # --- TTF gas: Yahoo first, CSV as fallback / gap filler ----------------
    ttf = _ttf_from_yahoo(ccfg["ttf_ticker"], index)
    ttf_csv = ccfg.get("ttf_csv")
    if ttf_csv and (ROOT / ttf_csv).exists():
        csv = read_price_csv(ROOT / ttf_csv)
        log.info("TTF CSV: %s daily prices (%s -> %s)", len(csv), csv.index.min().date(), csv.index.max().date())
        if not ttf.empty:
            ttf.index = pd.to_datetime(ttf.index).tz_localize(None).normalize()
        ttf = csv if ttf.empty else ttf.combine_first(csv)
    elif ttf.empty:
        log.warning("No TTF data: Yahoo empty and no CSV at %s — gas feature skipped", ttf_csv)
    if not ttf.empty:
        out["ttf_gas"] = _daily_to_hourly(ttf, index, lag)

    # --- EUA carbon: manual CSV -------------------------------------------
    eua_path = ROOT / ccfg["eua_csv"]
    if Path(eua_path).exists():
        out["eua_carbon"] = _daily_to_hourly(read_price_csv(eua_path), index, lag)
    else:
        log.info("No EUA CSV at %s — carbon feature skipped", eua_path)
    return out
