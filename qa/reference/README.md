# Frozen snow reference sample

`snow_points.geojson` holds the points the observed snow cover is scored against (README section 2, Q1). It is frozen: its SHA-256 is in `snow_points.geojson.sha256`, and the tests fail if the file changes. Do not edit it. A new sample is a new file, drawn and labelled the same way.

## Labels

Every point is one 20 m pixel of the Sentinel-2 grid (EPSG:32630), labelled by eye on Sentinel-2 L1C chips: true colour (B04/B03/B02) and SWIR false colour (B11/B8/B4). The labeller never saw any snow classifier code or output. Classes and rules are in the file's `metadata.protocol`.

- `snow`, `no_snow`, `cloud`: scored. These points have `scored: true`.
- `unsure`: mixed pixels at a snow edge, shadow too dark to read, thin haze, or any doubt. These points stay in the file with `scored: false` and are left out of every score. They show where the reference cannot decide.

## Design

- 15 dates of 2025-26 on relative orbit R094, listed with their phase and snowline in `dates.json`.
- Five strata: snowline band, terrain shadow, forest, cloud edge, open terrain, each split into elevation bands. The definitions are in `metadata.design`, and the code is in `strata.py`.
- Two seeded draws (`draw` on each point):
  1. `draw: 1` is the main stratified sample, 360 points per stratum spread over all dates.
  2. `draw: 2` is a supplement on the dates that have a snowline. It uses the same strata, restricted to ground at or above that date's snowline (read from the DEM, not from the images), and puts most of its points in forest and cloud edge, where the first draw found little snow. It oversamples snow-prone ground, so weight each draw by its own cells (`cell_pixels`) when estimating area-wide rates.
- `in_strata` lists every stratum a point falls in, not only the one it was drawn from.

## Rebuild and review

```
python -m qa.reference.sample --cache C --out points.geojson
python -m qa.reference.sample --cache C --out points2.geojson --supplement points.geojson
python -m qa.reference.chips pages --points points2.geojson --cache C --out pages
python -m qa.reference.freeze --points points2.geojson --labels labels.csv
python -m qa.reference.chips blind --points qa/reference/snow_points.geojson --cache C --out blind --seed N
python -m qa.reference.chips agreement --points qa/reference/snow_points.geojson --labels relabel.csv
```
