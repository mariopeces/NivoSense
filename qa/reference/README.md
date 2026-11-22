# Frozen snow reference sample

`snow_points.geojson` holds the points the observed snow cover is scored against (README section 2, Q1). It is frozen: the tests hold its SHA-256 as a literal (`FROZEN_SHA256` in `tests/qa_reference/test_reference.py`), so any change to the file fails CI until the test changes in the same reviewed commit. Do not edit the file. A new sample is a new file, drawn and labelled the same way.

## Labels

Every point is one 20 m pixel of the Sentinel-2 grid (EPSG:32630), labelled by eye on Sentinel-2 L1C chips: true colour (B04/B03/B02) and SWIR false colour (B11/B8/B4). The labeller never saw any snow classifier code or output. Classes and rules are in the file's `metadata.protocol`.

- `snow`, `no_snow`, `cloud`: scored. These points have `scored: true`.
- `unsure`: mixed pixels at a snow edge, shadow too dark to read, thin haze, or any doubt. These points stay in the file with `scored: false` and are left out of every score. They show where the reference cannot decide, so Q1 reports the unsure share next to each F1.

## Design

- 15 dates of 2025-26 on relative orbit R094, listed with their phase and snowline in `dates.json`.
- Five strata: snowline band, terrain shadow, forest, cloud edge, open terrain. Each is split into elevation bands. The definitions are in `metadata.design`, the code in `strata.py`. The strata overlap, except open terrain. `in_strata` lists every stratum a point lies in; `stratum` is the one it was drawn from.
- Four seeded draws (`draw` on each point, parameters in `metadata.supplements` and `sample.py`):
  1. **Draw 1** is the main stratified sample: 360 points per stratum, split evenly over the dates and then over the elevation bands. It is not proportional to area.
  2. **Draw 2** uses the same strata and bands on the 13 dates with a snowline, restricted to ground at or above that date's snowline. Most of its points are in forest and cloud edge.
  3. **Draw 3** samples forest and cloud edge only, at least 500 m above the date's snowline, where about half the points of draws 1 and 2 were snow.
  4. **Draw 4** samples cloud edge only, at least 200 m above the snowline, because draw 3 ran out of cloud-edge ground at the minimum spacing.

  Draws 3 and 4 bring forest and cloud edge to at least 100 scored snow points each (a test checks it). Draws 2 to 4 use only the DEM and the snowline read on the overviews; no image index or classifier output decides where they go. They oversample snow-prone ground on purpose, so unweighted pooled numbers are biased towards snow.
- `metadata.cells` lists, for every (draw, date, stratum, elevation band) cell, its pixels and the points drawn in it.

## Q1 scoring rule

Use `score.py`: `python -m qa.reference.score --predictions predictions.csv`, where the CSV has columns `id,class` and the classes are `snow`, `no_snow`, `cloud` or `unknown`.

1. **Population.** All pixels of the domain on the sample dates. Each stratum's population is the pixels that lie in it.
2. **Weights.** A pixel could be picked by any draw, from any stratum it lies in. Its inclusion probability is the sum of points / pixels over those draw cells. That is every stratum in `in_strata`, in draw 1 always, and in a later draw only when the pixel's elevation is at least the draw's height above the date's snowline (a multi-frame Horvitz-Thompson design). Each point stores it as `inclusion_probability`, and `weight` is its inverse.
3. **Points scored.** Only `scored: true` points count. A stratum's score uses every scored point whose `in_strata` contains it, not only the points drawn from it. The ski resort polygon, once it exists, is excluded before scoring.
4. **Confusion matrix and F1.** Rows are the reference classes (snow, no snow, cloud) and columns the predicted classes (snow, no snow, cloud, unknown). Each point adds its weight. Snow F1 = 2 TP / (2 TP + FP + FN): FP is any non-snow reference predicted as snow, and FN is snow predicted as anything else, `unknown` included.
5. **Threshold.** The Q1 thresholds (snow F1 >= 0.85 overall and >= 0.70 in every stratum) are judged on the **weighted** scores. The report also gives unweighted pooled scores and unweighted per-draw scores for transparency; those must not be used for the threshold.
6. **What to publish.** Per stratum: the weighted and unweighted confusion matrices, precision, recall and F1, the number of scored points and the unsure share.

`python -m qa.reference.score --prevalence` prints the snow share per stratum: unweighted per draw and pooled, draw 1 alone with its own weights, and all draws weighted. On the frozen sample the weighted pooled share comes back to the draw-1 estimate (table in the PR evidence), which is what the weights are for.

## Rebuild and review

```
python -m qa.reference.sample --cache C --out points.geojson
python -m qa.reference.sample --cache C --out points2.geojson --supplement points.geojson --draw 2
python -m qa.reference.sample --cache C --out points3.geojson --supplement points2.geojson --draw 3
python -m qa.reference.sample --cache C --out points4.geojson --supplement points3.geojson --draw 4
python -m qa.reference.chips pages --points points4.geojson --cache C --out pages
python -m qa.reference.freeze --points points4.geojson --labels labels.csv
python -m qa.reference.chips blind --points qa/reference/snow_points.geojson --cache C --out blind --seed N
python -m qa.reference.chips agreement --points qa/reference/snow_points.geojson --labels relabel.csv
```
