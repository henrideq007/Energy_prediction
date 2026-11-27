"""T45 — candidate feature families with publication lags (offline, synthetic frames)."""

import re

import numpy as np
import pandas as pd
import pytest

from energy_forecast.config import load_config
from energy_forecast.data.commodities import _daily_to_hourly
from energy_forecast.features import (
    CANDIDATE_MIN_LAG_H,
    CANDIDATE_PREFIXES,
    KNOWN_AHEAD_COLUMNS,
    build_features,
    candidate_features,
    candidate_min_lag_h,
    hydro_min_safe_lag_h,
    issue_time,
    leakage_check,
    make_xy,
    source_before_delivery_day,
)

TZ = "Europe/Brussels"
POLICY = load_config()["candidate_features"]
FAMILIES = list(POLICY)


def _frame(days: int = 20, start: str = "2021-12-20") -> pd.DataFrame:
    idx = pd.date_range(start, periods=24 * days, freq="h", tz="UTC")
    n = len(idx)
    ramp = np.arange(n, dtype=float)
    cols = ["xch_BE_FR_net_export", "xch_BE_net_position", "nb_FR_load_actual", "nb_FR_gen_nuclear",
            "nb_NL_load_fc", "nb_DE_LU_fc_wind", "fb_BE_min_np", "fb_BE_max_np", "unav_FR_nuclear_mw",
            "cap_BE_solar", "hydro_res_FR_mwh", "wfr_paris_temperature_2m", "elia_wind_weekaheadforecast",
            "elia_wind_dayaheadforecast", "elia_solar_measured", "cmd_coal_api2", "cmd_gas_storage_eu_pct",
            "flag_gas_monthly_proxy"]
    df = pd.DataFrame({c: ramp + 1000 * i for i, c in enumerate(cols)}, index=idx)
    df["price_da"] = 50 + np.sin(ramp / 24)
    df["load_forecast"] = 10000.0
    df["gen_nuclear"] = 4000 + ramp
    df["cap_BE_nuclear"] = 5943.0
    df["unav_BE_nuclear_mw"] = np.where(idx < pd.Timestamp("2022-01-01", tz=TZ), 0.0, 500.0)
    return df


def test_policy_lags_respect_the_safety_floor_and_have_expected_values():
    lags = {fam: [tuple(r["lags_h"]) for r in spec["rules"]] for fam, spec in POLICY.items()}
    assert lags["xch"] == [(48, 168)] and lags["nb_actual"] == [(48, 168)]
    assert lags["nb_fc"] == [(24, 168)] and lags["fb"] == [(24, 168)]
    assert lags["unav"] == [(0,)] and lags["cap"] == [(0,)] and lags["wfr"] == [(0,)]
    assert lags["cmd"] == [(0,), (48,)]                       # coal same-time, AGSI gas storage lag 48
    assert lags["elia_other"] == [(24,), (24,), (48, 168)]    # week-ahead same-time pending T53
    assert lags["hydro_res"] == [(336,)]
    # Building every family on a frame with every column type must not raise (lags >= floors)
    candidate_features(_frame(), FAMILIES, POLICY, TZ)


@pytest.mark.parametrize("col,lag", [
    ("xch_BE_FR_net_export", 48), ("xch_BE_net_position", 168), ("nb_FR_load_actual", 48),
    ("nb_FR_gen_nuclear", 168), ("nb_NL_load_fc", 24), ("nb_DE_LU_fc_wind", 168), ("fb_BE_min_np", 24),
    ("hydro_res_FR_mwh", 336), ("elia_wind_dayaheadforecast", 24), ("elia_solar_measured", 48),
    ("elia_wind_weekaheadforecast", 24), ("cmd_gas_storage_eu_pct", 48),
])
def test_lagged_value_at_t_equals_source_at_t_minus_h(col, lag):
    df = _frame()
    out = candidate_features(df, FAMILIES, POLICY, TZ)
    name = f"{col}_lag{lag}"
    assert name in out
    assert out[name].iloc[:lag].isna().all()
    np.testing.assert_array_equal(out[name].iloc[lag:].to_numpy(), df[col].iloc[:-lag].to_numpy())
    assert col not in out  # never the unlagged value


