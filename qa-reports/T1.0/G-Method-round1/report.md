# T1.0 Frozen reference sample: G-Method round 1

- PR #28, branch `plan/t10-reference`, head **a53a3e4** (unchanged since dispatch), stacked on `plan/t11-s2-ingest` dafc7f3. Evidence branch `evidence/t10-reference` 40ed9c1.
- Frozen file `qa/reference/snow_points.geojson`: SHA-256 recomputed as `67ee82fed3c31af9aca5b1b34b5a412d352953ed4000e5c59c5888edc8807faf`. It matches the PR text and the sidecar.
- Independence: I did not open classifier code or output (`pipelines/snow_obs`, `plan/t12-*`, `plan-snowobs`). I did not use the builder's `chips.py blind` helper or its pages. I built my own chips from the recorded scene ids, and I read no stored label until my relabel was hashed.

**Verdict: fail.** One major finding: the README does not say how Q1 weights the two draws. The Accept line itself passes with a wide margin (99.3%), and so does every other item I was asked to judge.

## 1. Blind relabel (Accept line)

Procedure, in this order:

1. **Draw.** `tools/draw_blind.py`, seed **7340211**. Allocation is proportional over every (draw, date, stratum) cell: floor(10%) in each cell, then the remaining points by weighted lottery on the fractional parts. That gives 207 of 2,065 points (ceil of 10%): 179 from draw 1 and 28 from draw 2, on all 15 dates and all 5 strata. The script strips `label` and `scored` before writing `blind_points.geojson`, so I never saw them.
2. **Chips.** `tools/make_chips.py` takes each point's `chip_scene_id`, fetches the Earth Search `sentinel-2-l1c` item, and reads B02/B03/B04/B08/B11 windows straight from the JP2s (unsigned S3). Reflectance uses the item's `raster:bands` scale and offset (0.0001, -0.1). Each point gets three panels:
   - true colour B04/B03/B02, 720 m wide, x4;
   - SWIR false colour B11/B8/B4, same window;
   - true colour context, 2.4 km.

   The stretch is reflectance 0 to 1 with gamma 0.5, the same on every date. Pages show a shuffled key (`B001` to `B207`) and the date only, with no stratum and no draw (`chips/blind_*.png`, key in `chips/key.json`).
3. **Labelling.** Visual judgement only; I computed no index. The class rules are the protocol's.
4. **Bug in my own chips, and the fix.** rasterio rounds a fractional window offset. B11 is a 20 m band, so the point's offset is half a pixel, and my first-pass SWIR panels came out shifted 10 m (one 10 m pixel up and left) against true colour.
   - Cross-correlation of B11 with B04 and B08 confirmed it: after the fix the peak sits at a shift of (0, 0). Before the fix it sat at (-1, -1).
   - `tools/fix_swir.py` re-reads B11 on whole 20 m pixels and crops to the 10 m-aligned window.
   - I then relabelled, at x10 zoom with the corrected SWIR (`chips/zoom_*.png`), every point I had marked as doubtful (51) plus every point whose 80 m neighbourhood was heterogeneous in red or B11 (37): 88 points in all.
   - `gmethod_relabel_audit.csv` keeps the first-pass and final label for each point.
5. **Lock.** `gmethod_relabel.csv` was hashed (`c52db6a457006a36eacf433bc49bc4bce70e36a82b5bfe1fbeac611dfbbdc671`) before the comparison. `tools/agree.py` then joined it with the frozen labels.

Result (full tables in `agreement_tables.md`):

| scope | relabelled | unsure (either side) | compared | agree | agreement | 95% CI (Wilson) |
|---|---|---|---|---|---|---|
| **overall** | 207 | 64 | 143 | 142 | **0.993** | 0.961 to 0.999 |
| snowline band | 40 | 11 | 29 | 28 | 0.966 | 0.828 to 0.994 |
| terrain shadow | 40 | 10 | 30 | 30 | 1.000 | 0.886 to 1.0 |
| forest | 47 | 13 | 34 | 34 | 1.000 | 0.898 to 1.0 |
| cloud edge | 40 | 22 | 18 | 18 | 1.000 | 0.824 to 1.0 |
| open terrain | 40 | 8 | 32 | 32 | 1.000 | 0.893 to 1.0 |
| draw 1 | 179 | 50 | 129 | 129 | 1.000 | 0.971 to 1.0 |
| draw 2 | 28 | 14 | 14 | 13 | 0.929 | 0.685 to 0.987 |

