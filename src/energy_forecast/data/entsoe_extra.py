"""ENTSO-E — extra series collected in Phase 1 (candidate data points DP-025..DP-044).

None of these columns enter the model automatically: `features.py` only picks up the core
prefixes. Prefixes used here (decision D-24):

    nb_<ZONE>_*      neighbour fundamentals (FR, NL, DE_LU): load forecast, wind/solar forecast,
                     generation forecast, actual load, FR actual nuclear generation
    unav_*           nuclear unit unavailability (MW) AS KNOWN AT D-1 10:00 (leakage-free, D-27)
    xch_*            day-ahead scheduled exchanges / net position (auction RESULTS -> lag only)
    cap_BE_*         installed capacity per production type (yearly, forward-filled)
    hydro_res_*      weekly hydro reservoir filling (MWh, forward-filled)

Every series is cached in data/raw/entsoe like the core series.
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd

from energy_forecast.config import Config
from energy_forecast.data.entsoe_source import _cached_fetch, _client, call_with_retry
from energy_forecast.data.utils import month_chunks

log = logging.getLogger(__name__)
TZ = "Europe/Brussels"


# --------------------------------------------------------------------------- neighbours
def _neighbour_fundamentals(cfg: Config, client, start, end) -> pd.DataFrame:
    """DP-029, DP-030, DP-032..DP-036 (+ actual load and FR nuclear generation for lags)."""
    frames = []
    for nb in cfg["entsoe_extra"]["neighbour_zones"]:
        p = f"nb_{nb}_"
        lf = _cached_fetch(cfg, f"loadfc_{nb}", lambda s, e, nb=nb: client.query_load_forecast(nb, start=s, end=e), start, end)
        if not lf.empty:
            frames.append(lf.iloc[:, [0]].set_axis([p + "load_fc"], axis=1))
        la = _cached_fetch(cfg, f"load_{nb}", lambda s, e, nb=nb: client.query_load(nb, start=s, end=e), start, end)
        if not la.empty:
            frames.append(la.iloc[:, [0]].set_axis([p + "load_actual"], axis=1))
        ws = _cached_fetch(cfg, f"wsfc_{nb}", lambda s, e, nb=nb: client.query_wind_and_solar_forecast(nb, start=s, end=e), start, end)
        if not ws.empty:
            out = pd.DataFrame(index=ws.index)
            if "solar" in ws:
                out[p + "fc_solar"] = ws["solar"]
            wind = [c for c in ("wind_onshore", "wind_offshore") if c in ws]
            if wind:
                out[p + "fc_wind"] = ws[wind].sum(axis=1, min_count=1)
            frames.append(out)
        gf = _cached_fetch(cfg, f"genfc_{nb}", lambda s, e, nb=nb: client.query_generation_forecast(nb, start=s, end=e), start, end)
        if not gf.empty:
            frames.append(gf.iloc[:, [0]].set_axis([p + "fc_gen_total"], axis=1))
    # FR actual nuclear generation (proxy for FR nuclear availability, DP-031; lag-only use)
    if "FR" in cfg["entsoe_extra"]["neighbour_zones"]:
        g = _cached_fetch(cfg, "gennuc_FR", lambda s, e: client.query_generation("FR", start=s, end=e, psr_type="B14"), start, end)
        if not g.empty:
            frames.append(g.iloc[:, [0]].set_axis(["nb_FR_gen_nuclear"], axis=1))
    return pd.concat(frames, axis=1) if frames else pd.DataFrame()


# --------------------------------------------------------------------------- exchanges
def _exchanges(cfg: Config, client, start, end) -> pd.DataFrame:
    """DP-026: day-ahead scheduled commercial exchanges BE<->neighbour (net export, MW) and BE net position."""
    out = {}
    for nb in cfg["entsoe_extra"]["exchange_borders"]:
        exp = _cached_fetch(cfg, f"sched_BE_{nb}", lambda s, e, nb=nb: client.query_scheduled_exchanges("BE", nb, start=s, end=e, dayahead=True), start, end)
        imp = _cached_fetch(cfg, f"sched_{nb}_BE", lambda s, e, nb=nb: client.query_scheduled_exchanges(nb, "BE", start=s, end=e, dayahead=True), start, end)
        if not exp.empty or not imp.empty:
            e_ = exp.iloc[:, 0] if not exp.empty else 0.0
            i_ = imp.iloc[:, 0] if not imp.empty else 0.0
            out[f"xch_BE_{nb}_net_export"] = e_ - i_ if not (exp.empty or imp.empty) else (e_ if not exp.empty else -i_)
    npos = _cached_fetch(cfg, "netpos_BE", lambda s, e: client.query_net_position("BE", start=s, end=e, dayahead=True), start, end)
    if not npos.empty:
        out["xch_BE_net_position"] = npos.iloc[:, 0]
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- capacity & hydro
def _capacity(cfg: Config, client, start, end, index) -> pd.DataFrame:
    """DP-041: installed capacity per production type (published once a year)."""
    f = cfg.path("raw_dir") / "entsoe" / "capacity_BE.parquet"
    if f.exists() and pd.Timestamp(f.stat().st_mtime, unit="s", tz="UTC") > pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30):
        cap = pd.read_parquet(f)
    else:
        cap = call_with_retry(lambda: client.query_installed_generation_capacity(
            "BE", start=start.tz_convert(TZ), end=(end + pd.DateOffset(years=1)).tz_convert(TZ)), "capacity BE")
        cap.columns = [str(c).lower().replace(" ", "_").replace("-", "_").replace("/", "_") for c in cap.columns]
        cap.to_parquet(f)
    cap = cap.add_prefix("cap_BE_")
    cap.index = pd.DatetimeIndex(cap.index).tz_convert("UTC").normalize()
    # A value valid "from 1 Jan" is published at the start of the year -> safe to forward-fill.
    return cap.reindex(cap.index.union(index)).ffill().reindex(index)


def _hydro_reservoirs(cfg: Config, client, start, end, index) -> pd.DataFrame:
    """DP-044: weekly aggregated filling of reservoirs & hydro storage (MWh)."""
    out = {}
    for z in cfg["entsoe_extra"]["hydro_reservoir_zones"]:
        s = _weekly_fetch(cfg, client, z, start, end)
        if s is not None and not s.empty:
            # Published the week after; keep the raw week stamp here, the lag is applied in Phase 3.
            out[f"hydro_res_{z}_mwh"] = s.reindex(s.index.union(index)).ffill().reindex(index)
    return pd.DataFrame(out, index=index)


def _weekly_fetch(cfg, client, zone, start, end) -> pd.Series | None:
    from entsoe.exceptions import NoMatchingDataError

    f = cfg.path("raw_dir") / "entsoe" / f"hydrores_{zone}.parquet"
    if f.exists() and pd.Timestamp(f.stat().st_mtime, unit="s", tz="UTC") > pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3):
        return pd.read_parquet(f).iloc[:, 0]
    parts = []
    for s, e in month_chunks(start, end, 12):
        try:
            r = call_with_retry(lambda s=s, e=e: client.query_aggregate_water_reservoirs_and_hydro_storage(
                zone, start=s.tz_convert(TZ), end=e.tz_convert(TZ)), f"hydro reservoirs {zone} {s.date()}")
        except NoMatchingDataError:
            continue
        parts.append(r if isinstance(r, pd.Series) else r.iloc[:, 0])
        time.sleep(cfg["entsoe"]["request_sleep_s"])
    if not parts:
        return None
    s = pd.concat(parts)
    s.index = pd.DatetimeIndex(s.index).tz_convert("UTC")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.to_frame("mwh").to_parquet(f)
    return s


# --------------------------------------------------------------------------- outages
def _outage_messages(cfg: Config, client, zone: str, start, end) -> pd.DataFrame:
    """Raw unavailability messages (A80, generation units), cached per quarter."""
    from entsoe.exceptions import NoMatchingDataError

    cache = cfg.path("raw_dir") / "entsoe"
    today = pd.Timestamp.now(tz="UTC").floor("D")
    parts = []
    for s, e in month_chunks(start, end, 3):
        f = cache / f"unavail_{zone}_{s:%Y%m%d}_{e:%Y%m%d}.parquet"
        recent = e >= today - pd.Timedelta(days=40)  # outage plans keep being revised
        if f.exists() and not recent:
            parts.append(pd.read_parquet(f))
            continue
        log.info("ENTSO-E outages %s %s -> %s", zone, s.date(), e.date())
        try:
            u = call_with_retry(lambda s=s, e=e: client.query_unavailability_of_generation_units(
                zone, start=s.tz_convert(TZ), end=e.tz_convert(TZ)), f"outages {zone} {s.date()}")
        except NoMatchingDataError:
            u = pd.DataFrame()
        except Exception as exc:  # the outage endpoint is slow / flaky: keep going
            log.warning("Outages %s %s failed: %s", zone, s.date(), exc)
            continue
        u = _tidy_outages(u)
        u.to_parquet(f)
        parts.append(u)
        time.sleep(cfg["entsoe"]["request_sleep_s"])
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame()
    m = pd.concat(parts, ignore_index=True)
    return m.drop_duplicates(subset=["mrid", "revision", "start", "end", "avail_qty"])


def first_delivery_hour_known(t: pd.Series, issue_hour: int = 10) -> pd.Series:
    """First delivery hour (UTC) whose forecast is issued after information time t.

    Day D is forecast on D-1 at `issue_hour`:00 Brussels time, i.e. D 00:00 - (24 - issue_hour) h.
    A message created at t is therefore usable for every day D with D 00:00 >= t + (24 - issue_hour) h.
    """
    loc = pd.DatetimeIndex(t).tz_convert(TZ) + pd.Timedelta(hours=24 - issue_hour)
    d = loc.normalize()
    d = d.where(loc == d, d + pd.Timedelta(days=1))  # ceil to local midnight
    # rebuild midnights in local time (DST-safe) and go back to UTC
    d = pd.DatetimeIndex([pd.Timestamp(x.date(), tz=TZ) for x in d])
    return pd.Series(d.tz_convert("UTC"), index=t.index)


def unavailable_mw_known_at_issue(msgs: pd.DataFrame, index: pd.DatetimeIndex, plant_type: str | None,
                                  issue_hour: int = 10) -> pd.Series:
    """Hourly unavailable MW for delivery hour h, using ONLY the message revisions published before
    the forecast issue time of h (D-1 10:00). Later revisions / cancellations are ignored (no leakage)."""
    out = pd.Series(0.0, index=index)
    if msgs.empty:
        return out
    m = msgs if plant_type is None else msgs[msgs["plant_type"].str.contains(plant_type, case=False, na=False)]
    if m.empty:
        return out
    m = m.copy()
    m["created_doc_time"] = pd.to_datetime(m["created_doc_time"], utc=True)
    m["start"] = pd.to_datetime(m["start"], utc=True)
    m["end"] = pd.to_datetime(m["end"], utc=True)
    # validity window of each revision = [its publication, publication of the next revision of the same mrid)
    rev = (m.groupby(["mrid", "revision"], as_index=False)["created_doc_time"].min()
             .sort_values(["mrid", "revision"]))
    rev["next_created"] = rev.groupby("mrid")["created_doc_time"].shift(-1)
    m = m.merge(rev[["mrid", "revision", "next_created"]], on=["mrid", "revision"], how="left")
    m = m[~m["docstatus"].fillna("").str.contains("Cancel|Withdraw", case=False)]
    m["unav"] = (m["nominal_power"] - m["avail_qty"]).clip(lower=0)
    m = m[m["unav"] > 0]
    if m.empty:
        return out
    known_from = first_delivery_hour_known(m["created_doc_time"], issue_hour)
    known_until = first_delivery_hour_known(m["next_created"].fillna(pd.Timestamp("2200-01-01", tz="UTC")), issue_hour)
    lo = np.maximum(m["start"].values, known_from.values)
    hi = np.minimum(m["end"].values, known_until.values)
    vals = out.to_numpy().copy()
    idx = index.values
    for a, b, v in zip(lo, hi, m["unav"].to_numpy()):
        if a >= b:
            continue
        i0, i1 = np.searchsorted(idx, a, "left"), np.searchsorted(idx, b, "left")
        vals[i0:i1] += v
    return pd.Series(vals, index=index)


def revision_history(cfg: Config, client, zone: str, msgs: pd.DataFrame, workers: int = 10,
                     min_hours: int = 48) -> pd.DataFrame:
    """All revisions of every message in `msgs` (the period query only returns the LATEST revision).

    One request per mRID (only for mRIDs whose latest revision is > 1), run on a few threads and
    cached incrementally in data/raw/entsoe/unavail_hist_<zone>.parquet.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from entsoe.exceptions import NoMatchingDataError

    f = cfg.path("raw_dir") / "entsoe" / f"unavail_hist_{zone}.parquet"
    f.parent.mkdir(parents=True, exist_ok=True)
    hist = pd.read_parquet(f) if f.exists() else pd.DataFrame()
    latest = msgs.groupby("mrid")["revision"].max()
    have = hist.groupby("mrid")["revision"].max() if not hist.empty else pd.Series(dtype=float)
    # (re)query mRIDs with several revisions whose cached history is missing or older than the latest one
    # query window = the message's own event period +/- 6 months (revisions may move the dates);
    # entsoe-py splits long windows into yearly requests, so a narrow window keeps it to 1-2 calls
    span = (msgs.assign(start=pd.to_datetime(msgs["start"], utc=True), end=pd.to_datetime(msgs["end"], utc=True))
                .groupby("mrid").agg(a=("start", "min"), b=("end", "max")))
    # Only outages >= min_hours need their history: they hold ~99% of the unavailable MWh (BE 99.2%,
    # FR 98.5%, checked 4 Nov 2026). Shorter ones keep their latest revision, which is still leakage-free
    # (it only counts from its own publication time) — short forced outages are rarely known at D-1 anyway.
    long_ = (span["b"] - span["a"]) >= pd.Timedelta(hours=min_hours)
    bad_f = f.with_name(f"unavail_hist_{zone}_rejected.txt")  # mRIDs the API rejects (HTTP 400): don't retry
    rejected = set(bad_f.read_text().split()) if bad_f.exists() else set()
    todo = [m for m, r in latest.items()
            if r > 1 and long_.get(m, False) and have.get(m, 0) < r and m not in rejected]
    log.info("Outage revision history %s: %s mRIDs to query (%s cached)", zone, len(todo), len(have))
    far = pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=400)

    def one(mrid):
        a = span.at[mrid, "a"] - pd.Timedelta(days=183)
        b = min(span.at[mrid, "b"], far) + pd.Timedelta(days=183)
        try:
            u = call_with_retry(lambda: client.query_unavailability_of_generation_units(
                zone, start=a.tz_convert(TZ), end=b.tz_convert(TZ), mRID=mrid), f"outage history {zone}")
        except NoMatchingDataError:
            return None
        except Exception as exc:
            log.warning("%s", exc)
            if "HTTP 400" in str(exc):
                rejected.add(mrid)
            return None
        return _tidy_outages(u)

    new_parts = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, m) for m in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            if r is not None and not r.empty:
                new_parts.append(r)
            if i % 100 == 0 or i == len(futs):
                hist = pd.concat([hist, *new_parts], ignore_index=True) if new_parts else hist
                new_parts = []
                if not hist.empty:
                    hist = hist.drop_duplicates(subset=["mrid", "revision", "start", "end", "avail_qty"])
                    hist.to_parquet(f)
                log.info("Outage revision history %s: %s / %s", zone, i, len(futs))
    if rejected:
        bad_f.write_text(" ".join(sorted(rejected)))
    # every message without a fetched history (single revision, short, or failed query) keeps its latest revision
    rest = msgs[~msgs["mrid"].isin(hist["mrid"])] if not hist.empty else msgs
    out = pd.concat([hist, rest], ignore_index=True) if not hist.empty else rest
    return out.drop_duplicates(subset=["mrid", "revision", "start", "end", "avail_qty"])


