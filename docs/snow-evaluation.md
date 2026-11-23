# NivoSense snow model v2: evaluation against v1 and in-situ data

Date: 2026-11-23. Author: evaluation agent (Claude), for the owner of NivoSense.
Scope: the evidence that decides whether v2 can replace v1, and what the data can and cannot prove. No model code was changed. Everything below was computed by `scripts/snow_v2_evaluation.py` (logic in `qa/validation/evaluation.py`, tests in `tests/qa_validation/test_evaluation.py`); the raw tables are in `docs/snow-evaluation/`.

Conventions: "held out" means the scored dates were not assimilated. "In sample" means they were. Errors are model minus reference. Water years are named by the year they end in (2025 is 2024-10-01 to 2025-09-30), as in the catalogue. Seeds are fixed (`season_seed`, one fixed resampling seed); the numbers reproduce.

## 0. Straight answers

**C.1 Can v2 replace v1 on the site today?** As the source of snow cover, yes: where v1 exists, v2 is better on every presence metric, and it has no gap in the record. As a validated SWE and depth product, no: it does not reach the section 5.4 gate of `snow-methodology.md`, and neither does v1.

- Snow presence against Sentinel-2, WY2025, 18 dates where v1 did not insert the observation: v1 F1 0.692, MCC 0.650; v2 prior median F1 0.744, MCC 0.692; v2 particle batch smoother (PBS), held out, F1 0.755, MCC 0.700. On all 21 dates with a v1 entry: v1 0.781 / 0.736, v2 prior 0.813 / 0.760, v2 PBS held out 0.818 / 0.764. Snow area bias: v1 -21 % (-28 % on the 18), v2 prior -3 % (-7 %). Snow line: v1 is 168 m too high on average (median +183 m), v2 prior +30 m (median -15 m).
- v1 is not held out in this comparison (it was calibrated on WY2025 Sentinel-2 dates and inserts the observation on 3 of the 21 dates), and v2 prior uses no Sentinel-2 data at all, so the comparison favours v1 if anything.
- The v2 gains are modest, v1 only exists for 21 dates of one season (3 November 2024 to 30 March 2025, accumulation season only), and v2 is only 0.03 to 0.05 F1 better. The three-season v2 range is F1 0.72 to 0.86 (WY2024 0.747, WY2025 0.809, WY2026 0.855 for PBS held out; prior 0.722, 0.815, 0.839). The gate asks for 0.90 overall and 0.80 in every 200 m band holding at least 5 % of the snow cells. v2 passes the band gate in 5 of 6 qualifying bands in WY2025 and 6 of 7 in WY2026 (WY2024: 0 of 6 for the prior and 3 of 6 for the PBS) and fails the overall gate in every season. In the thin-snow 1,700 and 1,800 m bands F1 is 0.08 and 0.31 for v1 and 0.27 and 0.34 for the v2 prior (WY2025, 21 dates).
- Camera snow depth (Poqueira, 2510 m, four seasons): v2 prior median RMSE 0.300 m, bias +0.017 m, correlation 0.53, KGE 0.37, against gate values of RMSE at most 0.30 m, absolute bias at most 0.10 m, correlation at least 0.8 (the gate is stated for days with snow; the numbers here are over all 1,216 camera days). It fails on correlation and sits on the RMSE limit with a bias made of +0.28 m and -0.13 m season errors that cancel. v1 cannot be scored: it has no entries before October 2024.
- The PBS does not help: held-out presence F1 is within 0.03 of the prior in every season (Brier worse in two of three), and the MODIS-fSCA PBS makes the camera depth clearly worse (RMSE 0.505 m, bias +0.199 m, 80 % interval covers 32 % of snow days). What beats v1 is the v2 structure and priors, not the assimilation.

**C.2 What does the evidence say about SWE magnitude, and how much trust?** Little trust in the number, reasonable trust in the pattern and timing. Nothing in this repository measures SWE; the camera measures depth at one 30 x 30 m plot. At that plot the v2 prior median peak depth was 1.89, 0.89, 0.17 and 0.48 m against 1.04, 1.19, 0.41 and 0.88 m observed (a factor of 1.8 too high, 0.75, 0.41 and 0.54), so one season at one point can be wrong by a factor of two in either direction; the 80 % interval (p10 to p90, a factor of 4 to 7 wide) held the observed peak in 3 of 4 seasons. The daily median is no better than predicting no snow at all (RMSE 0.300 m against 0.277 m for zero depth) and worse than the camera's own climatology of the other seasons (0.223 m). The error is mostly forcing: ERA5 precipitation is 0.59 to 1.07 of the high-elevation gauge totals by water year (0.69 to 0.83 pooled) and ERA5 is 1.2 C too cold at the camera's own gauge; IFS precipitation in WY2018 was 1.08 to 1.58 of the gauges at three stations and 28 to 57 % above ERA5 at the same points. Correcting ERA5 toward that one gauge (precipitation x1.34 to x1.68, temperature +1.0 to +1.45 C) cut the camera RMSE from 0.300 to 0.228 m. Assimilating snow cover does not fix magnitude: in the twin tests the season multiplier b0 was recovered within 10 % in only 4 and 6 of 10 cases, and fSCA PBS on the camera pushed b0 up and the depth too high. Treat SWE as a model estimate that can be off by a factor of two per season; the ensemble spread is the honest statement of that.

**C.3 What single measurement would most improve the product?** Daily snow depth from the ERHIN snow poles (pertigas) of the Confederacion Hidrografica del Guadalquivir, 21 of them in Sierra Nevada according to the official page read for the methodology review, for the Sentinel-2 years (2016 to today), with the station list, coordinates, elevations, any density or SWE readings and the licence. What to ask for: the depth series, the station metadata, whether poles have a co-located precipitation gauge, and the data policy. Why this one: it is multi-site and multi-elevation (the camera is one point), it overlaps the seasons for which we have Sentinel-2, v1 and v2, and it gives the only handle on the thing the data cannot yet constrain (precipitation and temperature bias by season and elevation). The PG2 result shows how much one co-located gauge is worth: it removed about a quarter of the depth RMSE. Next in line: the UGR/UCO snow-pole depth and temperature series under moratorium (PANGAEA 992415, 992412, 992414, 991999), the Guadalfeo stations after 2018 (the PANGAEA files end on 2018-08-31), Cetursa snow depth outside the pistes, and AEMET Pradollano (5511).

**C.4 What the site should show now.** Honest and still useful:

