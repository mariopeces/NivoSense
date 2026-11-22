# NivoSense snow methodology review and v2 design

Date of research: 2026-11-22. Author: research agent (Claude), for the owner of NivoSense.
Scope: how SWE and snow depth are estimated and validated by the scientific community and by operational providers, an honest assessment of the current NivoSense model, one recommended v2 design, the data sources that were tested today, a validation plan, and an ordered task list.

Conventions used in this document:

- **Verified** means I opened the page or PDF (or ran the API call) and the statement or number is copied from it. The URL is given next to it.
- **Snippet only** means I only saw a search-engine summary or an abstract mirror, not the paper. These numbers must be checked before they are quoted outside this document.
- **Judgement** means my own inference. It is never presented as a published fact.
- **Not opened** means a paper I name for context but could not read. No numbers are taken from it.
- No quote in this document comes from memory. Where a method description (for example the form of the snow depletion curve in section 3) is my formulation of a published idea, it is marked as such.

## 0. Summary

1. The owner's criticism is correct on the points that matter. The current model never sees a SWE or snow depth measurement, calibrates six free parameters on 20 binary snow-cover dates from one year, and corrects the state only by deleting snow where Sentinel-2 sees bare ground. Its SWE and depth numbers have never been checked against anything. See section 2.
2. The credible published approaches fall in two families. (a) Physics models forced by meteorology and corrected by station snow depth, with Sentinel-2/Landsat snow cover added as a second constraint (Swiss OSHD / FSM2OSHD, IT-SNOW, SNODAS-type systems). (b) Retrospective Bayesian reanalysis that adjusts forcing uncertainty (above all precipitation) so that the simulated snow-covered fraction matches satellite fSCA (Margulis group, Aalstad et al., Mazzolini et al.). Sierra Nevada (Spain) has no open snow depth station network and no open SWE, so family (b) is the one that can be implemented honestly today.
3. ExoLabs does not estimate SWE from a satellite sensor. Its public documentation describes a snow depth product made by geostatistical interpolation of station snow depth inside a satellite snow mask, and an "empirical" SWE product. Its only published snow depth error is an average of 0.36 m on Davos data, and its SWE page gives an estimated RMSE of 53 kg/m2 with no reference data. See section 1.3.
4. Recommendation (details in section 3): design B, a particle batch smoother (with ES-MDA as fallback) on the existing temperature-index ensemble, with the unknowns being precipitation bias and gradient, temperature bias, rain/snow threshold, melt factors and a sub-grid snow depletion parameter, run season-to-date every day, observed through a sub-grid snow depletion curve against the Sentinel-2 snow fraction of each 100 m cell. It gives retrospective reanalysis (design A) as a special case, publishes quantiles and an age-of-observation flag, and leaves a clean path to FSM2 (design C) and Sentinel-1 wet snow (design D).
5. Forcing finding: on Open-Meteo, ERA5-Land has no precipitation (temperature and snow depth only), so precipitation must come from IFS (2017 onward) or ERA5; the two disagree strongly on snowfall in mountains, which is why precipitation bias is the unknown in the recommended design.
6. Open in-situ data exist but are thin: Refugio Poqueira camera snow depth 2009-2013, Guadalfeo station precipitation and temperature to 2018, IFAPA RIA low-altitude stations. There is no open SWE and no open daily snow depth from a government network. See sections 4 and 5.

---

## 1. What the community and companies do

### 1.1 Method table

Metrics are copied from the cited source. "n.r." means not reported in what I read.

| Method | Who | Data | Validation and quoted errors | URL |
|---|---|---|---|---|
| Western US snow reanalysis (WUS-SR): SSiB3 land surface model plus Liston 2004 depletion curve, 50 replicates, Particle Batch Smoother, posterior SWE, fSCA, depth daily | UCLA, Fang, Liu, Margulis 2022 | Landsat 5/7/8 fSCA (spectral unmixing), MERRA-2 forcing, SRTM DEM, tree canopy cover; about 500 m (16 arc-seconds), WY1985-2021 | Peak SWE vs lidar-derived SWE near 1 April: r 0.75 to 0.91, "mean difference below 0.15 m and RMSD below 0.38 m" (snippet only, Fang 2022 abstract via search). The user guide states that SWE artifacts "may exist" where few fSCA images are available because of clouds or a single Landsat | https://nsidc.org/sites/default/files/wus_ucla_sr-v001-userguide.pdf (verified, user guide); https://doi.org/10.1038/s41597-022-01768-7 (paper not opened, Nature pages blocked) |
| Joint Landsat and MODIS reanalysis (PBS) | Margulis, Liu, Baldo 2019 | Landsat and MODSCAG fSCA, MERRA-2, 480 m | Verified Table 3 vs ASO lidar, Tuolumne, WY2015/16/17: prior RMSD 0.087 / 0.364 / 0.629 m, Landsat-only posterior RMSD 0.054 / 0.222 / 0.308 m; posterior correlation about 45 % higher and RMSD about 29 % lower than the prior across flight dates. Single basin | https://www.frontiersin.org/articles/10.3389/feart.2019.00272 |
| Particle batch smoother vs ensemble batch smoother | Margulis, Girotto, Cortes, Durand 2015, J. Hydrometeorology | Landsat 5 fSCA, 27 years, American River basin, snow pillows and courses | Snippet only: "for snow pillows the PBS RMSE was approx. 54% of that seen in the EnBS" | https://modis.gsfc.nasa.gov/sci_team/pubs/abstract_new.php?id=19138 (abstract mirror); https://ntrs.nasa.gov/citations/20160004965 (timed out) |
| ES-MDA (ensemble smoother with multiple data assimilation) of MODIS and Sentinel-2 fSCA in a simple snow model | Aalstad et al. 2018, The Cryosphere 12, 247 | MODIS and Sentinel-2 fSCA, downscaled forcing, Ny-Alesund, 1 km scale | Snippet only: vs prior, RMSE for fSCA, peak mean SWE and sub-grid CV improved "by about 75%, 60%, and 20%"; ES-MDA "either outperforms or nearly matches" ES and PBS | https://tc.copernicus.org/articles/12/247/2018/ (search summary; paper not opened) |
| SWE reconstruction (back-calculation of melt from snow disappearance date) | Cline, Bales, Dozier 1998 (WRR); Rittger, Bair, Kahl, Dozier 2016 (Adv. Water Resour.) | Satellite snow-cover duration plus energy-balance melt | Snippet only. Cline 1998 tested in a 1.2 km2 basin (Emerald Lake). A 2023 intercomparison states these models "are only applicable in hindcasts and give SWE only at peak" (search summary) | https://escholarship.org/uc/item/3c68m0q8 ; https://www.frontiersin.org/articles/10.3389/feart.2023.1106621 (both search results, not opened) |
| Operational Swiss service: FSM2oshd at 250 m hourly, plus OI/EnKF/particle filter of station HS, 1 km temperature-index climatology | SLF, Mott et al. 2023 | Station HS (IMIS and cantonal), SWE sites, meteorological analyses, Sentinel-2 snow cover for evaluation | Verified: model "solves the complete mass and energy balance"; OI "reduces the errors in all elevation bands" for SWE at 45 sites (1,195 to 2,690 m); satellite assimilation is described as future work in that paper. No RMSE in the part read | https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2023.1228158/full ; https://www.slf.ch/en/snow/snow-as-a-water-resource/snow-hydrological-forecasting/ |
| High-resolution Swiss dataset 2016-2025 from FSM2OSHD with particle filter of HS at 444 stations | Oberrauch et al., TC 20, 3387, 2026 | HS from 444 stations, 250 m | Verified: leave-one-station-out in the highest band (mean peak HS above 2 m) RMSE 6.25 cm, bias -3.34 cm; snow-line altitude median bias vs Sentinel-2 fSCA within +-100 m (WY2018-2025) | https://tc.copernicus.org/articles/20/3387/2026/ |
| Sentinel-2 snow cover fraction joined to an HS particle filter through a particle batch smoother (preprint) | Oberrauch et al., egusphere-2026-2725 | HS plus Sentinel-2 SCF | Verified (abstract): "reduces the RMSE and bias of SCF estimates during the ablation season by approximately 50%" at observed locations. No absolute values | https://egusphere.copernicus.org/preprints/2026/egusphere-2026-2725/ |
| SPASS: 1 km quantile-mapped temperature-index model from 1962 | Marty et al., TC 19, 4391, 2025 | Gridded meteorology, station HS | Verified: vs station HS yearly RMSE 25 cm (20 %) at 2500 m and 1.5 cm (80 %) at 500 m; monthly RMSE 30 cm (25 %) at 2500 m and 3 cm (100 %) at 500 m. OSHD-EKF performs "only slightly better" | https://tc.copernicus.org/articles/19/4391/2025/ |
| Particle filter of HS at 40 Swiss sites | Magnusson et al. 2017, WRR 53 | HS | Snippet only: "reduces the root-mean-squared-error for SWE by 64%" vs no assimilation | https://modarch.gsfc.nasa.gov/sci_team/pubs/abstract_new.php?id=25271 |
| Bias-Detecting Ensemble for precipitation correction | Winstral et al. 2019, WRR 55 | Station HS, 38 independent sites | Snippet only: Nash-Sutcliffe for HS from 0.81 to 0.98 | not opened |
| ICESat-2 snow depth plus Sentinel-2 fSCA assimilation with FSM2 in the Spanish Pyrenees | Mazzolini et al., TC 19, 3831, 2025 | ICESat-2 depth profiles, Sentinel-2 fSCA, FSM2, Izas catchment | Snippet only: joint assimilation "improves by 19%" over fSCA-only during accumulation; benefit degrades in ablation | https://tc.copernicus.org/articles/19/3831/2025/ |
| IT-SNOW reanalysis (S3M chain) | CIMA Foundation, Sarigil et al., HESS 30, 6763, 2026 | Forcing, about 350 ultrasonic HS sensors, 500 m | Verified: vs Sentinel-1 snow depth mean bias -10 mm, mean RMSE 220 mm; vs ground data RMSE 300 to 600 mm (HS) and 90 to 300 mm (SWE) | https://hess.copernicus.org/articles/30/6763/2026/ |
| Sentinel-1 C-band snow depth, Northern Hemisphere mountains, 1 km, empirical change detection of VH/VV ratio | Lievens et al. 2019, Nat. Commun. 10, 4629 | Sentinel-1, IMS snow cover, forest correction | Verified (PMC): vs in situ spatial correlation 0.76 (Feb 2018), temporal correlation mean 0.77, MAE 0.18 m, bias -0.01 m (2,000 sites); "Shallow or intermittent snow gives the lowest temporal correlations"; wet snow may cause underestimation | https://pmc.ncbi.nlm.nih.gov/articles/PMC6789005 |
| Sentinel-1 snow depth, European Alps, 100 m to 1 km | Lievens et al. 2022, TC 16, 159 | Sentinel-1 VV/VH, dry and wet snow detection | Verified (abstract): "dry snow depth retrievals at 500 m and 1 km resolution have a spatio-temporal correlation of 0.89"; "The mean absolute error equals 20 %-30 % of the measured values for snow depths between 1.5 and 3 m"; relative MAE 40 % to 70 % for shallow snow; "In regions with shallow maximum snow depths (<1 m), gVV0 generally remains relatively constant"; wet snow flagged with a -2 dB threshold | https://tc.copernicus.org/articles/16/159/2022/ |
| Sentinel-1 plus XGBoost snow depth, Alps, 100 m, sub-weekly, 2015-2024 | Boeykens et al. (incl. Lievens), TC 20, 3187, 2026 | Sentinel-1 dual-pol plus downscaled forcing or modelled depth | Snippet only: R = 0.80, biases -0.04 and -0.03 m; the 2022 algorithm is described as limited in wet and shallow snow, forests, and after freeze-thaw | https://tc.copernicus.org/articles/20/3187/2026/ |
| Pan-European SWE 5 km | Copernicus CLMS | Passive microwave plus optical mask | Verified: RMSE 37.4 mm (GlobSnow v2.0: 44.3 mm), reference Russian and Finnish transects; pre-operational | https://land.copernicus.eu/api/en/products/snow/snow-water-equivalent-v1-0-5km/quality |
| HR-S&I fractional snow cover from Sentinel-2, 20 m | Copernicus, Barrou Dumont et al., TC 15, 4975, 2021 | Sentinel-2 | Verified: accuracy 94 %, kappa 0.81; precision 93 %, recall 78 % | https://tc.copernicus.org/articles/15/4975/2021/ |
| Airborne lidar depth times modelled density | ASO / JPL, Painter et al. 2016 | Scanning lidar | Not opened. Snippet only: density often dominates SWE error | https://doi.org/10.1016/j.rse.2016.06.018 |
| SNODAS | NOAA NOHRSC | Modelling and data assimilation system, 1 km daily, 2003-present | Verified: the NSIDC page has no limitations section; service reduced to "Basic" level. No error figures on the page | https://nsidc.org/data/g02158/versions/1 |
| UA SWE | University of Arizona | In situ SNOTEL and COOP snow measurements plus PRISM, 4 km daily, 1981-2023 | Verified: no validation statement on the NSIDC page | https://nsidc.org/data/nsidc-0719/versions/1 |
| SnowModel (MicroMet, EnBal, SnowPack, SnowTran-3D) | Liston and Elder 2006 | Meteorology, DEM, land cover | Snippet only: "closely reproduced observed snow-water-equivalent distribution, time evolution, and interannual variability patterns" | https://research.fs.usda.gov/treesearch/26319 |
| FSM2 multi-physics energy-balance snow model with forest canopy | Essery et al. 2025, GMD 18, 3583 | Needs full meteorological forcing (user guide lists variables; I did not open it); Fortran, MIT licence | Verified from the README only; no skill numbers read | https://github.com/RichardEssery/FSM2 |
| ExoLabs COSMOS snow depth, 20 m | ExoLabs (UZH spin-off) | Satellite snow masks, station HS, topography | Verified: "average error of just 0.36 meters" over 23 reference datasets, 2,274,247 points, Davos | https://exolabs-ch.gitbook.io/cosmos/snow-depth |
| ExoLabs COSMOS snow water | ExoLabs | "an empirical approach" to density and SWE | Verified: only "estimated RMSE of 53 kg/m2", no reference data given | https://exolabs-ch.gitbook.io/cosmos/snow-water |