@pytest.mark.parametrize("col", ["unav_FR_nuclear_mw", "cap_BE_solar", "wfr_paris_temperature_2m",
                                 "cmd_coal_api2"])
def test_same_time_families_keep_the_raw_value(col):
    df = _frame()
    out = candidate_features(df, FAMILIES, POLICY, TZ)
    pd.testing.assert_series_equal(out[col], df[col])
    assert not [c for c in out if c.startswith(col + "_lag")]


def test_flag_columns_never_produced():
    out = candidate_features(_frame(), FAMILIES, POLICY, TZ)
    assert not [c for c in out if c.startswith(("flag_", "fc_"))]


def test_unav_be_masked_before_valid_from_and_proxy_built():
    df = _frame()
    out = candidate_features(df, ["unav"], POLICY, TZ)
    boundary = pd.Timestamp(POLICY["unav"]["valid_from"]["unav_BE_nuclear_mw"], tz=TZ)
    be = out["unav_BE_nuclear_mw"]
    assert be[be.index < boundary].isna().all()          # 0 before 2022 = "unknown" -> NaN
    assert be[be.index >= boundary].eq(500.0).all()
    assert out["unav_FR_nuclear_mw"].notna().all()         # FR has full history: never masked
    proxy = out["nuc_BE_gap_proxy_lag48"]
    expected = df["cap_BE_nuclear"] - df["gen_nuclear"].shift(48)
    pd.testing.assert_series_equal(proxy, expected, check_names=False)
    assert proxy.iloc[48:].notna().all()                   # available before 2022 too
    assert leakage_check(out) == []


def test_proxy_skipped_when_inputs_missing():
    out = candidate_features(_frame().drop(columns=["gen_nuclear"]), ["unav"], POLICY, TZ)
    assert "nuc_BE_gap_proxy_lag48" not in out


def test_hydro_floor_derivation():
    # stamp Monday 00:00 (up to 1 h early) + publication by end of Thursday after the week (11 days) + 37 h
    assert hydro_min_safe_lag_h() == 264 + 1 + 37 == 302
    assert candidate_min_lag_h("hydro_res_FR_mwh") == 302
    assert POLICY["hydro_res"]["rules"][0]["lags_h"][0] >= 302


def _weekly_hydro(index: pd.DatetimeIndex, offset_h: int) -> tuple[pd.Series, pd.Series]:
    """Week value = id of week W, stamped Monday 00:00 local + offset_h (observed: -1 = Sunday 23:00, 0, +1);
    publication = end of the Thursday after W = Monday 00:00 of W + 11 days."""
    first = (index.min().tz_convert(TZ) - pd.Timedelta(days=14)).tz_localize(None).normalize()
    mondays = pd.date_range(first, index.max().tz_convert(TZ).tz_localize(None), freq="W-MON").tz_localize(TZ)
    stamps = mondays + pd.Timedelta(hours=offset_h)
    week_id = pd.Series(np.arange(len(mondays), dtype=float), index=stamps.tz_convert("UTC"))
    published = pd.Series([(m.tz_localize(None) + pd.Timedelta(days=11)) for m in mondays]).dt.tz_localize(TZ)
    published.index = week_id.to_numpy()
    hourly = week_id.reindex(week_id.index.union(index)).ffill().reindex(index)
    return hourly, published


def _hydro_violations(lag_h: int, offset_h: int) -> int:
    # 2 years -> covers both DST transitions twice
    idx = pd.date_range("2024-01-01", "2026-01-01", freq="h", tz="UTC", inclusive="left")
    hourly, published = _weekly_hydro(idx, offset_h)
    if lag_h >= hydro_min_safe_lag_h():   # through the real builder
        rule = {"hydro_res": {"rules": [{"pattern": "^hydro_res_", "lags_h": [lag_h]}]}}
        used = candidate_features(pd.DataFrame({"hydro_res_FR_mwh": hourly}), ["hydro_res"], rule, TZ).iloc[:, 0]
    else:                                 # the builder refuses such a lag: simulate it directly
        used = hourly.shift(lag_h)
    used = used.dropna()
    pub = pd.DatetimeIndex(published.loc[used.to_numpy()].to_numpy()).tz_convert("UTC")
    return int((pub > issue_time(used.index, TZ, 11)).sum())