1. Show the Sentinel-2 observed snow cover as the primary layer, labelled as an observation with its date.
2. Show modelled snow cover as a probability (share of ensemble members with SWE of at least 5 mm) with the snow line altitude and its spread, from the v2 prior ensemble. Do not switch the PBS on yet: it has no held-out gain. State the known behaviour: the snow line errs by 100 to 200 m and the snow area by 20 % either way, with the sign changing between seasons (WY2024 -23 %, WY2026 +22 % for the prior), because precipitation is unknown.
3. Show snow depth as a range (p10, p50, p90), labelled "estimacion del modelo, comprobada solo en un punto (2009 a 2013)", not as a single map of centimetres.
4. Do not show SWE in mm or the basin water volume as a number. If a SWE layer must stay, show it only as the p10 to p90 range with "sin validar con medidas; incertidumbre de un factor 2 o mas", and take the basin volume chart off until pole data exist.
5. Do not use the word "validated". The gate in section 5.4 is not met by v1 or v2, and the accuracy of the Sentinel-2 reference itself (94 % for HR-S&I) caps what can be shown.

## 1. What was run

| Item | Value |
|---|---|
| Code | `scripts/snow_v2_evaluation.py` (commands `sentinel`, `camera`, `forcing`), `qa/validation/evaluation.py` |
| v1 | prod catalogue layers `swe` in mm (SWE of at least 5 mm is snow), read over HTTPS; entries exist only from 2024-10-17 |
| v2 prior | 1,000 members of `sample_parameters` with the default priors (the all-season priors of `regions/sierra-nevada.snow-priors.json` equal the defaults, b0 median 1.0, CV 0.4, dT sd 1.5; the per-fold values differed only in the b0 CV, 0.25 to 0.6), Open-Meteo `ecmwf_ifs` forcing as in v1, 1,067 classes, median over members |
| v2 PBS | the same ensemble weighted by `pbs_weights(cost(...))`, `n_corr` 3, effective size tempered to 30 |
| Hold-out | dates dealt to 3 folds in 12 day blocks counted from 1 October; each fold scored with weights from the other two folds. The in-sample PBS (all dates assimilated) is shown for reference only |
| Reference | `snow_obs` of the catalogue (WY2024 42 dates, WY2025 47, WY2026 76); a 100 m cell is decided when half of its 20 m pixels are decisive and holds snow when half are snow; ski resort excluded; only cells inside a model class are scored (97.7 % of the domain cells) |
| Camera | PANGAEA 871706 (Pimentel, Herrero and Polo 2017, CC-BY-3.0), MODIS MOD10A1 and MYD10A1 v061 fSCA from the Planetary Computer, ERA5 hourly forcing from Open-Meteo (`era5`, not `era5_land`) through `pipelines/snow_model_v2/forcing.py` |
| Forcing check | Guadalfeo stations PG1, PG2, PG4, PG5 (PANGAEA 895236, CC-BY-4.0), daily to 2018-08-31 |
| Outputs | `docs/snow-evaluation/*.csv` and `*.json` |

One trap found, not changed: `forcing.fetch_season_forcing` names a water year by the year it starts in (`water_year=2024` is 2024-10-01 to 2025-09-30), while `experiments.load_season`, the catalogue and this document name it by the year it ends in. The script converts explicitly; the first run of the camera series was wrong for that reason and was discarded.

## 2. A. Sentinel-2 snow presence, SWE of at least 5 mm

### 2.1 Headline scores (pooled over dates; PBS held out unless marked)

All dates of each season. v1 has entries only for WY2025, so its row covers 21 of the 47 dates and is not comparable with the v2 rows of that season; the like-for-like rows follow.

| Water year | Model | Dates | F1 | MCC | Snow area bias | Snow line error, mean (m) | Snow line error, MAE (m) |
|---|---|---|---|---|---|---|---|
| 2024 | v2 prior median | 42 | 0.722 | 0.696 | -23 % | +89 | 192 |
| 2024 | v2 PBS, held out | 42 | 0.747 | 0.710 | +18 % | -106 | 229 |
| 2024 | v2 PBS, in sample (reference only) | 42 | 0.758 | 0.723 | +17 % | -107 | 211 |
| 2024 | v2 prior, median fSCA >= 0.5 | 42 | 0.703 | 0.679 | -28 % | +155 | 238 |
| 2024 | v2 PBS held out, median fSCA >= 0.5 | 42 | 0.749 | 0.716 | -10 % | +45 | 186 |
| 2025 | v1 (site today) | 21 | 0.781 | 0.736 | -21 % | +168 | 208 |
| 2025 | v2 prior median | 47 | 0.815 | 0.784 | -0 % | -34 | 130 |
| 2025 | v2 PBS, held out | 47 | 0.809 | 0.778 | +18 % | -132 | 185 |
| 2025 | v2 PBS, in sample (reference only) | 47 | 0.815 | 0.785 | +18 % | -136 | 180 |
| 2025 | v2 prior, median fSCA >= 0.5 | 47 | 0.813 | 0.781 | +2 % | -27 | 112 |
| 2025 | v2 PBS held out, median fSCA >= 0.5 | 47 | 0.811 | 0.779 | +0 % | +2 | 135 |
| 2026 | v2 prior median | 76 | 0.839 | 0.820 | +22 % | -170 | 208 |
| 2026 | v2 PBS, held out | 76 | 0.855 | 0.836 | +14 % | -114 | 167 |
| 2026 | v2 PBS, in sample (reference only) | 76 | 0.857 | 0.839 | +15 % | -127 | 170 |
| 2026 | v2 prior, median fSCA >= 0.5 | 76 | 0.864 | 0.847 | +16 % | -79 | 124 |
| 2026 | v2 PBS held out, median fSCA >= 0.5 | 76 | 0.867 | 0.849 | +2 % | +2 | 101 |

Rows with "median fSCA >= 0.5" use the sub-grid snow covered fraction of the model instead of the SWE threshold; they are an extra, not the requested score.

WY2025 on the 21 dates that have a v1 entry (3 of them with the Sentinel-2 mask inserted into v1, so v1 is not independent there):

| Water year | Model | Dates | F1 | MCC | Snow area bias | Snow line error, mean (m) | Snow line error, MAE (m) |
|---|---|---|---|---|---|---|---|
| 2025 | v1 (site today) | 21 | 0.781 | 0.736 | -21 % | +168 | 208 |
| 2025 | v2 prior median | 21 | 0.813 | 0.760 | -3 % | +30 | 151 |
| 2025 | v2 PBS, held out | 21 | 0.818 | 0.764 | +9 % | -41 | 150 |
| 2025 | v2 PBS, in sample (reference only) | 21 | 0.826 | 0.775 | +9 % | -48 | 138 |
| 2025 | v2 prior, median fSCA >= 0.5 | 21 | 0.815 | 0.761 | +8 % | -41 | 150 |
| 2025 | v2 PBS held out, median fSCA >= 0.5 | 21 | 0.810 | 0.756 | +1 % | +42 | 171 |

WY2025 on the 18 dates where v1 did not insert the observation (the independent test of v1):

