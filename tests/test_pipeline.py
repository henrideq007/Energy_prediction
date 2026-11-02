import numpy as np
import pandas as pd
import pytest

from energy_forecast.data.synthetic import make_synthetic
from energy_forecast.features import build_features, leakage_check, make_xy
from energy_forecast.metrics import all_metrics, direction_accuracy
from energy_forecast.models import get_model
from energy_forecast.split import train_val_test, walk_forward
from energy_forecast.validation import clean_and_validate


@pytest.fixture(scope="module")
def df():
    return make_synthetic("2024-01-01", "2024-09-01")


def test_validation_fills_short_gaps_and_keeps_spikes(df):
    dirty = df.copy()
    dirty.iloc[100, dirty.columns.get_loc("price_da")] = 9999  # impossible -> removed
    dirty = dirty.drop(dirty.index[200:202])                    # missing timestamps -> re-indexed
    clean, rep = clean_and_validate(dirty)
    assert rep.missing_timestamps == 2
    assert rep.out_of_bounds["price_da"] == 1
    assert clean.index.is_monotonic_increasing and clean.index.is_unique
    assert len(clean) == len(df)
    assert "flag_price_spike" in clean


def test_no_same_time_actuals_in_features(df):
    X = build_features(df)
    assert leakage_check(X) == []
    assert "price_da_lag24" in X and "gen_solar_lag48" in X
    assert "gen_solar_lag24" not in X  # actuals of D-1 afternoon are unknown at issue time


def test_lag_alignment(df):
    X = build_features(df)
    t = df.index[500]
    assert X.loc[t, "price_da_lag24"] == pytest.approx(df["price_da"].iloc[476])
    assert X.loc[t, "load_actual_lag48"] == pytest.approx(df["load_actual"].iloc[452], nan_ok=True)


def test_daily_stats_use_previous_day_only(df):
    X = build_features(df)
    loc = df.index.tz_convert("Europe/Brussels")
    day = pd.Timestamp("2024-03-10")
    prev = df["price_da"][loc.normalize().tz_localize(None) == day - pd.Timedelta(days=1)]
    row = X[loc.normalize().tz_localize(None) == day].iloc[5]
    assert row["price_da_d1_mean"] == pytest.approx(prev.mean())


def test_walk_forward_is_chronological(df):
    folds = list(walk_forward(df.index, "2024-06", 3))
    assert [f.name for f in folds] == ["2024-06", "2024-07", "2024-08"]
    for f in folds:
        assert f.train_idx.max() < f.test_idx.min()
    s = train_val_test(df.index, "2024-05-01", "2024-07-01")
    assert s["train"].max() < s["val"].min() < s["test"].min()


@pytest.mark.parametrize("name", ["naive_day", "seasonal_naive_week", "tso_forecast", "ridge", "lightgbm"])
def test_models_fit_predict(df, name):
    X, y = make_xy(df, "gen_solar")
    cut = int(len(X) * 0.8)
    m = get_model(name, "gen_solar", X.columns)
    m.fit(X.iloc[:cut], y.iloc[:cut])
    p = m.predict(X.iloc[cut:])
    assert len(p) == len(X) - cut and np.isfinite(p).all()


def test_metrics():
    idx = pd.date_range("2024-01-01", periods=48, freq="h", tz="UTC")
    y = pd.Series(np.sin(np.arange(48) / 4) * 50 + 80, index=idx)
    m = all_metrics(y, y, y.shift(24))
    assert m["MAE"] == 0 and m["rMAE"] == 0 and m["PeakHit"] == 1
    assert direction_accuracy(y, -y) == 0
