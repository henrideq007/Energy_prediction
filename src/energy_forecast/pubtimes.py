"""Publication-time log (decision D-16): is tomorrow's data already published at check time?

Our forecast for delivery day D is issued on D-1 at 11:00 Brussels time (D-29,
`forecast.issue_hour_local`). A series may only be a same-time feature if it is published BEFORE
that cut-off. `scripts/check_publication_times.py` runs the checks below several times a day
(GitHub workflow `publication-times.yml`) and appends one row per series to
`reports/publication_times.csv`, kept in the GitHub release `pubtimes`.

CSV schema (fixed — the released log is appended to, never rewritten):
    checked_at_local  "YYYY-MM-DD HH:MM", Brussels local time of the check
    delivery_day      "YYYY-MM-DD" — delivery day D+1 (Brussels), or the gas day for THE
    zone              bidding zone / hub
    series            series name (with its dataset / document id)
    status            available | not_published | empty | error: <ExceptionName>
    n_points          number of points found (0 unless available)

Sources (each is an isolated function: one failing source never stops the others):
    entsoe  ENTSO-E A65 load fc, A69 wind/solar fc, A71 generation fc, A44 day-ahead prices
    elia    Elia near-real-time wind/solar datasets, "day-ahead 11AM" run (+ latest day-ahead run)
    the     THE (German gas hub) daily VTP average price, gas days today-1 and today
    jao     JAO Core final flow-based domain, min/max BE net position for D+1

`summarise()` turns the log into a per-series verdict vs the cut-off (see its docstring).
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from energy_forecast.data.commodities import THE_URL, parse_the_xml

log = logging.getLogger(__name__)

TZ = "Europe/Brussels"
COLUMNS = ["checked_at_local", "delivery_day", "zone", "series", "status", "n_points"]
SOURCES = ("entsoe", "elia", "the", "jao")
DEFAULT_ZONES = ("BE", "FR", "NL", "DE_LU")
UA = {"User-Agent": "energy-forecast-research/0.1"}

Row = dict[str, Any]

# --------------------------------------------------------------------------- ENTSO-E
ENTSOE_SERIES = {
    # series name: EntsoePandasClient method
    "load_forecast (A65)": "query_load_forecast",
    "wind_solar_forecast (A69)": "query_wind_and_solar_forecast",
    "generation_forecast (A71)": "query_generation_forecast",
    "day_ahead_prices (A44)": "query_day_ahead_prices",
}

# --------------------------------------------------------------------------- Elia
# Near-real-time Elia datasets (the historical ods031/ods032/ods209 used by data/elia.py lag ~2 days).
# TO BE CONFIRMED BY THE FIRST CI RUN: these ids could not be verified from the cloud sandbox.
# A wrong id shows up in the log as "error: HTTPError" (404) for that series.
ELIA_WIND_NRT_DATASET = "ods086"
ELIA_SOLAR_NRT_DATASET = "ods087"
ELIA_SERIES = [
    # (series name, dataset id, forecast field)
    (f"elia_wind_dayahead11h ({ELIA_WIND_NRT_DATASET})", ELIA_WIND_NRT_DATASET, "dayahead11hforecast"),
    (f"elia_solar_dayahead11h ({ELIA_SOLAR_NRT_DATASET})", ELIA_SOLAR_NRT_DATASET, "dayahead11hforecast"),
    # latest day-ahead run (published D-1 evening) — logged for comparison only
    (f"elia_wind_dayahead ({ELIA_WIND_NRT_DATASET})", ELIA_WIND_NRT_DATASET, "dayaheadforecast"),
    (f"elia_solar_dayahead ({ELIA_SOLAR_NRT_DATASET})", ELIA_SOLAR_NRT_DATASET, "dayaheadforecast"),
]
ELIA_DEFAULT_BASE_URL = "https://opendata.elia.be/api/explore/v2.1/catalog/datasets"

# --------------------------------------------------------------------------- THE / JAO
THE_SERIES = "the_vtp_daily_price"
THE_ZONE = "DE_THE"
THE_LOOKBACK_DAYS = 5
JAO_SERIES = "jao_core_minmax_np"
JAO_ZONE = "BE"

# --------------------------------------------------------------------------- summary
MIN_DAYS = 10  # fewer covered delivery days than this -> "insufficient data"
# Which observation answers "was it known at the cut-off?": checked date - delivery_day.
# Default: the check on D-1 for delivery day D. THE gas day G is published after the gas day, so the
# relevant observation is the check on G+1 (delivery_day = checked date - 1).
DEFAULT_LEAD_DAYS = 1
LEAD_DAYS = {THE_SERIES: -1}


def _row(now: pd.Timestamp, delivery_day: Any, zone: str, series: str, status: str, n: int = 0) -> Row:
    return {"checked_at_local": now.strftime("%Y-%m-%d %H:%M"), "delivery_day": str(pd.Timestamp(delivery_day).date()),
            "zone": zone, "series": series, "status": status, "n_points": int(n)}


def _error(exc: BaseException) -> str:
    return f"error: {type(exc).__name__}"


def _is_no_data(exc: BaseException) -> bool:
    """entsoe-py and jao-py both raise their own `NoMatchingDataError` when nothing is published yet."""
    return type(exc).__name__ == "NoMatchingDataError"


def next_delivery_day(now: pd.Timestamp) -> pd.Timestamp:
    """Delivery day D+1 at local midnight (Brussels) for a check made at `now`."""
    return (now.tz_convert(TZ).normalize() + pd.DateOffset(days=1)).normalize()


# --------------------------------------------------------------------------- checks
def check_entsoe(now: pd.Timestamp, zones: Iterable[str], client: Any = None) -> list[Row]:
    """ENTSO-E series for D+1. A missing API key / missing package gives error rows, not an exception."""
    d1 = next_delivery_day(now)
    start, end = d1, d1 + pd.DateOffset(days=1)  # calendar day: 23/25 h on DST days
    zones = list(zones)
    if client is None:
        try:
            from entsoe import EntsoePandasClient

            from energy_forecast.config import entsoe_api_key

            client = EntsoePandasClient(api_key=entsoe_api_key())
        except Exception as exc:
            log.warning("ENTSO-E client unavailable: %s", type(exc).__name__)
            return [_row(now, d1, z, s, _error(exc)) for z in zones for s in ENTSOE_SERIES]
    rows = []
    for z in zones:
        for name, method in ENTSOE_SERIES.items():
            status, n = "available", 0
            try:
                n = len(getattr(client, method)(z, start=start, end=end))
                if n == 0:
                    status = "empty"
            except Exception as exc:  # network/API errors are logged, not fatal
                status = "not_published" if _is_no_data(exc) else _error(exc)
                n = 0
            rows.append(_row(now, d1, z, name, status, n))
    return rows


def count_elia_points(base_url: str, dataset: str, field: str, day: pd.Timestamp,
                      get: Callable[..., Any] = requests.get) -> int:
    """Number of 15-min timestamps of local `day` where `field` is not null in an Elia dataset.

    Grouped by datetime so several region / grid rows per timestamp count once.
    """
    day = pd.Timestamp(day)
    if day.tzinfo is None:
        day = day.tz_localize(TZ)
    a = day.normalize().tz_convert("UTC")
    b = (day.normalize() + pd.DateOffset(days=1)).tz_convert("UTC")  # calendar day: 23/25 h on DST days
    where = (f"datetime >= '{a:%Y-%m-%dT%H:%M:%S}Z' and datetime < '{b:%Y-%m-%dT%H:%M:%S}Z'"
             f" and {field} is not null")
    r = get(f"{base_url}/{dataset}/exports/json", headers=UA, timeout=60,
            params={"select": f"datetime, sum({field}) as v", "where": where,
                    "group_by": "datetime", "timezone": "UTC"})
    r.raise_for_status()
    data = r.json() or []
    return sum(1 for rec in data if rec.get("v") is not None)


def check_elia(now: pd.Timestamp, base_url: str = ELIA_DEFAULT_BASE_URL,
               get: Callable[..., Any] = requests.get) -> list[Row]:
    """Elia wind/solar forecast runs for delivery day D+1 (Brussels)."""
    d1 = next_delivery_day(now)
    rows = []
    for name, ds, field in ELIA_SERIES:
        try:
            n = count_elia_points(base_url, ds, field, d1, get=get)
            rows.append(_row(now, d1, "BE", name, "available" if n > 0 else "not_published", n))
        except Exception as exc:
            rows.append(_row(now, d1, "BE", name, _error(exc)))
    return rows


def the_rows(now: pd.Timestamp, prices: pd.Series) -> list[Row]:
    """Rows for gas days today-1 and today from a parsed THE price series (index = gas day)."""
    today = now.tz_convert(TZ).tz_localize(None).normalize()
    rows = []
    for g in (today - pd.Timedelta(days=1), today):
        has = g in prices.index and pd.notna(prices.loc[g])
        rows.append(_row(now, g, THE_ZONE, THE_SERIES, "available" if has else "not_published", int(has)))
    return rows


def check_the(now: pd.Timestamp, get: Callable[..., Any] = requests.get) -> list[Row]:
    """THE daily VTP average price for gas days today-1 and today (delivery_day = gas day)."""
    today = now.tz_convert(TZ).tz_localize(None).normalize()
    try:
        r = get(THE_URL, headers=UA, timeout=60,
                params={"startDate": f"{today - pd.Timedelta(days=THE_LOOKBACK_DAYS):%Y-%m-%d}",
                        "endDate": f"{today:%Y-%m-%d}"})
        r.raise_for_status()
        prices = parse_the_xml(r.content)
    except Exception as exc:
        return [_row(now, g, THE_ZONE, THE_SERIES, _error(exc)) for g in (today - pd.Timedelta(days=1), today)]
    return the_rows(now, prices)


def check_jao(now: pd.Timestamp, client: Any = None, zone: str = JAO_ZONE) -> list[Row]:
    """JAO Core final flow-based domain (min/max net position) for D+1."""
    d1 = next_delivery_day(now)
    try:
        if client is None:
            from jao import JaoPublicationToolPandasClient

            client = JaoPublicationToolPandasClient()
        x = client.query_minmax_np(pd.Timestamp(d1.date(), tz=TZ))
    except Exception as exc:
        return [_row(now, d1, zone, JAO_SERIES, "not_published" if _is_no_data(exc) else _error(exc))]
    col = f"min{zone}"
    n = 0 if x is None or len(x) == 0 or col not in x else int(pd.to_numeric(x[col], errors="coerce").notna().sum())
    return [_row(now, d1, zone, JAO_SERIES, "available" if n > 0 else "not_published", n)]


def _fallback_series(source: str, zones: list[str], now: pd.Timestamp) -> list[tuple[Any, str, str]]:
    """(delivery_day, zone, series) of a source, used to log error rows if the source itself crashes."""
    d1 = next_delivery_day(now)
    if source == "entsoe":
        return [(d1, z, s) for z in zones for s in ENTSOE_SERIES]
    if source == "elia":
        return [(d1, "BE", s) for s, _, _ in ELIA_SERIES]
    if source == "the":
        today = now.tz_convert(TZ).tz_localize(None).normalize()
        return [(today - pd.Timedelta(days=1), THE_ZONE, THE_SERIES), (today, THE_ZONE, THE_SERIES)]
    return [(d1, JAO_ZONE, JAO_SERIES)]


def run_checks(sources: Iterable[str] = SOURCES, zones: Iterable[str] = DEFAULT_ZONES,
               now: pd.Timestamp | None = None, elia_base_url: str = ELIA_DEFAULT_BASE_URL,
               checkers: dict[str, Callable[[pd.Timestamp, list[str]], list[Row]]] | None = None) -> list[Row]:
    """Run every requested source; a source that raises gets error rows and the others still run."""
    now = pd.Timestamp.now(tz=TZ) if now is None else now.tz_convert(TZ)
    zones = list(zones)
    default: dict[str, Callable[[pd.Timestamp, list[str]], list[Row]]] = {
        "entsoe": lambda t, zs: check_entsoe(t, zs),
        "elia": lambda t, zs: check_elia(t, base_url=elia_base_url),
        "the": lambda t, zs: check_the(t),
        "jao": lambda t, zs: check_jao(t),
    }
    checkers = {**default, **(checkers or {})}
    rows: list[Row] = []
    for src in sources:
        try:
            rows += checkers[src](now, zones)
        except Exception as exc:
            log.warning("Source %s failed: %r", src, exc)
            rows += [_row(now, d, z, s, _error(exc)) for d, z, s in _fallback_series(src, zones, now)]
    return rows


def append_rows(rows: list[Row], path: Path) -> None:
    """Append rows to the CSV log with the fixed column order (header only for a new file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


# --------------------------------------------------------------------------- summary
def _hhmm(minutes: float) -> str:
    if pd.isna(minutes):
        return ""
    m = int(minutes)
    return f"{m // 60:02d}:{m % 60:02d}"


def parse_cutoff(cutoff: int | str) -> int:
    """Cut-off as minutes after local midnight: an int hour (11) or an "HH:MM" string ("11:11")."""
    if isinstance(cutoff, str) and ":" in cutoff:
        h, m = (int(x) for x in cutoff.split(":", 1))
    else:
        h, m = int(cutoff), 0
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"invalid cut-off {cutoff!r}")
    return h * 60 + m