| Water year | Model | Dates | F1 | MCC | Snow area bias | Snow line error, mean (m) | Snow line error, MAE (m) |
|---|---|---|---|---|---|---|---|
| 2025 | v1 (site today) | 18 | 0.692 | 0.650 | -28 % | +184 | 230 |
| 2025 | v2 prior median | 18 | 0.744 | 0.692 | -7 % | +50 | 162 |
| 2025 | v2 PBS, held out | 18 | 0.755 | 0.700 | +10 % | -34 | 161 |
| 2025 | v2 PBS, in sample (reference only) | 18 | 0.768 | 0.716 | +9 % | -42 | 147 |
| 2025 | v2 prior, median fSCA >= 0.5 | 18 | 0.753 | 0.698 | +11 % | -40 | 167 |
| 2025 | v2 PBS held out, median fSCA >= 0.5 | 18 | 0.740 | 0.684 | +1 % | +57 | 191 |

What is held out and what is not: the "v2 prior" rows use no observation. The "v2 PBS, held out" rows were never fitted to the dates they are scored on. The "in sample" rows are for comparison only. v1 was calibrated on Sentinel-2 dates of WY2025 and inserts the mask when it has one, so its WY2025 numbers are not held out.

Findings:

- v2 prior beats v1 where both exist, by 0.03 F1 on the 21 dates and 0.05 on the 18 independent dates, and removes most of its snow-area deficit.
- PBS held out is within 0.03 F1 of the prior in all three seasons (+0.025, -0.006, +0.016) and in sample the gain is at most 0.01 higher again. The Brier score of the ensemble probability of SWE of at least 5 mm is worse for the PBS in WY2024 (0.055 against 0.044) and WY2025 (0.048 against 0.039) and about equal in WY2026 (0.030 against 0.031). This agrees with the assimilation agent's held-out CRPS of fSCA (prior 0.0277, PBS 0.0283).
- The PBS changes the sign of the snow area bias (WY2024 prior -23 %, PBS +18 %; WY2025 -0 % and +18 %) without improving F1: it trades misses for false alarms.
- Season to season the prior moves from -23 % to +22 % snow area, the signature of a precipitation multiplier that is unknown and varies by season.

### 2.2 Snow line altitude

Snow line per date: the elevation z that best separates snow (above) from bare (below) among the decided cells (fewest misclassified cells, `evaluation.snow_line`); defined for dates with at least 200 decided cells and both classes present. Error is model minus Sentinel-2.

| Water year | Dates | Model | Dates with a snow line | Median error (m) | Median abs error (m) | 90th percentile abs error (m) |
|---|---|---|---|---|---|---|
| 2024 | all dates | v2 prior median | 37 | +63 | 139 | 403 |
| 2024 | all dates | v2 PBS, held out | 38 | -161 | 198 | 397 |
| 2025 | all dates | v1 (site today) | 21 | +183 | 185 | 296 |
| 2025 | all dates | v2 prior median | 43 | -52 | 96 | 297 |
| 2025 | all dates | v2 PBS, held out | 43 | -127 | 139 | 392 |
| 2025 | v1 dates | v1 (site today) | 21 | +183 | 185 | 296 |
| 2025 | v1 dates | v2 prior median | 21 | -15 | 102 | 297 |
| 2025 | v1 dates | v2 PBS, held out | 21 | -99 | 102 | 285 |
| 2026 | all dates | v2 prior median | 46 | -197 | 199 | 306 |
| 2026 | all dates | v2 PBS, held out | 47 | -147 | 162 | 280 |

Against the gate (median within +-100 m, 90th percentile within +-250 m): v2 prior passes the median in WY2024 (+63 m) and WY2025 (-52 m) and fails it in WY2026 (-197 m); no model passes the 90th percentile (280 to 403 m). v1 fails both (median +183 m).

### 2.3 Gate by 200 m band (section 5.4: F1 at least 0.80 in every band holding at least 5 % of the snow cells)

The table lists the bands that qualify; F1 is pooled over the dates of the season (held out for the PBS).

WY2024, 42 dates (no v1):

| 200 m band | Share of observed snow cells | v2 prior median | v2 PBS, held out |
|---|---|---|---|
| 2000 to 2199 | 8 % | 0.74 | 0.65 |
| 2200 to 2399 | 14 % | 0.66 | 0.64 |
| 2400 to 2599 | 19 % | 0.68 | 0.71 |
| 2600 to 2799 | 21 % | 0.76 | 0.81 |
| 2800 to 2999 | 20 % | 0.77 | 0.84 |
| 3000 to 3199 | 9 % | 0.80 | 0.82 |
| bands passing 0.80 |  | 0 of 6 | 3 of 6 |

WY2025, the 21 dates with a v1 entry:

| 200 m band | Share of observed snow cells | v1 (site today) | v2 prior median | v2 PBS, held out |
|---|---|---|---|---|
| 2000 to 2199 | 14 % | 0.70 | 0.77 | 0.79 |
| 2200 to 2399 | 18 % | 0.84 | 0.84 | 0.85 |
| 2400 to 2599 | 18 % | 0.80 | 0.82 | 0.81 |
| 2600 to 2799 | 19 % | 0.78 | 0.82 | 0.82 |
| 2800 to 2999 | 17 % | 0.81 | 0.87 | 0.89 |
| 3000 to 3199 | 7 % | 0.89 | 0.93 | 0.93 |
| bands passing 0.80 |  | 3 of 6 | 5 of 6 | 5 of 6 |

WY2025, all 47 dates (v2 only):

| 200 m band | Share of observed snow cells | v2 prior median | v2 PBS, held out |
|---|---|---|---|
| 2000 to 2199 | 11 % | 0.74 | 0.75 |
| 2200 to 2399 | 17 % | 0.82 | 0.81 |
| 2400 to 2599 | 19 % | 0.83 | 0.81 |
| 2600 to 2799 | 20 % | 0.83 | 0.82 |
| 2800 to 2999 | 19 % | 0.87 | 0.86 |
| 3000 to 3199 | 8 % | 0.89 | 0.88 |
| bands passing 0.80 |  | 5 of 6 | 5 of 6 |

WY2026, 76 dates (no v1):

| 200 m band | Share of observed snow cells | v2 prior median | v2 PBS, held out |
|---|---|---|---|
| 1800 to 1999 | 7 % | 0.78 | 0.77 |
| 2000 to 2199 | 12 % | 0.85 | 0.87 |
| 2200 to 2399 | 17 % | 0.82 | 0.84 |
| 2400 to 2599 | 19 % | 0.81 | 0.84 |
| 2600 to 2799 | 18 % | 0.87 | 0.89 |
| 2800 to 2999 | 15 % | 0.91 | 0.92 |
| 3000 to 3199 | 6 % | 0.91 | 0.91 |
| bands passing 0.80 |  | 6 of 7 | 6 of 7 |

### 2.4 Tables per season and 100 m band

Cells x dates is the number of decided cell-dates in the band. The observed snow share is the share of those that are snow. Bands below 1,300 m have no snow (F1 undefined or zero). F1 is meaningless where the observed share is under about 5 %, and MCC is undefined where a model predicts one class only.

