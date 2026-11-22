"""Tests for the Phase 1 data extension (4 Nov 2026): outages, gas/carbon proxies, staleness."""

import pandas as pd

from energy_forecast.data import commodities
from energy_forecast.data.entsoe_extra import first_delivery_hour_known, unavailable_mw_known_at_issue
from energy_forecast.features import build_features, leakage_check

TZ = "Europe/Brussels"


def _msg(created, mrid, rev, start, end, nominal, avail, status=None, plant="Nuclear"):
    return {"created_doc_time": pd.Timestamp(created, tz=TZ), "mrid": mrid, "revision": rev, "docstatus": status,
            "plant_type": plant, "nominal_power": nominal, "avail_qty": avail,
            "start": pd.Timestamp(start, tz=TZ), "end": pd.Timestamp(end, tz=TZ)}


def test_first_delivery_hour_known_uses_d_minus_1_10h():
    t = pd.Series(pd.to_datetime(["2026-03-10 09:59", "2026-03-10 10:01"]).tz_localize(TZ))
    out = first_delivery_hour_known(t).dt.tz_convert(TZ)
    assert out.iloc[0] == pd.Timestamp("2026-03-11 00:00", tz=TZ)   # published before 10:00 -> usable for D+1
    assert out.iloc[1] == pd.Timestamp("2026-03-12 00:00", tz=TZ)   # after 10:00 -> only from D+2


def test_outage_revisions_are_used_only_once_published():
    idx = pd.date_range("2026-03-01", "2026-03-20", freq="h", tz=TZ, inclusive="left").tz_convert("UTC")
    msgs = pd.DataFrame([
        # rev 1 (published 1 Mar 08:00): unit fully out 5 -> 15 Mar
        _msg("2026-03-01 08:00", "A", 1, "2026-03-05", "2026-03-15", 1000, 0),
        # rev 2 (published 8 Mar 15:00): outage CANCELLED
        _msg("2026-03-08 15:00", "A", 2, "2026-03-05", "2026-03-15", 1000, 0, status="Cancelled"),
        # a gas unit, must be ignored by the nuclear filter
        _msg("2026-03-01 08:00", "G", 1, "2026-03-05", "2026-03-15", 400, 0, plant="Fossil Gas"),
    ])
    s = unavailable_mw_known_at_issue(msgs, idx, "Nuclear").tz_convert(TZ)
    assert s.loc["2026-03-04"].eq(0).all()
    assert s.loc["2026-03-05":"2026-03-09"].eq(1000).all()   # cancellation (8 Mar 15:00) not known for 9 Mar
    assert s.loc["2026-03-10":"2026-03-19"].eq(0).all()      # known from the 9 Mar 10:00 issue -> day 10 Mar
    all_types = unavailable_mw_known_at_issue(msgs, idx, None).tz_convert(TZ)
    assert all_types.loc["2026-03-06 12:00"] == 1400


def test_daily_to_hourly_never_carries_a_dead_source():
    s = pd.Series([10.0, 11.0], index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    idx = pd.date_range("2026-01-01", "2026-02-01", freq="h", tz="UTC", inclusive="left")
    out = commodities._daily_to_hourly(s, idx, lag_days=2, max_stale_days=10)
    assert out.loc["2026-01-04 12:00"] == 11
    assert out.loc["2026-01-20":].isna().all()


def test_eua_gaps_filled_from_scaled_etc():
    days = pd.date_range("2026-01-01", periods=40, freq="D")
    etc = pd.Series(100.0, index=days)
    auction = pd.Series(103.0, index=days[:30])            # auctions stop after 30 days
    price, flag = commodities.eua_with_etc_fill(auction, etc)
    assert price.loc[days[35]] == 103.0                   # ETC x ratio 1.03
    assert flag.loc[days[35]] == 1 and flag.loc[days[5]] == 0


def test_candidate_columns_do_not_enter_features():
    idx = pd.date_range("2026-01-01", periods=24 * 10, freq="h", tz="UTC")
    df = pd.DataFrame({"price_da": 50.0, "load_forecast": 10000.0, "nb_FR_load_fc": 60000.0,
                       "unav_BE_nuclear_mw": 1000.0, "elia_wind_dayaheadforecast": 500.0,
                       "xch_BE_FR_net_export": 100.0, "wfr_paris_temperature_2m": 5.0,
                       "cmd_coal_api2": 100.0, "flag_gas_monthly_proxy": 1.0}, index=idx)
    X = build_features(df)
    assert not [c for c in X.columns if c.startswith(("nb_", "unav_", "elia_", "xch_", "wfr_", "cmd_", "flag_"))]
    assert leakage_check(X) == []