@pytest.mark.parametrize("offset_h", [-1, 0, 1])   # Sunday 23:00, Monday 00:00, Monday 01:00 local
def test_hydro_value_used_was_published_before_every_issue_time(offset_h):
    assert _hydro_violations(POLICY["hydro_res"]["rules"][0]["lags_h"][0], offset_h) == 0
    assert _hydro_violations(hydro_min_safe_lag_h(), offset_h) == 0


def test_hydro_floor_is_needed():
    # A shorter lag would use week values before their (assumed) publication -> the floor is not arbitrary
    assert _hydro_violations(hydro_min_safe_lag_h() - 24, offset_h=-1) > 0
    # earliest observed stamp (Sunday 23:00): exact minimum 290 h <= the generic 302 h floor
    assert _hydro_violations(289, offset_h=-1) > 0 and _hydro_violations(290, offset_h=-1) == 0
    with pytest.raises(ValueError, match="safety floor"):
        candidate_features(_frame(), ["hydro_res"], {"hydro_res": {"rules": [
            {"pattern": "^hydro_res_", "lags_h": [168]}]}}, TZ)


def test_issue_time_is_d_minus_1_11h_local():
    idx = pd.DatetimeIndex([pd.Timestamp("2026-03-29 00:00", tz=TZ), pd.Timestamp("2026-10-25 23:00", tz=TZ)])
    out = issue_time(idx.tz_convert("UTC"), TZ, 11).tz_convert(TZ)
    assert list(out) == [pd.Timestamp("2026-03-28 11:00", tz=TZ), pd.Timestamp("2026-10-24 11:00", tz=TZ)]


def test_default_build_features_unchanged():
    df = _frame()
    base = build_features(df)
    for opt in (None, []):
        pd.testing.assert_frame_equal(build_features(df, candidate_families=opt), base)
    assert not [c for c in base if c.startswith(("nb_", "unav_", "xch_", "fb_", "cap_", "hydro_", "wfr_",
                                                  "cmd_", "nuc_", "flag_"))]
    with_cand = build_features(df, candidate_families=["xch", "unav"], candidate_policy=POLICY)
    pd.testing.assert_frame_equal(with_cand[base.columns], base)
    assert {"xch_BE_net_position_lag48", "unav_FR_nuclear_mw", "nuc_BE_gap_proxy_lag48"} <= set(with_cand)
    assert leakage_check(with_cand) == []
    X, _ = make_xy(df, "price_da", candidate_families=["cap"], candidate_policy=POLICY)
    assert "cap_BE_solar" in X


def test_default_policy_loaded_from_config_when_none():
    X = build_features(_frame(), candidate_families=["wfr"])
    assert "wfr_paris_temperature_2m" in X


def test_unknown_family_raises():
    with pytest.raises(ValueError, match="Unknown candidate family"):
        candidate_features(_frame(), ["xch", "nope"], POLICY, TZ)


def test_missing_columns_are_skipped():
    out = candidate_features(_frame()[["price_da"]], FAMILIES, POLICY, TZ)
    assert out.empty and len(out.index) == 24 * 20


def test_rule_matching_an_unguarded_column_raises():
    with pytest.raises(ValueError, match="safety floor"):
        candidate_features(_frame(), ["x"], {"x": {"rules": [{"pattern": "^flag_", "lags_h": [0]}]}}, TZ)


@pytest.mark.parametrize("col", ["xch_BE_net_position", "xch_BE_FR_net_export_lag24", "nb_FR_load_actual_lag24",
                                 "nb_FR_gen_nuclear", "nb_NL_load_fc", "fb_BE_min_np", "elia_wind_measured",
                                 "elia_wind_dayaheadforecast", "hydro_res_FR_mwh", "hydro_res_CH_mwh_lag168",
                                 "nuc_BE_gap_proxy_lag24", "nb_FR_mystery_series", "elia_wind_otherrun",
                                 "elia_wind_weekaheadforecast", "cmd_gas_storage_eu_pct",
                                 "cmd_gas_storage_eu_pct_lag24"])
