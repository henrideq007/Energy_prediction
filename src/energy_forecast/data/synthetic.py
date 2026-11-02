"""Synthetic Belgian-like dataset with the same schema as the real one.

Used for tests, CI and the `demo` command so the full pipeline runs without
an API key. Numbers are plausible, NOT real — never report results on them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_synthetic(start: str = "2022-01-01", end: str = "2025-12-31", seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq="1h", tz="UTC", inclusive="left")
    n = len(idx)
    loc = idx.tz_convert("Europe/Brussels")
    hour = loc.hour.to_numpy()
    doy = loc.day_of_year.to_numpy()
    dow = loc.day_of_week.to_numpy()
    season = np.cos(2 * np.pi * (doy - 15) / 365.25)  # +1 winter, -1 summer

    temp = 11 - 8 * season + 4 * np.sin(2 * np.pi * (hour - 9) / 24) + rng.normal(0, 2.5, n)
    wind = np.clip(6 + 2.5 * season + np.cumsum(rng.normal(0, 0.35, n)) % 7 - 3.5 + rng.normal(0, 1.2, n), 0, None)
    daylen = 12 - 4 * season                                   # ~8h in winter, ~16h in summer
    sunrise = 13 - daylen / 2                                  # solar noon ~13:00 local
    sun_elev = np.clip(np.sin(np.pi * (hour - sunrise) / daylen), 0, None) * ((hour > sunrise) & (hour < sunrise + daylen))
    cloud = np.clip(55 + 15 * season + rng.normal(0, 25, n), 0, 100)
    radiation = 800 * sun_elev * (1 - 0.3 * season) * (1 - cloud / 140)

    load = 9500 + 1200 * season - 900 * (dow >= 5) + 1300 * np.sin(np.pi * np.clip(hour - 6, 0, 16) / 16) - 40 * (temp - 11)
    load = load + rng.normal(0, 250, n)
    gen_solar = 7.5 * radiation + rng.normal(0, 80, n).clip(0)
    gen_wind = np.clip(400 * wind ** 1.4 / 4, 0, 5500) + rng.normal(0, 150, n)
    gen_wind = gen_wind.clip(0)
    gen_nuclear = np.where(idx < pd.Timestamp("2025-02-15", tz="UTC"), 3900, 2000) + rng.normal(0, 60, n)
    residual = load - gen_solar - gen_wind - gen_nuclear
    gen_gas = np.clip(residual * 0.8 + 1500, 600, 7000)
    gen_other = 900 + rng.normal(0, 50, n)

    days = np.arange(n) / 24
    ttf = 35 + 25 * np.exp(-((days - 250) / 120) ** 2) + 5 * np.sin(days / 40) + np.cumsum(rng.normal(0, 0.05, n))
    eua = 75 + 8 * np.sin(days / 90) + np.cumsum(rng.normal(0, 0.03, n))
    marginal = 2.0 * ttf + 0.37 * eua
    price = marginal * (0.55 + 0.6 * np.tanh(residual / 4000)) + 12 * np.sin(np.pi * (hour - 5) / 12) + rng.normal(0, 9, n)
    price = np.where(gen_solar + gen_wind > load * 0.75, price - 80, price)  # negative-price episodes
    price = np.clip(price, -500, 5000)

    df = pd.DataFrame(
        {
            "price_da": price,
            "price_da_FR": price * 0.92 + rng.normal(0, 8, n),
            "price_da_NL": price * 1.02 + rng.normal(0, 6, n),
            "price_da_DE_LU": price * 0.97 + rng.normal(0, 10, n),
            "load_actual": load,
            "load_forecast": load + rng.normal(0, 300, n),
            "gen_solar": gen_solar,
            "gen_wind": gen_wind,
            "gen_nuclear": gen_nuclear,
            "gen_gas": gen_gas,
            "gen_total": gen_solar + gen_wind + gen_nuclear + gen_gas + gen_other,
            "fc_solar": gen_solar * rng.normal(1, 0.12, n),
            "fc_wind": gen_wind * rng.normal(1, 0.18, n),
            "fc_gen_total": (gen_solar + gen_wind + gen_nuclear + gen_gas + gen_other) * rng.normal(1, 0.03, n),
            "w_brussels_temperature_2m": temp,
            "w_brussels_wind_speed_10m": wind * 0.7,
            "w_brussels_shortwave_radiation": radiation,
            "w_brussels_cloud_cover": cloud,
            "w_offshore_wind_zone_wind_speed_10m": wind,
            "ttf_gas": ttf,
            "eua_carbon": eua,
        },
        index=idx,
    )
    # Inject realistic data-quality issues so the validation step has work to do
    df.iloc[rng.choice(n, 40, replace=False), df.columns.get_loc("load_actual")] = np.nan
    df.iloc[5000:5006, df.columns.get_loc("gen_wind")] = np.nan
    return df
