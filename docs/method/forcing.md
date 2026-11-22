# Forcing study

Which meteorological archive should drive the NivoSense snow model over the Sierra Nevada?
This page records the archives that exist, how they are scored and what the scores say.
Every number here comes from `pipelines/forcing_study/study.py`. The commands are listed at the end.

**Status (2026-11-22): the snow-presence scores and the recommendation are pending on T1.7.**
They wait for the past-season Sentinel-2 snow masks, which are the scoring reference.
The precipitation comparison against stations is complete. The interim run on the current season only shows that the pipeline works. It is not a study result.

## 1. Archives that exist for 2023-09 to today

Every source below was queried live on 2026-11-22 at a point in the domain (37.06 N, 3.38 W, near Veleta).
The query pulled the full hourly series from 2023-09-01 to 2026-11-21 and counted the gaps (`study.py inventory`).

| Archive | Access | Grid near the massif | Period with data | Gaps (h) | Usable |
|---|---|---|---|---|---|
| ECMWF IFS HRES (`ecmwf_ifs`) | Open-Meteo archive API | about 9 km | full | 0 | yes: the model's current forcing |
| DWD ICON-EU (`icon_eu`) | Open-Meteo historical forecast API | 0.0625 deg, about 7 km | full | 0 | yes |
| NOAA GFS (`gfs_global`) | Open-Meteo historical forecast API | about 13 km | full | 0 | yes |
| Meteo-France ARPEGE Europe (`meteofrance_arpege_europe`) | Open-Meteo historical forecast API | 0.1 deg | full | 35 | yes (0.12% of hours, under the model's 2% gap rule) |
| ERA5 (`era5`) | Open-Meteo archive API | 0.25 deg | to about 6 days ago | 0 | as `era5_seamless` |
| ERA5-Land on Open-Meteo (`era5_land`) | Open-Meteo archive API | 0.1 deg | to about 6 days ago | 0 | temperature only: precipitation and radiation are empty |
| ERA5-Land + ERA5 (`era5_seamless`) | Open-Meteo archive API | 0.1 deg temperature, 0.25 deg precipitation | to about 6 days ago | 0 | yes: the no-key ERA5-family reference |
| ERA5-Land complete | Copernicus CDS (`reanalysis-era5-land`) | 0.1 deg | 1950 to about 5 days ago | n/a | pending: needs a CDS API key |
| DWD ICON global (`icon_global`) | Open-Meteo historical forecast API | about 13 km | full | 0 | not scored: coarser duplicate of ICON-EU |
| UK Met Office global 10 km | Open-Meteo historical forecast API | 10 km | full; shortwave only from 2025-01-02 | 0 | no: radiation missing for 2023-24 |
| ECCC GEM global | Open-Meteo historical forecast API | about 15 km | full | 0 | not scored: coarser |
| ECMWF IFS 0.25 deg open data (`ecmwf_ifs025`) | Open-Meteo historical forecast API | 0.25 deg | from 2024-02 | 243 (precipitation) | no: starts too late |
| ECMWF IFS analysis (`ecmwf_ifs_analysis_long_window`) | Open-Meteo archive API | about 9 km | precipitation stops 2024-11-11 | | no |
| CERRA | Open-Meteo archive API | 5.5 km | nothing after 2021 | | no |
| AROME France and France HD, KNMI and DMI HARMONIE-AROME | Open-Meteo historical forecast API | | "No data is available for this location" | | no: their domains end north of the massif |
| AEMET HARMONIE-AROME | AEMET | 2.5 km | current run only | | no: there is no open archive. AEMET publishes only the latest run (the colour-classified maps the forecast workflow reads), and our own forecast artifacts expire after 14 days |

The candidates approved for scoring are `ecmwf_ifs`, `icon_eu`, `gfs_global`, `meteofrance_arpege_europe` and `era5_seamless`, plus ERA5-Land from the CDS once a key exists.

Point totals at the inventory point vary widely by archive. For hydrological September to August 2023-24, 2024-25 and 2025-26, the totals in mm were:

| Archive | 2023-24 | 2024-25 | 2025-26 |
|---|---|---|---|
| ECMWF IFS | 988 | 980 | 1335 |
| ICON-EU | 1177 | 872 | 1506 |
| GFS | 843 | 783 | 1159 |
| ARPEGE Europe | 1000 | 629 | 1196 |
| ERA5 | 592 | 675 | 823 |

A spread of up to two to one at one point is why the choice matters.

### Access and licences

- **Open-Meteo.** The data are CC BY 4.0, credited to Open-Meteo and the source model's centre. The free API is for non-commercial use only. NivoSense is a non-profit public service, which falls under that use. The API limits clients to 600 calls a minute, 5,000 an hour and 10,000 a day. One call is one location with up to 10 variables and 2 weeks of data ([terms](https://open-meteo.com/en/terms)).
  - One season at the model's 0.1 deg request grid (65 points) costs about 1,700 calls per archive.
  - The study caches every response on disk and keeps a ledger that holds it under 90% of each limit. The full three-season fetch therefore takes about three days and is never repeated.
- **ERA5-Land from the Copernicus CDS.** Licensed CC BY 4.0. Access needs a free CDS account, the dataset licence accepted once on the website, and an API key. Only Mario can create these. The adapter (`pipelines/forcing_study/era5_land.py`) reads `CDSAPI_KEY` and runs as soon as the key exists.
- **RIA, the Red de Información Agroclimática de Andalucía (IFAPA, Junta de Andalucía).** An open REST service with no key. The data are CC BY-NC 4.0 (Junta de Andalucía open data portal). They are used here only for scoring and are never republished.
- **AEMET OpenData.** Free, but every request needs an API key, which is emailed to a person, so it has to be Mario's. Requests without a key are rejected. The station reader (`stations.py`) reads `AEMET_API_KEY` and is skipped without it.

## 2. Method

### Snow presence (the deciding score)

`study.py snow` runs the current model in `pipelines/snow_model` unchanged:

- the 100 m grid over the sub-basins of the domain;
- the Copernicus GLO-30 DEM;
- the lapse-rate and precipitation-gradient downscaling of the forcing to each cell, from the four nearest forcing points;
- the temperature-index snowpack with a radiation term.

The comparison is between forcings, so everything else is held fixed:

- **Same ensemble.** For every forcing the model runs the same 48-member Latin hypercube sample of the six parameters (`ensemble.PARAMETER_RANGES`, seed 1). A forcing with a wet or warm bias is not penalised for a fixed parameter choice: the ensemble lets each forcing find its own precipitation scale, lapse rate and melt factors.
- **Same calibration rule as the model.** Clear Sentinel-2 dates from the three hydrological years 2023-24, 2024-25 and 2025-26 are sorted by date. Every third date is held out (`validation.split_fit_test`). Members are weighted on the other two-thirds by their misclassification rate (`ensemble.tempered_weights`, target effective size 12).
- **Scored only on held-out dates.** The weighted ensemble's snow probability is thresholded at 0.5 and compared with the observed snow state of each 100 m cell. A cell counts as snow when at least half of its valid 20 m pixels are snow, and it is usable when at least half are valid (`validation.observed_snow`). The unweighted ensemble (the prior) is reported too.
- **Populations.**
  - All held-out dates, and the snow-season subset: dates where S2 sees snow on at least 1% of the usable cells, the rule the model's calibration gate already uses.
  - The whole domain, and by elevation band: under 1,500 m, 1,500 to 2,000, 2,000 to 2,500, 2,500 to 3,000, and 3,000 m and over.
  - Cells inside the ski resort are excluded through `--exclude` once its polygon exists (T2.3), because artificial snow is outside the model's reach.
- **Metrics.** The confusion matrix (tp, fp, fn, tn), accuracy and F1, plus the README Q3 measure: modelled snow where S2 sees bare ground, as a share of the modelled snow area.

The reference is the past-season observed snow cover from T1.7: the T1.2 classifier run over 2023-09-01 to 2025-09-30. The current season has no full-season reference yet.

### Precipitation against stations (a check, not the decision)

`study.py precip` compares each forcing's daily precipitation, taken at the station's coordinates, with the station record. The period is 1 October 2023 to 30 September 2026, every complete day both have.

- **Stations.** These are the open stations within 0.1 deg of the domain box. Six RIA stations qualify: Cádiar (928 m), Huéneja (1,110 m), Granada Camino del Purchil (630 m), Jerez del Marquesado (1,201 m), Padul (747 m) and Fiñana (958 m). AEMET stations join when the key exists.
- **What the stations can tell us.** The stations are agricultural and sit 1,000 to 2,500 m below the snow zone. They test the timing of precipitation events and the foothill bias. They are not snowpack truth, and they say nothing about the precipitation gradient with elevation, which the model calibrates.
- **Day boundary.** The RIA day boundary was checked empirically. Daily correlation peaks at a 00 UTC boundary (within one hour) and drops for a 06 to 07 UTC boundary. Forcings are therefore summed over UTC days for RIA. AEMET's climatological day runs from 07 to 07 UTC.
- **Metrics.**
  - The total ratio (forcing over station) and the Pearson r of daily and of 5-day totals.
  - For wet days (at least 1 mm), the probability of detection and the false alarm ratio.
  - Per station, then the median ratio and the mean of the others across stations.

## 3. Results

### Precipitation against RIA stations, October 2023 to September 2026 (final)

| Forcing | Median ratio | Mean daily r | Mean 5-day r | Wet-day POD | Wet-day FAR |
|---|---|---|---|---|---|
| ECMWF IFS | 1.57 | 0.71 | 0.78 | 0.89 | 0.43 |
| ICON-EU | 1.21 | 0.73 | 0.79 | 0.81 | 0.30 |
| GFS | 1.51 | 0.73 | 0.79 | 0.87 | 0.41 |
| ARPEGE Europe | 1.09 | 0.65 | 0.73 | 0.77 | 0.34 |
| ERA5-Land + ERA5 | 1.74 | 0.72 | 0.80 | 0.92 | 0.53 |
| ERA5-Land (CDS) | pending: CDS key | | | | |

Six stations, 1,063 to 1,095 days each. Per-station figures are in `precip.json`.

What the table shows:

- **Timing.** All five archives time foothill precipitation about equally well. Daily r is 0.71 to 0.73 for four of them and 0.65 for ARPEGE; 5-day r is 0.73 to 0.80.
- **Wet bias.** Every archive except ARPEGE is wetter than the foothill gauges, by 21% (ICON-EU) to 74% (ERA5-Land + ERA5).
  - Part of this is real. A forcing cell averages terrain up to the crest, and the gauges sit in the rain shadow of the valleys. Huéneja, Jerez del Marquesado and Fiñana, on the dry northern and eastern side, show the largest ratios for every archive.
  - Part of it is drizzle. The coarse archives make too many wet days: the false alarm ratio is 0.53 for ERA5-Land + ERA5.
- **The model absorbs part of the bias.** A constant volume bias is what the model's `precipitation_scale` parameter (0.7 to 1.6) and precipitation gradient absorb. The snow-presence scores, not these ratios, decide.

### Snow presence by elevation band (pending on T1.7)

Pending. The table fills from `snow.json` once the T1.7 masks exist. The forcing cache for 2023-24 to 2025-26 is being filled now: about three days under the Open-Meteo limits.

### Interim run on the current season (pipeline test only)

<!-- filled from the interim run -->

## 4. Recommendation

Pending on T1.7. The rule, fixed before the scores exist:

1. **Primary criterion.** Choose the forcing with the highest held-out snow-season F1 of the weighted ensemble, pooled over the three seasons, provided its Q3 false-snow share is no worse than the current forcing's (ECMWF IFS).
2. **Close calls.** When two forcings are within 0.01 F1, prefer the one with fewer false-snow cells in the 2,000 to 3,000 m bands, where the 2026-11-19 crest error happened.
   If they are still tied, prefer:
   - the one with the longer guaranteed archive and operational continuity;
   - then the one already used operationally (ECMWF IFS).
3. **Blends.** A blend (for example, temperature from one archive and precipitation from another) is considered only if each forcing wins different bands by more than 0.02 F1.

## 5. Reproduce

```bash
python -m pipelines.forcing_study.study inventory --end 2026-11-21 --cache .cache/forcing --output out
python -m pipelines.forcing_study.study fetch  --years 2023 2024 2025 --cache .cache/forcing --output out
python -m pipelines.forcing_study.study precip --years 2023 2024 2025 --cache .cache/forcing --output out
python -m pipelines.forcing_study.study snow   --years 2023 2024 2025 --reference <T1.7 cache> --cache .cache/forcing --output out
```

`CDSAPI_KEY` and `AEMET_API_KEY` in the environment add ERA5-Land and the AEMET stations.

## 6. Limits

- One reference sensor. Snow presence is scored against Sentinel-2 only, so SWE and depth magnitudes are not tested by this study.
- The forcing comparison inherits the model's own simplifications: no wind redistribution or sublimation (T2.3). A forcing can score well partly by compensating for missing physics. The ranking is therefore valid for the model as it is today and is rechecked after T2.3.
- Open-Meteo downscales temperature to the 90 m elevation of each requested point, and the model then applies its own lapse rate from that elevation. The same applies to every Open-Meteo forcing, so it does not favour one of them. ERA5-Land from the CDS comes at its own orography instead.