Not found: SWE or snow depth documentation from commercial providers other than ExoLabs (Planet, Descartes Labs, Spire, SnowForecast). Meteoblue describes its snow depth as a rough estimate (snippet): https://content.meteoblue.com/en/research-education/specifications/weather-variables/precipitation/snow/ . Copernicus HR-S&I has no SWE product that I could verify. For SNOWGRID (GeoSphere Austria) I found no error numbers.

### 1.2 Reading the table (judgement)

- Nobody validates a snow-cover-only model on snow cover alone and calls the SWE good. Published systems either assimilate station HS (Switzerland, Italy) or are checked against lidar or pillows (Margulis group). For depth the best-case numbers are 6.25 cm RMSE at stations that were assimilated in neighbouring areas (Oberrauch 2026, highest elevation band) and 17.3 to 25.6 cm in earlier OSHD work (as quoted in Lievens 2022, verified abstract page text). For SWE, systems with ground data have 90 to 300 mm RMSE (IT-SNOW) and the Landsat reanalysis has about 0.2 to 0.4 m RMSD against lidar at peak in a deep-snow basin.
- For regions with no station HS, the only published way to constrain SWE magnitude is the fSCA reanalysis: precipitation is the unknown and the melt-out timing of each place tells you how much snow had to be there. Margulis et al. 2019 (page opened, limits section read through a summarising tool, so the wording below is a paraphrase to be checked, not a quote) lists these limits: fSCA carries weak instantaneous information on SWE, accumulation-season measurements are often non-informative because the ensemble spread is negligible, forest snow is invisible to the sensor, the method is a retrospective smoother that cannot run in real time, and posterior peak SWE can still be underestimated at high elevations.
- Thin, patchy, wet Mediterranean snow is a favourable case for fSCA assimilation (snow cover disappears and reappears repeatedly, so the observation carries information on the rain/snow line, the melt rate and the accumulated amount) and an unfavourable case for Sentinel-1 depth (Lievens 2022: shallow snow below 1 m maximum depth has little backscatter signal; wet snow lowers backscatter). This is my judgement from those two sources.
- Raw reanalysis snow is not a substitute. Kouki et al. (TC 17, 5007, 2023, snippet only) report that ERA5 and ERA5-Land overestimate Northern Hemisphere SWE "by roughly 150% to 200%" (search summary, not read in the paper). Sarigil et al. (verified): ERA5-Land overestimates mean annual SWE and snow cover duration in the Alps, and "CERRA-Land shows more moderate biases than ERA5-Land in the Italian Alps" but underestimates SWE in most subregions. Use reanalyses as forcing (temperature, precipitation), not as a snow product.

### 1.3 ExoLabs, what is actually documented

All items verified on the pages named, unless marked.

