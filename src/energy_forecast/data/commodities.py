"""Fuel & carbon prices — the marginal cost drivers of gas-fired plants that often set the BE price.

Gas (`ttf_gas`, EUR/MWh) — first available source wins, day by day (decision D-25):
  1. Yahoo Finance `TTF=F` (yfinance) — real TTF front-month closes. Retried (futures tickers fail
     intermittently, two yfinance code paths) and every successful download is kept in a local cache
     (`commodities.ttf_cache`, decision D-23). As of Nov 2026 Yahoo only serves recent quotes, so the cache
     builds the real-TTF record from now on.
  2. manual CSV `commodities.ttf_csv` (date,price) — fills days Yahoo/cache do not have
  3. THE (Trading Hub Europe, German hub) official daily VTP average price — free API, no key,
     from 1 Oct 2021. THE and TTF are tightly coupled (spread usually < 2 EUR/MWh).
  4. IMF "Global price of natural gas, EU" (FRED PNGASEUUSDM, TTF-based), MONTHLY, converted to
     EUR/MWh with the daily EUR/USD (FRED DEXUSEU) — back-fill for 2019 → Sep 2021 only
Carbon (`eua_carbon`, EUR/t) (decision D-26):
  1. manual CSV `commodities.eua_csv`
  2. EEX EU ETS primary-auction clearing prices (official, free xlsx reports in data/raw/eex/)
  3. SparkChange Physical Carbon EUA ETC (`CO2.L`, EUR) x rolling ratio to the auction price —
     fills auction-free days and the period after the last auction report
Other candidates (not used by the model until the ablation test, D-15):
  coal_api2 (Yahoo MTF=F, DP-047) · gas_storage_eu_pct (GIE AGSI+, needs AGSI_API_KEY, DP-048)

Daily values are shifted by `publication_lag_days` so a forecast only uses closes that were
known at issue time, then forward-filled to hourly. `flag_*` columns tell which proxy was used.
"""

from __future__ import annotations

import io
import logging
import os
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

from energy_forecast.config import ROOT, Config

log = logging.getLogger(__name__)
UA = {"User-Agent": "energy-forecast-research/0.1 (+github energy-price-prediction)"}
MWH_PER_MMBTU = 0.293071


def _daily_to_hourly(s: pd.Series, index: pd.DatetimeIndex, lag_days: int, max_stale_days: int = 10) -> pd.Series:
    """Shift a daily series by `lag_days`, forward-fill to hourly, but never carry a value for more
    than `max_stale_days` (weekends/holidays are fine; a dead source becomes NaN, not a flat line)."""
    s = s.copy()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.index = (s.index + pd.Timedelta(days=lag_days)).tz_localize("UTC")
    full = s.index.union(index)
    out = s.reindex(full).ffill()
    last = pd.Series(s.index, index=s.index).reindex(full).ffill()
    stale = (pd.Series(full, index=full) - last) > pd.Timedelta(days=max_stale_days)
    return out.mask(stale).reindex(index)