WY2024, 42 dates:

| Band (m, from) | Cells x dates | Obs. snow share | v2 prior median (F1 / MCC) | v2 PBS, held out (F1 / MCC) |
|---|---|---|---|---|
| 1300 | 145522 | 0.00 | 0.00 / n/a | 0.00 / n/a |
| 1400 | 127769 | 0.01 | 0.00 / n/a | 0.00 / n/a |
| 1500 | 134134 | 0.02 | 0.00 / n/a | 0.00 / n/a |
| 1600 | 136931 | 0.03 | 0.30 / 0.41 | 0.55 / 0.58 |
| 1700 | 148354 | 0.04 | 0.59 / 0.61 | 0.60 / 0.60 |
| 1800 | 150215 | 0.05 | 0.60 / 0.60 | 0.64 / 0.62 |
| 1900 | 157123 | 0.06 | 0.69 / 0.68 | 0.71 / 0.69 |
| 2000 | 174609 | 0.08 | 0.77 / 0.75 | 0.70 / 0.67 |
| 2100 | 174464 | 0.10 | 0.71 / 0.69 | 0.62 / 0.58 |
| 2200 | 191756 | 0.13 | 0.68 / 0.65 | 0.62 / 0.56 |
| 2300 | 191678 | 0.18 | 0.64 / 0.59 | 0.65 / 0.58 |
| 2400 | 174300 | 0.23 | 0.64 / 0.57 | 0.69 / 0.59 |
| 2500 | 145345 | 0.29 | 0.72 / 0.63 | 0.73 / 0.62 |
| 2600 | 121990 | 0.36 | 0.75 / 0.64 | 0.80 / 0.67 |
| 2700 | 105120 | 0.44 | 0.78 / 0.65 | 0.83 / 0.68 |
| 2800 | 93099 | 0.49 | 0.77 / 0.61 | 0.82 / 0.63 |
| 2900 | 66918 | 0.60 | 0.76 / 0.53 | 0.85 / 0.59 |
| 3000 | 45747 | 0.61 | 0.79 / 0.50 | 0.82 / 0.48 |
| 3100 | 15453 | 0.61 | 0.81 / 0.51 | 0.81 / 0.44 |
| 3200 | 6051 | 0.70 | 0.89 / 0.61 | 0.86 / 0.43 |
| 3300 | 583 | 0.47 | 0.69 / 0.33 | 0.68 / 0.28 |

WY2025, 21 dates with a v1 entry:

| Band (m, from) | Cells x dates | Obs. snow share | v1 (site today) (F1 / MCC) | v2 prior median (F1 / MCC) | v2 PBS, held out (F1 / MCC) |
|---|---|---|---|---|---|
| 1300 | 81117 | 0.00 | 0.00 / n/a | 0.00 / n/a | 0.00 / n/a |
| 1400 | 71764 | 0.00 | 0.00 / n/a | 0.00 / n/a | 0.00 / n/a |
| 1500 | 63738 | 0.00 | 0.00 / n/a | 0.00 / n/a | 0.00 / n/a |
| 1600 | 64659 | 0.01 | 0.00 / n/a | 0.00 / n/a | 0.00 / n/a |
| 1700 | 71679 | 0.04 | 0.08 / 0.19 | 0.27 / 0.32 | 0.35 / 0.41 |
| 1800 | 73771 | 0.08 | 0.31 / 0.37 | 0.34 / 0.29 | 0.32 / 0.26 |
| 1900 | 80010 | 0.15 | 0.51 / 0.47 | 0.48 / 0.37 | 0.48 / 0.37 |
| 2000 | 91645 | 0.26 | 0.62 / 0.54 | 0.71 / 0.61 | 0.74 / 0.64 |
| 2100 | 91682 | 0.34 | 0.76 / 0.67 | 0.82 / 0.73 | 0.83 / 0.75 |
| 2200 | 96783 | 0.36 | 0.84 / 0.77 | 0.85 / 0.77 | 0.85 / 0.76 |
| 2300 | 93746 | 0.38 | 0.83 / 0.75 | 0.84 / 0.74 | 0.85 / 0.75 |
| 2400 | 83957 | 0.42 | 0.81 / 0.70 | 0.82 / 0.70 | 0.81 / 0.66 |
| 2500 | 70346 | 0.50 | 0.78 / 0.63 | 0.81 / 0.63 | 0.80 / 0.59 |
| 2600 | 60416 | 0.58 | 0.78 / 0.56 | 0.81 / 0.57 | 0.81 / 0.52 |
| 2700 | 53807 | 0.69 | 0.78 / 0.47 | 0.82 / 0.50 | 0.84 / 0.44 |
| 2800 | 48227 | 0.75 | 0.80 / 0.44 | 0.85 / 0.46 | 0.87 / 0.36 |
| 2900 | 34473 | 0.84 | 0.82 / 0.40 | 0.90 / 0.42 | 0.91 / 0.25 |
| 3000 | 23198 | 0.87 | 0.87 / 0.39 | 0.92 / 0.07 | 0.93 / 0.09 |
| 3100 | 7628 | 0.90 | 0.94 / 0.42 | 0.95 / n/a | 0.95 / n/a |
| 3200 | 2887 | 0.94 | 0.97 / 0.17 | 0.97 / n/a | 0.97 / n/a |
| 3300 | 251 | 0.94 | 0.97 / n/a | 0.97 / n/a | 0.97 / n/a |

WY2025, all 47 dates (v2 only):

| Band (m, from) | Cells x dates | Obs. snow share | v2 prior median (F1 / MCC) | v2 PBS, held out (F1 / MCC) |
|---|---|---|---|---|
| 1300 | 191154 | 0.00 | 0.00 / n/a | 0.00 / n/a |
| 1400 | 166318 | 0.00 | 0.00 / n/a | 0.00 / n/a |
| 1500 | 150192 | 0.00 | 0.00 / n/a | 0.00 / n/a |
| 1600 | 150686 | 0.00 | 0.00 / n/a | 0.00 / n/a |
| 1700 | 162712 | 0.02 | 0.27 / 0.33 | 0.35 / 0.41 |
| 1800 | 165678 | 0.03 | 0.34 / 0.32 | 0.32 / 0.29 |
| 1900 | 174468 | 0.07 | 0.47 / 0.43 | 0.47 / 0.43 |
| 2000 | 194964 | 0.13 | 0.69 / 0.65 | 0.70 / 0.66 |
| 2100 | 193268 | 0.19 | 0.77 / 0.72 | 0.78 / 0.73 |
| 2200 | 206034 | 0.22 | 0.82 / 0.76 | 0.81 / 0.76 |
| 2300 | 200159 | 0.25 | 0.83 / 0.77 | 0.82 / 0.75 |
| 2400 | 179090 | 0.30 | 0.83 / 0.76 | 0.81 / 0.72 |
| 2500 | 149627 | 0.36 | 0.82 / 0.72 | 0.81 / 0.69 |
| 2600 | 127598 | 0.43 | 0.82 / 0.69 | 0.81 / 0.66 |
| 2700 | 112736 | 0.52 | 0.84 / 0.67 | 0.84 / 0.64 |
| 2800 | 101243 | 0.58 | 0.85 / 0.65 | 0.85 / 0.61 |
| 2900 | 72933 | 0.67 | 0.89 / 0.66 | 0.88 / 0.61 |
| 3000 | 49542 | 0.68 | 0.89 / 0.63 | 0.89 / 0.60 |
| 3100 | 16480 | 0.69 | 0.89 / 0.61 | 0.87 / 0.48 |
| 3200 | 6395 | 0.75 | 0.92 / 0.64 | 0.90 / 0.54 |
| 3300 | 608 | 0.61 | 0.80 / 0.40 | 0.80 / 0.40 |

