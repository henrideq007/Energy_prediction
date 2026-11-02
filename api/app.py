"""REST API serving the 24h forecast.

Run locally:   uvicorn api.app:app --reload
Then open:     http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
from fastapi import FastAPI, HTTPException

from energy_forecast.config import load_config

app = FastAPI(title="Belgian Electricity Forecast API", version="0.1.0",
              description="Day-ahead (24h) price and production forecasts for the BE bidding zone.")
cfg = load_config()


@app.get("/health")
def health() -> dict:
    models = [p.stem for p in cfg.path("models_dir").glob("*.joblib")]
    return {"status": "ok", "models_loaded": models}


@app.get("/models")
def models() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(cfg.path("models_dir").glob("*.json"))]


@app.get("/forecast")
def forecast(day: date | None = None, refresh: bool = False) -> dict:
    """Forecast for `day` (default tomorrow). Uses the cached file unless refresh=true."""
    day = day or (pd.Timestamp.now(tz=cfg.tz) + pd.Timedelta(days=1)).date()
    cached = cfg.path("forecasts_dir") / f"forecast_{day}.json"
    if cached.exists() and not refresh:
        return json.loads(cached.read_text(encoding="utf-8"))
    try:
        from energy_forecast.predict import predict_live

        predict_live(cfg, day)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Forecast failed: {exc}") from exc
    return json.loads(cached.read_text(encoding="utf-8"))
