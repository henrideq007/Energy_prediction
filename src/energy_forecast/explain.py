"""Explainability: which drivers move the Belgian price? (SHAP on the LightGBM model)."""

from __future__ import annotations

import logging

import pandas as pd

from energy_forecast.config import Config
from energy_forecast.features import make_xy
from energy_forecast.models import get_model

log = logging.getLogger(__name__)


def explain(cfg: Config, df: pd.DataFrame, target: str | None = None, sample: int = 3000) -> pd.DataFrame:
    target = target or cfg["targets"]["price"]
    fc = cfg["forecast"]
    X, y = make_xy(df, target, tz=cfg.tz, min_lag_actuals=fc["min_lag_actuals_h"], min_lag_prices=fc["min_lag_prices_h"])
    test_start = pd.Timestamp(cfg["split"]["test_start"], tz="UTC")
    tr, te = X.index < test_start, X.index >= test_start
    model = get_model("lightgbm", target, X.columns, random_state=cfg["random_state"])
    model.fit(X[tr], y[tr])
    Xte = X[te].sample(min(sample, int(te.sum())), random_state=cfg["random_state"])
    reports = cfg.path("reports_dir")
    try:
        import shap

        sv = shap.TreeExplainer(model).shap_values(Xte)
        imp = pd.Series(abs(sv).mean(axis=0), index=X.columns, name="mean_abs_shap")
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            shap.summary_plot(sv, Xte, show=False, max_display=20)
            plt.tight_layout()
            plt.savefig(reports / f"shap_{target}.png", dpi=110)
            plt.close()
        except Exception as exc:  # plotting is a nice-to-have
            log.warning("SHAP plot failed: %s", exc)
    except ImportError:
        log.warning("shap not installed -> using LightGBM gain importance")
        imp = pd.Series(model.booster_.feature_importance("gain"), index=X.columns, name="gain")
    imp = imp.sort_values(ascending=False)
    imp.to_csv(reports / f"feature_importance_{target}.csv")
    return imp