WY2026, 76 dates:

| Band (m, from) | Cells x dates | Obs. snow share | v2 prior median (F1 / MCC) | v2 PBS, held out (F1 / MCC) |
|---|---|---|---|---|
| 1300 | 311418 | 0.00 | 0.00 / -0.00 | 0.00 / -0.00 |
| 1400 | 276014 | 0.01 | 0.00 / -0.00 | 0.00 / -0.00 |
| 1500 | 254160 | 0.03 | 0.22 / 0.29 | 0.23 / 0.33 |
| 1600 | 260150 | 0.05 | 0.50 / 0.54 | 0.47 / 0.52 |
| 1700 | 283790 | 0.07 | 0.71 / 0.72 | 0.66 / 0.68 |
| 1800 | 290059 | 0.08 | 0.74 / 0.72 | 0.70 / 0.70 |
| 1900 | 305859 | 0.10 | 0.81 / 0.79 | 0.82 / 0.80 |
| 2000 | 340015 | 0.13 | 0.87 / 0.85 | 0.87 / 0.85 |
| 2100 | 337372 | 0.15 | 0.84 / 0.81 | 0.87 / 0.85 |
| 2200 | 362436 | 0.17 | 0.82 / 0.79 | 0.84 / 0.81 |
| 2300 | 355150 | 0.20 | 0.81 / 0.77 | 0.83 / 0.79 |
| 2400 | 319108 | 0.23 | 0.80 / 0.75 | 0.83 / 0.78 |
| 2500 | 262746 | 0.28 | 0.83 / 0.77 | 0.85 / 0.80 |
| 2600 | 219194 | 0.32 | 0.86 / 0.79 | 0.88 / 0.83 |
| 2700 | 188056 | 0.38 | 0.89 / 0.83 | 0.91 / 0.85 |
| 2800 | 165333 | 0.41 | 0.90 / 0.84 | 0.92 / 0.86 |
| 2900 | 115598 | 0.46 | 0.92 / 0.86 | 0.93 / 0.88 |
| 3000 | 78016 | 0.47 | 0.91 / 0.83 | 0.91 / 0.84 |
| 3100 | 26199 | 0.47 | 0.90 / 0.81 | 0.91 / 0.82 |
| 3200 | 10188 | 0.49 | 0.88 / 0.77 | 0.90 / 0.80 |
| 3300 | 995 | 0.41 | 0.78 / 0.63 | 0.77 / 0.61 |

The thin-snow bands (1,600 to 1,900 m) are the weak point for every model and every season, with the held-out PBS no better than the prior. That is where snow comes and goes, where forcing temperature errors matter most, and where Sentinel-2 snow shares are small.

### 2.5 Caveats for A

- v1 can only be compared in WY2025, on dates from 3 November 2024 to 30 March 2025 (accumulation season). Nothing is known about v1 in melt season.
- The reference is Sentinel-2 classification (decisive cells only; shadow and cloud cells are excluded, which favours sunlit slopes). Its own accuracy (HR-S&I 94 %, `snow-methodology.md` 2.2) caps what any model can show.
- Scores are pooled over dates and cells, so the many easy bare cells and the autocorrelation between neighbouring dates and cells make the effective sample smaller than the cell counts suggest; differences of 0.01 to 0.02 F1 are not meaningful.
- Blocks are 12 days and the adjacent blocks belong to other folds, so a held-out date near a block edge has an assimilated date a few days away: the leakage is limited, not zero. The held-out and in-sample PBS numbers differ by 0.01 or less, so leakage is not what limits the PBS.
- v2 and v1 use the same IFS forcing at 0.1 degrees here, so the comparison isolates the model, not the forcing.

## 3. B. Poqueira camera, 2009 to 2013

### 3.1 Setup

- Camera: 37.02825 N, -3.32337 E, 2,510 m (PANGAEA loader constant, checked against the file header). Model cell: row 251, column 286 of the 100 m grid, DEM elevation 2,498 m (12 m below the camera), slope 13.1 degrees, aspect 201.7 degrees (south-southwest facing). One class, radiation index of that cell.
- Forcing: ERA5 through `fetch_season_forcing`. The camera falls in the ERA5 cell centred at 37.0 N, -3.25 E; the 0.25 degree cell has a mean DEM elevation of 1,955 m. Primary run: values requested for the DEM cell elevation 2,498 m (as the task specified), so the model applies no lapse or precipitation gradient (dz = 0). Sensitivity: values requested for the ERA5 cell mean elevation 1,955 m, so the model's own lapse rate and gradient apply (dz = +543 m). Third variant, a diagnostic: the primary forcing corrected toward the PG2 gauge, which stands at the camera (section 4).
- Ensemble: 5,000 members, default priors, one regional storm segmentation from the single point's precipitation. Water years 2010 to 2013 (camera days: 315, 356, 336 and 209; the file has a gap and ends 2013-05-31).
- Data assimilation: particle batch smoother on MODIS fSCA of the 500 m pixel at the camera (clear days, Terra and Aqua averaged: 205, 240, 261 and 146 dates), observation error from `observation_error` for a pool of 25 cells (0.141), `n_corr` 3 (10 gives the same conclusion: pooled RMSE 0.473 m). The camera is not used in any fit, so the camera is an independent test of both the prior and the PBS. The effective size was tempered to 150 (3 % of 5,000) in every season, i.e. the weights were flattened, not trusted.
- Baselines: the default-parameter run (one deterministic member at the middle of every prior range, b0 = 1, no storm noise: a degree-day model with default parameters); the camera's own climatology from the other three seasons (plus or minus 7 days of the same day of the year); and zero depth.

### 3.2 Depth, all four seasons together (primary forcing)

Scores over the 1,216 camera days; the interval coverage over snow days uses the days where the camera or the ensemble p90 exceeds 1 cm, because the long bare summers sit trivially inside a zero-width interval.

