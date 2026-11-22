"""Weather from Open-Meteo (free, no API key).

- archive             : ERA5 reanalysis (observed). Good for exploration, slightly optimistic in backtests.
- historical_forecast : archived NWP forecasts — what was actually forecast at the time (realistic).
- live                : current forecast, used by the live 24h prediction.
"""

from __future__ import annotations

import hashlib
import logging

import pandas as pd
import requests

from energy_forecast.config import Config

log = logging.getLogger(__name__)

URLS = {
    "archive": "https://archive-api.open-meteo.com/v1/archive",
    "historical_forecast": "https://historical-forecast-api.open-meteo.com/v1/forecast",
    "live": "https://api.open-meteo.com/v1/forecast",
}


def _fetch_location(url: str, lat: float, lon: float, variables: list[str], params: dict) -> pd.DataFrame:
    q = {"latitude": lat, "longitude": lon, "hourly": ",".join(variables), "timezone": "UTC", **params}
    r = requests.get(url, params=q, timeout=60)
    r.raise_for_status()
    h = r.json()["hourly"]
    df = pd.DataFrame(h)
    df.index = pd.to_datetime(df.pop("time"), utc=True)
    return df


ARCHIVE_LAG_DAYS = 6  # the ERA5 archive is published with a ~5-day delay


def fetch_weather(cfg: Config, start: pd.Timestamp, end: pd.Timestamp, source: str | None = None) -> pd.DataFrame:
    """Return hourly UTC weather, one column per (location, variable): w_<loc>_<var>.

    History sources (archive / historical_forecast) are only queried up to today - ARCHIVE_LAG_DAYS.
    The most recent days (and up to 15 days ahead) are filled from the live forecast API.
    """
    wcfg = cfg["weather"]
    source = source or wcfg["source"]
    url = URLS[source]
    today = pd.Timestamp.now(tz="UTC").normalize()
    hist_end = min(end, today - pd.Timedelta(days=ARCHIVE_LAG_DAYS))
    # Core Belgian points -> prefix w_ (used by features.py). Candidate points (e.g. France, DP-043)
    # -> their own prefix (ignored by features.py until the ablation test, decisions D-15 / D-23).
    groups = [("w_", wcfg["locations"], wcfg["variables"])]
    cand = wcfg.get("candidate_locations") or {}
    if cand:
        groups.append((wcfg.get("candidate_prefix", "wc_"), cand, wcfg.get("candidate_variables", wcfg["variables"])))
    cache = cfg.path("raw_dir") / "weather"
    cache.mkdir(parents=True, exist_ok=True)
    frames = []
    for prefix, loc, lat, lon, variables in [(p, n, la, lo, v) for p, locs, v in groups for n, (la, lo) in locs.items()]:
        if source == "live":
            df = _fetch_location(url, lat, lon, variables, {"past_days": 7, "forecast_days": 3})
            frames.append(df.add_prefix(f"{prefix}{loc}_"))
            continue

        parts = []
        # 1) History, year by year, never later than hist_end
        for y in range(start.year, hist_end.year + 1):
            s = max(start, pd.Timestamp(f"{y}-01-01", tz="UTC"))
            e = min(hist_end, pd.Timestamp(f"{y}-12-31", tz="UTC"))
            if s > e:
                continue
            # Complete past years are cached (keyed on source, point and variable list)
            key = hashlib.md5(",".join(variables).encode()).hexdigest()[:8]
            f = cache / f"{source}_{prefix}{loc}_{y}_{key}.parquet"
            if f.exists() and y < today.year and s == pd.Timestamp(f"{y}-01-01", tz="UTC"):
                parts.append(pd.read_parquet(f))
                continue
            log.info("Open-Meteo %s %s %s", source, loc, y)
            d = _fetch_location(url, lat, lon, variables, {"start_date": f"{s:%Y-%m-%d}", "end_date": f"{e:%Y-%m-%d}"})
            if y < today.year and s == pd.Timestamp(f"{y}-01-01", tz="UTC"):
                d.to_parquet(f)
            parts.append(d)

        # 2) Recent days (+ near future) from the live forecast API
        if end > hist_end:
            tail_start = max(start.normalize(), hist_end + pd.Timedelta(days=1))
            past_days = int(min(92, max(0, (today - tail_start).days + 1)))
            forecast_days = int(min(16, max(1, (end.normalize() - today).days + 1)))
            log.info("Open-Meteo live (recent days) %s %s -> %s", loc, tail_start.date(), end.date())
            tail = _fetch_location(URLS["live"], lat, lon, variables,
                                   {"past_days": past_days, "forecast_days": forecast_days})
            tail = tail[(tail.index >= tail_start) & (tail.index < end.normalize() + pd.Timedelta(days=1))]
            parts.append(tail)

        df = pd.concat(parts)
        frames.append(df.add_prefix(f"{prefix}{loc}_"))
    out = pd.concat(frames, axis=1).sort_index()
    return out[~out.index.duplicated(keep="last")]