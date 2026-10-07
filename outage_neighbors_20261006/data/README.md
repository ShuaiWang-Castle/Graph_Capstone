# Data

Everything here comes from public sources. Nothing is taken or derived from restricted data.

## Files

| File | Content |
|---|---|
| `events.csv` | The 26 storm windows: first and last hour (UTC), number of counties, storm type of the day in the NOAA catalogue, peak customers out. |
| `events/<window>.npz` | One window of 169 hours. `fips` (n), `hours` (169, UTC), `outage_share` (n x 169, NaN where not observed), `customers` (n), `weather` (n x 169 x 12), `channels` (12). |
| `county_statics.csv` | 3,222 counties: `log_area`, `rucc`, `log_pop`, `log_pop_density`, `n_neighbours`, `n_utilities`, `coop_share`, `saidi`, `saifi`, `log_cust`, `log_cust_density`, `lat`, `lon`. |
| `storm_reports.csv.gz` | NOAA Storm Events rows of the window counties that begin inside the window: type, begin and end time (UTC), magnitude. |
| `geo/us_counties.geojson` | County outlines for maps. |
| `extra/derecho_2020-08-10.*`, `extra/spc_wind_reports_2020-08-10.csv` | The 10 August 2020 Midwest derecho: 118 counties x 168 hours from 06:00 UTC, a county table, and the wind reports of that day. |

## Definitions

- `outage_share` is customers without power divided by the county's customers, hourly. It is the mean of the
  15-minute values that were observed and carried a count; an hour with none is NaN.
- The source records omit zeros. The panels were densified upstream with an explicit observation mask: a missing
  cell counts as zero only if a collection run happened at that time and the county was reporting in that week;
  otherwise it stays unobserved. Unobserved cells are NaN here.
- `customers` is the modelled number of electric customers per county from the 2024 EAGLE-I release, applied to all
  years.
- All times are UTC.
- Weather channels: `cape` (J/kg), `cloud` (fraction), `gust` and `wind_speed` and `u10` and `v10` (m/s), `precip`
  (mm), `pressure` (Pa), `rh` (%), `snowfall`, `soil_moisture` (m3/m3), `t2m_c` (deg C). They are ERA5 fields at
  0.25 degrees, area-weighted onto counties.
- **A county whose weather block is entirely zero has no weather values.** This affects 22% to 81% of the counties
  in 18 of the 26 windows. Treat such blocks as missing, not as calm weather.
- Static columns: `rucc` is the USDA rural-urban continuum code (1 most urban, 9 most rural); `coop_share` the
  share of cooperative utilities among those serving the county; `saidi` and `saifi` the utility reliability
  indices from EIA-861 spread over the counties each utility serves, so they are approximate at county level.
- In the derecho files, `onset_hour` is the first hour at 20% of the county's peak, `restore_hours` the hours from
  the peak until the share falls to 10% of it (`censored` if that did not happen within the window), and
  `wind_report_hour` the median hour of the wind reports within 40 km of the county centroid. Hours count from
  06:00 UTC on 10 August 2020. The share uses the modelled county customers of the 2014-2022 EAGLE-I release.

## Sources and terms

| Data | Source | Terms |
|---|---|---|
| Outage records | EAGLE-I, Oak Ridge National Laboratory. "The Environment for Analysis of Geo-Located Energy Information's Recorded Electricity Outages 2014-2025", doi:10.6084/m9.figshare.24237376; ORNL records doi:10.13139/ORNLNCCS/1975202 and later yearly releases. | CC BY 4.0 |
| Weather | ERA5 hourly data on single levels, Copernicus Climate Change Service. Contains modified Copernicus Climate Change Service information; neither the European Commission nor ECMWF is responsible for any use made of it. | Licence to use Copernicus products |
| Storm reports | NOAA NCEI Storm Events Database; NOAA Storm Prediction Center storm reports. | U.S. government work |
| County centroids, area, adjacency, outlines | U.S. Census Bureau (Gazetteer 2023, county adjacency 2023, cartographic boundaries). | U.S. government work |
| Rural-urban codes | USDA Economic Research Service, Rural-Urban Continuum Codes 2023. | U.S. government work |
| Utilities and reliability | U.S. Energy Information Administration, Form EIA-861. | U.S. government work |

The storm windows, the densification rule, the county weighting of ERA5 and the static table were built in a
separate public-data project of the same author. `code/build_dataset.py` shows how those panels were reshaped into
the files here.
