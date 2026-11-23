"""Is tomorrow's data already published? (decision D-16 — leakage check)

Our forecast for day D is issued on D-1 at 11:00 Brussels time (D-29, `forecast.issue_hour_local`).
A series may only be used as a same-time feature if it is available BEFORE that moment. The legal
deadline for day-ahead wind/solar and generation forecasts is 18:00 D-1 (Reg. 543/2013 art. 14),
so we check empirically: the GitHub workflow `publication-times.yml` runs this script several times
a day (around 09:45, 10:15, 10:50, 11:05, 11:15, 12:00, 18:30) and every run appends one line per
series to reports/publication_times.csv (kept in the GitHub release `pubtimes`).

Sources (see energy_forecast.pubtimes): ENTSO-E (A65/A69/A71/A44, needs ENTSOE_API_KEY), Elia
near-real-time wind/solar "day-ahead 11AM" run, THE daily gas price, JAO Core flow-based domain.
A source that fails (network, missing key, missing package) gets "error: <Exception>" rows; the
others still run.

    python scripts/check_publication_times.py                       # everything (workflow default)
    python scripts/check_publication_times.py --zones BE --sources entsoe elia
    python scripts/check_publication_times.py --summarise           # verdict per series from the log
    python scripts/check_publication_times.py --summarise path/to/publication_times.csv

Windows Task Scheduler (optional): create a task that runs
    <repo>\\.venv\\Scripts\\python.exe <repo>\\scripts\\check_publication_times.py
daily at 10:50 and 11:15 with "Start in" = <repo>.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from energy_forecast import pubtimes
from energy_forecast.config import ROOT, load_config

OUT = ROOT / "reports" / "publication_times.csv"
SUMMARY_MD = ROOT / "reports" / "publication_times_summary.md"


def _summarise(path: Path, cutoff: str, write_md: bool) -> None:
    log_df = pd.read_csv(path, dtype=str)
    summary = pubtimes.summarise(log_df, cutoff=cutoff)
    with pd.option_context("display.width", 200, "display.max_columns", None, "display.max_rows", None):
        print(f"Cut-off {cutoff} Brussels — {len(log_df)} log rows from {path}")
        print(summary.to_string(index=False))
    if write_md:
        SUMMARY_MD.parent.mkdir(exist_ok=True)
        SUMMARY_MD.write_text(pubtimes.summary_markdown(summary, cutoff), encoding="utf-8")
        print(f"Wrote {SUMMARY_MD}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--zones", nargs="+", default=list(pubtimes.DEFAULT_ZONES), help="ENTSO-E zones")
    p.add_argument("--sources", nargs="+", choices=pubtimes.SOURCES, default=list(pubtimes.SOURCES))
    p.add_argument("--summarise", nargs="?", const=str(OUT), default=None, metavar="PATH",
                   help=f"summarise a log instead of checking (default {OUT.relative_to(ROOT)})")
    p.add_argument("--cutoff", default=None, metavar="HH:MM",
                   help="with --summarise: cut-off time (default forecast.issue_hour_local:00; try 11:11, the live job time)")
    p.add_argument("--no-md", action="store_true", help=f"with --summarise: do not write {SUMMARY_MD.name}")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()

    if args.summarise is not None:
        cutoff = args.cutoff or f"{int(cfg['forecast']['issue_hour_local']):02d}:00"
        pubtimes.parse_cutoff(cutoff)  # fail early on a malformed value
        _summarise(Path(args.summarise), cutoff, write_md=not args.no_md)
        return

    base_url = (cfg.get("elia") or {}).get("base_url", pubtimes.ELIA_DEFAULT_BASE_URL)
    rows = pubtimes.run_checks(sources=args.sources, zones=args.zones, elia_base_url=base_url)
    for r in rows:
        print(f"{r['checked_at_local'][-5:]} {r['delivery_day']} {r['zone']:<6} {r['series']:<36} "
              f"{r['status']:<22} {r['n_points']:>4} points")
    pubtimes.append_rows(rows, OUT)
    print(f"Appended {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
