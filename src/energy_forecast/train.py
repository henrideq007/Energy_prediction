"""Train the final models on all available history and save them to models/."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import joblib
import pandas as pd

from energy_forecast.config import Config
from energy_forecast.features import make_xy
from energy_forecast.models import get_model

log = logging.getLogger(__name__)


def pick_best(cfg: Config, target: str, default: str = "lightgbm") -> str:
    board_path = cfg.path("reports_dir") / "leaderboard.csv"
    if board_path.exists():
        board = pd.read_csv(board_path)
        g = board[board.target == target].sort_values("MAE")
        if not g.empty:
            return str(g.iloc[0]["model"])
    return default


def train_final(cfg: Config, df: pd.DataFrame, targets: list[str] | None = None,
                model_override: str | None = None) -> dict:
    fc = cfg["forecast"]
    out_dir = cfg.path("models_dir")
    targets = targets or [t for t in cfg.all_targets if t in df.columns]
    summary = {}
    for target in targets:
        X, y = make_xy(df, target, tz=cfg.tz, min_lag_actuals=fc["min_lag_actuals_h"], min_lag_prices=fc["min_lag_prices_h"])
        name = model_override or pick_best(cfg, target)
        model = get_model(name, target, X.columns, random_state=cfg["random_state"])
        model.fit(X, y)
        bundle = {"model": model, "features": list(X.columns), "target": target, "model_name": name}

        if target == cfg["targets"]["price"]:
            # Prediction interval: LightGBM quantile models (P10 / P90)
            bundle["quantiles"] = {}
            for q in cfg["models"]["quantiles"]:
                if q == 0.5:
                    continue
                qm = get_model("lightgbm", target, X.columns, random_state=cfg["random_state"], quantile=q)
                qm.fit(X, y)
                bundle["quantiles"][q] = qm

        joblib.dump(bundle, out_dir / f"{target}.joblib")
        meta = {"target": target, "model": name, "n_rows": len(X), "n_features": X.shape[1],
                "train_start": str(X.index.min()), "train_end": str(X.index.max()),
                "trained_utc": datetime.now(timezone.utc).isoformat()}
        (out_dir / f"{target}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        summary[target] = meta
        log.info("Trained %s with %s on %s rows", target, name, len(X))
    return summary
