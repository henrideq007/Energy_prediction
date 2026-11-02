# %% [markdown]
# # 01 — Exploratory data analysis
# Run cell by cell in VS Code (Python Interactive: "Run Cell").
# Requires `energy-forecast fetch` and `energy-forecast validate` to have been run.

# %%
import matplotlib.pyplot as plt
import pandas as pd

from energy_forecast.config import load_config

cfg = load_config()
df = pd.read_parquet(cfg.path("processed_dir") / "dataset_clean.parquet")
df.index = df.index.tz_convert(cfg.tz)
df.info()

# %% Price over time — note the 2021-2023 crisis regime
df["price_da"].resample("W").mean().plot(figsize=(12, 4), title="BE day-ahead price, weekly mean (EUR/MWh)")
plt.show()

# %% Daily profile by season
prof = df.assign(hour=df.index.hour, q=df.index.quarter).groupby(["q", "hour"])["price_da"].mean().unstack(0)
prof.plot(figsize=(10, 4), title="Average hourly price profile by quarter")
plt.show()

# %% Negative prices per year (solar-driven)
(df["price_da"] < 0).groupby(df.index.year).sum().plot.bar(title="Negative-price hours per year")
plt.show()

# %% Production mix
gen_cols = [c for c in df.columns if c.startswith("gen_") and c != "gen_total"]
df[gen_cols].resample("ME").mean().plot.area(figsize=(12, 4), title="Monthly mean generation by type (MW)")
plt.show()

# %% Price vs residual load forecast — the core fundamental relationship
if {"load_forecast", "fc_solar", "fc_wind"}.issubset(df.columns):
    rl = df["load_forecast"] - df["fc_solar"] - df["fc_wind"]
    recent = df.index >= "2023-07-01"
    plt.figure(figsize=(6, 5))
    plt.scatter(rl[recent], df.loc[recent, "price_da"], s=1, alpha=0.2)
    plt.xlabel("Residual load forecast (MW)"); plt.ylabel("Price (EUR/MWh)")
    plt.title("Merit-order effect (since mid-2023)")
    plt.show()

# %% Correlation of candidates with price
df.corr(numeric_only=True)["price_da"].sort_values().plot.barh(figsize=(6, 10))
plt.show()
