# Data validation report
- Period: 2022-01-01 00:00:00+00:00 → 2025-12-31 23:00:00+00:00 (35,064 hourly rows)
- Missing timestamps (re-indexed): 0
- Duplicate timestamps (dropped): 0
- Negative-price hours: 775
- Price spikes flagged (|robust z| > 6): 557
- Constant columns dropped: none

| column | missing % (after cleaning) | out-of-bounds removed | short gaps interpolated |
|---|---|---|---|
| gen_wind | 0.01 | 0 | 3 |
| price_da | 0.00 | 0 | 0 |
| price_da_FR | 0.00 | 0 | 0 |
| price_da_NL | 0.00 | 0 | 0 |
| price_da_DE_LU | 0.00 | 0 | 0 |
| load_actual | 0.00 | 0 | 40 |
| load_forecast | 0.00 | 0 | 0 |
| gen_solar | 0.00 | 0 | 0 |
| gen_nuclear | 0.00 | 0 | 0 |
| gen_gas | 0.00 | 0 | 0 |
| gen_total | 0.00 | 0 | 0 |
| fc_solar | 0.00 | 0 | 0 |
| fc_wind | 0.00 | 0 | 0 |
| fc_gen_total | 0.00 | 0 | 0 |
| w_brussels_temperature_2m | 0.00 | 0 | 0 |
| w_brussels_wind_speed_10m | 0.00 | 0 | 0 |
| w_brussels_shortwave_radiation | 0.00 | 0 | 0 |
| w_brussels_cloud_cover | 0.00 | 0 | 0 |
| w_offshore_wind_zone_wind_speed_10m | 0.00 | 0 | 0 |
| ttf_gas | 0.00 | 0 | 0 |
| eua_carbon | 0.00 | 0 | 0 |
| flag_price_spike | 0.00 | 0 | 0 |