def _tidy_outages(u: pd.DataFrame) -> pd.DataFrame:
    if u is None or u.empty:
        return pd.DataFrame()
    u = u.reset_index().rename(columns={"index": "created_doc_time"})
    keep = ["created_doc_time", "mrid", "revision", "docstatus", "businesstype", "plant_type",
            "production_resource_name", "nominal_power", "avail_qty", "start", "end"]
    u = u[[c for c in keep if c in u.columns]].copy()
    for c in ("nominal_power", "avail_qty", "revision"):
        u[c] = pd.to_numeric(u[c], errors="coerce")
    for c in ("docstatus", "businesstype", "plant_type", "production_resource_name", "mrid"):
        u[c] = u[c].astype("string")
    return u


def _outages(cfg: Config, client, start, end, index) -> pd.DataFrame:
    """DP-025 (BE nuclear) and DP-031 (FR nuclear): unavailable MW as known at D-1 10:00 (D-27).

    Uses the FULL revision history of each nuclear outage message. Other plant types are not
    rebuilt (their history would need ~23k extra requests); an ex-post version would leak.
    """
    issue = cfg["forecast"]["issue_hour_local"]
    out = {}
    for zone in cfg["entsoe_extra"]["outage_zones"]:
        msgs = _outage_messages(cfg, client, zone, start, end)
        log.info("Outage messages %s: %s rows", zone, len(msgs))
        if msgs.empty:
            continue
        nuc = msgs[msgs["plant_type"].str.contains("Nuclear", case=False, na=False)]
        full = revision_history(cfg, client, zone, nuc)
        log.info("Nuclear outage revisions %s: %s rows for %s mRIDs", zone, len(full), full["mrid"].nunique())
        out[f"unav_{zone}_nuclear_mw"] = unavailable_mw_known_at_issue(full, index, "Nuclear", issue)
    return pd.DataFrame(out, index=index)


