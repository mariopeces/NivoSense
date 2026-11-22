# T1.0 Frozen reference sample: G-Code round 1

- PR #28, branch `plan/t10-reference`. Dispatched on head a53a3e4. **The head moved to fa4586f during the review** (draws 3 and 4, `score.py`, pinned hash), so the verdict is on **fa4586f**. Stacked on `plan/t11-s2-ingest` dafc7f3. I judged only T1.0's diff (`qa/reference/`, `tests/qa_reference/`).
- Frozen file: SHA-256 recomputed as `a6f2586b23df03de6b1effffaec9c55ea49a4e15d859f6323c7c2407c0d9372e`, 2,439 points (draws 1/2/3/4: 1,750 / 315 / 310 / 64), 1,766 scored. This matches `FROZEN_SHA256` in the test and the PR text. The dispatch hash 67ee82fe… is superseded.
- Independence: I did not open classifier code or output, and I did not judge labels.

**Verdict: fail.** One major finding: the chip and blind-relabel helpers have untested behaviour, and deliberate breaks of it still pass CI. Every other check passes, including an exact, independent rerun of all four seeded draws.

## What I checked and how

| Check | Result | How |
|---|---|---|
| Draws reproducible | **pass** | I reran `sample.py` from scratch in my own cache, with fresh Earth Search L2A/L1C, GLO-30 and WorldCover reads on the 17b37fb domain. I ran draw 1 (seed 20261122) on the a53a3e4 code, then draws 2/3/4 (seeds 20261123/24/25) on the fa4586f code. Compared with the frozen file: 2,439/2,439 ids, **0 field mismatches** on id, draw, date, x, y, geometry, stratum, elevation band, cell_pixels, elevation, cos_incidence, cast_shadow, tree_fraction, in_strata and chip_scene_id. `seed`, `stratum_pixels`, `dates` (all scene ids), `supplements` and `cells` are all identical (`rerun_compare_fa4586f.txt`). On a53a3e4 the two-draw file also reproduced exactly (`rerun_compare_a53a3e4.txt`). |
| Hash test catches edits | **pass** | On fa4586f the hash is a literal in the test. Changing one whitespace byte of the sample fails the test (N1). On a53a3e4 the test read a sidecar that `freeze.py` rewrote: I relabelled 100 unsure points to no_snow, regenerated the sidecar and the tests stayed green. fa4586f removed the sidecar, which fixes this. |
| Chip building | **pass (code), see major for tests** | `mosaic_cell`, `window` and `marked` are correct: the 2x2 centre block has 16 pixels on each side (zoom) and 50 on each side (context), with marks 2 px outside it. B11 is 20 m data upsampled 2x by `read_aligned` on a grid snapped to 20 m edges, so it is not offset. |
| Blind and agreement helpers | **pass (code), see major for tests** | `agreement` drops unsure on either side, never divides by zero, and refuses unknown ids. `read_labels` refuses unknown labels. `blind_subset` is a seeded random 10%. |
| `score.py` (new) | pass | The weights match the draw design. A later draw counts only when elevation ≥ snowline + `above_snowline_m`, and the sum runs over every stratum in `in_strata`. The test recomputes the stored weights for all 2,439 points. Deliberate breaks of the restriction, of in_strata membership, of unknown→miss in F1, of unsure exclusion and of the unsure share all fail tests (N24 to N29). |
| Scene ids real | pass | 20 random L2A/L1C ids fetched by id from Earth Search: 20/20 found, dates match. The full rerun's live STAC search returned exactly the frozen `metadata.dates` ids on all 15 dates. Every `chip_scene_id` is in its date's L1C list. |
| Points inside the T2.1 domain | pass | 0 of 2,439 outside the `domain` part of either `plan/t21-domain` 17b37fb or bad749e. Minimum spacing on a date is 200.0 m. All x/y sit on 20 m pixel centres, and lon/lat match x/y within 6 mm. |
| Tests, ruff, mypy (T0.6 config, main 65b9327+) | pass | fa4586f merged onto main 5a5530b, with pinned numpy 2.4.6, mypy 1.20.2, ruff 0.17.6 and pytest 9.2.0. `ruff check .` and `ruff format --check` are clean. `mypy` (config): no issues in 31 files. `mypy qa/reference`: clean. `pytest tests/qa_reference tests/s2`: 53 passed. PR CI on fa4586f: python and frontend pass. |
| Secrets, personal data | pass | No tokens, keys, e-mails or local paths in the diff. The labeller is recorded as "LLM labelling agent (Claude)". |
| Dependencies | pass | No new dependency. numpy, rasterio and Pillow are already pinned in main's `pipelines/requirements.lock`. |

## Deliberate breaks (fa4586f, `mutations_fa4586f.txt`)

Caught: N1 sample byte, N24 score restriction, N25 drawn-stratum-only, N26 unknown not a miss, N28 unsure scored, N29 unsure share.

