# %% [markdown]
# # 01 — Exploratory data analysis (T11)
# Run cell by cell in VS Code (Python Interactive: "Run Cell").
# Requires `data/processed/dataset_clean.parquet` (`python scripts/publish_data.py restore`
# then `python -m energy_forecast validate`). All logic lives in `energy_forecast.eda`;
# `python scripts/run_eda.py` writes the same tables + figures to `reports/eda/`.
# Descriptive only. `fc_*` (Elia 6PM run) may be described here but are baseline-only (D-16/D-29).

# %%
import matplotlib.pyplot as plt
import pandas as pd

from energy_forecast import eda
from energy_forecast.config import load_config

cfg = load_config()
df = eda.to_local(pd.read_parquet(cfg.path("processed_dir") / "dataset_clean.parquet"), cfg.tz)
df = eda.trim_to_valid(df)  # price span only (gas etc. run a little longer)
# NB: `ttf_gas` = IMF monthly proxy to Sep 2021, THE VTP daily after (D-25), stored with a 2-day lag.
df.info()

# %% Price regimes: weekly mean + TTF, and summary stats per regime / year
eda.plot_weekly_price(df)
plt.show()
display(eda.regime_summary(df).round(1))  # noqa: F821 (IPython)
display(eda.yearly_summary(df).round(1))  # noqa: F821

# %% Daily profiles by season and weekday/weekend, per regime
prof_season = eda.hourly_profile(df, by=("regime", "season"))
eda.plot_profiles(prof_season, "Mean hourly price by season, per regime")
plt.show()
prof_day = eda.hourly_profile(df, by=("regime", "daytype"))
eda.plot_profiles(prof_day, "Weekday vs weekend, per regime")
plt.show()
display(eda.profile_shape(prof_season).round(1))  # noqa: F821

# %% Negative prices: per year, hour x month heatmap, conditional on the Elia 11AM solar forecast
print(eda.negative_counts(df, "year"))
eda.plot_heatmap(eda.negative_heatmap(df, since="2023-07-01"), "Negative-price hours (%), Jul 2023 →", "%")
plt.show()
post = df[eda.label_regime(df.index) == "post_crisis"]
eda.negative_share_by_bins(post, post[eda.ELIA_11H["solar"]], [0, 1000, 2000, 3000, 4000, 5000, 6000, 9000])

# %% Merit order: price vs residual load forecast (Elia 11AM run, fc_* fallback flagged)
rl, src = eda.residual_load(df)
print(src.value_counts())
regime = eda.label_regime(df.index)
eda.plot_merit_order(eda.merit_order_bins(df["price_da"], rl, regime), "Merit order per regime")
plt.show()
eda.merit_order_slope(df["price_da"], rl, regime).round(2)

# %% Gas price vs price on daily means, proxy period excluded
eda.gas_price_correlation_daily(df).round(2)

# %% Correlations with core drivers (candidate families excluded, availability labelled)
eda.price_correlations(df).round(2)