- Per date, all 15 dates agree at 1.000 except 2026-03-25 (10 of 11).
- Cohen's kappa on the compared points is 0.977. For the snow class: 23 points both say snow, out of 24 where either side says snow.
- Cross table (rows are frozen labels, columns are mine):

| frozen / G-Method | snow | no_snow | cloud | unsure | total |
|---|---|---|---|---|---|
| snow | 23 | 1 | 0 | 6 | 30 |
| no_snow | 0 | 117 | 0 | 9 | 126 |
| cloud | 0 | 0 | 2 | 3 | 5 |
| unsure | 6 | 10 | 0 | 30 | 46 |

- The one disagreement is `2026-03-25-115` (draw 2, snowline band, 2,399 m). The frozen label is snow; my label is no_snow. It is a snow-edge pixel: at x10 the marked pixel lies on bare ground right next to a snow tongue. It is a pixel-boundary call, not a class confusion.
- **Accept line: met.** Agreement is 0.993 against the 0.90 bar, and the lower CI bound (0.961) is also above it.
- Context the bar does not count:
  - 64 of 207 pairs (31%) drop out because one side said unsure.
  - If every definite-versus-unsure pair counted as a disagreement, agreement would be 142 of 177 (0.80).
  - Of the 30 frozen snow points in my subset, I could not confirm 6 (I called them unsure).

## 2. Dates (card: early season, storm, mid-winter, melt, late spring, 2026-11-20)

From `dates.md` (frozen labels, used only after my relabel was locked):

- **Early season:** 2025-11-03 has 0 snow among 100 points, so it is before the first snowfall. 2025-11-28 has snow above about 2,350 m.
- **Storm:** 2025-12-18, 2026-01-07 and 2026-02-16. These hold the lowest snow points of the sample (1,690 to 1,810 m) and the most unsure points, from fresh snow and cloud remnants.
- **Mid-winter:** 2026-01-12 (sun at 29 degrees), 2026-02-21 and 2026-03-13.
- **Melt:** 2026-03-25, 2026-04-14 and 2026-04-27. The snowline is recorded as 2,250 to 2,500 m.
- **Late spring:** 2026-05-12, 2026-05-27 and 2026-06-13. Snow drops to 4 points on 06-13.
- **2026-11-20:** 99 points, 0 snow. The 7 points inside the Q4 crest box (lon -3.42 to -3.30, lat 37.01 to 37.07, up to 2,995 m) are all no_snow.

My own chips agree with these phases: no snow on 2025-11-03 and 2026-11-20, fresh low snow and forest snow speckle on 2026-01-07, and patchy summit snow in June. **Pass.**

## 3. Stratification is real

`tools/strata_check.py` recomputes the stratum inputs for my 207 points without the builder's code:

- its own GLO-30 mosaic, reprojected bilinear to 20 m UTM 30N;
- local incidence from central differences, with sun angles taken from the L2A items of the date;
- cast shadow traced 8 km towards the sun;
- WorldCover 2021 v200 class 10, sampled in the four 10 m cells of each pixel;
- L2A SCL classes 8, 9 and 10 within 100 m of the pixel.

| check | result |
|---|---|
| elevation vs `elevation_m` | median diff 0.0 m, p95 abs 0.8 m, max abs 2.3 m |
| local incidence cosine vs `cos_incidence` | p95 abs diff 0.005, max 0.029 |
| cast shadow vs `cast_shadow` | 206 of 207 agree |
| tree fraction vs `tree_fraction` | 206 of 207 exact, max diff 0.25 |
| drawn stratum supported by my layers | snowline 40/40, shadow 40/40, forest 47/47, cloud edge 40/40, open 40/40 |
| `in_strata` flags | 11 differences in 1,035 flags. 8 are pixels under SCL cloud: the builder's `in_strata` lists other strata only on SCL clear sky, as documented. 3 are cloud-edge flags where my single-tile SCL window differs from the builder's mosaicked SCL at tile overlaps. |

**Pass.**

## 4. Chip scene ids against Earth Search

`tools/stac_check.py` sends my own POST `/search` for `sentinel-2-l1c` over the T2.1 domain polygon on each date (`stac_check.md`).