def _naive_daily(s: pd.Series) -> pd.Series:
    s = s.dropna().copy()
    idx = pd.to_datetime(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


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


# --------------------------------------------------------------------------- Yahoo
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
            log.warning("Yahoo %s %s failed: %s", ticker, method, exc)
            continue
        if data is None or data.empty or "Close" not in data:
            continue
        close = data["Close"]
        close = close.iloc[:, 0] if isinstance(close, pd.DataFrame) else close
        close = close.dropna()
        if not close.empty:
            return close
    return pd.Series(dtype=float)


def _yahoo_series(ticker: str, start: str, end: str) -> pd.Series:
    """Single Yahoo call that never raises (used for the ETC and coal candidates)."""
    try:
        return _yahoo_close(ticker, start, end)
    except ImportError as exc:
        log.warning("yfinance is not installed: %s", exc)
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
    log.warning("Yahoo returned no data for %s after %s attempts — using cache / other gas sources", ticker, attempts)
    return pd.Series(dtype=float)


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


# --------------------------------------------------------------------------- THE (German gas hub)
THE_URL = "https://api.tradinghub.eu/api/dataexport/xmlexport/PricesEnergyImbalance"
THE_START = pd.Timestamp("2021-10-01")


def gas_from_the(cache_dir: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Official THE daily VTP average price (EUR/MWh) per gas day, cached per year."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    this_year = pd.Timestamp.now().year
    parts = []
    for y in range(max(start.year, THE_START.year), end.year + 1):
        f = cache_dir / f"the_vtp_{y}.parquet"
        if f.exists() and y < this_year:
            parts.append(pd.read_parquet(f)["price"])
            continue
        try:
            r = requests.get(THE_URL, params={"startDate": f"{y}-01-01", "endDate": f"{y}-12-31"}, headers=UA, timeout=120)
            r.raise_for_status()
            x = pd.read_xml(io.BytesIO(r.content), xpath="//PricesEnergyImbalance/PricesEnergyImbalance")
        except Exception as exc:
            log.warning("THE gas prices %s failed: %s", y, exc)
            if f.exists():
                parts.append(pd.read_parquet(f)["price"])
            continue
        s = pd.Series(pd.to_numeric(x["VTPDailyAveragePrice"], errors="coerce").to_numpy(),
                      index=pd.to_datetime(x["Gasday"]), name="price").dropna().sort_index()
        s.to_frame().to_parquet(f)
        parts.append(s)
    if not parts:
        return pd.Series(dtype=float)
    return _naive_daily(pd.concat(parts))


# --------------------------------------------------------------------------- FRED (monthly back-fill)
def _fred(series_id: str, cache_dir: Path) -> pd.Series:
    f = cache_dir / f"fred_{series_id}.csv"
    fresh = f.exists() and pd.Timestamp(f.stat().st_mtime, unit="s") > pd.Timestamp.now() - pd.Timedelta(days=7)
    if not fresh:
        try:
            r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                             params={"id": series_id, "cosd": "2018-01-01"}, headers=UA, timeout=60)
            r.raise_for_status()
            f.write_bytes(r.content)
        except Exception as exc:
            log.warning("FRED %s failed: %s", series_id, exc)
    if not f.exists():
        return pd.Series(dtype=float)
    d = pd.read_csv(f)
    return pd.Series(pd.to_numeric(d.iloc[:, 1], errors="coerce").to_numpy(),
                     index=pd.to_datetime(d.iloc[:, 0])).dropna()


def gas_monthly_proxy(cache_dir: Path) -> pd.Series:
    """IMF EU gas price (USD/MMBtu, monthly) -> EUR/MWh, as a DAILY step series.

    A monthly average is only fully known after the month ends, so each month's value is
    stamped on the 1st of the FOLLOWING month (no look-ahead), then forward-filled.
    """
    usd = _fred("PNGASEUUSDM", cache_dir)
    fx = _fred("DEXUSEU", cache_dir)  # USD per EUR
    if usd.empty or fx.empty:
        return pd.Series(dtype=float)
    fx_m = fx.resample("MS").mean()
    eur_mwh = (usd / fx_m.reindex(usd.index).ffill()) / MWH_PER_MMBTU
    eur_mwh.index = eur_mwh.index + pd.offsets.MonthBegin(1)
    days = pd.date_range(eur_mwh.index.min(), pd.Timestamp.now().normalize(), freq="D")
    return eur_mwh.reindex(days).ffill().dropna()


# --------------------------------------------------------------------------- EEX EUA auctions
EEX_BASE = "https://www.eex.com/fileadmin/EEX/Downloads/Markets/Environmentals/EUA_Emission_Spot_Primary_Market_Auction_Report"
EEX_ARCHIVE = f"{EEX_BASE}/Archive_Reports/emission-spot-primary-market-auction-report-2012-2025-data.zip"


def _ensure_eex_reports(eex_dir: Path) -> None:
    eex_dir.mkdir(parents=True, exist_ok=True)
    if any(eex_dir.glob("emission-spot-primary-market-auction-report-2025-data.*")):
        return
    try:
        r = requests.get(EEX_ARCHIVE, headers={"User-Agent": "Mozilla/5.0"}, timeout=180)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for n in z.namelist():
                if n.endswith((".xls", ".xlsx")) and any(f"-{y}-" in n for y in range(2018, 2030)):
                    (eex_dir / Path(n).name).write_bytes(z.read(n))
    except Exception as exc:
        log.warning("EEX auction archive download failed: %s", exc)


def eua_from_eex(eex_dir: Path) -> pd.Series:
    """Daily mean EUA primary-auction clearing price (EUR/t) from every report in data/raw/eex/.

    The current-year report is not linked statically on eex.com: download
    'Emission Spot Primary Market Auction Report <year>' by hand into that folder to extend it.
    """
    _ensure_eex_reports(eex_dir)
    parts = []
    for f in sorted(eex_dir.glob("emission-spot-primary-market-auction-report-*-data.xls*")):
        try:
            x = pd.read_excel(f, header=5)
        except Exception as exc:
            log.warning("Cannot read %s: %s", f.name, exc)
            continue
        pc = [c for c in x.columns if str(c).startswith("Auction Price")]
        if not pc or "Date" not in x:
            continue
        name = x.get("Auction Name", pd.Series("", index=x.index)).astype(str)
        ok = ~name.str.contains("EUAA|aviation", case=False)  # aviation allowances trade differently
        parts.append(pd.DataFrame({"date": pd.to_datetime(x.loc[ok, "Date"], errors="coerce"),
                                   "price": pd.to_numeric(x.loc[ok, pc[0]], errors="coerce")}))
    if not parts:
        return pd.Series(dtype=float)
    a = pd.concat(parts).dropna()
    return a.groupby("date")["price"].mean().sort_index()


def eua_with_etc_fill(auction: pd.Series, etc: pd.Series, window: int = 60) -> tuple[pd.Series, pd.Series]:
    """Combine auction prices with the EUA ETC scaled by a rolling auction/ETC ratio.

    Returns (price, flag) where flag = 1 on days filled from the ETC.
    """
    auction, etc = _naive_daily(auction), _naive_daily(etc)
    if etc.empty:
        return auction, pd.Series(0, index=auction.index)
    ratio = (auction / etc).dropna()
    ratio = ratio.rolling(window, min_periods=5).median()
    ratio = ratio.reindex(ratio.index.union(etc.index)).ffill().reindex(etc.index)
    est = (etc * ratio).dropna()
    price = auction.combine_first(est)
    flag = pd.Series(0, index=price.index)
    flag.loc[price.index.difference(auction.index)] = 1
    return price, flag


# --------------------------------------------------------------------------- AGSI+ gas storage
def gas_storage_agsi(cache_dir: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """EU aggregated gas storage filling (% full). Needs a free key in .env: AGSI_API_KEY."""
    key = os.getenv("AGSI_API_KEY", "")
    if not key:
        log.info("AGSI_API_KEY not set — gas storage (DP-048) skipped")
        return pd.Series(dtype=float)
    f = cache_dir / "agsi_eu.parquet"
    rows, page = [], 1
    try:
        while True:
            r = requests.get("https://agsi.gie.eu/api", headers={"x-key": key, **UA}, timeout=120,
                             params={"type": "eu", "from": f"{start:%Y-%m-%d}", "to": f"{end:%Y-%m-%d}", "size": 300, "page": page})
            r.raise_for_status()
            j = r.json()
            rows += j.get("data", [])
            if page >= int(j.get("last_page", 1)):
                break
            page += 1
        d = pd.DataFrame(rows)
        s = pd.Series(pd.to_numeric(d["full"], errors="coerce").to_numpy(), index=pd.to_datetime(d["gasDayStart"]), name="full")
        s.sort_index().to_frame().to_parquet(f)
    except Exception as exc:
        log.warning("AGSI+ failed: %s", exc)
        if not f.exists():
            return pd.Series(dtype=float)
        s = pd.read_parquet(f)["full"]
    return _naive_daily(s)


# --------------------------------------------------------------------------- entry point
def fetch_commodities(cfg: Config, index: pd.DatetimeIndex) -> pd.DataFrame:
    ccfg = cfg["commodities"]
    out = pd.DataFrame(index=index)
    if not ccfg.get("enabled", True):
        return out
    lag = ccfg["publication_lag_days"]
    raw = ROOT / ccfg.get("raw_dir", "data/raw/commodities")
    start, end = index.min(), index.max()

    # --- Gas: Yahoo TTF (+ cache) > manual CSV > THE daily > IMF monthly (D-23, D-25) ----
    layers: list[tuple[str, pd.Series]] = []
    ttf = _ttf_from_yahoo(ccfg["ttf_ticker"], index)
    if ccfg.get("ttf_cache"):
        ttf = _merge_with_cache(ttf, ROOT / ccfg["ttf_cache"])
    layers.append(("yahoo", ttf))
    ttf_csv = ccfg.get("ttf_csv")
    if ttf_csv and (ROOT / ttf_csv).exists():
        csv = read_price_csv(ROOT / ttf_csv)
        log.info("TTF CSV: %s daily prices (%s -> %s)", len(csv), csv.index.min().date(), csv.index.max().date())
        layers.append(("csv", csv))
    if ccfg.get("gas_the_api", False):
        the = gas_from_the(raw, start, end)
        log.info("THE gas: %s days", len(the))
        layers.append(("the", the))
    if ccfg.get("gas_monthly_backfill", False):
        layers.append(("imf_monthly", gas_monthly_proxy(raw)))
    gas, monthly_days = pd.Series(dtype=float), pd.DatetimeIndex([])
    for name, s in layers:
        s = _naive_daily(s)
        if s.empty:
            continue
        new = s.index.difference(gas.index)
        if name == "imf_monthly":
            # only before the first daily value: never mix a monthly step into the daily era
            first_daily = gas.index.min() if not gas.empty else s.index.max() + pd.Timedelta(days=1)
            new = new[new < first_daily]
            monthly_days = new
        gas = pd.concat([gas, s.loc[new]]).sort_index()
    if gas.empty:
        log.warning("No gas price from any source — gas feature skipped")
    else:
        out["ttf_gas"] = _daily_to_hourly(gas, index, lag)
        if len(monthly_days):
            flag = pd.Series(0.0, index=gas.index)
            flag.loc[monthly_days] = 1.0
            out["flag_gas_monthly_proxy"] = _daily_to_hourly(flag, index, lag)

    # --- EUA carbon: CSV > EEX auctions (+ ETC fill) ----------------------
    eua_path = ROOT / ccfg["eua_csv"]
    eua = read_price_csv(eua_path) if Path(eua_path).exists() else pd.Series(dtype=float)
    if ccfg.get("eua_eex_auctions", False):
        auctions = eua_from_eex(ROOT / ccfg.get("eex_dir", "data/raw/eex"))
        etc = _yahoo_series(ccfg.get("eua_etc_ticker", "CO2.L"), "2021-01-01",
                           (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")) if ccfg.get("eua_etc_ticker") else pd.Series(dtype=float)
        filled, flag = eua_with_etc_fill(auctions, etc)
        log.info("EUA: %s auction days, %s ETC-filled days", len(auctions), int(flag.sum()))
        eua = _naive_daily(eua).combine_first(filled) if not eua.empty else filled
        if flag.any():
            out["flag_eua_etc_proxy"] = _daily_to_hourly(flag.astype(float), index, lag)
    if not eua.empty:
        # auctions pause ~3 weeks at Christmas and 46 days in Jan 2021 (ETS phase 4 start): allow 50 days
        out["eua_carbon"] = _daily_to_hourly(eua, index, lag, max_stale_days=50)
    else:
        log.info("No EUA source — carbon feature skipped")

    # --- Candidates (prefix cmd_: ignored by features.py until proven, D-15) ---
    if ccfg.get("coal_ticker"):
        coal = _yahoo_series(ccfg["coal_ticker"], (start - pd.Timedelta(days=30)).strftime("%Y-%m-%d"),
                            (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        if not coal.empty:
            out["cmd_coal_api2"] = _daily_to_hourly(coal, index, lag)
    if ccfg.get("gas_storage_agsi", False):
        st = gas_storage_agsi(raw, start, end)
        if not st.empty:
            out["cmd_gas_storage_eu_pct"] = _daily_to_hourly(st, index, lag)
    return out
