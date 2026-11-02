"""Assemble all sources into one hourly UTC dataset: data/processed/dataset.parquet."""

from __future__ import annotations

import logging

import pandas as pd

from energy_forecast.config import Config

log = logging.getLogger(__name__)


def build_dataset(cfg: Config, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
                  weather_source: str | None = None, save: bool = True) -> pd.DataFrame:
    from energy_forecast.data.commodities import fetch_commodities
    from energy_forecast.data.elia import fetch_elia
    from energy_forecast.data.entsoe_source import fetch_entsoe
    from energy_forecast.data.weather import fetch_weather

    start = start or cfg.start
    end = end or cfg.end + pd.Timedelta(days=2)

    grid = fetch_entsoe(cfg, start, end)
    log.info("ENTSO-E: %s rows, %s cols", *grid.shape)
    weather = fetch_weather(cfg, start, end, source=weather_source)
    log.info("Weather: %s rows, %s cols", *weather.shape)

    idx = pd.date_range(start, end, freq="1h", tz="UTC", inclusive="left")
    df = pd.DataFrame(index=idx).join(grid).join(weather)
    df = df.join(fetch_commodities(cfg, idx))
    elia = fetch_elia(cfg, start, end)
    if not elia.empty:
        df = df.join(elia)
    df.index.name = "timestamp_utc"

    if save:
        out = cfg.path("processed_dir") / "dataset.parquet"
        df.to_parquet(out)
        log.info("Saved %s (%s rows x %s cols)", out, *df.shape)
    return df


def load_dataset(cfg: Config) -> pd.DataFrame:
    path = cfg.path("processed_dir") / "dataset.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run `energy-forecast fetch` (or `demo`) first.")
    return pd.read_parquet(path)