- Snow depth (https://exolabs-ch.gitbook.io/cosmos/snow-depth): inputs are satellite snow cover masks, weather station snow depth values and topographic relationships (slope, sun exposure) quantified with fifty NASA Airborne Snow Observatories datasets. The method is geostatistical interpolation of the station values with local and regional drifts. When snow cover and snow depth disagree the product favours snow depth. Resolution 20 m (a simplified global product at 300 m). Validation: 23 independent reference datasets from Davos, 2,274,247 points, "average error of just 0.36 meters". No RMSE, bias, or description of how the reference data were produced.
- Snow cover (https://exolabs-ch.gitbook.io/cosmos/snow-cover): Sentinel-2, Sentinel-3, Landsat 8/9, VIIRS and MODIS, 20 m high-resolution product and 500 m global product, cloud gaps filled by machine learning. The page lists seven platforms while claiming "nine different optical satellites" and gives no validation.
- Snow water (https://exolabs-ch.gitbook.io/cosmos/snow-water): "an empirical approach"; estimated RMSE 53 kg/m2; no reference data, no resolution.
- Peer-reviewed or semi-technical sources: Leiterer, Stasinowsky and Mayer, Bulletin SEV/VSE 2/2021 (not peer reviewed; the first author is the ExoLabs CEO), https://www.bulletin.ch/sites/default/files/2022-12/2021_02_Leiterer_Abschaetzung_des_Schneewassers.pdf : SWE from three components (in-situ data including Think Outside radar and stations, a UBIMET mass-balance model, ExoLabs satellite products), a regression of snow depth on topography, a generalized additive model that spreads ground SWE and station values, and daily recalibration of the UBIMET model against stations. Quoted limitation: "eine flaechendeckende Validierung dieser neuen SWE-Produkte noch aussteht" (a nationwide validation of these new SWE products is still pending).
- Caye Daudt et al., ISPRS J. Photogramm. Remote Sens. 197, 105-121, 2023, https://doi.org/10.1016/j.isprsjprs.2023.01.017 : country-scale snow depth from Sentinel-2 with a neural network, first trained on ExoLabs snow maps, then fine-tuned on Dischma valley data from WSL. I could not open the abstract, so I have no error numbers.
- I found no independent evaluation of any ExoLabs product.
- Judgement: ExoLabs snow depth is a station interpolation constrained by a satellite snow mask, not an independent satellite retrieval; its SWE is depth times a density model plus a mass-balance model recalibrated on stations. Both depend on a dense station network (Switzerland) that Sierra Nevada does not have. The method is not transferable to Sierra Nevada without stations.

### 1.4 Spain and Sierra Nevada

- WiMMed group (Polo, Herrero, Pimentel, Perez-Palazon): Guadalfeo monitoring network and Refugio Poqueira camera data are open on PANGAEA (section 4). Verified published numbers: camera snow cover fraction accuracy "0.075 m2 m-2" (Polo et al. 2019, ESSD 11:393, https://essd.copernicus.org/articles/11/393/2019/essd-11-393-2019.html); Pimentel et al. 2017 (Remote Sensing 9(10):995, https://doi.org/10.3390/rs9100995): "Both methods provided satisfactory results when the snow cover was above 85% of the study area; below this threshold, the use of spectral mixture analysis is clearly recommended. Mixed pixels can reach up to 40% of the area during wet and cold years."; Pimentel et al. 2015 (J. Hydrometeorology, https://doi.org/10.1175/JHM-D-14-0046.1): "A reduction in the error for snow depth to 50% (from 463.87 to 261.21 mm and from 238.22 to 128.50 mm) is achieved if the appropriate curve is selected." (abstract via Crossref; the point is that snow depth error depends on the density or depletion curve chosen).
- Collados-Lara et al. 2017 (Hydrological Processes, https://doi.org/10.1002/hyp.11165): cross-validated snow estimation procedure, no numbers in the abstract. A 2020 paper (Sci. Total Environ., https://doi.org/10.1016/j.scitotenv.2020.140485) gives a "mean seasonal SWE 330 Hm3, maximum 480 Hm3" figure in a search snippet only.
- ERHIN (MITECO): official page states "281 pertigas ... 21 en Sierra Nevada" and 16 snow gauges, none in Sierra Nevada. I found no downloadable station data.
- MODIS snow cover maps for Sierra Nevada from 2002 exist on Zenodo (EURAC, https://zenodo.org/records/3407391, CC-BY-4.0). Not in situ.
- I found no published Sentinel-2 assimilation SWE validation in Sierra Nevada. The closest Spanish work is Mazzolini et al. 2025 in the Pyrenees (above).

---

## 2. Honest assessment of the current model

Source: code in `pipelines/snow_model/` (snowpack.py, forcing.py, insertion.py, ensemble.py, daily.py, validation.py, run.py) and `regions/sierra-nevada.snow-calibration.json` at origin/main commit 4d7de6f. What the code does was read in the code; the comparison with the literature is judgement.

### 2.1 What it does

- Forcing: Open-Meteo archive, model `ecmwf_ifs`, 0.1 degree grid, hourly temperature, precipitation, shortwave. Each 100 m cell takes 4 neighbouring forcing points, shifted by a fixed lapse rate (member value 4.5 to 8.0 K/km) and a precipitation factor `1 + gradient * dz/100 m`, clipped to 0.3 to 3.0 (gradient 0 to 0.10 per 100 m), times a global `precipitation_scale` (0.7 to 1.6).
- Snow physics: one bulk layer. Snowfall fraction is a linear ramp over +-1 K around a threshold (0 to 2.5 C). Melt is `(melt_factor + radiation_factor * shortwave) * positive_degree_hours`, bounded by SWE. New snow density is `67.92 + 51.25 exp(T/2.59)` clipped to 50 to 200 kg/m3 (this matches the Hedstrom and Pomeroy form as I remember it; not verified against the paper). Compaction toward 450 kg/m3 at 2 %/day dry and 5 %/day when melting. Depth is SWE divided by that density.
- Snow cover diagnostic: a cell is snow covered when modelled depth is at least 3 cm. It is binary.
- Calibration: 48 Latin-hypercube members, six parameters, scored on 20 fit dates of Sentinel-2 snow masks from a single year (the `calibration_years` entry is 2025), weights from an exponential cost tempered to an effective size of 12, 10 held-out test dates (every third date), gate `min_f1 = 0.8`. The 16 highest-weight members are the operational ensemble.
- Operational run: starts each 1 October with zero snow, steps the ensemble one day, applies direct insertion of Sentinel-2 (cells with at least 50 % decisive pixels and at least 85 % of those bare are set to zero SWE and depth; shaded cells inherit bare if the lit bands from 200 m below up show almost no snow), publishes the ensemble median of `swe` and `snow_depth`.

### 2.2 Problems, ordered by how much they hurt

1. **SWE and depth are not constrained or validated by any SWE or depth information.** The only data used are binary snow cover masks, and `validation.py` computes only snow-presence metrics (F1, MCC, Brier, accuracy). A model can have F1 above 0.8 with SWE wrong by a factor of two, because precipitation scale and melt factor trade off: more snow with faster melt gives the same melt-out date. With six free parameters and one season this equifinality is likely (judgement). It is why the literature makes forcing uncertainty explicit and conditions on the melt-out behaviour of many places at once (Margulis et al. 2019).
2. **Calibration is global and static.** The six parameters are fitted once, on one year, and applied to every later season. Mountain precipitation bias changes between seasons; the reanalysis literature estimates it per reanalysis year (Margulis et al. 2019 perturb a lognormal multiplicative precipitation factor with bounds 0.1 to 5 for each water year).
3. **Direct insertion only removes snow and has no memory.** It sets bare cells to zero and never adds snow where Sentinel-2 sees snow. The next snowfall is simulated with the same biased precipitation, so the error returns, and the removal breaks the mass balance. It does not update the parameters that caused the error. The assimilation methods in section 1 update weights or parameters through a Bayesian or Kalman update.
4. **Observation operator mismatch.** The model cover is binary (depth at least 3 cm) at 100 m, while the observation is a sub-cell fraction of 25 pixels of 20 m. The WUS-SR uses a sub-grid snow depletion curve (Liston et al. 2004, per the NSIDC user guide) and an explicit fSCA error (about 10 % at 480 m, Margulis et al. 2019).
5. **The snow-pixel classification has no stated error.** Bare/snow thresholds are the authors' own choice (the code comments say so). There is no comparison with an independent reference. Published references: HR-S&I Sentinel-2 accuracy 94 %, kappa 0.81 (Barrou Dumont 2021); Poqueira camera cover fraction accuracy 0.075 (Polo 2019).
6. **One forcing source, six varied parameters.** IFS at 0.1 degree is a coarse field for a 3,000 m range, and the only handles are a global scale and an elevation gradient. There is no storm-level precipitation error, so the ensemble does not represent the main source of error. No wind redistribution, canopy, sublimation, rain-on-snow refreeze or liquid water retention. These matter less for thin Mediterranean snow than for the Alps (judgement), but they are not zero.
7. **Ensemble spread is not a calibrated uncertainty.** The 16 operational members are the top-weighted calibration members and the published layer is their median. Nothing checks spread against error (spread-skill, coverage), and nothing in the product tells a user whether a cell was observed two days or two months ago.
8. **Validation leakage and weak design.** Test dates are every third date of the same season (`split_fit_test`), so neighbouring and strongly correlated dates sit on both sides of the split. One season of calibration cannot show interannual skill. There is no held-out season and no SWE or depth reference.
9. **Depth is a diagnostic of one density curve.** Density is not perturbed and no depth observation is used.

### 2.3 What it gets right (keep)

- The ensemble framework, the tempered weights with a target effective size, and `weighted_quantiles` are the machinery a particle batch smoother needs.
- The Sentinel-2 classification with confidence classes and a shadow flag is better than a plain NDSI threshold, and the 20 m pixels give a real sub-grid fraction inside a 100 m cell.
- Daily checkpoints are operationally convenient. In v2 they become a cache, not the source of truth.

### 2.4 Verdict (judgement)

The current model is a reasonable snow-cover model and a poor SWE model. Its snow-cover skill can be defended with the F1 numbers it reports. Its SWE and depth cannot be defended: nothing measures them, and the structure allows large compensating errors. The change needed is to treat precipitation (and temperature) bias as an explicit, season-specific unknown, use the proper sub-grid observation operator, and report calibrated uncertainty, which is what the comparable published fSCA reanalyses do.

---

## 3. Recommended v2 design

### 3.1 Comparison of the four options

Effort numbers are my estimates in working days for one developer who knows the repo, including tests and the publishing step but not the validation campaign. Compute figures are judgement and must be benchmarked (task T0).

| | A. fSCA SWE reconstruction (retrospective) plus forward model | B. Particle batch smoother or ES-MDA on the temperature-index ensemble, precipitation bias unknown | C. Multi-layer FSM2 type model on ERA5-Land with S2 assimilation | D. Hybrid with Sentinel-1 wet snow and depth |
|---|---|---|---|---|
| Pedigree | Cline et al. 1998, Rittger et al. 2016: back-calculate SWE from snow disappearance. A 2023 intercomparison says it gives SWE only at peak and only in hindcast (search summary) | Margulis et al. 2015, 2019; Fang et al. 2022 (WUS-SR: 50 replicates, PBS); Aalstad et al. 2018 (ES-MDA, Sentinel-2 and MODIS); Oberrauch et al. 2026 preprint (PBS with Sentinel-2) | Essery et al. 2025 (FSM2); Mazzolini et al. 2025 (FSM2 with Sentinel-2 and ICESat-2, Pyrenees); OSHD (FSM2oshd) | Lievens et al. 2019, 2022; Boeykens et al. 2026; wet snow flag from a -2 dB backscatter change |
| Data needed | S2 fSCA, DEM, forcing, a melt model | Same as A | Full forcing: temperature, humidity, wind, pressure, shortwave, longwave, precipitation phase (I did not open the FSM2 user guide to confirm the list) | S1 RTC (Planetary Computer, tested), snow mask, forest cover, a depth reference to calibrate |
| Compute on a free runner | Light | Light if the smoother runs on elevation/aspect classes and only the final posterior runs on 100 m cells (about 2.5 x 10^8 class-days per pass for 1,000 members, my estimate) | Fortran executable, several layers, hourly; one to two orders of magnitude heavier per member than B (judgement), so the ensemble must be small | One S1 RTC scene is about 1.8 GB (tested: `Content-Range ... /1845184501`); range reads help, data volume is the cost |
| Skill for thin patchy snow | Good for melt-season amount; blind in accumulation; no real-time use | Good where snow melts out repeatedly (cover change carries information); weakly constrained mid-winter | Better physics, but forcing error dominates; no extra constraint over B without station HS (judgement) | Low for depth in shallow snow (Lievens 2022: maximum depth below 1 m gives little signal); wet-snow flag useful |
| Failure modes | Needs the whole melt season; cloud gaps at melt-out; ephemeral snow is the hard case | Weight collapse with few observations; compensation between melt and precipitation when melt parameters are free (priors and tempering, 3.3 and 3.6); forest and shadow bias in fSCA | More parameters to guess; still needs a precipitation bias; effort and runtime | Wet snow undercounting, forests, freeze-thaw; depth bias in thin snow |
| Clouds and gaps between S2 passes | Waits | Posterior parameters are season-wide, so a cloudy spell costs only the information of that date; between passes the model integrates forward; the age of the last clear observation is published | Same as B | S1 sees through cloud: a real advantage for a wet-snow flag |
| Honest uncertainty | Single estimate | Weighted ensemble quantiles; process noise and tempering keep spread honest (3.3, 3.6) | Same if the ensemble is large enough | Ensemble of retrievals not standard |
| Effort | 8 to 10 days standalone | 15 to 20 days, reusing `ensemble.py`, the `insertion.py` cell state and the `daily.py` publishing | 25 to 40 days | 12 to 20 days for a wet-snow flag; a depth layer is not recommended |

### 3.2 Recommendation

**Build B.** It contains A (run over a finished season it is a Bayesian SWE reconstruction), it reuses the ensemble framework and tempered weights, it needs only data that exist and were tested (section 4), and it is the nearest implementable cousin of the WUS-SR and of Oberrauch et al. 2026.

- C is the upgrade path once station HS or SWE exist for the range, because its extra physics cannot be tested without them (judgement). The smoother in B is model-agnostic, so FSM2 can replace the bulk model later.
- D is limited to a wet-snow flag (Lievens 2022: -2 dB change threshold). Do not fuse S1 depth into SWE here without station data to calibrate the rescaling.
- Not recommended: more calibration of the six static parameters on more years. It does not address problems 1 to 3 of section 2.

### 3.3 State, parameters and priors

`i` indexes model points (3.5), `m = 1..N` members, `t` days. Parameters are drawn once per season and member (seeded by water year).

Priors are my starting values, to be tuned on the other seasons in the leave-one-season-out scheme of section 5. Margulis et al. 2019 values are given for orientation; they are for MERRA-2 over the Tuolumne and are not transferable.

| Symbol | Meaning | Prior |
|---|---|---|
| `b0` | Season precipitation multiplier at the reference elevation | lognormal, median 1.0 on the IFS field, CV 0.4, bounds 0.3 to 3.0 (Margulis 2019: Tuolumne mean 2, CV 0.75, bounds 0.1 to 5) |
| `g` | Precipitation gradient per 100 m | uniform 0 to 0.10 (current range) |
| `dT` | Additive temperature bias | normal, mean 0, SD 1.5 K (Margulis 2019: Tuolumne mean 0.5 K, SD 2 K) |
| `L` | Lapse rate | uniform 4.5 to 8.0 K/km (current range) |
| `Ts` | Rain/snow threshold | uniform 0 to 2.5 C (current range) |
| `DDF` | Degree-day melt factor | uniform 1.0 to 3.5 (current range) |
| `rad` | Radiation melt factor | uniform 0 to 0.012 (current range) |
| `beta` | Sub-grid CV of SWE (depletion curve) | uniform 0.05 to 0.8 (Margulis 2019) |
| `rho_s` | Scale on the compaction curve (affects depth only) | normal, mean 1, SD 0.15 (new) |
| `xi_e` | Storm-level log precipitation error, independent per storm `e` | normal, mean 0, SD 0.25 (new, judgement) |

Storm-level process noise is essential. Without it every member sees the same storm timing and amounts, the spread collapses once the parameters are fixed, and the ensemble is overconfident between observations. With it the weights act on parameters and storm noise together (a plain PBS on the trajectory), and the spread grows in cloudy periods.

State per member and point: SWE `S` (mm), depth `h` (m), `S_peak` (mm, SWE at the start of the current melt episode), `M_cum` (mm, melt since that peak).

### 3.4 Forward model (changes to the existing model)

Keep the daily step of `snowpack.py` and change these items.

1. Forcing perturbation: `P'(i,t) = b0 * exp(g * (z_i - z_ref)/100) * exp(xi_e(t)) * P_IFS(i,t)` and `T'(i,t) = T_IFS(i,t) - L * (z_i - z_f)/1000 + dT`, where `z_f` is the forcing point elevation.
2. Sub-grid snow cover. This is my formulation of the depletion-curve idea of Liston et al. 2004 used in the WUS-SR; check it against the paper before implementing (task T3). Local peak SWE in a cell is lognormal with mean `S_peak` and CV `beta`: `sigma2 = ln(1 + beta^2)`, `mu = ln(S_peak) - sigma2/2`. During a melt episode the covered fraction is the share of the cell whose local peak SWE exceeds the melt since the peak:
   `f_sca = 1 - Phi((ln(M_cum) - mu) / sigma)`, with `f_sca = 1` when `M_cum = 0`.
   A snowfall of at least `S_new` (start with 5 mm) restores `f_sca = 1` and resets `S_peak <- S`, `M_cum <- 0`. The state SWE `S` stays the cell mean, which is what is published.
3. Depth: `h = S / rho`, with `rho` from the existing compaction scheme multiplied by `rho_s`. State in the product that depth is the cell mean.
4. Remove direct insertion from the forward run. Observations act only through the weights (3.6).

### 3.5 Domain reduction (what makes it cheap)

Parameters are regional and the likelihood is pooled, so the smoother does not need all cells (about 0.9 degree by 0.27 degree at 100 m is roughly 240,000 cells, my estimate). Build classes by elevation band (100 m), aspect (N, E, S, W, flat) and forcing cell, keep classes with at least 20 cells, and run the `N` members on class-mean points. After the weights are computed, run the top weighted members (for example 100) once on the 100 m grid to produce maps.

Cost (judgement, benchmark in T0): `N = 1000` members x 1000 classes x 250 days = 2.5 x 10^8 class-days per pass; the full-grid pass is 100 x 240,000 x 250 = 6 x 10^9 cell-days, comparable to a present calibration year (48 members) and inside the 6 h limit with margin.

### 3.6 Observation operator and likelihood

For each clear Sentinel-2 date `k` and class `c`:

- Observed fraction `y(c,k)`: snow share among decisive pixels (snow, or high-confidence bare, as in `insertion.cell_state`) pooled over the cells of the class that have at least 50 % decisive pixels. Cloud and terrain-shadow pixels are excluded, not treated as bare. The shadow inheritance rule of `insertion.shadow_bare` may be used as lower-confidence bare evidence.
- Model fraction `x_m(c,k)`: mean of `f_sca` over the class (3.4).
- Observation error `sigma_o = sqrt(0.10^2 + (0.5/sqrt(n))^2)` where `n` is the number of decisive cells in the class. The 0.10 floor is the Landsat fSCA standard deviation of "about 10%" at about 480 m in Margulis et al. 2019, taken as a floor for a pooled class. Replace it with a Sentinel-2 specific error from the validation of section 5.
- Cost `J_m = 0.5 * sum_{c,k} ((y - x_m)/sigma_o)^2 / n_corr`. `n_corr >= 1` is a correlation correction because dates within three days and neighbouring classes are not independent; start at 3 and tune on coverage.
- Weights `w_m` proportional to `exp(-lambda * J_m)` with `lambda` set by the existing `tempered_weights` to reach an effective size target (30 for `N = 1000`; the current code uses 12 for 48 members).
- Fallback if the effective size stays below 10: ES-MDA (Aalstad et al. 2018 as described in the search summary, paper not opened): `Na = 4` iterations, `alpha = Na` each so that the inverse inflation factors sum to 1, parameters transformed to Gaussian space, forward model rerun each iteration. Choose PBS or ES-MDA on held-out dates (task T6).

### 3.7 Daily operational algorithm

1. Make sure the catalogue `snow_obs` holds every clear S2 date since 1 October of the water year (backfill, task T1).
2. Fetch forcing from 1 October to the latest day (archive plus forecast for the last days; section 4). Cache the archive part.
3. Draw `N` members, seeded by water year so the prior never changes between days.
4. Run the class-reduced domain for all members from 1 October to today.
5. Compute `J_m` and `w_m` from all observations to date, tempered.
6. Resample or take the top `R` (100) members, run them on the 100 m grid from 1 October to today, and compute weighted quantiles of SWE and depth per cell.
7. Publish (3.8). Store the season seed, weights, member parameters, `sigma_o` and the observation dates used. Daily state files are no longer needed: the season-to-date rerun is cheap and removes the state-signature mismatch that `daily.py` guards against.
8. For a finished water year run once more with all observations (retrospective mode), freeze, publish as reanalysis, and feed the validation harness.

Recomputing from 1 October each day means today's value is a smoothed estimate of the season with the latest observation, as in the WUS-SR but with an expanding window. Earlier dates change retroactively; the catalogue needs a version tag for that (judgement).

### 3.8 What the product publishes

Per date and 100 m cell:

| Layer | Content |
|---|---|
| `swe_p50`, `swe_p10`, `swe_p90` | Weighted quantiles of SWE (mm). |
| `snow_depth_p50`, `snow_depth_p10`, `snow_depth_p90` | Same for depth (m), cell mean. |
| `p_snow` | Weighted probability that `f_sca >= 0.5` (replaces the binary diagnostic; enables Brier and reliability scores). |
| `fsca_p50` | Weighted median sub-grid snow fraction. |
| `obs_age_days` | Days since the last clear decisive S2 observation of the cell, or of its class when the cell was shaded or cloudy. |
| `quality` | 0 observed on this date and consistent with the posterior; 1 last observation 1 to 5 days ago; 2 six to 15 days; 3 more than 15 days (prior and forcing dominate); 4 forecast days. Lower the level by one if the posterior effective size is below 15 or the cell is forested or in terrain shadow. |
| Season metadata | Effective size, number of observations used, posterior medians of `b0`, `g`, `dT`, so a reader can see the precipitation correction the data demanded. |

If no clear observation exists since 1 October the product must publish quality 3 or worse everywhere and say SWE is prior-driven.

### 3.9 Expected skill and limits for Sierra Nevada (judgement)

- Where it should work: melt-season SWE amount above about 2,000 m, snow-line elevation, melt-out date, snow presence. Thin Mediterranean snow melts out and returns repeatedly, which repeatedly informs the rain/snow limit and the melt rate. The Poqueira camera series (maximum depth 1.19 m over 2009 to 2013, from the PANGAEA file the data agent read) shows that even the 2,510 m station seldom has deep snow.
- Where it will not: mid-winter amount when the range is fully snow covered (fSCA of 1 carries no magnitude information, as Margulis et al. 2019 note), forest and cloud periods, winter terrain shadow, wind-redistributed crest snow and cornices (not modelled).
- Numbers: unknown until validated. The nearest published numbers are WUS-SR peak SWE RMSD below 0.38 m and Landsat-only ASO RMSD 0.22 to 0.31 m in WY2016 and WY2017 (Margulis 2019 Table 3; WY2015 was 0.054 m). Those are deep-snow basins; I have no Sierra Nevada (Spain) number and do not claim the same skill.

---

## 4. Data sources verified accessible today (2026-11-22)

"Tested" means a call was run from this machine on 2026-11-22 (by me or by a research sub-agent in this session) and the result is given. Items I could not test are in 4.4. Throughout, an HTTP 200 on a landing page is not a data test; the data tests are marked.

### 4.1 Satellite and terrain (tested by me)

| Source | What I tested | Result |
|---|---|---|
| Sentinel-2 L2A, Earth Search STAC `https://earth-search.aws.element84.com/v1/search`, collection `sentinel-2-l2a` | POST search over the Sierra Nevada bbox for March 2018; POST search for the oldest scenes over a point; range read of a COG asset | HTTP 200, 19 items for March 2018 (e.g. `S2B_30SVF_20180330_1_L2A`), assets include `scl`, `green`, `nir`, `swir16`, `visual`. The oldest items returned for the point were `S2A_30SVF_20161110_0_L2A`, so the archive starts 2016-11, not 2017. `Range: bytes=0-1023` on `.../sentinel-s2-l2a-cogs/30/S/VF/2018/3/S2B_30SVF_20180330_1_L2A/SCL.tif` returned 206 with `Content-Range: bytes 0-1023/1566177`. No key |
| Sentinel-1 RTC, Planetary Computer STAC `https://planetarycomputer.microsoft.com/api/stac/v1`, collection `sentinel-1-rtc` | POST search for Jan to Mar 2023; collection metadata; token endpoint `/api/sas/v1/token/<account>/<container>`; ranged read | HTTP 200, 19 items, assets `vv`, `vh`, polarizations VV and VH, e.g. `S1A_IW_GRDH_1SDV_20230226T061913_..._rtc`. Collection start 2014-10-10, licence CC-BY-4.0. The token endpoint issued a token with no key. Ranged read returned 206, `Content-Range: bytes 0-1023/1845184501` (one scene 1.8 GB) |
| MODIS MOD10A1/MYD10A1 v061 on Planetary Computer, collection `modis-10A1-061` | STAC search for Feb 2024 over a small box; token; ranged read of `NDSI_Snow_Cover` | 5 items returned (tile h17v05, assets `NDSI_Snow_Cover`, QA bands); ranged read 206. No key |
| Copernicus DEM GLO-30 | `curl -I` on `https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N37_00_W004_00_DEM/Copernicus_DSM_COG_10_N37_00_W004_00_DEM.tif`; Planetary Computer collection `cop-dem-glo-30` | HTTP 200 for the AWS object; the Planetary Computer collection exists (licence shown as "proprietary", read the Copernicus DEM licence before redistribution) |
| ERA5 on Planetary Computer (`era5-pds`) | Collection list | Present in the catalogue. Not downloaded (agent test, below) |
| Copernicus Data Space STAC `https://stac.dataspace.copernicus.eu/v1/collections?limit=200` | Listing | HTTP 200 without a key. The first 200 collections include `clms_sce_europe_500m_daily_v1`, `clms_swe_northernhemisphere_5km_daily_v1` and `..._v2`, and `clms_lie_*` (lake ice). I did not see a high-resolution GFSC/HR-S&I collection in that list, and I did not test downloads or a second page of the listing |

### 4.2 Forcing (tested by a research sub-agent, with one check by me)

Requests: `https://archive-api.open-meteo.com/v1/archive?latitude=37.05&longitude=-3.31&...&models=<m>`. All HTTP 200 without a key. Open-Meteo snapped the request to the cell named and returned elevation 3389 m (its 90 m DEM at that point, near the Mulhacen summit), so these tests sample a summit cell.

| Model on Open-Meteo archive | Cell returned | Variables that returned values (Jan 2024 test) | Resolution and period |
|---|---|---|---|
| `ecmwf_ifs` | 37.083, -3.329 | precipitation, snowfall, temperature_2m, shortwave_radiation; no snow_depth | 9 km hourly (docs); earliest returned 2017 (docs: IFS HRES available from 2017-01-01) |
| `era5` | 37.0, -3.25 | same as IFS; no snow_depth | 0.25 degree hourly, 5 day delay; from 1940 |
| `era5_land` | 37.1, -3.30 | **only temperature_2m and snow_depth**; precipitation, snowfall and radiation returned no values (retested on 1990, 2010, 2021, 2023, 2025 dates). The docs variable matrix agrees | 0.1 degree hourly, 5 day delay; from 1950 |
| `era5_seamless` | 37.1, -3.30 | all five | mixes ERA5 and ERA5-Land |
| `cerra` | 37.044, -3.298 | nothing for 2024; has data 1985-01-01 to 2021-06-30 | 5 km; docs "CERRA Europe 5 km Hourly 1985 to June 2021" |
| `ecmwf_ifs025`, `ecmwf_aifs025` (archive) | | no values | |

- **Consequence: the question "is ERA5-Land available as an anonymous alternative" has a clear answer. On Open-Meteo, ERA5-Land has no precipitation, so it cannot be the precipitation forcing. Use `era5` for precipitation, snowfall and radiation, and `era5_land` for temperature and snow depth only.**
- Historical-forecast API `https://historical-forecast-api.open-meteo.com/v1/forecast`: `ecmwf_ifs` data from 2018 at the test point; `icon_global`, `icon_eu` first data on the probe 2023-06-15; `gfs_seamless` 2022-01-15 (snowfall empty on later probes); ARPEGE Europe and UKMO from 2023-06-15; `meteofrance_arome_france` and `icon_d2` returned "No data is available for this location". The France-only AROME models do not cover this region on Open-Meteo, so there is no open 2.5 km archive there.
- Check by me (the repo-relevant one): the archive API adjusts temperature to the requested elevation. Same day, same point, `ecmwf_ifs`, 12 UTC: default (elevation 3389 m) -5.0 C; `&elevation=1000` 10.3 C (15.3 K over 2,389 m, about 6.4 K/km); `&elevation=3389` -5.0 C. Daily precipitation total also changed (1.2 mm default versus 1.5 mm at 1000 m), which I cannot explain. The repo's `forcing.py` stores the returned elevation as the forcing point elevation and applies its member lapse rate relative to it, so there is no double correction, but the temperature field has already received Open-Meteo's own lapse rate (about 6.4 K/km here) at the 90 m DEM point, which may be a single steep pixel rather than a 0.1 degree cell mean. Test this in T2 (compare points with `&elevation=` equal to the cell mean).
- Snowfall spread across models (sub-agent, January 2021 at the same cell): ERA5 113.6 mm precipitation and 22.1 cm snowfall; IFS 146.3 mm and 87.6 cm; CERRA 184.9 mm and 117.9 cm. Our own rain/snow partition removes the model snowfall dependence, but the precipitation totals still differ by about 60 % between ERA5 and CERRA for that month at that cell.
- Open-Meteo terms (read from the website source `open-meteo/open-meteo-website` on GitHub, `terms/+page.svelte`, because open-meteo.com timed out): "Less than 10'000 API calls per day, 5'000 per hour and 600 per minute. You may only use the free API services for non-commercial purposes. You accept to the CC-BY 4.0 licence"; non-commercial examples include "Private or non-profit websites or apps that do not have subscriptions or advertising"; commercial examples include "Websites or apps that have subscriptions or display advertisements. Commercial products or promotional activities." Requests "extending over a period of more than 2 weeks for a single location are considered multiple API calls." A free app without ads or subscriptions fits the quoted non-profit example, but "non-profit" is in that sentence, so a company running NivoSense should confirm with Open-Meteo or buy the plan. This is my reading of the text.
- Keyless alternatives for ERA5 (not Land): Google Cloud `gcp-public-data-arco-era5` (listing and metadata read, HTTP 200; ERA5 not Land; coverage 1940 to 2026-06-30; a point series needs one chunk read per hour; no data value was read); Planetary Computer `era5-pds` (STAC and token keyless; no data downloaded). AWS `era5-pds` returned 403. No keyless ERA5-Land source other than Open-Meteo was found.
- CERRA (5.5 km, 1984-09-01 to 2026-08-31 per the CDS catalogue) needs a CDS account for downloads; the CDS catalogue API answered without a key. E-OBS v34.0e (0.1 degree, 1950 to 2026-06-30, 3.2 GB file, HTTP 200) is keyless but "strictly for use in non-commercial research and non-commercial education projects only". IMERG V07 returned 401 (Earthdata login). AEMET OpenData: no key returned an empty body, a fake key returned `"estado": 401`; a free key is needed, and a datos.gob.es article (2024) says AEMET does not treat numerical model outputs as open data (not verified against AEMET). MSWEP, Spain02/SPREAD, MESCAN: not tested.

Implication for the design (judgement): precipitation forcing = `ecmwf_ifs` (9 km, 2017 onward) as primary, with `era5` (0.25 degree, 1940 onward) as an alternative forcing source drawn per member in the ensemble (a discrete structural-uncertainty parameter) and as the only source for seasons before 2017-18. Temperature from the same source. Do not use `era5_land` for precipitation. Mountain precipitation bias is large and mostly a bias in snowfall; the literature says it should be corrected with snow observations: Von Kaenel and Margulis (2025, https://tc.copernicus.org/articles/19/3309/2025/) "significant biases and high uncertainty in mountain precipitation data products pose significant challenges", their bias correction reduced "multi-year averaged normalized root mean square difference (NRMSD) from 78 % to 33 %" and "lies in capturing the spatial distribution of precipitation bias rather than its interannual variability", and Winstral et al. 2019 (https://jannefiluren.github.io/docs/Winstral2019%20-%20The%20bias%20detecting%20ensemble%20for%20snow%20assimilation.pdf) used an ensemble of predetermined forcing perturbations evaluated with snow depth at "nearly 300 sites" with Nash-Sutcliffe 0.98 against 0.81 without. The first supports a season-specific `b0` as in 3.3; the second is the same idea with stations, which we do not have.

Rain/snow partition: Jennings et al. 2018 (https://pmc.ncbi.nlm.nih.gov/articles/PMC5861046) report a mean 50 % rain-snow air temperature threshold of 1.0 C ranging "from -0.4 to 2.4 °C for 95% of the stations", "higher values observed in the Pyrenees, Alps, and Scandinavian Mountains", and that methods including humidity perform better. The 0 to 2.5 C prior range in 3.3 covers that range; a humidity-based variant (wet bulb) is a possible later upgrade.

Density for depth: Sturm et al. 2010 (J. Hydrometeorology 11, 1380): "the predictive power of the model for snow depths less than 30 cm is relatively poor". Jonas et al. 2009 (J. Hydrology 378, 161): bulk density depends on season, snow depth, site altitude and site location. Both are Alpine or North American; the thin snow of Sierra Nevada is the poor case for them, which is a reason to perturb density (`rho_s`) rather than fix a curve.

### 4.3 In situ and reference (tested by a research sub-agent; see 5.1 for use)

| Source | Test and result | Usable without a request |
|---|---|---|
| PANGAEA 895236 Guadalfeo Monitoring Network (Polo et al. 2019, ESSD 11:393), CC-BY-4.0 | `curl https://doi.pangaea.de/10.1594/PANGAEA.895236?format=zip` HTTP 200, 7,088,170 bytes; zip holds `Guadalfeo_PG1..5_meteo.tab` and `_hourly.tab`. Daily columns: relative humidity, air temperature, wind speed, precipitation, pressure; radiation at PG2 to PG5. PG1 37.049 N -3.214 E (2005-11-19 to 2018-08-31), PG2 37.029 N -3.324 E (2004-11-04 to 2018-08-31), PG4 37.008 N -3.355 E (2012-10-11 to 2018-08-31), PG5 37.085 N -3.473 E (2017-02-22 to 2018-08-31). PG3 (36.872 N) is on the Contraviesa crest outside the range | Yes |
| PANGAEA 871706 Refugio Poqueira camera (Pimentel, Herrero, Polo 2017), CC-BY-3.0 | `?format=textfile` HTTP 200, 31,908 bytes. Daily snow cover fraction and snow depth (m) at 37.02825 N -3.32337 E, 2,510 m, 2009-11-15 to 2013-05-31, 30 x 30 m plot; 1,218 daily rows in the data block read, maximum depth 1.1871 m, 461 days with depth above 0 | Yes |
| PANGAEA 992415, 992412, 992414, 991999 (Lopez Calero, Collados-Lara et al., in review): in-situ snow depth and temperature from snow poles 2020-03 to 2025-02 (37.02-37.12 N, -3.42 to -3.25 E), citizen-science photos, Pleiades-derived depth March 2024 | Textfile downloads of 992412 and 992414 returned HTTP 401 ("you need to be authorized ... contact the principal investigator"), 992415 returned 400, JSON-LD `isAccessibleForFree:false`; licence CC-BY-4.0 only "after moratorium ends" | **No** |
| Drone snow depth 992025, 992022 (Feb 2024) | Landing pages 200; downloads not tested; a snippet suggested a moratorium to 2027-02-12 (not verified) | No (unverified) |
| IFAPA RIA (Junta de Andalucia) | `GET https://www.juntadeandalucia.es/agriculturaypesca/ifapa/riaws/estaciones/18` HTTP 200 JSON station list; `/datosdiarios/18/6/2023-12-01/2025-11-20/false` HTTP 200, 713 rows (Jerez del Marquesado, 1,201 m); station 7 (Cadiar, 928 m) 721 rows. Daily temperature, precipitation, humidity, wind, radiation; no snow. Hourly path returned 404 in one try. Licence not checked | Yes, no key; low altitude only |
| AEMET OpenData | No key: HTTP 200, empty body; fake key: `"estado": 401`. Key required | No |
| AEMET public web page, Pradollano (climate id 5511, 3,092 m) | `https://www.aemet.es/en/eltiempo/observacion/ultimosdatos?k=and&l=5511` HTTP 200 HTML, last 24 h plus 7 daily summaries, no snow field found | Short window only |
| MITECO ERHIN | The official pages (`.../erhin/medicion-seguimiento-manto-nival.html`, `datos-interes.html`) return 200 and state "281 pertigas ... 21 en Sierra Nevada" and 16 snow gauges, none in Sierra Nevada. I found no station data download. The pole locations are in a map viewer (`sig.mapama.gob.es/redes-seguimiento/`) that was not opened | Reports only |
| SAIH Guadalquivir (`chguadalquivir.es/saih`) | Pages 200; menus for reservoirs, flows, rain, temperature, historical data; no snow depth or SWE entry found; no historical query run; "Informes Nivales" link exists | Not confirmed |
| Meteostat bulk file for Granada airport 08419 | `https://data.meteostat.net/hourly/2024/08419.csv.gz` HTTP 200; `snwd` column empty on the lines printed | Yes, lowland |
| NOAA GHCN-Daily and ISD | Station lists HTTP 200. Only Granada airport (SPE00120089, 567 m) and Granada/Armilla (SPM00008420, 717 m) in the area; no mountain stations | Yes, lowland |
| OGIMET | HTTP 403 | No |
| Zenodo 3407391 (EURAC, Jacob), CC-BY-4.0 | API lists `SNOW MAPS.7z`, 43.8 MB, daily MODIS snow cover for Sierra Nevada from 2002 | Yes (not downloaded) |
| obsnev.es (Observatorio de Cambio Global) | Home page 200; no data portal link found | Not tested |

Verified Sierra Nevada published numbers (quotes, see 1.4): camera cover fraction accuracy 0.075; Pimentel et al. 2017 on 85 % cover and mixed pixels up to 40 %; Pimentel et al. 2015 on the 50 % depth error reduction by the curve choice. For a Sierra Nevada forcing evaluation: HighResClimNevada (ESSD 17, 2809, 2025, https://essd.copernicus.org/articles/17/2809/2025/) states "HighResClimNevada exhibits a higher amount of precipitation when compared to station-based, coarse satellite-based, and reanalysis-based products", "ERA5-Land tends to overestimate both BIO1 max, BIO1, and BIO1 min" and "underestimations of roughly 3 °C are shown compared to ERA5-Land" (quotes via sub-agent from the paper page; gives no precipitation bias in mm). That data set is a candidate downscaled climate reference for the priors of 3.3 but I did not check its access or licence. I found no verified number for ERA5 precipitation bias in Iberian mountains.

### 4.4 Not tested

AEMET HARMONIE-AROME archive; MSWEP; Spain02/SPREAD; MESCAN-SURFEX; CERRA download (CDS key needed, none requested); Earth Engine; Cetursa; obsnev data downloads; ERHIN map viewer; GFSC (HR-S&I) download; Open-Meteo bisected earliest dates for ICON, ARPEGE and UKMO (probes began 2023-06-15, docs give earlier "available since" dates); DeWalle density paper (not found).

---

## 5. Validation plan and thresholds

### 5.1 Reference data that exists (from section 4)

| Reference | Variable | Period | Use | Limits |
|---|---|---|---|---|
| Refugio Poqueira camera, PANGAEA 871706 (CC-BY-3.0) | Daily snow cover fraction and snow depth at 37.02825 N, -3.32337 E, 2,510 m, 30 x 30 m plot | 2009-11-15 to 2013-05-31 | Only open snow depth for the range. Tests depth physics and the density curve. Needs a forcing and fSCA source for 2009 to 2013 that is not Sentinel-2 (MODIS from Planetary Computer, tested, 500 m; or Landsat); that tests the method, not today's product | One point, one plot, ends before Sentinel-2 L2A starts (2016-11 on the tile tested). Point to 100 m cell representativeness error |
| Guadalfeo network PG1, PG2, PG4, PG5, PANGAEA 895236 (CC-BY-4.0) | Daily and hourly precipitation, temperature, humidity, wind, radiation (no snow depth) | PG2 2004-11-04 to 2018-08-31; PG1 2005-11-19 to 2018-08-31; PG4 2012-10-11 to 2018-08-31; PG5 2017-02-22 to 2018-08-31 | Check the forcing precipitation and temperature at high elevation, and the posterior precipitation multiplier, for the seasons 2016-17 and 2017-18 that overlap Sentinel-2 | Data end in August 2018; precipitation as snow is probably undercaught (gauge type not checked, judgement). PG3 is outside the range |
| Sentinel-2 snow masks (our own `snow_obs`) | Snow presence per 20 m pixel | 2016-11 onwards (backfill) | Held-out dates for F1, melt-out date, coverage of the fSCA likelihood | Same sensor as the assimilated data: independence is only by date block |
| IFAPA RIA stations (keyless API) | Daily precipitation, temperature at 921 to 1,201 m | Multi-year | Low-elevation forcing check | Not in the snow zone |
| Meteostat 08419 and GHCN stations near Granada | Temperature, precipitation at 567 to 717 m | Long | Low-elevation forcing check | Not in the snow zone; Meteostat `snwd` column looked empty on the lines checked |
| Zenodo 3407391 (EURAC), MODIS snow maps 2002 onwards (CC-BY-4.0) | Snow cover maps | 2002 onwards | Cross-check of snow cover climatology | Not in situ; 500 m |

**There is no open in-situ SWE for Sierra Nevada, and no open daily snow depth from a government network.** Anything stronger would need the data owners, listed in 5.5.

### 5.2 Leave-one-season-out scheme

- Seasons: water years 2016-17 to 2025-26 once the Sentinel-2 backfill exists (ten seasons; the first S2 L2A scene on the tile I tested is from 2016-11-10, so 2016-17 is a partial season). IFS on Open-Meteo starts in 2017, so 2016-17 needs ERA5 forcing; nine seasons are IFS-eligible.
- Level 1, hyperparameters (priors of 3.3, `n_corr`, the observation error floor, `S_new`): for each held-out season tune them on the other nine seasons by maximising held-out likelihood or minimising CRPS of `f_sca`; apply to the held-out season without refitting. Report the spread of the hyperparameters across folds: a design whose priors move a lot between folds is not constrained enough.
- Level 2, observations inside the held-out season: for the held-out season, hold out blocks of Sentinel-2 dates (blocks of at least 10 days, covering the range of seasons, at least 30 % of the clear dates), run the smoother on the rest, and score on the held-out dates. Block holding avoids the leakage in the current every-third-date split.
- Level 3, independent data: score against the Poqueira camera series (2009 to 2013, run with MODIS or Landsat fSCA because Sentinel-2 L2A does not exist for those years) and against Guadalfeo precipitation for the overlapping seasons. Never use these for tuning.
- Always report the prior (no assimilation) and the current v1 model as baselines on the same folds. A change that does not beat v1 on held-out blocks is not accepted.

### 5.3 Metrics

| Target | Metric | Definition notes |
|---|---|---|
| Snow presence | F1, Matthews correlation, Brier score of `p_snow` by 200 m elevation band and by aspect class | Reference: held-out clear S2 cells with at least 50 % decisive pixels; report band by band, because a good all-range score can hide the 1,500 to 2,000 m band, which is where the thin snow is |
| Melt-out date | Median and 90th percentile of the absolute difference between the model melt-out date and the S2 melt-out date, per 100 m elevation band | S2 melt-out is itself uncertain by half the gap between clear passes; report that interval beside the error |
| Snow depth (Poqueira camera) | RMSE, bias, correlation, KGE on daily depth | Plot of 30 x 30 m versus a 100 m cell: report also against the same camera with the cell values aggregated over 3 x 3 cells |
| Precipitation correction | Ratio of posterior `b0` times gradient-extrapolated precipitation to Guadalfeo gauge totals per season (PG1, PG2, PG4, PG5) | Interpret together with gauge undercatch in snowfall |
| Ensemble reliability | CRPS of `f_sca` and of snow depth at the camera, spread-skill ratio (ensemble spread over RMSE of the median), coverage of the 80 % interval (p10 to p90), rank histogram of held-out fSCA | |
| Snow-line altitude | Difference in the elevation where `p_snow` equals 0.5 versus the S2 snow line, per date | Used by Oberrauch et al. 2026 against Sentinel-2 (median bias within +-100 m) |

### 5.4 Acceptance thresholds (judgement)

No published threshold exists for this range; these are set against the literature numbers in section 1 and against the observation error. They should be revisited after the first full cross-validation.

| Metric | Minimum to publish SWE and depth as "validated" | Basis |
|---|---|---|
| F1 of snow presence on held-out S2 blocks, all clear cells | At least 0.90 overall and at least 0.80 in every 200 m band that holds at least 5 % of the snow cells | Current gate is 0.8 on a leaky split; HR-S&I Sentinel-2 accuracy is 94 % so the reference itself caps what can be demonstrated |
| Snow-line altitude bias | Median within +-100 m, 90th percentile within +-250 m | Oberrauch et al. 2026 median bias within +-100 m |
| Melt-out date error vs S2 | Median absolute error at most 7 days; 90th percentile at most 15 days | Order of the S2 revisit gap plus half a week |
| Depth at the Poqueira camera | Correlation at least 0.8, RMSE at most 0.30 m, absolute bias at most 0.10 m on days with snow | Maximum depth in that series is 1.19 m; ExoLabs average error 0.36 m (their own Davos data); OSHD RMSE 17.3 to 25.6 cm after assimilation at stations that were assimilated, so this threshold is looser on purpose |
| Ensemble | 80 % interval coverage between 70 % and 90 % on held-out fSCA; spread-skill ratio between 0.8 and 1.2 | Standard reliability targets |
| Peak SWE | No in-situ reference. Until one is obtained, label SWE "model estimate, not validated against measurements" and publish the posterior interval | Honest labelling rather than a threshold |
| Improvement over v1 | Lower CRPS and Brier on held-out blocks in at least 8 of 10 seasons | Guard against a change that only wins by chance |

### 5.5 What to ask for, and from whom (nobody has been contacted)

- **ERHIN (MITECO, Confederacion Hidrografica del Guadalquivir):** the official page states there are 21 snow poles (pertigas) in Sierra Nevada (page verified; no data links found). Ask for the station list, coordinates, elevation and the series of snow depth and any snow-density or SWE measurements at those poles, with licence. This is the single most valuable data request, since it would give a multi-year snow depth reference in a high-elevation range.
- **UGR (Collados-Lara, Pulido-Velazquez) and UCO group (Herrero, Polo, Pimentel; PANGAEA datasets 992415, 992412, 992414, 991999 with in-situ snow depth and temperature 2020 to 2025, listed as available only after a moratorium):** ask for access, or the date the moratorium ends, for the snow-pole depth and temperature series, and the Pleiades-derived depth maps of March 2024. Also ask whether any snow density pits exist.
- **Cetursa (Sierra Nevada ski resort):** ask for the snow depth records and the snowmaking and grooming-season records, with the coordinates of sensors. Artificial snow does not represent natural snow, so the data are for depth validation outside the pistes only.
- **AEMET:** ask for the climatological series of Pradollano (climate id 5511, 3,092 m) and any snow-depth observations there (API needs a key that has to be requested; I did not request one). It is the highest official station in the range.
- **Refugio Poqueira / OBSNEV (Observatorio de Cambio Global Sierra Nevada):** ask whether snow sensors or camera data after 2013 exist and whether they can be released.

---

## 6. Implementation task list

Effort in working days for one developer (my estimates). Tasks in the same lane depend on each other; lanes are independent except where `needs` says otherwise, so different agents can take different lanes in parallel. All new code goes under `pipelines/snow_model_v2/` or the existing package behind a flag; v1 keeps publishing until v2 passes section 5.

| ID | Task | Lane | Effort | Needs | Output and acceptance |
|---|---|---|---|---|---|
| T0 | Benchmark the existing `Member.step` and forcing load on a Linux runner: cell-days per second, memory, wall time for 48 members x 240,000 cells x 250 days; and for a class-reduced domain | A (engine) | 1 | none | A short table in the PR; decides class count and `N` |
| T1 | Sentinel-2 snow mask backfill from Earth Search STAC (`sentinel-2-l2a`, tested; COG assets `scl`, `green`, `swir16`, etc. readable by range requests) for water years 2016-17 to 2025-26 into catalogue layer `snow_obs`, with the existing confidence classes and shadow flags; resumable, rate limited | B (data) | 3 | none | Catalogue entries for all clear dates; a count of clear dates per season |
| T2 | Forcing adapter: IFS (current) and ERA5 (`era5`, not `era5_land`, which has no precipitation on Open-Meteo, see 4.2) as a per-member alternative source, check of the Open-Meteo elevation adjustment (4.2), caching, hourly to class aggregation, fixed storm segmentation (a storm is a precipitation spell separated by at least 12 dry hours) for `xi_e` | B (data) | 2 | none | Cached arrays per water year; unit test of storm segmentation |
| T3 | Sub-grid depletion curve module (`f_sca` from `S_peak`, `M_cum`, `beta`) and reset rule; check against Liston et al. 2004 before coding; property tests (monotone in melt, reset on snowfall) | A (engine) | 2 | none | Module plus tests; a note on how it differs from Liston 2004 if it does |
| T4 | Class-reduced domain builder: elevation x aspect x forcing cell classes, class membership maps, class-to-cell upsampling | A (engine) | 2 | T0 | Class map plus test that class means reproduce the cell-wise run within a tolerance |
| T5 | Vectorised ensemble forward model with new parameters, process noise, perturbed forcing; runs over `N` members x classes; seeded by water year | A (engine) | 4 | T3, T4, T2 (can start with current forcing) | Deterministic given seed; reproduces v1 when `b0 = 1, g` as v1, `xi = 0` |
| T6 | Observation operator and likelihood (3.6), pooled class fractions from `insertion.cell_state`, tempered weights, PBS; ES-MDA fallback behind a switch; synthetic twin experiments (truth member, generated S2 fractions with noise, recover `b0`) | C (assimilation) | 5 | T3, T5 interface (can use a stub) | Twin experiment recovers `b0` within 10 % and covers the truth with the 80 % interval at least 70 % of the time |
| T7 | Daily runner: season-to-date smoother, top `R` members on the 100 m grid, weighted quantiles, products and quality flags (3.8), publish through `catalog.publish()` to staging first; removes state files | D (product) | 4 | T5, T6, T1 for real data | Layers `swe_p50/p10/p90`, `snow_depth_*`, `p_snow`, `fsca_p50`, `obs_age_days`, `quality`; snapshot test on a stored season |
| T8 | Validation harness: loaders for PANGAEA 871706 (camera) and 895236 (Guadalfeo), melt-out date extraction, metrics of 5.3, block holdout, baselines (prior, v1) | E (validation) | 4 | none for loaders; T7 for full runs | Notebook-free script producing a markdown report per fold |
| T9 | MODIS or Landsat fSCA path with ERA5 forcing for 2009 to 2013 (Planetary Computer `modis-10A1-061`, keyless SAS token tested) so the camera series can test the method | E (validation) | 3 | T6 interface | Runs the smoother with MODIS fSCA at 500 m and compares depth with the camera |
| T10 | Leave-one-season-out hyperparameter tuning run on the Actions runner (matrix over folds), producing the tuned priors file | C (assimilation) | 3 | T6, T1, T8 | Priors file in `regions/`, fold spread table |
| T11 | GitHub Actions workflows: nightly daily runner, weekly backfill, tuning matrix, with timeouts below 6 h and artefact upload | F (ops) | 2 | T7 | Workflows green on staging |
| T12 | Sentinel-1 wet snow flag (optional, D): RTC from Planetary Computer (token API tested; scenes about 1.8 GB so use windowed COG reads), -2 dB change threshold per Lievens 2022, orbit handling, forest mask; published as a separate layer, not fed into SWE | G (optional) | 8 | none | Layer plus comparison with S2 on days with partial cloud |
| T13 | Map UI and catalogue text: show quantiles, `quality`, `obs_age_days`, the "not validated against measurements" label for SWE; methodology page generated from this document | H (product/UI) | 3 | T7 data shape (agree it first) | UI shows age and uncertainty |
| T14 | Data requests list (section 5.5) turned into a decision for the owner; no contact by agents | I (owner) | 0.5 | none | A decision record |

Suggested parallel plan: lane A, B and E start immediately (T0, T1, T2, T3, T8 loaders); lane C starts when T3 and the T5 interface exist; lane D when T5 and T6 exist; F and H last. Minimum viable v2 is T0 to T8 and T11, about 28 working days on one developer or about 12 elapsed days with three agents.

---

## 7. Open questions for the owner

1. Is a retroactively revised product acceptable (3.7 step 8 changes past dates)? If not, publish the daily value as a nowcast with its own version tag and reprocess only finished years.
2. Is a "not validated against measurements" label on SWE acceptable until ERHIN or university data is obtained? The alternative is to publish nothing for SWE.
3. Which licence for the posterior ensemble products, given CC-BY-4.0 inputs (PC S1, PANGAEA) and the Open-Meteo terms (section 4.2, free tier is non-commercial; does Darwin running NivoSense count)?