- On all 15 dates, the R094 item set equals the recorded `l1c_scene_ids`.
- Every point's `chip_scene_id` is among them.
- The other items on those dates are on R051.
- 16 points (all on tile 30SVF) fall 9 to 149 m outside their item's STAC footprint polygon. Their raw B04 and B11 at the point are non-zero in the recorded scene (`tools/fp_check.py`), so the footprint polygon is simplified and the id is right.

**Pass.**

## 5. Inside the T2.1 domain

All 2,065 points lie inside the `part: domain` polygon of `data/domain.geojson` on `plan/t21-domain`, in both 17b37fb and bad749e, which have the same area. T2.1 is not merged yet, so a later change of its polygon would need this check again (follow-up). **Pass.**

## 6. Can 43 to 44 snow points support a per-stratum F1 >= 0.70 test?

Scored counts from the frozen file:
- forest: 370 scored, 43 snow (20 in draw 1, 23 in draw 2);
- cloud edge: 237 scored, 44 snow (24 / 20).

Counting every stratum a point falls in (`in_strata`) gives 56 and 52 snow points.

`tools/power.py` simulates the sampling distribution of measured F1, with precision equal to recall equal to the true F1, and binomial noise on the stratum's real positive and negative counts:

| stratum | true F1 | 95% range of measured F1 | P(measured < 0.70) |
|---|---|---|---|
| forest (43 / 327) | 0.70 | 0.59 to 0.80 | 0.49 |
| forest | 0.75 | 0.65 to 0.84 | 0.16 |
| forest | 0.80 | 0.71 to 0.88 | 0.02 |
| cloud edge (44 / 193) | 0.75 | 0.65 to 0.84 | 0.16 |
| cloud edge | 0.80 | 0.71 to 0.88 | 0.02 |

- **Expect about ±0.09 to 0.10 (95%) on forest and cloud-edge F1.**
- The test catches a gross failure (true F1 around 0.6 or lower). It cannot tell 0.70 from 0.80, and a classifier at a true 0.75 fails it one time in six.
- The cloud-edge stratum also has the highest unsure share (43%), so its F1 rests on the easier 57% of points.
- Half-width falls to 0.057 at 100 snow points and 0.047 at 150.
- **Recommendation:** reach at least 100 snow points in each of forest and cloud edge. At draw 2's snow yields (32% and 42%), that is about 180 more scored forest points and 140 more cloud-edge points. If Mario wants this, it must be done **before T1.2 sees the sample**; otherwise, Q1 should publish F1 with its CI per stratum.
- Not a blocker: the card's numeric design (at least 1,500 points, at least 12 dates, 5 strata) is met.

## 7. Does draw 2 need weights in Q1, and does the README say so?

**Yes, it needs them, and the README does not say so for Q1.**

- Draw 2 samples only ground at or above each date's snowline, and puts most of its quota in forest and cloud edge. There it supplies 53% and 45% of the snow points.
- Pooled unweighted, forest snow prevalence is 11.6%; draw 1 alone gives 6.7%. Precision, and so F1, moves with prevalence. Example: recall 0.80 and a 2% false-positive rate in forest give F1 0.77 at draw-1 prevalence but 0.82 pooled, a +0.05 inflation that is as large as the margin being tested.
- The README and the frozen metadata say: "weight each draw by its own cells (`cell_pixels`) when estimating area-wide rates". Read literally, that only covers estimating per draw. It does not:
  - say whether Q1's per-stratum F1 and confusion matrices are weighted;
  - say how to combine the draws. Draw-2 cells are nested inside draw-1 cells, so a point above the snowline could have come from either draw. Its inclusion probability is n1/N1 + n2/N2, and pooling the two per-draw weights double-counts that ground;
  - mention that draw 1 is not proportional either (equal quotas per date and per elevation band), so a population F1 needs cell weights even for draw 1 alone.

Everything needed is in the file: `cell_pixels`, the draw-2 cell sizes on draw-2 points, and the per-cell counts. Only the rule is missing. This is the **major** finding below.

## 8. Is the frozen hash enforced by a test?

- `tests/qa_reference/test_reference.py::FrozenSampleTest.test_sample_matches_its_frozen_hash` compares the file with its `.sha256` sidecar.
- Run on a copy of the PR tree:
  - pristine: OK;
  - one `"snow"` label edited, sidecar left alone: **FAIL**, so the guard works;
  - label edited and sidecar regenerated (which `freeze.py` does on every run): **OK**.
