"""Command line interface.

    energy-forecast fetch       download & assemble the raw dataset (needs ENTSOE_API_KEY)
    energy-forecast validate    clean + validate -> dataset_clean.parquet + reports/validation_report.md
    energy-forecast backtest    walk-forward comparison of all models -> reports/leaderboard.md
    energy-forecast train       fit the best model per target on all history -> models/
    energy-forecast predict     live 24h forecast for tomorrow (or --date) -> forecasts/
    energy-forecast explain     SHAP drivers of the price -> reports/shap_price_da.png
    energy-forecast demo        full pipeline on SYNTHETIC data (no API key needed)
"""

from __future__ import annotations

import argparse
import copy
import logging
import sys

import pandas as pd

from energy_forecast.config import Config, load_config


def _clean_dataset(cfg: Config) -> pd.DataFrame:
    path = cfg.path("processed_dir") / "dataset_clean.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return cmd_validate(cfg, argparse.Namespace())


def cmd_fetch(cfg: Config, a) -> None:
    from energy_forecast.data.build_dataset import build_dataset

    start = pd.Timestamp(a.start, tz="UTC") if a.start else None
    end = pd.Timestamp(a.end, tz="UTC") if a.end else None
    df = build_dataset(cfg, start, end, weather_source=a.weather_source)
    print(f"Dataset: {df.shape[0]:,} rows x {df.shape[1]} columns, {df.index.min()} -> {df.index.max()}")


def cmd_validate(cfg: Config, a) -> pd.DataFrame:
    from energy_forecast.data.build_dataset import load_dataset
    from energy_forecast.validation import clean_and_validate

    df, rep = clean_and_validate(load_dataset(cfg), price_col=cfg["targets"]["price"])
    df.to_parquet(cfg.path("processed_dir") / "dataset_clean.parquet")
    reports = cfg.path("reports_dir")
    (reports / "validation_report.md").write_text(rep.to_markdown(), encoding="utf-8")
    (reports / "validation_report.json").write_text(rep.to_json(), encoding="utf-8")
    print(rep.to_markdown())
    return df


def cmd_backtest(cfg: Config, a) -> None:
    from energy_forecast.backtest import run_backtest

    board = run_backtest(cfg, _clean_dataset(cfg), targets=a.targets, models=a.models, n_folds=a.folds,
                         data_tag=getattr(a, "data_tag", "real"))
    print((cfg.path("reports_dir") / "leaderboard.md").read_text(encoding="utf-8"))
    return board


def cmd_train(cfg: Config, a) -> None:
    from energy_forecast.train import train_final

    for t, m in train_final(cfg, _clean_dataset(cfg), targets=a.targets, model_override=a.model).items():
        print(f"{t:<10} -> {m['model']:<20} trained on {m['n_rows']:,} rows ({m['train_start'][:10]} -> {m['train_end'][:10]})")


def cmd_predict(cfg: Config, a) -> None:
    from energy_forecast.predict import predict_live

    day = pd.Timestamp(a.date).date() if a.date else None
    out = predict_live(cfg, day)
    print(out.round(1).to_string())


def cmd_explain(cfg: Config, a) -> None:
    from energy_forecast.explain import explain

    print(explain(cfg, _clean_dataset(cfg), target=a.target).head(20).to_string())


def cmd_demo(cfg: Config, a) -> None:
    """End-to-end run on synthetic data, isolated in */demo folders."""
    from energy_forecast.data.synthetic import make_synthetic
    from energy_forecast.predict import predict_from_frame, save_forecast

    raw = copy.deepcopy(cfg.raw)
    for k in ("processed_dir", "reports_dir", "models_dir", "forecasts_dir"):
        raw["paths"][k] = raw["paths"][k] + "/demo"
    raw["split"]["backtest"].update(first_test_month="2025-07", n_folds=a.folds or 3)
    raw["split"].update(test_start="2025-07-01")
    dcfg = Config(raw)
    print("=== DEMO on SYNTHETIC data — numbers are NOT real market results ===")
    df = make_synthetic(end="2026-01-01")
    df.to_parquet(dcfg.path("processed_dir") / "dataset.parquet")
    cmd_validate(dcfg, a)
    models = a.models or ["naive_day", "seasonal_naive_week", "tso_forecast", "ridge", "lightgbm"]
    ns = argparse.Namespace(targets=a.targets, models=models, folds=None, data_tag="synthetic", model=None)
    cmd_backtest(dcfg, ns)
    cmd_train(dcfg, ns)
    day = pd.Timestamp("2025-12-15").date()
    out = predict_from_frame(dcfg, df, day)
    save_forecast(dcfg, out, day)
    print(out.round(1).head(24).to_string())


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="energy-forecast", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None, help="path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("fetch"); s.add_argument("--start"); s.add_argument("--end")
    s.add_argument("--weather-source", choices=["archive", "historical_forecast"], default=None)
    sub.add_parser("validate")
    for name in ("backtest", "demo"):
        s = sub.add_parser(name)
        s.add_argument("--targets", nargs="+"); s.add_argument("--models", nargs="+"); s.add_argument("--folds", type=int)
    s = sub.add_parser("train"); s.add_argument("--targets", nargs="+"); s.add_argument("--model")
    s = sub.add_parser("predict"); s.add_argument("--date", help="delivery day YYYY-MM-DD (default: tomorrow)")
    s = sub.add_parser("explain"); s.add_argument("--target")

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(a.config)
    {"fetch": cmd_fetch, "validate": cmd_validate, "backtest": cmd_backtest, "train": cmd_train,
     "predict": cmd_predict, "explain": cmd_explain, "demo": cmd_demo}[a.cmd](cfg, a)


if __name__ == "__main__":
    sys.exit(main())
