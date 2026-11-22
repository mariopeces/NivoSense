# WeatherNext 3 in NivoSense

Status: the pipeline module and the interface are built and were checked against real data, but the GitHub service accounts are not on the WeatherNext allowlist yet. Until they are, the workflow publishes AEMET only and the site does not list WeatherNext.

## What it is and why it is an exception

- Google DeepMind's AI weather model. Surface grid 0.1 degrees (about 11 km, shown as ~10 km), station grid 0.05 degrees, 64 ensemble members, 15-day horizon for the 00, 06, 12 and 18 UTC runs. Source: https://developers.google.com/weathernext/guides/models.
- NivoSense keeps only models with a native grid finer than 5 km (AEMET HARMONIE-AROME, 2.5 km). The owner granted WeatherNext 3 as an explicit exception; the list is `COARSE_MODELS_ALLOWED` in `pipelines/weather_forecasts/config.py` and a test fails for any other model coarser than 5 km.
- WeatherNext Gen and WeatherNext 2 are 0.25 degrees and are not used.

## What the pipeline reads

`pipelines/weather_forecasts/weathernext.py` opens the precomputed statistics Zarr v3 store, which is not requester-pays:

`gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/2026_to_present/<YYYYMMDD>_<HH>hr_01_preds/predictions.zarr`

It takes the ensemble mean (`_mean`) of `temperature_2m` (K to degrees C), `wind_speed_10m` (m/s to km/h) and `total_precipitation_1hr` (m to mm, summed from the run time to each horizon), cropped to the region bbox, for 24, 48, 72 and 120 h. Only the 00, 06, 12 and 18 UTC runs are used because the hourly interim runs stop at 48 h. The latest run whose last chunk exists is chosen (the 12 UTC run lands about 19:45 UTC).

## Access state

Checked on 2026-11-22 with read-only listings of the bucket:

| Identity | Result |
| --- | --- |
| Mario's personal Google account | Allowed. The store was listed and a tiny read worked. |
| Mario's Darwin Geospatial account | 403, not allowlisted. |
| `GCP_SA_STAGING` and `GCP_SA_PROD` service accounts | Not testable from this machine (no impersonation rights); no sign they are allowlisted. |

## What Mario must do

1. Open the WeatherNext Data Request Form linked from https://developers.google.com/weathernext/guides/earth-engine and submit it with the identity that CI uses: `nivosense-gha-prod@nivosense.iam.gserviceaccount.com` (the value of the `GCP_SA_PROD` variable). Add `nivosense-gha-staging@nivosense.iam.gserviceaccount.com` if staging should run it too.
2. Suggested answers:
   - Project: NivoSense, a free, non-profit snow monitoring website for the Sierra Nevada (Spain), by Darwin Geospatial.
   - Use: map layers showing the ensemble-mean forecast of temperature, wind and precipitation over the Sierra Nevada bounding box (about 1.1 by 0.4 degrees), refreshed four times a day, with attribution and the "experimental, not an official warning" notice shown beside the layer.
   - Data volume: a few hundred kilobytes per run (the statistics store is read lazily and only the region is fetched).
   - Email to allow: the service account above.
3. Approval takes 5 to 7 business days according to the guide. Nothing else changes in the repository: the workflow already authenticates with Workload Identity Federation (`GCP_WIF_PROVIDER`, `GCP_SA_PROD`), no key is stored, and the next scheduled run adds the model to the manifest and the site lists it.
4. Cost: the statistics bucket is not requester-pays; reading one region is a handful of chunks. No paid API is enabled by this work.

## Licence and attribution

- Forecasts for the future and the last hour: "GDM Real-Time Weather Forecasting Experimental Data Terms of Use" (https://storage.googleapis.com/weathernext-public/terms-of-use.pdf). Data one hour old or more: CC BY 4.0.
- Provided as is for information and research; not an official forecast, watch or warning. The layer legend says "Predicción experimental, no es un aviso oficial" and credits Google DeepMind.
- Terms to respect: do not use the outputs to build a competing product or to replace the models. A free map layer of the mean forecast does neither, but Mario should confirm that reading when he submits the form. Support: weathernext@google.com.
- Disclaimers: https://developers.google.com/weathernext/guides/disclaimers.md.txt.

## Local test

With an allowlisted Google account in Application Default Credentials, `python -m pipelines.weather_forecasts.run --output weather-output` adds `weathernext` to the manifest. The unit test builds a small synthetic dataset in the store's real layout (dimensions `lead_time`, `lat_0p1`, `lon_0p1`, longitudes 0 to 360); that fixture is never shown on the site.
