"""Live 24h forecast for delivery day D (default: tomorrow, Europe/Brussels).

Live flow:  ENTSO-E (last ~35 days + TSO forecasts for D)  +  Open-Meteo live forecast
            -> clean -> features -> saved models -> forecasts/forecast_<D>.csv/.json
"""

from __future__ import annotations

import json
import logging
from datetime import date

import joblib
import pandas as pd

from energy_forecast.config import Config
from energy_forecast.features import build_features
from energy_forecast.validation import clean_and_validate

log = logging.getLogger(__name__)
HISTORY_DAYS = 35  # enough for 28-day rolling price features + weekly lags


def _load_bundles(cfg: Config) -> dict:
    bundles = {}
    for f in sorted(cfg.path("models_dir").glob("*.joblib")):
        bundles[f.stem] = joblib.load(f)
    if not bundles:
        raise FileNotFoundError("No trained models in models/ — run `energy-forecast train` first.")
    return bundles


def predict_from_frame(cfg: Config, df: pd.DataFrame, day: date) -> pd.DataFrame:
    """Predict all 24 hours of local `day` from a dataset that covers the history before it."""
    tz, fc = cfg.tz, cfg["forecast"]
    clean, _ = clean_and_validate(df, price_col=cfg["targets"]["price"])
    X = build_features(clean, tz=tz, min_lag_actuals=fc["min_lag_actuals_h"], min_lag_prices=fc["min_lag_prices_h"])
    d0 = pd.Timestamp(day).tz_localize(tz)
    rows = X.loc[(X.index >= d0.tz_convert("UTC")) & (X.index < (d0 + pd.Timedelta(days=1)).tz_convert("UTC"))]
    if rows.empty:
        raise ValueError(f"No feature rows for {day} — is the dataset long enough?")

    out = pd.DataFrame(index=rows.index)
    for target, b in _load_bundles(cfg).items():
        Xt = rows.reindex(columns=b["features"])  # missing live columns -> NaN (tree models cope)
        lo = 0 if target.startswith("gen_") else None  # production cannot be negative
        out[f"{target}_pred"] = pd.Series(b["model"].predict(Xt), index=rows.index).clip(lower=lo)
        for q, qm in b.get("quantiles", {}).items():
            out[f"{target}_p{int(q * 100)}"] = pd.Series(qm.predict(Xt), index=rows.index).clip(lower=lo)
        if target in clean:
            out[f"{target}_actual"] = clean.loc[rows.index, target]  # filled if already published
    out.index = out.index.tz_convert(tz)
    out.index.name = "delivery_hour_local"
    return out


def predict_live(cfg: Config, day: date | None = None) -> pd.DataFrame:
    from energy_forecast.data.build_dataset import build_dataset

    tz = cfg.tz
    day = day or (pd.Timestamp.now(tz=tz) + pd.Timedelta(days=1)).date()
    d0 = pd.Timestamp(day).tz_localize(tz).tz_convert("UTC")
    df = build_dataset(cfg, start=d0 - pd.Timedelta(days=HISTORY_DAYS), end=d0 + pd.Timedelta(days=1),
                       weather_source="live", save=False)
    out = predict_from_frame(cfg, df, day)
    save_forecast(cfg, out, day)
    return out


def save_forecast(cfg: Config, out: pd.DataFrame, day: date) -> None:
    d = cfg.path("forecasts_dir")
    out.round(2).to_csv(d / f"forecast_{day}.csv")
    payload = {"delivery_day": str(day), "generated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
               "hours": json.loads(out.round(2).reset_index().to_json(orient="records", date_format="iso"))}
    (d / f"forecast_{day}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("Saved forecast for %s to %s", day, d)