- So the test catches an accidental edit, but a re-freeze passes CI silently. Pinning the hash as a constant in the test, or in the card or STATUS, would make a re-freeze show up as a test diff. Minor.
- CI on PR #28: python pass, frontend pass.

## 9. Other observations (follow-ups, not blocking)

- **Two LLM labellers.** The frozen labels and this relabel both come from an LLM labeller (Claude). 99% agreement shows consistency, not accuracy against a human reference. A short human spot check on the snow / unsure boundary would make the sample stronger.
- **Unsure share.** 23% of points overall are unsure: 43% in cloud edge, 25% in snowline band. Q1 should publish the unsure share next to each stratum's F1, because excluding unsure removes the hardest pixels.
- **Ski resort.** No point is flagged as inside the ski resort. That polygon is a later task (tasks.md line 265), and Q1 must exclude it when it exists.

## Finding JSON

```json
{
  "gauntlet": "G-Method",
  "task": "T1.0",
  "round": 1,
  "verdict": "fail",
  "findings": [
    {
      "severity": "major",
      "where": "qa/reference/README.md (Design, draw 2 paragraph); same text in snow_points.geojson metadata.design.supplement",
      "what": "No rule for weighting the two draws in Q1. Draw 2 oversamples snow-prone ground (53% of forest and 45% of cloud-edge snow points), and draw 1 itself is not proportional (equal quotas per date and elevation band). 'Weight each draw by its own cells when estimating area-wide rates' does not say whether Q1 per-stratum F1 and confusion matrices are weighted, and pooling per-draw cell weights double-counts above-snowline ground because draw-2 cells are nested in draw-1 cells.",
      "observed": "Forest snow prevalence 6.7% in draw 1 vs 11.6% pooled. With recall 0.80 and 2% FPR, forest F1 is 0.77 at draw-1 prevalence vs 0.82 pooled unweighted (+0.05, the size of the Q1 margin). Counts in qa-reports/T1.0/G-Method-round1/power.md.",
      "to_pass": "README states the Q1 scoring rule: per-stratum confusion matrices and F1 reported (a) per draw, unweighted, and (b) for the threshold, design-weighted with w = 1/pi, where pi = n1/N1 for the point's (date, stratum, elevation band) cell in draw 1, plus n2/N2 of its draw-2 cell when it lies at or above the snowline (N from cell_pixels). Or it states that the threshold is scored on draw 1 with its cell weights and draw 2 only as a supplementary recall check. It also says unweighted pooled numbers must not be used for the threshold."
    },
    {
      "severity": "minor",
      "where": "qa/reference/snow_points.geojson: forest and cloud_edge strata",
      "what": "43 and 44 snow points give a 95% range of about +-0.10 on per-stratum F1: the Q1 F1 >= 0.70 test cannot tell 0.70 from 0.80, and a true 0.75 fails 16% of the time. Cloud edge is also 43% unsure.",
      "observed": "Binomial simulation on the real positive and negative counts (power.md): true F1 0.75 gives a measured range of 0.65 to 0.84; half-width is 0.057 at 100 snow points.",
      "to_pass": "Follow-up for the coordinator or Mario, before T1.2 sees the sample: a third draw for at least 100 snow points in forest and cloud edge (about 180 and 140 more scored points), or Q1 publishes per-stratum F1 with its CI."
    },
    {
      "severity": "minor",
      "where": "tests/qa_reference/test_reference.py: FrozenSampleTest.test_sample_matches_its_frozen_hash",
      "what": "The hash is checked against the sidecar file that freeze.py regenerates, so a re-freeze (file plus sidecar) passes CI silently.",
      "observed": "On a copy of the PR tree: one label edited gives FAIL; label edited and sidecar regenerated gives OK.",
      "to_pass": "Pin 67ee82fe... as a constant in the test (or in the card or STATUS) so a re-freeze needs a visible test change."
    }
  ],
  "followups": [
    "Re-run the inside-domain check when T2.1 merges (all 2,065 points are inside plan/t21-domain bad749e today).",
    "Both label sets come from an LLM labeller; a short human spot check on the snow / unsure boundary.",
    "Q1 publishes the unsure share per stratum next to F1.",
    "Flag or exclude points inside the ski resort once its polygon exists (tasks.md line 265).",
    "3 of 207 cloud-edge in_strata flags differ from a single-tile SCL recomputation at tile overlaps; harmless for the drawn strata."
  ]
}
```
