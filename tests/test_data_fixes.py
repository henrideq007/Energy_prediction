"""Tests for the data fixes of 3 Nov 2026 (first real fetch)."""

import numpy as np
import pandas as pd

from energy_forecast.config import Config
from energy_forecast.data import commodities
from energy_forecast.data.entsoe_source import fill_zero_generation
from energy_forecast.validation import clean_and_validate, interpolate_short_gaps


def _hourly(values):
    idx = pd.date_range("2026-01-01", periods=len(values), freq="h", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def test_only_short_gaps_are_interpolated():
    s = _hourly([1, np.nan, np.nan, 4, 5, np.nan, np.nan, np.nan, np.nan, np.nan, 11])
    out = interpolate_short_gaps(s, 3)
    assert out.iloc[1] == 2 and out.iloc[2] == 3          # 2-hour gap filled
    assert out.iloc[5:10].isna().all()                     # 5-hour gap left completely empty
    assert out.iloc[10] == 11


def test_clean_and_validate_keeps_long_gaps_empty():
    df = pd.DataFrame({"price_da": np.arange(200.0)}, index=_hourly(np.zeros(200)).index)
    df.iloc[50:60, 0] = np.nan                             # 10-hour gap
    clean, rep = clean_and_validate(df)
    assert clean["price_da"].iloc[50:60].isna().all()
    assert rep.interpolated.get("price_da", 0) == 0


def test_pumped_storage_missing_means_zero():
    gen = pd.DataFrame({"nuclear": [100.0, 100.0, np.nan],
                        "hydro_pumped_storage": [np.nan, 50.0, np.nan],
                        "wind_offshore": [np.nan, 10.0, np.nan]})
    out = fill_zero_generation(gen)
    assert out.loc[0, "hydro_pumped_storage"] == 0 and out.loc[0, "wind_offshore"] == 0
    assert out.loc[1, "hydro_pumped_storage"] == 50
    assert out.loc[2].isna().all()                         # hour with no data at all stays missing


def test_read_price_csv_formats(tmp_path):
    f = tmp_path / "ttf.csv"
    f.write_text("date,price\n2026-10-26,31.5\n27/10/2026,\"32,25\"\n", encoding="utf-8")
    s = commodities.read_price_csv(f)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2026-10-26", "2026-10-27"]
    assert s.iloc[1] == 32.25


def test_ttf_csv_fallback_when_yahoo_empty(tmp_path, monkeypatch):
    f = tmp_path / "ttf.csv"
    f.write_text("date,price\n2026-10-20,30\n2026-10-21,31\n2026-10-22,32\n", encoding="utf-8")
    monkeypatch.setattr(commodities, "_ttf_from_yahoo", lambda ticker, index: pd.Series(dtype=float))
    cfg = Config({"commodities": {"enabled": True, "ttf_ticker": "TTF=F", "ttf_csv": str(f),
                                  "eua_csv": str(tmp_path / "missing.csv"), "publication_lag_days": 2}})
    idx = pd.date_range("2026-10-23", "2026-10-25", freq="h", tz="UTC", inclusive="left")
    out = commodities.fetch_commodities(cfg, idx)
    assert "ttf_gas" in out and out["ttf_gas"].notna().all()
    assert out.loc["2026-10-23 05:00", "ttf_gas"].item() == 31   # close of D-2 (21 Oct) used on 23 Oct
