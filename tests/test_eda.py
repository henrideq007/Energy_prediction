"""Unit tests for the EDA helpers (synthetic frames, no network)."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
import pytest

from energy_forecast import eda

TZ = "Europe/Brussels"


def _frame(start: str = "2021-06-29", hours: int = 24 * 6) -> pd.DataFrame:
    idx = pd.date_range(start, periods=hours, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    load = 9000 + 1000 * np.sin(np.arange(hours) / 24 * 2 * np.pi)
    wind = rng.uniform(0, 3000, hours)
    solar = rng.uniform(0, 3000, hours)
    price = 0.02 * (load - wind - solar) + rng.normal(0, 1, hours)
    df = pd.DataFrame({
        "price_da": price, "load_forecast": load,
        "elia_wind_dayahead11hforecast": wind, "elia_solar_dayahead11hforecast": solar,
        "fc_wind": wind, "fc_solar": solar, "flag_price_spike": 0,
    }, index=idx)
    return eda.to_local(df, TZ)


def test_to_local_requires_tz_aware_index():
    df = pd.DataFrame({"x": [1.0]}, index=pd.DatetimeIndex(["2024-01-01"]))
    with pytest.raises(ValueError):
        eda.to_local(df, TZ)
    out = eda.to_local(df.tz_localize("UTC"), TZ)
    assert str(out.index.tz) == TZ and out.index[0].hour == 1


def test_label_regime_boundaries_are_local_and_inclusive():
    idx = pd.DatetimeIndex(["2019-01-01 00:00", "2021-06-30 23:00", "2021-07-01 00:00",
                            "2023-07-01 00:00", "2018-12-31 23:00"]).tz_localize(TZ)
    lab = eda.label_regime(idx)
    assert list(lab.astype(object)[:4]) == ["pre_crisis", "pre_crisis", "crisis", "post_crisis"]
    assert pd.isna(lab.iloc[4])
    assert list(lab.cat.categories) == eda.REGIME_ORDER


def test_calendar_frame_season_and_daytype():
    idx = pd.DatetimeIndex(["2024-01-06 10:00", "2024-07-08 10:00"]).tz_localize(TZ)  # Sat, Mon
    cal = eda.calendar_frame(idx)
    assert list(cal["season"].astype(str)) == ["winter", "summer"]
    assert list(cal["daytype"]) == ["weekend", "weekday"]


def test_regime_summary_stats_and_shares():
    idx = pd.date_range("2021-06-30", periods=48, freq="h", tz=TZ)
    p = np.r_[np.full(24, 10.0), np.r_[np.full(12, -5.0), np.full(12, 100.0)]]
    df = pd.DataFrame({"price_da": p, "flag_price_spike": np.r_[np.zeros(36), np.ones(12)]},
                      index=idx)
    s = eda.regime_summary(df)
    assert s.loc["pre_crisis", "mean"] == 10.0 and s.loc["pre_crisis", "negative_share_pct"] == 0
    assert s.loc["crisis", "negative_share_pct"] == pytest.approx(50.0)
    assert s.loc["crisis", "spike_share_pct"] == pytest.approx(50.0)
    assert s.loc["crisis", "hours"] == 24
    assert "post_crisis" not in s.index


def test_regime_summary_without_spike_flag():
    df = _frame().drop(columns="flag_price_spike")
    assert eda.regime_summary(df)["spike_share_pct"].isna().all()


def test_hourly_profile_shape_and_values():
    idx = pd.date_range("2024-01-01", periods=24 * 14, freq="h", tz=TZ)
    df = pd.DataFrame({"price_da": idx.hour.astype(float)}, index=idx)
    prof = eda.hourly_profile(df, by=("regime", "daytype"))
    assert prof.shape == (24, 2)
    assert (prof[("post_crisis", "weekday")].values == np.arange(24)).all()
    shape = eda.profile_shape(prof)
    assert (shape["peak_hour"] == 23).all() and (shape["spread"] == 23).all()


def test_negative_counts_and_heatmap():
    idx = pd.date_range("2024-05-01", periods=48, freq="h", tz=TZ)
    p = np.where(idx.hour == 13, -10.0, 50.0)
    p[0] = np.nan
    df = pd.DataFrame({"price_da": p}, index=idx)
    assert eda.negative_counts(df, "hour").loc[13] == 2
    assert eda.negative_counts(df, "year").loc[2024] == 2
    heat = eda.negative_heatmap(df)
    assert heat.loc[13, 5] == pytest.approx(100.0) and heat.loc[12, 5] == 0
    assert heat.loc[0, 5] == 0  # one NaN hour ignored, the other one is positive


def test_negative_share_by_bins():
    idx = pd.date_range("2024-05-01", periods=4, freq="h", tz=TZ)
    df = pd.DataFrame({"price_da": [-1.0, 5.0, -2.0, -3.0]}, index=idx)
    drv = pd.Series([100.0, 200.0, 5000.0, 6000.0], index=idx)
    out = eda.negative_share_by_bins(df, drv, [0, 1000, 10000])
    assert list(out["hours"]) == [2, 2]
    assert list(out["negative_share_pct"]) == [50.0, 100.0]


def test_residual_load_prefers_elia_11h_and_flags_fallback():
    df = _frame()
    df["fc_solar"] = df["elia_solar_dayahead11hforecast"] + 111
    df.iloc[:5, df.columns.get_loc("elia_solar_dayahead11hforecast")] = np.nan
    rl, src = eda.residual_load(df)
    exp = df["load_forecast"] - df["elia_wind_dayahead11hforecast"] - df["fc_solar"]
    assert np.allclose(rl.iloc[:5], exp.iloc[:5])
    exp11 = (df["load_forecast"] - df["elia_wind_dayahead11hforecast"]
             - df["elia_solar_dayahead11hforecast"])
    assert np.allclose(rl.iloc[5:], exp11.iloc[5:])
    assert (src.iloc[:5] == "fc_fallback").all() and (src.iloc[5:] == "elia_11h").all()


def test_residual_load_needs_load_forecast():
    with pytest.raises(KeyError):
        eda.residual_load(_frame().drop(columns="load_forecast"))


def test_merit_order_slope_recovers_linear_relation():
    idx = pd.date_range("2024-01-01", periods=200, freq="h", tz=TZ)
    rl = pd.Series(np.linspace(2000, 12000, 200), index=idx)
    price = 10.0 + 15.0 * rl / 1000
    groups = pd.Series(np.where(np.arange(200) < 100, "a", "b"), index=idx)
    out = eda.merit_order_slope(price, rl, groups)
    assert out.loc["a", "slope_eur_per_gw"] == pytest.approx(15.0)
    assert out.loc["b", "intercept"] == pytest.approx(10.0)
    assert out.loc["a", "r2"] == pytest.approx(1.0)


def test_merit_order_bins_drops_sparse_bins():
    idx = pd.date_range("2024-01-01", periods=120, freq="h", tz=TZ)
    rl = pd.Series(np.r_[np.full(100, 5500.0), np.full(20, 8500.0)], index=idx)
    price = pd.Series(np.r_[np.full(100, 40.0), np.full(20, 90.0)], index=idx)
    out = eda.merit_order_bins(price, rl, min_count=50)
    assert len(out) == 1
    assert out["median"].iloc[0] == 40.0 and out["hours"].iloc[0] == 100


def test_core_driver_columns_excludes_candidates_and_other_elia_runs():
    cols = ["price_da", "price_da_FR", "load_forecast", "nb_FR_load_fc", "unav_BE_nuclear_mw",
            "xch_BE_net_position", "fb_BE_min_np", "cap_BE_solar", "hydro_res_FR_mwh",
            "wfr_paris_temperature_2m", "cmd_coal_api2", "flag_price_spike",
            "elia_wind_dayahead11hforecast", "elia_wind_dayaheadforecast", "fc_wind", "ttf_gas"]
    assert eda.core_driver_columns(cols) == ["price_da_FR", "load_forecast",
                                             "elia_wind_dayahead11hforecast", "fc_wind", "ttf_gas"]


def test_driver_availability_marks_fc_as_baseline_only():
    assert eda.driver_availability("fc_solar").startswith("baseline-only")
    assert eda.driver_availability("gen_wind") == "lag >= 48h"
    assert eda.driver_availability("price_da_NL") == "lag >= 24h"
    assert eda.driver_availability("elia_solar_dayahead11hforecast") == "same-time"


def test_price_correlations_sorted_and_labelled():
    df = _frame()
    df["noise"] = np.random.default_rng(1).normal(size=len(df))
    out = eda.price_correlations(df)
    assert "flag_price_spike" not in out.index and "price_da" not in out.index
    assert out["pearson"].abs().is_monotonic_decreasing
    assert {"spearman", "availability"}.issubset(out.columns)
    assert out.loc["load_forecast", "pearson"] > 0


def test_to_markdown_table():
    t = pd.DataFrame({"a": [1.234, np.nan], "b": ["x", "y"]}, index=pd.Index([1, 2], name="k"))
    md = eda.to_markdown_table(t, floatfmt=".2f").splitlines()
    assert md[0] == "| k | a | b |"
    assert md[2] == "| 1 | 1.23 | x |" and md[3] == "| 2 |  | y |"


def test_plots_return_figures():
    import matplotlib.pyplot as plt

    df = _frame(hours=24 * 21)
    figs = [eda.plot_weekly_price(df),
            eda.plot_profiles(eda.hourly_profile(df, by=("regime", "season")), "t"),
            eda.plot_heatmap(eda.negative_heatmap(df), "t", "%")]
    rl, _ = eda.residual_load(df)
    figs.append(eda.plot_merit_order(eda.merit_order_bins(df["price_da"], rl, min_count=1), "t"))
    for f in figs:
        assert f.axes
        plt.close(f)


def test_yearly_summary_counts_and_stats():
    idx = pd.date_range("2023-12-31 22:00", periods=4, freq="h", tz=TZ)  # 2 h in 2023, 2 h in 2024
    df = pd.DataFrame({"price_da": [10.0, -5.0, 20.0, np.nan]}, index=idx)
    y = eda.yearly_summary(df)
    assert list(y.index) == [2023, 2024]
    assert y.loc[2023, "hours"] == 2 and y.loc[2023, "negative_hours"] == 1
    assert y.loc[2023, "mean"] == 2.5 and y.loc[2023, "min"] == -5.0
    assert y.loc[2024, "hours"] == 1 and y.loc[2024, "max"] == 20.0


@pytest.mark.parametrize("day, n_hours", [("2024-03-31", 23), ("2024-10-27", 25)])
def test_dst_days_keep_local_hours(day, n_hours):
    # UTC grid converted to local time: the spring day has no 02:00, the autumn day has two.
    start = pd.Timestamp(day, tz=TZ).tz_convert("UTC")
    idx = pd.date_range(start, periods=n_hours, freq="h", tz="UTC")
    df = eda.to_local(pd.DataFrame({"price_da": 1.0}, index=idx), TZ)
    assert (df.index.date == pd.Timestamp(day).date()).all()
    hours = pd.Series(df.index.hour)
    if n_hours == 23:
        assert 2 not in set(hours)
    else:
        assert (hours == 2).sum() == 2
    assert eda.label_regime(df.index).eq("post_crisis").all()
    prof = eda.hourly_profile(df, by=("regime",))
    assert len(prof) == (23 if n_hours == 23 else 24)
    assert (prof.iloc[:, 0] == 1.0).all()


def test_label_regime_boundary_in_utc_is_local_midnight():
    # 2021-06-30 22:00 UTC = 2021-07-01 00:00 Brussels (CEST) -> already "crisis"
    idx = pd.DatetimeIndex(["2021-06-30 21:00", "2021-06-30 22:00"]).tz_localize("UTC").tz_convert(TZ)
    assert list(eda.label_regime(idx).astype(str)) == ["pre_crisis", "crisis"]


def test_trim_to_valid_drops_edge_nans_only():
    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz=TZ)
    df = pd.DataFrame({"price_da": [np.nan, 1.0, np.nan, 2.0, np.nan], "gas": 1.0}, index=idx)
    out = eda.trim_to_valid(df)
    assert list(out.index) == list(idx[1:4])
    assert eda.trim_to_valid(df.assign(price_da=np.nan)).empty


def test_gas_price_correlation_daily_excludes_proxy_hours():
    idx = pd.date_range("2023-07-01", periods=24 * 10, freq="h", tz=TZ)
    day = np.arange(len(idx)) // 24
    gas = day.astype(float)
    price = 2.0 * gas + 5.0
    flag = (day < 5).astype(float)
    price[day < 5] = -price[day < 5]          # anti-correlated proxy days would spoil the corr
    df = pd.DataFrame({"price_da": price, "ttf_gas": gas, "flag_gas_monthly_proxy": flag}, index=idx)
    out = eda.gas_price_correlation_daily(df)
    assert out.loc["all", "days"] == 5 and out.loc["all", "pearson"] == pytest.approx(1.0)
    assert out.loc["post_crisis", "start"] == pd.Timestamp("2023-07-06").date()
    assert "crisis" not in out.index


def test_bins_log_values_outside_edges(caplog):
    idx = pd.date_range("2024-05-01", periods=3, freq="h", tz=TZ)
    df = pd.DataFrame({"price_da": [1.0, 2.0, 3.0]}, index=idx)
    with caplog.at_level("INFO", logger="energy_forecast.eda"):
        eda.negative_share_by_bins(df, pd.Series([5.0, 50.0, 500.0], index=idx), [0, 100])
    assert "1 values outside bin edges" in caplog.text