def test_leakage_check_flags_candidates_without_their_lag(col):
    assert leakage_check(pd.DataFrame(columns=["hour", col])) == [col]


@pytest.mark.parametrize("col", ["unav_FR_nuclear_mw", "unav_BE_nuclear_mw", "cap_BE_solar",
                                 "wfr_paris_temperature_2m", "elia_wind_weekaheadforecast_lag24", "cmd_coal_api2",
                                 "cmd_gas_storage_eu_pct_lag48",
                                 "xch_BE_net_position_lag48", "nb_FR_load_actual_lag168", "nb_NL_load_fc_lag24",
                                 "fb_BE_max_np_lag24", "elia_wind_dayaheadforecast_lag24",
                                 "elia_solar_measured_lag48", "hydro_res_FR_mwh_lag336", "nuc_BE_gap_proxy_lag48",
                                 "elia_wind_dayahead11hforecast", "elia_solar_dayahead11h_p10"])
def test_leakage_check_accepts_properly_lagged_candidates(col):
    assert leakage_check(pd.DataFrame(columns=["hour", col])) == []


# Column names of the real dataset (Nov 2026) + AGSI gas storage (present only with AGSI_API_KEY)
REAL_CANDIDATE_COLUMNS = (
    [f"wfr_{c}_temperature_2m" for c in ("paris", "lyon", "lille", "toulouse", "marseille")]
    + [f"nb_{z}_{s}" for z in ("FR", "NL", "DE_LU") for s in ("load_fc", "load_actual", "fc_solar", "fc_wind",
                                                               "fc_gen_total")]
    + ["nb_FR_gen_nuclear"]
    + [f"xch_BE_{b}_net_export" for b in ("FR", "NL", "DE_LU", "GB")] + ["xch_BE_net_position"]
    + [f"cap_BE_{t}" for t in ("biomass", "energy_storage", "fossil_gas", "fossil_oil", "hydro_pumped_storage",
                               "hydro_run_of_river_and_pondage", "nuclear", "other", "solar", "waste",
                               "wind_offshore", "wind_onshore")]
    + ["hydro_res_FR_mwh", "hydro_res_CH_mwh", "unav_BE_nuclear_mw", "unav_FR_nuclear_mw",
       "cmd_coal_api2", "cmd_gas_storage_eu_pct", "fb_BE_min_np", "fb_BE_max_np"]
    + [f"elia_{t}_{r}" for t in ("wind", "solar") for r in ("measured", "weekaheadforecast", "dayahead11hforecast",
                                                            "dayaheadforecast")]
    + ["elia_solar_dayahead11h_p10", "elia_solar_dayahead11h_p90"]
)


def test_every_config_rule_is_guarded_by_a_floor_and_respects_it():
    covered = set()
    for fam, spec in POLICY.items():
        for rule in spec["rules"]:
            matched = [c for c in REAL_CANDIDATE_COLUMNS if re.search(rule["pattern"], c)]
            assert matched, f"{fam}: pattern {rule['pattern']} matches no known column"
            for c in matched:
                floor = candidate_min_lag_h(c)
                assert floor is not None, f"{fam}: {c} has no floor rule in CANDIDATE_MIN_LAG_H"
                assert min(rule["lags_h"]) >= floor, f"{fam}: {c} lag {rule['lags_h']} < floor {floor}"
                assert c not in KNOWN_AHEAD_COLUMNS
            covered |= set(matched)
    # conversely, every candidate column of the real dataset belongs to a family (except the Elia 11AM run)
    expected = {c for c in REAL_CANDIDATE_COLUMNS if c.startswith(CANDIDATE_PREFIXES) and c not in KNOWN_AHEAD_COLUMNS}
    assert covered == expected
    assert all(floor >= 0 for _, floor in CANDIDATE_MIN_LAG_H)


def _dst_year_frame() -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", "2026-01-01", freq="h", tz="UTC", inclusive="left")  # both DST switches
    cols = [c for c in REAL_CANDIDATE_COLUMNS if not c.startswith("elia_solar_dayahead11h")]
    return pd.DataFrame({c: np.arange(len(idx), dtype=float) for c in cols}, index=idx)


