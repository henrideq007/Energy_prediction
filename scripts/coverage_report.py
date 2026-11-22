"""Coverage of every column of dataset.parquet -> reports/data_coverage.md (+ .csv).

    python scripts/coverage_report.py

For each column: first / last non-missing hour, % missing over the full grid (2019 -> today),
% missing inside its own coverage window, and % missing in the backtest window (last 12 months).
Used to fill the Phase 1 exit criterion "all core columns < 2% missing" and the Notion inventory.
"""

from __future__ import annotations

import pandas as pd

from energy_forecast.config import ROOT, load_config

CORE_PREFIXES = ("price_da", "load_actual", "load_forecast", "gen_", "fc_", "w_", "ttf_gas", "eua_carbon")


def coverage(df: pd.DataFrame, bt_start: pd.Timestamp, last_actual: pd.Timestamp) -> pd.DataFrame:
    rows = []
    grid = df.loc[:last_actual]
    for c in df.columns:
        s = grid[c]
        nn = s.dropna()
        first, last = (nn.index.min(), nn.index.max()) if len(nn) else (pd.NaT, pd.NaT)
        inside = s.loc[first:last] if len(nn) else s
        rows.append({
            "column": c,
            "group": "core" if c.startswith(CORE_PREFIXES) else ("flag" if c.startswith("flag_") else "candidate"),
            "first": first, "last": last,
            "missing_pct_full": round(s.isna().mean() * 100, 2),
            "missing_pct_in_window": round(inside.isna().mean() * 100, 2),
            "missing_pct_backtest": round(s.loc[bt_start:].isna().mean() * 100, 2),
        })
    return pd.DataFrame(rows)


def main() -> None:
    cfg = load_config()
    df = pd.read_parquet(cfg.path("processed_dir") / "dataset.parquet")
    bt_start = pd.Timestamp(cfg["split"]["backtest"]["first_test_month"] + "-01", tz="UTC")
    last_actual = df["price_da"].dropna().index.max() if "price_da" in df else df.index.max()
    cov = coverage(df, bt_start, last_actual)
    out = ROOT / "reports"
    cov.to_csv(out / "data_coverage.csv", index=False)
    lines = [
        "# Data coverage",
        f"- Dataset: {len(df):,} hourly rows × {df.shape[1]} columns, {df.index.min()} → {df.index.max()}",
        f"- Missing % computed up to the last known BE price ({last_actual}); backtest window from {bt_start.date()}",
        "",
        "| column | group | first | last | missing % (2019→) | missing % (own window) | missing % (backtest) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in cov.itertuples():
        f = r.first.strftime("%Y-%m-%d") if pd.notna(r.first) else "—"
        la = r.last.strftime("%Y-%m-%d") if pd.notna(r.last) else "—"
        lines.append(f"| {r.column} | {r.group} | {f} | {la} | {r.missing_pct_full} | {r.missing_pct_in_window} | {r.missing_pct_backtest} |")
    (out / "data_coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    core = cov[cov.group == "core"]
    bad = core[core.missing_pct_full >= 2]
    print(f"{len(cov)} columns ({len(core)} core). Core columns >= 2% missing: {bad.column.tolist() or 'none'}")


if __name__ == "__main__":
    main()
