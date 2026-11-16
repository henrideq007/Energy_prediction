"""Tests for the TTF gas fallback logic (Yahoo first, manual CSV fills gaps).

No network and no real price file needed: Yahoo is monkeypatched and the CSV is written to tmp_path.
"""

import pandas as pd
import pytest

from energy_forecast.data import commodities


def _cfg(ttf_csv: str, eua_csv: str = "data/external/does_not_exist.csv", lag: int = 0) -> dict:
    return {
        "commodities": {
            "enabled": True,
            "publication_lag_days": lag,
            "ttf_ticker": "TTF=F",
            "ttf_csv": ttf_csv,
            "eua_csv": eua_csv,
        }
    }


def _hourly_index() -> pd.DatetimeIndex:
    return pd.date_range("2026-01-01", "2026-01-05 23:00", freq="h", tz="UTC")


def test_read_price_csv_iso_dates(tmp_path):
    p = tmp_path / "ttf.csv"
    p.write_text("date,price\n2026-01-02,31.5\n2026-01-01,30\n")
    s = commodities.read_price_csv(p)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-01-02"]
    assert list(s.values) == [30.0, 31.5]


def test_read_price_csv_day_first_and_decimal_comma(tmp_path):
    p = tmp_path / "ttf.csv"
    p.write_text("date,price\n02/01/2026,\"31,25\"\n")
    s = commodities.read_price_csv(p)
    assert s.index[0] == pd.Timestamp("2026-01-02")
    assert s.iloc[0] == pytest.approx(31.25)


def test_read_price_csv_rejects_missing_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("day,value\n2026-01-01,30\n")
    with pytest.raises(ValueError, match="date,price"):
        commodities.read_price_csv(p)


def test_csv_used_when_yahoo_empty(tmp_path, monkeypatch):
    csv = tmp_path / "ttf.csv"
    csv.write_text("date,price\n2026-01-01,30\n2026-01-02,32\n2026-01-03,34\n")
    monkeypatch.setattr(commodities, "_ttf_from_yahoo", lambda ticker, index: pd.Series(dtype=float))

    out = commodities.fetch_commodities(_cfg(str(csv)), _hourly_index())

    assert "ttf_gas" in out.columns
    assert out["ttf_gas"].notna().all()
    # Lag 0: the 2026-01-02 close applies from 2026-01-02 00:00 UTC onward
    assert out.loc["2026-01-02 00:00", "ttf_gas"] == 32.0


def test_csv_fills_gaps_in_yahoo_series(tmp_path, monkeypatch):
    csv = tmp_path / "ttf.csv"
    csv.write_text("date,price\n2026-01-01,30\n2026-01-02,99\n2026-01-03,34\n")
    yahoo = pd.Series(
        [10.0, 20.0],
        index=pd.to_datetime(["2026-01-01", "2026-01-03"]),
    )
    monkeypatch.setattr(commodities, "_ttf_from_yahoo", lambda ticker, index: yahoo)

    out = commodities.fetch_commodities(_cfg(str(csv)), _hourly_index())

    # Yahoo wins where it has data (2026-01-01 -> 10, 2026-01-03 -> 20)
    assert out.loc["2026-01-01 12:00", "ttf_gas"] == 10.0
    assert out.loc["2026-01-03 12:00", "ttf_gas"] == 20.0
    # The CSV fills the missing day (2026-01-02 -> 99)
    assert out.loc["2026-01-02 12:00", "ttf_gas"] == 99.0


def test_gas_feature_skipped_when_no_source(tmp_path, monkeypatch):
    monkeypatch.setattr(commodities, "_ttf_from_yahoo", lambda ticker, index: pd.Series(dtype=float))
    missing = str(tmp_path / "absent.csv")

    out = commodities.fetch_commodities(_cfg(missing), _hourly_index())

    assert "ttf_gas" not in out.columns


def test_yahoo_retried_until_data(monkeypatch):
    calls = []

    def fake_close(ticker, start, end):
        calls.append(ticker)
        if len(calls) < 3:
            return pd.Series(dtype=float)
        return pd.Series([30.0], index=pd.to_datetime(["2026-01-02"]))

    monkeypatch.setattr(commodities, "_yahoo_close", fake_close)
    out = commodities._ttf_from_yahoo("TTF=F", _hourly_index(), attempts=3, sleep_s=0)

    assert len(calls) == 3
    assert out.iloc[0] == 30.0


def test_yahoo_gives_up_after_attempts(monkeypatch):
    calls = []
    monkeypatch.setattr(
        commodities, "_yahoo_close", lambda t, s, e: calls.append(t) or pd.Series(dtype=float)
    )
    out = commodities._ttf_from_yahoo("TTF=F", _hourly_index(), attempts=2, sleep_s=0)

    assert len(calls) == 2
    assert out.empty


def test_cache_written_then_reused_when_yahoo_fails(tmp_path, monkeypatch):
    cache = tmp_path / "cache" / "ttf_yahoo_cache.csv"
    cfg = _cfg(str(tmp_path / "absent.csv"))
    cfg["commodities"]["ttf_cache"] = str(cache)

    # Run 1: Yahoo works (tz-aware index, as yfinance can return) -> cache is written
    yahoo = pd.Series(
        [30.0, 32.0], index=pd.to_datetime(["2026-01-01", "2026-01-02"]).tz_localize("Europe/Amsterdam")
    )
    monkeypatch.setattr(commodities, "_ttf_from_yahoo", lambda ticker, index: yahoo)
    first = commodities.fetch_commodities(cfg, _hourly_index())
    assert cache.exists()
    assert first.loc["2026-01-02 12:00", "ttf_gas"] == 32.0

    # Run 2: Yahoo is down -> same values come back from the cache
    monkeypatch.setattr(commodities, "_ttf_from_yahoo", lambda ticker, index: pd.Series(dtype=float))
    second = commodities.fetch_commodities(cfg, _hourly_index())
    pd.testing.assert_series_equal(first["ttf_gas"], second["ttf_gas"])


def test_fresh_yahoo_overrides_and_extends_cache(tmp_path, monkeypatch):
    cache = tmp_path / "ttf_yahoo_cache.csv"
    cache.write_text("date,price\n2026-01-01,30\n2026-01-02,32\n")
    cfg = _cfg(str(tmp_path / "absent.csv"))
    cfg["commodities"]["ttf_cache"] = str(cache)
    yahoo = pd.Series([33.0, 35.0], index=pd.to_datetime(["2026-01-02", "2026-01-03"]))
    monkeypatch.setattr(commodities, "_ttf_from_yahoo", lambda ticker, index: yahoo)

    commodities.fetch_commodities(cfg, _hourly_index())

    saved = commodities.read_price_csv(cache)
    assert list(saved.values) == [30.0, 33.0, 35.0]
