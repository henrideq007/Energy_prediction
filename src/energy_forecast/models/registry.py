"""Model zoo. Every model follows the scikit-learn fit/predict API.

Baselines matter: a model is only interesting if it beats `seasonal_naive_week`
(and, for production targets, the TSO's own `tso_forecast`).
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

MODEL_DESCRIPTIONS = {
    "naive_day": "Baseline: value of the most recent valid lag (24h for prices, 48h for actuals).",
    "seasonal_naive_week": "Baseline: same hour one week earlier (lag 168h).",
    "tso_forecast": "Baseline (production only): the TSO's published day-ahead forecast.",
    "ridge": "Linear model with standardised features and CV-tuned L2 penalty (LEAR-style).",
    "random_forest": "Bagged decision trees; robust non-linear benchmark.",
    "lightgbm": "Gradient-boosted trees (LightGBM); usually the strongest tabular model.",
    "xgboost": "Gradient-boosted trees (XGBoost); alternative GBM implementation.",
}

TSO_COLUMN = {"gen_solar": "fc_solar", "gen_wind": "fc_wind", "gen_total": "fc_gen_total"}


class ColumnBaseline(BaseEstimator, RegressorMixin):
    """Predicts by copying one feature column (with a fallback column)."""

    def __init__(self, column: str | None = None, fallback: str | None = None):
        self.column = column
        self.fallback = fallback

    def fit(self, X: pd.DataFrame, y=None):
        self.mean_ = float(np.nanmean(y)) if y is not None else 0.0
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        out = pd.Series(np.nan, index=X.index)
        for c in (self.column, self.fallback):
            if c and c in X:
                out = out.fillna(X[c])
        return out.fillna(self.mean_).to_numpy()


def _smallest_lag_col(X_cols, target: str) -> str | None:
    lags = [(int(m.group(1)), c) for c in X_cols if (m := re.fullmatch(rf"{re.escape(target)}_lag(\d+)", c))]
    return min(lags)[1] if lags else None


def get_model(name: str, target: str, X_cols, random_state: int = 42, quantile: float | None = None):
    week = f"{target}_lag168"
    if name == "naive_day":
        return ColumnBaseline(_smallest_lag_col(X_cols, target), week)
    if name == "seasonal_naive_week":
        return ColumnBaseline(week, _smallest_lag_col(X_cols, target))
    if name == "tso_forecast":
        return ColumnBaseline(TSO_COLUMN.get(target), week)
    if name == "ridge":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             RidgeCV(alphas=np.logspace(-2, 3, 12)))
    if name == "random_forest":
        return make_pipeline(SimpleImputer(strategy="median"),
                             # max_samples bootstraps 30% of rows per tree: ~3x faster, similar accuracy
                             RandomForestRegressor(n_estimators=150, min_samples_leaf=5, max_features=0.33,
                                                   max_samples=0.3, n_jobs=-1, random_state=random_state))
    if name == "lightgbm":
        import lightgbm as lgb

        params = dict(n_estimators=800, learning_rate=0.03, num_leaves=63, min_child_samples=30,
                      subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                      random_state=random_state, verbose=-1)
        if quantile is not None:
            params.update(objective="quantile", alpha=quantile)
        return lgb.LGBMRegressor(**params)
    if name == "xgboost":
        import xgboost as xgb

        return xgb.XGBRegressor(n_estimators=800, learning_rate=0.03, max_depth=7, subsample=0.8,
                                colsample_bytree=0.8, min_child_weight=5, tree_method="hist",
                                random_state=random_state, n_jobs=-1)
    raise ValueError(f"Unknown model '{name}'. Options: {list(MODEL_DESCRIPTIONS)}")
