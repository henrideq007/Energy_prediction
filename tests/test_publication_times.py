"""Tests for the D-16 publication-time log (energy_forecast.pubtimes). No network: every API is faked."""

from __future__ import annotations

import csv

import pandas as pd
import pytest

from energy_forecast import pubtimes
from energy_forecast.data.commodities import parse_the_xml

NOW = pd.Timestamp("2026-11-23 10:50", tz="Europe/Brussels")

THE_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<PricesEnergyImbalance>
  <PricesEnergyImbalance><Gasday>2026-11-20T00:00:00</Gasday><VTPDailyAveragePrice>30.5</VTPDailyAveragePrice></PricesEnergyImbalance>
  <PricesEnergyImbalance><Gasday>2026-11-21T00:00:00+01:00</Gasday><VTPDailyAveragePrice>31.25</VTPDailyAveragePrice></PricesEnergyImbalance>
  <PricesEnergyImbalance><Gasday>2026-11-22</Gasday><VTPDailyAveragePrice>32</VTPDailyAveragePrice></PricesEnergyImbalance>
  <PricesEnergyImbalance><Gasday>2026-11-23</Gasday><VTPDailyAveragePrice></VTPDailyAveragePrice></PricesEnergyImbalance>
</PricesEnergyImbalance>
"""


class FakeResponse:
    def __init__(self, payload=None, content: bytes = b"", status: int = 200):
        self._payload, self.content, self.status_code = payload, content, status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise pubtimes.requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


class NoMatchingDataError(Exception):
    """Same class name as in entsoe-py / jao-py."""


# --------------------------------------------------------------------------- rows / CSV
def test_next_delivery_day_is_local_tomorrow():
    late = pd.Timestamp("2026-11-23 23:30", tz="UTC")  # already 24 Nov 00:30 in Brussels
    assert pubtimes.next_delivery_day(late).date() == pd.Timestamp("2026-11-25").date()
    assert pubtimes.next_delivery_day(NOW).date() == pd.Timestamp("2026-11-24").date()


def test_append_rows_keeps_schema(tmp_path):
    path = tmp_path / "log.csv"
    rows = [pubtimes._row(NOW, "2026-11-24", "BE", "x", "available", 96)]
    pubtimes.append_rows(rows, path)
    pubtimes.append_rows(rows, path)
    with open(path, encoding="utf-8") as f:
        data = list(csv.reader(f))
    assert data[0] == pubtimes.COLUMNS
    assert len(data) == 3
    assert data[1] == ["2026-11-23 10:50", "2026-11-24", "BE", "x", "available", "96"]


# --------------------------------------------------------------------------- Elia
def test_count_elia_points_groups_and_filters():
    calls = []

    def get(url, headers=None, timeout=None, params=None):
        calls.append((url, params))
        return FakeResponse([{"datetime": "2026-11-23T23:00:00+00:00", "v": 1200.0},
                             {"datetime": "2026-11-23T23:15:00+00:00", "v": 1100.0},
                             {"datetime": "2026-11-23T23:30:00+00:00", "v": None}])

    n = pubtimes.count_elia_points("https://x/datasets", "ods086", "dayahead11hforecast",
                                   pd.Timestamp("2026-11-24", tz="Europe/Brussels"), get=get)
    assert n == 2
    url, params = calls[0]
    assert url == "https://x/datasets/ods086/exports/json"
    assert params["group_by"] == "datetime"
    assert "sum(dayahead11hforecast)" in params["select"]
    # local day 24 Nov (CET) = 23 Nov 23:00 UTC -> 24 Nov 23:00 UTC
    assert "datetime >= '2026-11-23T23:00:00Z'" in params["where"]
    assert "datetime < '2026-11-24T23:00:00Z'" in params["where"]
    assert "dayahead11hforecast is not null" in params["where"]


def test_check_elia_statuses():
    def get(url, headers=None, timeout=None, params=None):
        if "ods087" in url:
            return FakeResponse(status=404)
        if "dayaheadforecast" in params["select"]:
            return FakeResponse([])
        return FakeResponse([{"datetime": f"t{i}", "v": 1.0} for i in range(96)])

    rows = {r["series"]: r for r in pubtimes.check_elia(NOW, base_url="https://x", get=get)}
    assert rows["elia_wind_dayahead11h (ods086)"]["status"] == "available"
    assert rows["elia_wind_dayahead11h (ods086)"]["n_points"] == 96
    assert rows["elia_wind_dayahead (ods086)"]["status"] == "not_published"
    assert rows["elia_solar_dayahead11h (ods087)"]["status"] == "error: HTTPError"
    assert all(r["delivery_day"] == "2026-11-24" and r["zone"] == "BE" for r in rows.values())


# --------------------------------------------------------------------------- THE
def test_parse_the_xml():
    s = parse_the_xml(THE_XML)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2026-11-20", "2026-11-21", "2026-11-22"]
    assert list(s.values) == [30.5, 31.25, 32.0]


def test_parse_the_xml_missing_fields_raises():
    with pytest.raises(ValueError):
        parse_the_xml(b"<PricesEnergyImbalance><PricesEnergyImbalance><Gasday>2026-11-20</Gasday>"
                      b"</PricesEnergyImbalance></PricesEnergyImbalance>")


def test_check_the_gas_day_rows():
    seen = {}

    def get(url, headers=None, timeout=None, params=None):
        seen.update(params)
        return FakeResponse(content=THE_XML)

    rows = pubtimes.check_the(NOW, get=get)
    assert seen == {"startDate": "2026-11-18", "endDate": "2026-11-23"}
    assert [(r["delivery_day"], r["status"], r["n_points"]) for r in rows] == [
        ("2026-11-22", "available", 1), ("2026-11-23", "not_published", 0)]
    assert {r["zone"] for r in rows} == {"DE_THE"} and {r["series"] for r in rows} == {"the_vtp_daily_price"}


def test_check_the_network_error():
    def get(*a, **k):
        raise ConnectionError("offline")

    rows = pubtimes.check_the(NOW, get=get)
    assert [r["status"] for r in rows] == ["error: ConnectionError"] * 2


# --------------------------------------------------------------------------- JAO
class FakeJao:
    def __init__(self, result=None, exc: Exception | None = None):
        self.result, self.exc, self.day = result, exc, None

    def query_minmax_np(self, day):
        self.day = day
        if self.exc:
            raise self.exc
        return self.result


def test_check_jao_available():
    df = pd.DataFrame({"mtu": pd.date_range("2026-11-24", periods=24, freq="h", tz="Europe/Brussels"),
                       "minBE": [-3000.0] * 23 + [None], "maxBE": [4000.0] * 24})
    client = FakeJao(df)
    [row] = pubtimes.check_jao(NOW, client=client)
    assert (row["status"], row["n_points"], row["delivery_day"]) == ("available", 23, "2026-11-24")
    assert client.day == pd.Timestamp("2026-11-24", tz="Europe/Brussels")


@pytest.mark.parametrize("client, status", [
    (FakeJao(pd.DataFrame()), "not_published"),
    (FakeJao(None), "not_published"),
    (FakeJao(pd.DataFrame({"minFR": [1.0]})), "not_published"),
    (FakeJao(exc=NoMatchingDataError()), "not_published"),
    (FakeJao(exc=TimeoutError()), "error: TimeoutError"),
])
def test_check_jao_not_published_or_error(client, status):
    [row] = pubtimes.check_jao(NOW, client=client)
    assert row["status"] == status and row["n_points"] == 0


# --------------------------------------------------------------------------- ENTSO-E
class FakeEntsoe:
    def query_load_forecast(self, z, start, end):
        return pd.Series(range(96))

    def query_wind_and_solar_forecast(self, z, start, end):
        raise NoMatchingDataError()

    def query_generation_forecast(self, z, start, end):
        return pd.Series(dtype=float)

    def query_day_ahead_prices(self, z, start, end):
        raise ConnectionError()


def test_check_entsoe_statuses():
    rows = {r["series"]: r for r in pubtimes.check_entsoe(NOW, ["BE"], client=FakeEntsoe())}
    assert rows["load_forecast (A65)"]["status"] == "available" and rows["load_forecast (A65)"]["n_points"] == 96
    assert rows["wind_solar_forecast (A69)"]["status"] == "not_published"
    assert rows["generation_forecast (A71)"]["status"] == "empty"
    assert rows["day_ahead_prices (A44)"]["status"] == "error: ConnectionError"


def test_check_entsoe_missing_key_gives_error_rows(monkeypatch):
    from energy_forecast import config

    def no_key():
        raise RuntimeError("ENTSOE_API_KEY missing")

    monkeypatch.setattr(config, "entsoe_api_key", no_key)
    rows = pubtimes.check_entsoe(NOW, ["BE", "FR"])
    assert len(rows) == 8
    assert {r["status"] for r in rows} == {"error: RuntimeError"}


# --------------------------------------------------------------------------- isolation
def test_one_source_failing_does_not_block_others():
    def boom(now, zones):
        raise ImportError("no package")

    ok = [pubtimes._row(NOW, "2026-11-24", "BE", "ok", "available", 1)]
    rows = pubtimes.run_checks(sources=["entsoe", "elia", "the", "jao"], zones=["BE"], now=NOW,
                               checkers={"entsoe": boom, "elia": lambda t, z: ok, "the": boom,
                                         "jao": lambda t, z: ok})
    by_status = pd.DataFrame(rows).groupby("status").size().to_dict()
    assert by_status == {"available": 2, "error: ImportError": 4 + 2}
    assert {r["series"] for r in rows if r["status"] == "error: ImportError"} == {
        *pubtimes.ENTSOE_SERIES, "the_vtp_daily_price"}
    assert all(list(r) == pubtimes.COLUMNS for r in rows)


def test_run_checks_respects_sources():
    called = []
    fake = {s: (lambda t, z, s=s: called.append(s) or []) for s in pubtimes.SOURCES}
    pubtimes.run_checks(sources=["elia", "jao"], now=NOW, checkers=fake)
    assert called == ["elia", "jao"]


# --------------------------------------------------------------------------- summarise
def _log(series: str, days: int, times_status: list[tuple[str, str]], lead: int = 1,
         zone: str = "BE") -> list[dict]:
    rows = []
    for i in range(days):
        check_day = pd.Timestamp("2026-11-01") + pd.Timedelta(days=i)
        delivery = check_day + pd.Timedelta(days=lead)
        for hhmm, status in times_status:
            rows.append({"checked_at_local": f"{check_day:%Y-%m-%d} {hhmm}", "delivery_day": f"{delivery:%Y-%m-%d}",
                         "zone": zone, "series": series, "status": status,
                         "n_points": "96" if status == "available" else "0"})
    return rows


def test_summarise_verdicts():
    rows = (_log("early", 12, [("09:45", "available"), ("12:00", "available")])
            + _log("late", 12, [("10:50", "not_published"), ("11:05", "not_published"), ("18:30", "available")])
            + _log("few", 5, [("09:45", "available")])
            + _log("no_pre", 12, [("12:00", "available")])
            + _log("errors", 12, [("09:45", "error: HTTPError")])
            + _log("the_vtp_daily_price", 12, [("09:45", "available"), ("08:00", "not_published")],
                   lead=-1, zone="DE_THE"))
    # mixed: available before the cut-off on 10 of 12 days, published between 10:50 and 11:05 on 2 days
    mixed = _log("mixed", 10, [("10:50", "available")])
    mixed += [r | {"status": "not_published"} for r in _log("mixed", 12, [("10:50", "x")])[10:]]
    mixed += [r | {"status": "available"} for r in _log("mixed", 12, [("11:05", "x")])[10:]]
    # the wrong-lead rows (check on D-2) must be ignored
    noise = _log("early", 12, [("09:00", "not_published")], lead=2)
    s = pubtimes.summarise(pd.DataFrame(rows + mixed + noise), cutoff=11).set_index("series")

    assert s.loc["early", "verdict"] == "before cut-off"
    assert s.loc["early", "earliest_available"] == "09:45"
    assert s.loc["early", "latest_not_published"] == ""
    assert s.loc["early", "n_days"] == 12
    assert s.loc["late", "verdict"] == "after cut-off"
    assert s.loc["late", "earliest_available"] == "18:30"
    assert s.loc["late", "latest_not_published"] == "11:05"
    assert s.loc["few", "verdict"] == "insufficient data"
    assert s.loc["no_pre", "verdict"] == "insufficient data"
    assert "errors" not in s.index  # error rows say nothing about publication
    assert s.loc["mixed", "verdict"] == "mixed"
    assert s.loc["mixed", "n_days_before_cutoff"] == 10 and s.loc["mixed", "n_days_pre_cutoff"] == 12
    # THE: gas day G checked on G+1; available at 09:45 every day -> known at the cut-off
    assert s.loc["the_vtp_daily_price", "verdict"] == "before cut-off"
    assert s.loc["the_vtp_daily_price", "zone"] == "DE_THE"


def test_summarise_after_cutoff_when_missing_at_1105_once():
    rows = _log("s", 12, [("10:50", "available")])
    rows.append({"checked_at_local": "2026-11-05 11:05", "delivery_day": "2026-11-06", "zone": "BE",
                 "series": "s", "status": "empty", "n_points": "0"})
    s = pubtimes.summarise(pd.DataFrame(rows), cutoff=11)
    assert s.loc[0, "verdict"] == "after cut-off"


def test_summarise_empty_and_markdown():
    empty = pubtimes.summarise(pd.DataFrame(columns=pubtimes.COLUMNS), cutoff=11)
    assert empty.empty
    s = pubtimes.summarise(pd.DataFrame(_log("early", 12, [("09:45", "available")])), cutoff=11)
    md = pubtimes.summary_markdown(s, 11)
    assert "| zone | series |" in md and "before cut-off" in md and "cut-off 11:00" in md


def _where_for(day: str) -> str:
    calls = []

    def get(url, headers=None, timeout=None, params=None):
        calls.append(params)
        return FakeResponse([])

    pubtimes.count_elia_points("https://x/datasets", "ods086", "dayahead11hforecast",
                               pd.Timestamp(day, tz="Europe/Brussels"), get=get)
    return calls[0]["where"]


def test_elia_window_is_a_calendar_day_on_dst_days():
    # spring forward: 28 Mar 2027 lasts 23 h (27 Mar 23:00Z -> 28 Mar 22:00Z)
    w = _where_for("2027-03-28")
    assert "datetime >= '2027-03-27T23:00:00Z'" in w and "datetime < '2027-03-28T22:00:00Z'" in w
    # fall back: 25 Oct 2026 lasts 25 h (24 Oct 22:00Z -> 25 Oct 23:00Z)
    w = _where_for("2026-10-25")
    assert "datetime >= '2026-10-24T22:00:00Z'" in w and "datetime < '2026-10-25T23:00:00Z'" in w


def test_next_delivery_day_on_dst_day():
    now = pd.Timestamp("2026-10-25 00:30", tz="Europe/Brussels")
    assert pubtimes.next_delivery_day(now) == pd.Timestamp("2026-10-26", tz="Europe/Brussels")


def test_parse_cutoff_and_minute_cutoff():
    assert pubtimes.parse_cutoff(11) == 660
    assert pubtimes.parse_cutoff("11:11") == 671
    import pytest
    with pytest.raises(ValueError):
        pubtimes.parse_cutoff("25:00")
    # published at 11:05 every day: after a strict 11:00 cut-off, before the 11:11 live-job time
    rows = _log("elia_11am", 12, [("10:50", "not_published"), ("11:05", "available")])
    assert pubtimes.summarise(pd.DataFrame(rows), cutoff=11).loc[0, "verdict"] == "after cut-off"
    s = pubtimes.summarise(pd.DataFrame(rows), cutoff="11:11")
    assert s.loc[0, "verdict"] == "before cut-off"
    assert "cut-off 11:11" in pubtimes.summary_markdown(s, "11:11")
