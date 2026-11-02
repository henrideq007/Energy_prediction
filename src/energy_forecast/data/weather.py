"""Weather from Open-Meteo (free, no API key).

- archive             : ERA5 reanalysis (observed). Good for exploration, slightly optimistic in backtests.
- historical_forecast : archived NWP forecasts — what was actually forecast at the time (realistic).
- live                : current forecast, used by the live 24h prediction.
"""

from __future__ import annotations

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


def fetch_weather(cfg: Config, start: pd.Timestamp, end: pd.Timestamp, source: str | None = None) -> pd.DataFrame:
    """Return hourly UTC weather, one column per (location, variable): w_<loc>_<var>."""
    wcfg = cfg["weather"]
    source = source or wcfg["source"]
    url = URLS[source]
    frames = []
    for loc, (lat, lon) in wcfg["locations"].items():
        if source == "live":
            params = {"past_days": 7, "forecast_days": 3}
        else:
            # The archive API is queried year by year to keep responses small
            parts = []
            for y in range(start.year, end.year + 1):
                s = max(start, pd.Timestamp(f"{y}-01-01", tz="UTC"))
                e = min(end, pd.Timestamp(f"{y}-12-31", tz="UTC"))
                log.info("Open-Meteo %s %s %s", source, loc, y)
                parts.append(
                    _fetch_location(url, lat, lon, wcfg["variables"], {"start_date": f"{s:%Y-%m-%d}", "end_date": f"{e:%Y-%m-%d}"})
                )
            df = pd.concat(parts)
            frames.append(df.add_prefix(f"w_{loc}_"))
            continue
        df = _fetch_location(url, lat, lon, wcfg["variables"], params)
        frames.append(df.add_prefix(f"w_{loc}_"))
    out = pd.concat(frames, axis=1).sort_index()
    return out[~out.index.duplicated(keep="last")]
