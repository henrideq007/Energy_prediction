# Data validation report
- Period: 2019-01-01 00:00:00+00:00 → 2026-10-27 23:00:00+00:00 (68,568 hourly rows)
- Missing timestamps (re-indexed): 0
- Duplicate timestamps (dropped): 0
- Negative-price hours: 1930
- Price spikes flagged (|robust z| > 6): 205
- Constant columns dropped: none

| column | missing % (after cleaning) | out-of-bounds removed | short gaps interpolated |
|---|---|---|---|
| gen_hydro | 29.03 | 0 | 17292 |
| price_da | 0.00 | 0 | 0 |
| price_da_FR | 0.00 | 0 | 0 |
| price_da_NL | 0.00 | 0 | 0 |
| price_da_DE_LU | 0.00 | 0 | 0 |
| load_actual | 0.00 | 0 | 0 |
| load_forecast | 0.00 | 0 | 0 |
| gen_solar | 0.00 | 0 | 0 |
| gen_wind | 0.00 | 0 | 0 |
| gen_nuclear | 0.00 | 0 | 0 |
| gen_gas | 0.00 | 0 | 0 |
| gen_biomass_waste | 0.00 | 0 | 0 |
| gen_total | 0.00 | 0 | 0 |
| fc_solar | 0.00 | 0 | 0 |
| fc_wind | 0.00 | 0 | 0 |
| fc_gen_total | 0.00 | 0 | 0 |
| w_brussels_temperature_2m | 0.00 | 0 | 0 |
| w_brussels_wind_speed_10m | 0.00 | 0 | 0 |
| w_brussels_shortwave_radiation | 0.00 | 0 | 0 |
| w_brussels_cloud_cover | 0.00 | 0 | 0 |
| w_antwerp_temperature_2m | 0.00 | 0 | 0 |
| w_antwerp_wind_speed_10m | 0.00 | 0 | 0 |
| w_antwerp_shortwave_radiation | 0.00 | 0 | 0 |
| w_antwerp_cloud_cover | 0.00 | 0 | 0 |
| w_liege_temperature_2m | 0.00 | 0 | 0 |
| w_liege_wind_speed_10m | 0.00 | 0 | 0 |
| w_liege_shortwave_radiation | 0.00 | 0 | 0 |
| w_liege_cloud_cover | 0.00 | 0 | 0 |
| w_offshore_wind_zone_temperature_2m | 0.00 | 0 | 0 |
| w_offshore_wind_zone_wind_speed_10m | 0.00 | 0 | 0 |
| w_offshore_wind_zone_shortwave_radiation | 0.00 | 0 | 0 |
| w_offshore_wind_zone_cloud_cover | 0.00 | 0 | 0 |
| flag_price_spike | 0.00 | 0 | 0 |