**Not caught (tests stay green):**
- N6 `blind_subset` returns the first 10% instead of a random 10%.
- N9 SWIR panel band order swapped (B4/B8/B11 instead of B11/B8/B4).
- N10 `read_labels` accepts any label.
- N11 `labelling_order` stops shuffling.
- N12/N12b `freeze` scores unsure points or sets weight 1.
- N16/N17/N18 `supplement` ignores `above_snowline_m`, uses the draw-1 seed, or ignores spacing to earlier draws.
- N20 `chip_scene_id` always takes the first tile.
- N23 `cell_table` ignores the elevation band.
- N30 `read_predictions` maps blank to unknown.

The sample-building breaks (N12, N16 to N23) cannot change the frozen file, and my rerun proves the frozen file came from the unbroken code. They go to follow-ups. The chip and blind helpers are still live: they are the published tools for the Accept-line relabel and any future re-check. Their breaks are the major finding.

## Finding JSON

```json
{
  "gauntlet": "G-Code",
  "task": "T1.0",
  "round": 1,
  "head": "fa4586f (dispatched on a53a3e4; head moved during review)",
  "verdict": "fail",
  "findings": [
    {
      "severity": "major",
      "where": "qa/reference/chips.py:80 (SWIR band order), :156-166 (labelling_order, blind_subset), :169-175 (read_labels); tests/qa_reference/test_reference.py ChipsTest",
      "what": "The live review tools for the Accept-line blind relabel have untested behaviour: the SWIR false-colour band order, the randomness of blind_subset, the per-date shuffle of labelling_order, and read_labels rejecting unknown labels. A deliberate break of each one leaves the suite green.",
      "observed": "Mutation runs on fa4586f: N6 blind_subset returns points[:count] -> 31 tests OK; N9 swir = (red, nir, swir16) -> OK; N10 read_labels accepts any label -> OK; N11 labelling_order sorted by id -> OK (mutations_fa4586f.txt)",
      "to_pass": "Add tests that fail on these breaks: point_panels' second panel is built from swir16/nir/red in that order (distinct per-band values in the synthetic mosaic); blind_subset differs from the first-N slice and changes with the seed; labelling_order keeps dates grouped but changes the within-date order; read_labels raises ValueError on an unknown or blank label."
    },
    {
      "severity": "minor",
      "where": "qa/reference/sample.py:257 supplement_masks, :322 cell_table, :264 supplement; qa/reference/freeze.py:94",
      "what": "The sample-building code (supplement restriction, seed, spacing to earlier draws, cell table, freeze's scored/weight fields) has no direct test. The frozen file is protected by the hash and its weights by test_stored_weights_are_the_inverse_inclusion_probabilities, but a future draw or freeze would run untested code.",
      "observed": "N12, N12b, N16, N17, N18, N20, N23 all leave the suite green. My independent rerun reproduced the frozen file exactly, so the frozen sample itself is unaffected.",
      "to_pass": "Follow-up: a synthetic test of supplement_masks (threshold = snowline + above_snowline_m) and cell_table (per-band pixel counts), and a freeze test on a 3-point collection."
    },
    {
      "severity": "minor",
      "where": "qa/reference/README.md 'Rebuild and review'; qa/reference/sample.py:405 (--domain default data/domain.geojson)",
      "what": "Reproduction depends on data/domain.geojson from plan/t21-domain 17b37fb. That file is not on this branch, and neither the README nor the frozen metadata names the commit or the file hash. The default --domain path does not exist on the branch.",
      "observed": "The rerun reproduced only after I fetched 17b37fb:data/domain.geojson by hand. bad749e changes stratum_pixels (the PR body's 'Found, not done' says so).",
      "to_pass": "Name the domain source (plan/t21-domain 17b37fb, data/domain.geojson, its SHA-256) in qa/reference/README.md under Rebuild."
    },
    {
      "severity": "minor",
      "where": "qa/reference/chips.py:112 (captions), sample.py point ids",
      "what": "Blind pages caption each chip with its point id. Later-draw points are numbered after draw 1 on each date, so the id reveals the snow-prone draws to a relabeller.",
      "observed": "write_pages calls page(..., {}), so the caption falls back to the point id; ids such as 2026-03-25-115 are draw 2 or later.",
      "to_pass": "In blind mode, caption with a neutral shuffled key (B001...) and write the key mapping to a separate file."
    },
    {
      "severity": "minor",
      "where": "qa/reference/freeze.py:94 (out defaults to SAMPLE_PATH), README Rebuild step",
      "what": "Running the README's rebuild sequence overwrites the frozen file in place. The pinned hash now makes CI fail afterwards, but the README tells people to do it.",
      "observed": "freeze(points, labels) writes qa/reference/snow_points.geojson by default.",
      "to_pass": "Make --out required (or refuse to overwrite an existing frozen file) and use a new file name in the README rebuild step."
    }
  ],
  "followups": [
    "pyproject.toml [tool.mypy] files = [pipelines, scripts] leaves qa/ out of CI mypy; qa/reference is clean when checked explicitly (T0.6 scope, not this card).",
    "score.confusion raises KeyError rather than ValueError on an unknown predicted class (still loud, not silent)."
  ]
}
```

Artifacts in this folder: `mutate.sh` (mutation harness), `mutations_a53a3e4.txt`, `mutations_fa4586f.txt`, `compare.py`, `rerun_compare_a53a3e4.txt`, `rerun_compare_fa4586f.txt`.
