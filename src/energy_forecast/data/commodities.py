"""Fuel & carbon prices — the marginal cost drivers of gas-fired plants that often set the BE price.

- TTF gas: Yahoo Finance front-month future via yfinance (free, daily close, unofficial).
  Yahoo is retried (futures tickers fail intermittently) and every successful download is kept in a
  local cache (`commodities.ttf_cache`), reused when Yahoo returns nothing.
  A manual CSV (`commodities.ttf_csv`, columns date,price) fills whatever is still missing.
- EUA carbon: no reliable free API -> optional manual CSV (date,price) in data/external/.
Daily values are shifted by `publication_lag_days` so a forecast only uses closes
that were known at issue time, then forward-filled to hourly.
"""

from __future__ import annotations

import logging
import time
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


def _yahoo_close(ticker: str, start: str, end: str) -> pd.Series:
    """One Yahoo attempt: `yf.download` first, then `Ticker.history` (a different code path in yfinance)."""
    import yfinance as yf

    for method in ("download", "history"):
        try:
            if method == "download":
                data = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
            else:
                data = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
        except Exception as exc:  # network / ticker issues should not kill the pipeline
            log.warning("TTF Yahoo %s failed: %s", method, exc)
            continue
        if data is None or data.empty or "Close" not in data:
            continue
        close = data["Close"]
        close = close.iloc[:, 0] if isinstance(close, pd.DataFrame) else close
        close = close.dropna()
        if not close.empty:
            return close
    return pd.Series(dtype=float)


def _ttf_from_yahoo(ticker: str, index: pd.DatetimeIndex, attempts: int = 3, sleep_s: float = 2.0) -> pd.Series:
    """TTF front-month daily closes from Yahoo. Futures tickers fail intermittently, so retry a few times."""
    start = (index.min() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    end = (index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    for attempt in range(1, attempts + 1):
        try:
            close = _yahoo_close(ticker, start, end)
        except ImportError as exc:
            log.warning("yfinance is not installed: %s", exc)
            return pd.Series(dtype=float)
        if not close.empty:
            return close
        if attempt < attempts:
            time.sleep(sleep_s * attempt)
    log.warning("Yahoo returned no data for %s after %s attempts — using cache / CSV fallback", ticker, attempts)
    return pd.Series(dtype=float)


def _naive_daily(s: pd.Series) -> pd.Series:
    s = s.copy()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def _merge_with_cache(fresh: pd.Series, cache_path: Path) -> pd.Series:
    """Keep every Yahoo close ever downloaded, so a failed download later does not lose the gas feature.

    Fresh values win over cached ones; the cache is rewritten only when Yahoo returned something.
    """
    cached = read_price_csv(cache_path) if cache_path.exists() else pd.Series(dtype=float)
    if fresh.empty:
        if not cached.empty:
            log.info("TTF: Yahoo empty, using %s cached closes (last %s)", len(cached), cached.index.max().date())
        return cached
    merged = _naive_daily(fresh).combine_first(cached) if not cached.empty else _naive_daily(fresh)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": merged.index.strftime("%Y-%m-%d"), "price": merged.to_numpy()}).to_csv(cache_path, index=False)
    return merged


def fetch_commodities(cfg: Config, index: pd.DatetimeIndex) -> pd.DataFrame:
    ccfg = cfg["commodities"]
    out = pd.DataFrame(index=index)
    if not ccfg.get("enabled", True):
        return out
    lag = ccfg["publication_lag_days"]

    # --- TTF gas: Yahoo first, CSV as fallback / gap filler ----------------
    ttf = _ttf_from_yahoo(ccfg["ttf_ticker"], index)
    if ccfg.get("ttf_cache"):
        ttf = _merge_with_cache(ttf, ROOT / ccfg["ttf_cache"])
    ttf_csv = ccfg.get("ttf_csv")
    if ttf_csv and (ROOT / ttf_csv).exists():
        csv = read_price_csv(ROOT / ttf_csv)
        log.info("TTF CSV: %s daily prices (%s -> %s)", len(csv), csv.index.min().date(), csv.index.max().date())
        if not ttf.empty:
            ttf = _naive_daily(ttf)
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