| Predictor | RMSE (m) | Bias (m) | r | KGE | CRPS (m) | 80 % interval coverage, all days | coverage, snow days |
|---|---|---|---|---|---|---|---|
| v2 prior median | 0.300 | 0.017 | 0.53 | 0.37 | 0.091 | 0.88 | 0.79 |
| v2 MODIS-PBS median | 0.505 | 0.199 | 0.70 | -1.15 | 0.167 | 0.59 | 0.32 |
| default-parameter run | 0.326 | 0.024 | 0.50 | 0.27 | n/a | n/a | n/a |
| camera climatology, other seasons | 0.223 | 0.000 | 0.49 | 0.43 | n/a | n/a | n/a |
| zero depth | 0.277 | n/a | n/a | n/a | n/a | n/a | n/a |

Per season:

| Water year | Model | Camera days | RMSE (m) | Bias (m) | r | KGE | Snow-day coverage | Camera melt-out | Melt-out error, days: median [p10, p90] |
|---|---|---|---|---|---|---|---|---|---|
| 2010 | prior | 315 | 0.473 | 0.278 | 0.83 | -1.43 | 0.84 | 2010-04-23 | +16 [-35, +72] |
| 2010 | PBS | 315 | 0.959 | 0.619 | 0.83 | -4.36 | 0.00 | 2010-04-23 | +55 [+38, +72] |
| 2010 | default run | 315 | 0.527 | 0.310 | 0.82 | -1.73 | n/a | 2010-04-23 | +26 [+26, +26] |
| 2011 | prior | 356 | 0.306 | -0.128 | 0.55 | 0.10 | 0.75 | 2011-05-04 | -1 [-60, +5] |
| 2011 | PBS | 356 | 0.202 | 0.089 | 0.91 | 0.50 | 0.54 | 2011-05-04 | +6 [+3, +11] |
| 2011 | default run | 356 | 0.319 | -0.136 | 0.50 | 0.04 | n/a | 2011-05-04 | -1 [-1, -1] |
| 2012 | prior | 336 | 0.067 | -0.021 | 0.32 | -0.24 | 0.62 | 2012-05-03 | +0 [-2, +18] |
| 2012 | PBS | 336 | 0.061 | -0.010 | 0.45 | 0.21 | 0.36 | 2012-05-03 | +18 [+18, +19] |
| 2012 | default run | 336 | 0.067 | -0.021 | 0.33 | -0.23 | n/a | 2012-05-03 | -1 [-1, -1] |
| 2013 | prior | 209 | 0.138 | -0.065 | 0.81 | 0.30 | 0.89 | 2013-05-03 | +19 [-2, +20] |
| 2013 | PBS | 209 | 0.148 | 0.090 | 0.91 | 0.20 | 0.45 | 2013-05-03 | +20 [+19, +21] |
| 2013 | default run | 209 | 0.140 | -0.064 | 0.79 | 0.31 | n/a | 2013-05-03 | +19 [+19, +19] |

Peak depth and the parameters the PBS wanted:

| Water year | Camera peak (m) | Prior peak median [p10, p90] (m) | PBS peak median [p10, p90] (m) | Default run peak (m) | Forcing precipitation (mm) | PBS mean b0 | PBS mean dT (C) | Station correction |
|---|---|---|---|---|---|---|---|---|
| 2010 | 1.04 | 1.89 [0.56, 4.02] | 2.96 [1.83, 4.38] | 1.97 | 1053 | 1.26 | -0.42 | None |
| 2011 | 1.19 | 0.89 [0.44, 1.77] | 1.52 [0.97, 2.26] | 0.86 | 764 | 1.24 | -1.82 | None |
| 2012 | 0.41 | 0.17 [0.08, 0.40] | 0.29 [0.17, 0.46] | 0.17 | 377 | 1.32 | -0.75 | None |
| 2013 | 0.88 | 0.48 [0.21, 1.07] | 0.88 [0.58, 1.41] | 0.46 | 805 | 1.56 | -0.52 | None |

Snow cover fraction (model sub-grid fSCA against the camera cover):

| Predictor | RMSE | Bias | r | KGE |
|---|---|---|---|---|
| prior | 0.246 | -0.021 | 0.82 | 0.81 |
| PBS | 0.266 | 0.094 | 0.84 | 0.62 |
| default run | 0.256 | -0.029 | 0.81 | 0.78 |

Findings:

- The prior median is unbiased overall (+0.017 m) only because +0.28 m in the wet 2010 and -0.13, -0.02 and -0.07 m in the other seasons cancel. Season by season the peak is off by factors of 1.8, 0.75, 0.41 and 0.54.
- It does not beat the trivial baselines on RMSE: 0.300 m against 0.277 m for zero depth, 0.326 m for the default-parameter run and 0.223 m for the camera climatology. Its correlation is 0.53 (0.83, 0.55, 0.32 and 0.81 by season); it follows the timing of the big seasons and not the small ones. KGE 0.37 is below the climatology's 0.43.
- The ensemble is roughly calibrated: the 80 % interval holds 88 % of all days and 79 % of snow days, and the observed peak lay inside p10 to p90 in 3 of 4 seasons (2012 just outside: 0.41 m against a p90 of 0.40 m). It is wide: p90 over p10 of the peak is 4 to 7.
- Melt-out (first bare day after the last day above 1 cm): the camera melted out on 2010-04-23, 2011-05-04, 2012-05-03 and 2013-05-03. The prior median error is +16, -1, 0 and +19 days, and the p10 to p90 interval is 65 to 110 days wide in 2010 and 2011. Even the median is a week off or more in two of four seasons; the PBS shifts all of them later (+55, +6, +18 and +20 days).
- The MODIS PBS is worse: RMSE 0.505 m, bias +0.199 m, KGE -1.15, 80 % coverage of snow days 32 %. It raises b0 (mean 1.24 to 1.56 against a prior mean of 1.07) and lowers dT (-0.4 to -1.8 C), keeps snow far too long in 2010 (melt-out +55 days) and cuts the spread. Correlation does improve (0.70 against 0.53), so the timing information is real and the magnitude is not. It improves 2011 (RMSE 0.202 against 0.306 m) and 2012 (0.061 against 0.067 m) and ruins 2010 (0.959 against 0.473 m).
- Why: the 500 m MODIS pixel is not the 30 x 30 m camera plot. On the 772 days when both have a clear value, mean cover is 0.31 for MODIS and 0.24 for the camera (correlation 0.91); the same melt-out rule gives MODIS dates of 2010-09-22, 2011-08-30, 2012-05-08 and 2013-05-24 against camera dates of 2010-04-26, 2011-04-28, 2012-05-08 and 2013-04-11. A pixel with higher, shaded terrain keeps snow for months after a south-southwest plot is bare, so a smoother that fits the pixel pushes the plot's snow up and its temperature down. The station says the opposite sign for temperature (ERA5 is too cold, not too warm). This is a representativeness limit, and it applies equally to a 100 m model cell against a 500 m pixel; it does not show that fSCA assimilation fails at a matched scale (Sentinel-2 at 20 m in section 2 is such a case, and it gives no gain either).

