"""Walk-forward backtest of every model on every target.

Outputs (in reports/):
  backtest_fold_metrics.csv   metrics per target x model x month
  leaderboard.csv / .md       metrics on all out-of-sample predictions pooled
  predictions_<target>.parquet
  backtest_<target>.png       one sample week, actual vs best models
  experiments.jsonl           one line per run (copy key numbers to Notion "Experiments")
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

import pandas as pd

from energy_forecast.config import Config
from energy_forecast.features import leakage_check, make_xy
from energy_forecast.metrics import all_metrics
from energy_forecast.models import get_model
from energy_forecast.split import walk_forward

log = logging.getLogger(__name__)


def _models_for(cfg: Config, target: str, override: list[str] | None) -> list[str]:
    if override:
        return [m for m in override if not (m == "tso_forecast" and target == cfg["targets"]["price"])]
    key = "price" if target == cfg["targets"]["price"] else "production"
    return cfg["models"][key]


def run_backtest(cfg: Config, df: pd.DataFrame, targets: list[str] | None = None, models: list[str] | None = None,
                 n_folds: int | None = None, data_tag: str = "real") -> pd.DataFrame:
    tz = cfg.tz
    fc = cfg["forecast"]
    bt = cfg["split"]["backtest"]
    targets = targets or [t for t in cfg.all_targets if t in df.columns]
    reports = cfg.path("reports_dir")
    run_id = f"{datetime.now(timezone.utc):%Y%m%d-%H%M}-{uuid.uuid4().hex[:4]}"
    fold_rows, board_rows = [], []

    for target in targets:
        X, y = make_xy(df, target, tz=tz, min_lag_actuals=fc["min_lag_actuals_h"], min_lag_prices=fc["min_lag_prices_h"])
        bad = leakage_check(X)
        assert not bad, f"Leakage risk, same-time actual columns in features: {bad}"
        preds = pd.DataFrame({"y": y})
        folds = list(walk_forward(X.index, bt["first_test_month"], n_folds or bt["n_folds"], tz=tz))
        if not folds:
            raise ValueError(f"No backtest folds — data ends before {bt['first_test_month']}?")
        naive_col = f"{target}_lag168"
        for name in _models_for(cfg, target, models):
            t0 = time.time()
            p_all = []
            for fold in folds:
                model = get_model(name, target, X.columns, random_state=cfg["random_state"])
                model.fit(X.loc[fold.train_idx], y.loc[fold.train_idx])
                p = pd.Series(model.predict(X.loc[fold.test_idx]), index=fold.test_idx)
                if target.startswith("gen_"):
                    p = p.clip(lower=0)  # production cannot be negative
                p_all.append(p)
                yt = y.loc[fold.test_idx]
                fold_rows.append({"run_id": run_id, "target": target, "model": name, "fold": fold.name,
                                  "n_train": len(fold.train_idx),
                                  **all_metrics(yt, p, X.loc[fold.test_idx, naive_col] if naive_col in X else None, tz)})
            p_all = pd.concat(p_all)
            preds[name] = p_all
            yt = y.loc[p_all.index]
            m = all_metrics(yt, p_all, X.loc[p_all.index, naive_col] if naive_col in X else None, tz)
            board_rows.append({"run_id": run_id, "target": target, "model": name, "n_test": len(p_all),
                               "seconds": round(time.time() - t0, 1), **m})
            log.info("%-10s %-20s MAE=%.2f rMAE=%.3f", target, name, m["MAE"], m.get("rMAE", float("nan")))
        preds.dropna(subset=[c for c in preds.columns if c != "y"], how="all").to_parquet(reports / f"predictions_{target}.parquet")
        _plot_sample_week(preds, target, reports, tz)

    folds_df = pd.DataFrame(fold_rows)
    board = pd.DataFrame(board_rows).sort_values(["target", "MAE"])
    folds_df.to_csv(reports / "backtest_fold_metrics.csv", index=False)
    board.to_csv(reports / "leaderboard.csv", index=False)
    (reports / "leaderboard.md").write_text(_board_md(board, run_id, data_tag), encoding="utf-8")
    with open(reports / "experiments.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"run_id": run_id, "utc": datetime.now(timezone.utc).isoformat(), "data": data_tag,
                            "folds": len(folds), "first_test_month": bt["first_test_month"],
                            "leaderboard": board.round(4).to_dict(orient="records")}) + "\n")
    return board


def _board_md(board: pd.DataFrame, run_id: str, data_tag: str) -> str:
    lines = [f"# Backtest leaderboard — run `{run_id}` (data: {data_tag})", "",
             "Walk-forward, expanding window, monthly folds. Lower MAE/RMSE/rMAE is better; "
             "rMAE < 1 means the model beats the weekly seasonal-naive baseline.", ""]
    for target, g in board.groupby("target", sort=False):
        lines += [f"## {target}", "", "| model | MAE | RMSE | rMAE | sMAPE % | DirAcc | PeakHit |", "|---|---|---|---|---|---|---|"]
        for _, r in g.iterrows():
            lines.append(f"| {r.model} | {r.MAE:.2f} | {r.RMSE:.2f} | {r.get('rMAE', float('nan')):.3f} | "
                         f"{r.sMAPE:.1f} | {r.DirAcc:.3f} | {r.PeakHit:.3f} |")
        lines.append("")
    return "\n".join(lines)


def _plot_sample_week(preds: pd.DataFrame, target: str, reports, tz: str) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    model_cols = [c for c in preds.columns if c != "y"]
    sub = preds.dropna(subset=model_cols, how="all")
    if sub.empty:
        return
    week = sub.iloc[-24 * 7:].copy()
    week.index = week.index.tz_convert(tz)
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(week.index, week["y"], color="black", lw=2, label="actual")
    for c in model_cols:
        ax.plot(week.index, week[c], lw=1, alpha=0.8, label=c)
    ax.set_title(f"{target} — last backtest week (out-of-sample)")
    ax.legend(ncol=4, fontsize=8)
    fig.tight_layout()
    fig.savefig(reports / f"backtest_{target}.png", dpi=110)
    plt.close(fig)