def test_lagged_candidates_never_use_a_source_hour_on_the_delivery_day():
    df = _dst_year_frame()
    out = candidate_features(df, FAMILIES, POLICY, TZ)
    lagged = [c for c in out if re.search(r"_lag\d+$", c) and not c.startswith("nuc_")]
    assert lagged
    deliv = df.index.tz_convert(TZ).tz_localize(None).normalize()
    for c in lagged:
        h = int(c.rsplit("_lag", 1)[1])
        s = out[c]
        ok = s.notna().to_numpy()
        src = (df.index - pd.Timedelta(hours=h)).tz_convert(TZ).tz_localize(None).normalize()
        assert (src[ok] <= deliv[ok] - pd.Timedelta(days=1)).all(), c          # source date <= D-1
        np.testing.assert_array_equal(s.to_numpy()[ok], np.arange(len(df))[ok] - h)  # value = source at t-h
        masked = np.flatnonzero(~ok)
        if h >= 48:
            assert (masked < h).all(), c                                       # only the series start
        else:
            extra = df.index[masked[masked >= h]].tz_convert(TZ)
            # the only DST leak: 23:00 of the 25-h autumn day (2025-10-26) -> 00:00 of the same day
            assert list(extra) == [pd.Timestamp("2025-10-26 23:00", tz=TZ)], (c, list(extra))


def test_source_before_delivery_day_spring_and_autumn():
    idx = pd.date_range("2025-01-01", "2026-01-01", freq="h", tz="UTC", inclusive="left")
    assert (~source_before_delivery_day(idx, 24, TZ)).sum() == 1
    for h in (48, 168, 336):
        assert source_before_delivery_day(idx, h, TZ).all()
    assert not source_before_delivery_day(idx, 0, TZ).any()


def test_agsi_gas_storage_needs_lag_48_against_its_publication_time():
    """Gas day X published ~18:00 CET on X+1; commodities stamps it at X+2 00:00 UTC (publication_lag_days=2)."""
    idx = pd.date_range("2025-01-01", "2026-01-01", freq="h", tz="UTC", inclusive="left")
    days = pd.date_range("2024-12-01", "2026-01-01", freq="D")
    daily = pd.Series(np.arange(len(days), dtype=float), index=days)
    hourly = _daily_to_hourly(daily, idx, lag_days=2)
    published = (days + pd.Timedelta(days=1, hours=18)).tz_localize(TZ)          # X+1 18:00 local
    issue = issue_time(idx, TZ, 11)

    def late(s: pd.Series) -> int:
        ok = s.notna().to_numpy()
        pub = published[s.to_numpy()[ok].astype(int)].tz_convert("UTC")
        return int((pub > issue[ok]).sum())

    assert late(hourly) > 0                                                     # lag 0 leaks
    out = candidate_features(pd.DataFrame({"cmd_gas_storage_eu_pct": hourly}), ["cmd"], POLICY, TZ)
    assert list(out) == ["cmd_gas_storage_eu_pct_lag48"]
    assert late(out.iloc[:, 0]) == 0


def test_candidate_collision_with_existing_columns_warns(caplog, monkeypatch):
    import energy_forecast.features as F

    df = _frame()
    policy = {"clash": {"rules": [{"pattern": "^cap_BE_solar$", "lags_h": [0]}]}}
    with caplog.at_level("WARNING", logger="energy_forecast.features"):
        build_features(df, candidate_families=["clash"], candidate_policy=policy)
    assert not caplog.records                      # cap_BE_solar is not a default feature: no clash
    # make cap_BE_solar a default (known-ahead) feature to force a clash
    monkeypatch.setattr(F, "KNOWN_AHEAD_PREFIXES", F.KNOWN_AHEAD_PREFIXES + ("cap_BE_solar",))
    with caplog.at_level("WARNING", logger="energy_forecast.features"):
        X = build_features(df, candidate_families=["clash"], candidate_policy=policy)
    assert list(X.columns).count("cap_BE_solar") == 1
    assert any("cap_BE_solar" in r.getMessage() for r in caplog.records)