### 3.3 Sensitivity: forcing elevation, and forcing corrected toward the PG2 gauge

ERA5 cell mean elevation as the forcing elevation (model lapse and gradient applied):

| Predictor | RMSE (m) | Bias (m) | r | KGE | CRPS (m) | 80 % interval coverage, all days | coverage, snow days |
|---|---|---|---|---|---|---|---|
| v2 prior median | 0.374 | 0.070 | 0.56 | -0.06 | 0.110 | 0.90 | 0.83 |
| v2 MODIS-PBS median | 0.549 | 0.232 | 0.73 | -1.47 | 0.193 | 0.55 | 0.26 |
| default-parameter run | 0.413 | 0.078 | 0.54 | -0.22 | n/a | n/a | n/a |
| camera climatology, other seasons | 0.223 | 0.000 | 0.49 | 0.43 | n/a | n/a | n/a |
| zero depth | 0.277 | n/a | n/a | n/a | n/a | n/a | n/a |

Forcing corrected toward PG2 (temperature shifted by the mean station minus ERA5 daily bias of each season, precipitation scaled by the season ratio of station to ERA5 over the days the station has data; the gauge undercatches snow, so the scaled precipitation is if anything low):

| Predictor | RMSE (m) | Bias (m) | r | KGE | CRPS (m) | 80 % interval coverage, all days | coverage, snow days |
|---|---|---|---|---|---|---|---|
| v2 prior median | 0.228 | -0.030 | 0.56 | 0.50 | 0.076 | 0.92 | 0.86 |
| v2 MODIS-PBS median | 0.500 | 0.217 | 0.75 | -1.26 | 0.179 | 0.56 | 0.26 |
| default-parameter run | 0.235 | -0.034 | 0.53 | 0.46 | n/a | n/a | n/a |
| camera climatology, other seasons | 0.223 | 0.000 | 0.49 | 0.43 | n/a | n/a | n/a |
| zero depth | 0.277 | n/a | n/a | n/a | n/a | n/a | n/a |

| Water year | Camera peak (m) | Prior peak median [p10, p90] (m) | PBS peak median [p10, p90] (m) | Default run peak (m) | Forcing precipitation (mm) | PBS mean b0 | PBS mean dT (C) | Station correction |
|---|---|---|---|---|---|---|---|---|
| 2010 | 1.04 | 1.47 [0.45, 4.01] | 2.94 [1.99, 4.40] | 1.39 | 1411 | 1.22 | -0.91 | +1.45 C, x1.34 |
| 2011 | 1.19 | 1.06 [0.50, 2.20] | 1.84 [1.27, 2.72] | 1.12 | 1068 | 1.12 | -2.18 | +0.99 C, x1.40 |
| 2012 | 0.41 | 0.23 [0.10, 0.51] | 0.35 [0.22, 0.68] | 0.19 | 635 | 1.30 | -0.93 | +1.12 C, x1.68 |
| 2013 | 0.88 | 0.52 [0.23, 1.17] | 1.06 [0.70, 1.63] | 0.51 | 1115 | 1.49 | -0.81 | +1.03 C, x1.39 |

Findings:

- Using the ERA5 cell mean elevation makes things worse (RMSE 0.374 m, 2010 bias +0.41 m): extrapolating a 1,955 m cell to 2,498 m with the prior lapse rate and gradient adds snow in the wet year (consistent with, not proof of, that cause).
- With the forcing corrected toward the PG2 gauge the prior median reaches RMSE 0.228 m, bias -0.030 m, KGE 0.50, correlation 0.56, 80 % interval coverage 92 % (86 % on snow days): on par with the camera climatology (0.223 m) and better than zero depth (0.277 m). The default-parameter run reaches 0.235 m. Most of the depth error of the primary run is therefore forcing, and a single gauge removes a quarter of it. The corrected variant is a diagnostic: PG2 is the camera's own station, so it uses information a production run over the whole range would not have, and it says nothing about places without a gauge. The correlation stays near 0.5, so timing at a point is still not good.
- Against the gate (correlation at least 0.8, RMSE at most 0.30 m, absolute bias at most 0.10 m): the corrected prior passes RMSE and bias and fails correlation; the primary prior sits on the RMSE limit and fails correlation; the PBS fails all three.

### 3.4 What the camera test covers and does not cover

It covers one 30 x 30 m plot at 2,510 m, 2009 to 2013, snow depth and snow cover, not SWE (no density is in the file). A 100 m cell is compared with 900 m2, so part of any error is representativeness (wind, local aspect). Four seasons are four samples of the forcing error; two were wet, one very dry (peak 0.41 m). Nothing here says anything about the current seasons, other places or elevations, or about the spatial pattern. Depth is not SWE: the density curve and the compaction scale `rho_s` are tested only through depth. It is, however, the only independent depth test available, and it was never used to tune anything.

## 4. Forcing check against the Guadalfeo stations

Stations (elevations from the Open-Meteo 90 m DEM at the coordinates, because the PANGAEA files carry none): PG1 37.049 N, -3.214 E, 2,477 m; PG2 37.029 N, -3.324 E, 2,515 m (the Poqueira camera site); PG4 37.008 N, -3.355 E, 2,134 m; PG5 37.085 N, -3.473 E, 1,659 m. Model values come from the forcing adapter requested at each station elevation, daily sums and means on UTC days, compared on the days where the station has a value. Water years with fewer than 300 common days are left out.

Annual ratio of ERA5 precipitation to the station total, by water year:

| Water year | PG1 | PG2 | PG4 | PG5 |
|---|---|---|---|---|
| 2005 | n/a | 0.72 | n/a | n/a |
| 2006 | n/a | 0.91 | n/a | n/a |
| 2007 | n/a | 0.86 | n/a | n/a |
| 2008 | n/a | 0.92 | n/a | n/a |
| 2010 | 0.69 | 0.75 | n/a | n/a |
| 2011 | 0.71 | 0.72 | n/a | n/a |
| 2012 | 0.74 | n/a | n/a | n/a |
| 2013 | 0.80 | 0.72 | 0.60 | n/a |
| 2014 | 1.03 | 0.88 | 0.73 | n/a |
| 2015 | 1.03 | 0.87 | 0.71 | n/a |
| 2016 | 0.80 | 0.62 | 0.59 | n/a |
| 2017 | 0.93 | 0.81 | 0.72 | n/a |
| 2018 | 1.07 | 1.01 | 0.81 | 0.63 |

Pooled and daily correlation (the correlation at lag -1 day is shown because the station day boundary is not documented: it is far lower than at lag 0, so the days are aligned):

