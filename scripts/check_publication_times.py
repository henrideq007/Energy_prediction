"""Are tomorrow's TSO forecasts already published? (decision D-16 — leakage check)

Our forecast is issued on D-1 at 10:00 Brussels time. A TSO forecast may only be used as a
same-time feature if it is available BEFORE that moment. The legal deadline for day-ahead
wind/solar and generation forecasts is 18:00 D-1 (Reg. 543/2013 art. 14), so we check it
empirically: run this script at a few times of day (e.g. 09:00, 09:45, 10:15, 12:00, 18:30)
on several days, and every run appends one line per series to reports/publication_times.csv.

    python scripts/check_publication_times.py            # BE + neighbours
    python scripts/check_publication_times.py --zones BE

Windows Task Scheduler (optional): create a task that runs
    <repo>\\.venv\\Scripts\\python.exe <repo>\\scripts\\check_publication_times.py
daily at 09:45 and 10:15 with "Start in" = <repo>.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import pandas as pd

from energy_forecast.config import ROOT, entsoe_api_key

TZ = "Europe/Brussels"
OUT = ROOT / "reports" / "publication_times.csv"


def check(zones: list[str]) -> list[dict]:
    from entsoe import EntsoePandasClient
    from entsoe.exceptions import NoMatchingDataError

    client = EntsoePandasClient(api_key=entsoe_api_key())
    now = pd.Timestamp.now(tz=TZ)
    d1 = (now + pd.Timedelta(days=1)).normalize()
    start, end = d1, d1 + pd.Timedelta(days=1)
    queries = {
        "load_forecast (A65)": lambda z: client.query_load_forecast(z, start=start, end=end),
        "wind_solar_forecast (A69)": lambda z: client.query_wind_and_solar_forecast(z, start=start, end=end),
        "generation_forecast (A71)": lambda z: client.query_generation_forecast(z, start=start, end=end),
        "day_ahead_prices (A44)": lambda z: client.query_day_ahead_prices(z, start=start, end=end),
    }
    rows = []
    for z in zones:
        for name, q in queries.items():
            status, n = "available", 0
            try:
                res = q(z)
                n = int(len(res))
                if n == 0:
                    status = "empty"
            except NoMatchingDataError:
                status = "not_published"
            except Exception as exc:  # network/API errors are logged, not fatal
                status = f"error: {type(exc).__name__}"
            rows.append({"checked_at_local": now.strftime("%Y-%m-%d %H:%M"), "delivery_day": str(d1.date()),
                         "zone": z, "series": name, "status": status, "n_points": n})
            print(f"{now:%H:%M} {z:<6} {name:<28} {status:<14} {n:>4} points")
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--zones", nargs="+", default=["BE", "FR", "NL", "DE_LU"])
    rows = check(p.parse_args().zones)
    OUT.parent.mkdir(exist_ok=True)
    new = not OUT.exists()
    with open(OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f"Appended {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