# --------------------------------------------------------------------------- entry point
def fetch_entsoe_extra(cfg: Config, start: pd.Timestamp, end: pd.Timestamp, index: pd.DatetimeIndex) -> pd.DataFrame:
    xcfg = cfg.get("entsoe_extra") or {}
    if not xcfg.get("enabled", False):
        return pd.DataFrame(index=index)
    client = _client()
    blocks = []
    steps = [
        ("neighbours", lambda: _neighbour_fundamentals(cfg, client, start, end)),
        ("exchanges", lambda: _exchanges(cfg, client, start, end)),
        ("capacity", lambda: _capacity(cfg, client, start, end, index)),
        ("hydro reservoirs", lambda: _hydro_reservoirs(cfg, client, start, end, index)),
        ("outages", lambda: _outages(cfg, client, start, end, index)),
    ]
    for name, fn in steps:
        try:
            b = fn()
            log.info("ENTSO-E extra %s: %s cols", name, b.shape[1])
            if not b.empty:
                blocks.append(b)
        except Exception as exc:  # one failing block must not kill the whole fetch
            log.warning("ENTSO-E extra block '%s' failed: %s", name, str(exc).split("securityToken")[0])
    if not blocks:
        return pd.DataFrame(index=index)
    return pd.concat([b.reindex(index) for b in blocks], axis=1)