| Station | Elevation (m) | Water years (>= 300 days) | Pooled ERA5/station | Min annual ratio | Max annual ratio | Mean daily r | Min daily r | Mean daily r at lag -1 day |
|---|---|---|---|---|---|---|---|---|
| PG1 | 2477 | 9 | 0.83 | 0.69 | 1.07 | 0.79 | 0.69 | 0.35 |
| PG2 | 2515 | 12 | 0.80 | 0.62 | 1.01 | 0.73 | 0.55 | 0.33 |
| PG4 | 2134 | 6 | 0.69 | 0.59 | 0.81 | 0.74 | 0.67 | 0.28 |

ERA5 and IFS in WY2018 (IFS archive starts 2017-01-01; the WY2017 request lacks Oct to Dec 2016 and fails the adapter's missing-data check, so IFS covers WY2018 only; stations end 2018-08-31):

| Station | Elevation (m) | Days | Station (mm) | ERA5 (mm) | ERA5/station | ERA5 daily r | IFS (mm) | IFS/station | IFS daily r |
|---|---|---|---|---|---|---|---|---|---|
| PG1 | 2477 | 335 | 702 | 751 | 1.07 | 0.86 | 960 | 1.37 | 0.86 |
| PG2 | 2515 | 323 | 745 | 750 | 1.01 | 0.74 | 1177 | 1.58 | 0.81 |
| PG4 | 2134 | 335 | 925 | 751 | 0.81 | 0.79 | 999 | 1.08 | 0.86 |
| PG5 | 1659 | 335 | 1221 | 766 | 0.63 | 0.77 | 1090 | 0.89 | 0.90 |

Temperature, mean of the daily model minus station difference, by water year (ERA5 for all stations; IFS in WY2018 only):

| Model | Station | Water years | Mean bias (C) | Min | Max | Mean RMSE (C) | Mean daily r |
|---|---|---|---|---|---|---|---|
| era5 | PG1 | 10 | -0.17 | -2.54 | 0.57 | 2.32 | 0.954 |
| era5 | PG2 | 14 | -1.23 | -1.67 | -0.92 | 2.67 | 0.945 |
| era5 | PG4 | 6 | -1.07 | -1.12 | -0.99 | 2.36 | 0.956 |
| era5 | PG5 | 1 | 0.55 | 0.55 | 0.55 | 1.82 | 0.971 |
| ecmwf_ifs | PG1 | 1 | -0.35 | -0.35 | -0.35 | 1.39 | 0.988 |
| ecmwf_ifs | PG2 | 1 | -2.00 | -2.00 | -2.00 | 2.44 | 0.987 |
| ecmwf_ifs | PG4 | 1 | -2.30 | -2.30 | -2.30 | 2.67 | 0.987 |
| ecmwf_ifs | PG5 | 1 | -0.17 | -0.17 | -0.17 | 1.18 | 0.990 |

Findings:

- ERA5 underestimates precipitation at the three high-elevation gauges in most years: pooled ratio 0.83 at PG1, 0.80 at PG2 and 0.69 at PG4, annual ratios from 0.59 to 1.07. The gauges undercatch snow, so the real shortfall is probably larger. WY2018 is the exception at PG1 and PG2 (1.07 and 1.01) and WY2014 and WY2015 at PG1 (1.03).
- IFS in WY2018 is wetter than ERA5 at the same points and above the gauges at three stations (1.37, 1.58 and 1.08 of the gauge at PG1, PG2 and PG4; 0.89 at PG5), 28 to 57 % above ERA5. The two forcing sources, both used in this work (IFS by v1 and the Sentinel-2 evaluation, ERA5 for the camera years), differ by tens of percent in total precipitation at the same point.
- Daily correlations are 0.55 to 0.90 (station means 0.73 to 0.79, years with at least 300 days) for ERA5 precipitation and higher for IFS in WY2018 (0.81 to 0.90): storm timing is good, amounts are not.
- Temperature: the daily correlation is 0.95 or better, but ERA5 is 0.9 to 1.7 C too cold at PG2 and PG4 (mean -1.23 and -1.07) and about right at PG1 and PG5 (-0.17 and +0.55). IFS in WY2018 is 2.0 and 2.3 C too cold at PG2 and PG4. A systematic cold bias of 1 to 2 C at the sites where the stations sit, with the variability right, is exactly what the dT parameter exists to absorb; the PBS on fSCA pulled dT the other way at the camera (section 3.2).
- This is the forcing error that dominates SWE magnitude: a 20 to 40 % precipitation error and a 1 to 2 C temperature error move peak SWE by more than the fSCA data can correct.

## 5. What the data can and cannot prove

Can prove:

- v2 prior gives a better Sentinel-2 snow presence than v1 on the 21 v1 dates of WY2025 and holds F1 0.72 to 0.86 over three seasons, with no tuning on those dates.
- Assimilating Sentinel-2 snow cover with the PBS gives no measurable held-out gain over the prior at this ensemble size and design.
- The ensemble is roughly calibrated for depth at the camera, and the forcing error is large and systematic.

Cannot prove:

- Anything about SWE: there is no measurement of it. The camera gives depth at one plot; the stations give forcing.
- Skill outside the camera plot for depth, outside 2009 to 2013 for the camera, outside November to March for v1.
- That v2 beats v1 in melt season, in the 1,500 to 1,900 m band (both are weak), or by more than a few hundredths of F1.
- The section 5.4 melt-out criterion against Sentinel-2 (not scored here; camera melt-out only).
- The "improvement over v1 in 8 of 10 seasons" criterion: v1 exists for one season.

## 6. Found, not done

- `forcing.fetch_season_forcing` and `experiments.load_season` name a water year differently (start year and end year); a one-line convention in the adapter would remove the trap.
- The validation harness `score_swe_presence` scores v1 on every valid grid cell including those outside the model domain polygon, where v1 is zero by construction; scores inside the domain are almost the same here (F1 0.781 against 0.783) because the Sentinel-2 snow cells are inside the domain.
- The model fSCA with a 0.5 threshold gives about the same presence score as SWE of at least 5 mm (WY2026 0.864 against 0.839, WY2024 0.703 against 0.722): the published layer could carry both.
- `qa.validation.metrics.crps_members` is quadratic in the number of members (66 GiB at 5,000 members); `evaluation.weighted_crps` is the sorted-ensemble version used here.

## 7. Reproduce

```
python -m scripts.snow_v2_evaluation sentinel --water-years 2024 2025 2026
python -m scripts.snow_v2_evaluation camera
python -m scripts.snow_v2_evaluation forcing
```

The forcing and the Sentinel-2 mirror come from `.cache/snow-v2` (Open-Meteo, prod catalogue read only); the camera, station and MODIS files from `qa-cache/` (PANGAEA, Planetary Computer). With the forcing cached, `sentinel` takes 2 to 4 minutes per season, `camera` about 2 minutes and `forcing` about 1 minute on a 14 thread machine; the first fetch from Open-Meteo takes longer.