def summarise(log_df: pd.DataFrame, cutoff: int | str, min_days: int = MIN_DAYS) -> pd.DataFrame:
    """Per (zone, series): when is the series published relative to the issue-time cut-off?

    Relevant observations: for delivery day D, the checks made on D-1 (checked date - delivery_day
    = 1 day). THE gas prices are about past gas days: for gas day G the relevant checks are the ones
    made on G+1 (delivery_day = checked date - 1, see `LEAD_DAYS`), i.e. "is yesterday's gas price
    known at today's cut-off?". Error rows are ignored (they say nothing about publication);
    status "empty" counts as not published.

    Columns:
        earliest_available      earliest time of day of an "available" relevant check
        latest_not_published    latest time of day of a "not published" relevant check
        n_days                  delivery days with at least one relevant non-error check
        n_days_pre_cutoff       of which days with at least one check strictly before the cut-off
        n_days_before_cutoff    of which days on which it was available at a check before the cut-off
        verdict                 see below

    Verdict (cut-off = `cutoff`, an hour or "HH:MM" local; "before" means strictly earlier). The issue
    time is 11:00 (D-29) but the live job runs at 11:11, so read the log at both cut-offs: the Elia
    "day-ahead 11AM" run is issued AT 11:00 and is expected to fail the strict 11:00 reading.
        insufficient data   n_days_pre_cutoff < `min_days` (no or too few checks before the cut-off)
        after cut-off       ever not published at a check at/after the cut-off, or never available
                            before the cut-off
        before cut-off      available at a check before the cut-off on EVERY day with a pre-cut-off check
        mixed               otherwise: available before the cut-off on some days only -> not safe
    Only "before cut-off" allows using the series as a same-time feature (D-16).
    """
    out_cols = ["zone", "series", "earliest_available", "latest_not_published", "n_days",
                "n_days_pre_cutoff", "n_days_before_cutoff", "verdict"]
    if log_df.empty:
        return pd.DataFrame(columns=out_cols)
    d = log_df.copy()
    checked = pd.to_datetime(d["checked_at_local"], errors="coerce")
    d["check_date"] = checked.dt.normalize()
    d["tod"] = checked.dt.hour * 60 + checked.dt.minute
    d["delivery"] = pd.to_datetime(d["delivery_day"], errors="coerce")
    d["status"] = d["status"].astype(str).str.strip()
    d = d[d["status"].isin(["available", "not_published", "empty"]) & checked.notna() & d["delivery"].notna()]
    lead = d["series"].map(LEAD_DAYS).fillna(DEFAULT_LEAD_DAYS)
    d = d[(d["delivery"] - d["check_date"]).dt.days == lead]
    d["avail"] = d["status"] == "available"
    d["pre"] = d["tod"] < parse_cutoff(cutoff)

    rows = []
    for (zone, series), g in d.groupby(["zone", "series"], sort=True):
        days = g["delivery"].unique()
        pre = g[g["pre"]]
        pre_days = pre["delivery"].unique()
        ok_days = pre.loc[pre["avail"], "delivery"].unique()
        late_missing = bool((~g["avail"] & ~g["pre"]).any())
        if len(pre_days) < min_days:
            verdict = "insufficient data"
        elif late_missing or len(ok_days) == 0:
            verdict = "after cut-off"
        elif len(ok_days) == len(pre_days):
            verdict = "before cut-off"
        else:
            verdict = "mixed"
        rows.append({"zone": zone, "series": series,
                     "earliest_available": _hhmm(g.loc[g["avail"], "tod"].min()),
                     "latest_not_published": _hhmm(g.loc[~g["avail"], "tod"].max()),
                     "n_days": len(days), "n_days_pre_cutoff": len(pre_days),
                     "n_days_before_cutoff": len(ok_days), "verdict": verdict})
    return pd.DataFrame(rows, columns=out_cols)


def summary_markdown(summary: pd.DataFrame, cutoff: int | str, min_days: int = MIN_DAYS) -> str:
    """Markdown table of `summarise()` output (no `tabulate` dependency)."""
    lines = [f"# Publication-time summary (D-16) — cut-off {_hhmm(parse_cutoff(cutoff))} Brussels",
             "", (f"Generated {pd.Timestamp.now(tz=TZ):%Y-%m-%d %H:%M} Brussels. Minimum {min_days} delivery days "
                  "with a check before the cut-off for a verdict. See `energy_forecast.pubtimes.summarise` for the rules."),
             ""]
    cols = list(summary.columns)
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join("---" for _ in cols) + "|")
    for _, r in summary.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines) + "\n"
