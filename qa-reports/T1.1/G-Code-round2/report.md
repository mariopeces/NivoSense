# G-Code, T1.1 Sentinel-2 ingest, round 2

**Verdict: pass** (0 blocker, 0 major, 3 minor). PR #14, `plan/t11-s2-ingest` @ `dafc7f3` (the head the coordinator named; unchanged when judged). Diff judged: `git diff origin/main...dafc7f3`, which touches only `pipelines/s2/` and `tests/s2/` (11 files). Every run used `data/basins.geojson`. Nothing was written to a bucket; no live writes were needed.

## Round-1 major 1: two platforms on one orbit and day

**Fixed, verified on real data with my own code.** `scan_platforms.py` uses only pystac-client and shapely, no PR code. It scanned 2024-10-01..2026-11-21 (1,534 items, 422 passes) for (date, orbit) passes that hold more than one datatake (`scan_platforms.txt`):

- S2A + S2C: 10 passes, 2024-11-05..2024-12-18, during S2C's tandem phase. Four of them are R094 passes covering all 4 tiles.
- S2A + S2B: 5 passes, 2026-02-03..02-23.
- S2B + S2C: none in this range, so I tested S2A + S2C instead.

`two_platforms.py` runs the PR's `ingest.run` on 2024-11-08 R094, 2024-11-05 R051, 2026-02-16 R094 and 2026-02-13 R051. For each datatake it then builds its own SCL mosaic with `rasterio.merge`, using only that datatake's granules at the newest baseline, and compares it with the stored `classes.tif` inside the domain (`two_platforms.txt`):

| pass | kept (valid) | alternative (valid) | domain px where the two datatakes' SCL differ | stored = kept / = other on those px |
|---|---|---|---|---|
| 2024-11-08 R094 | GS2C (0.3328, listed) | GS2A (0.2930) | 349,204 | 349,204 / **0** |
| 2024-11-05 R051 | GS2C (0.0980) | GS2A (0.0978) | 20,147 | 20,147 / **0** |
| 2026-02-16 R094 | GS2B (0.8965, listed) | GS2A (0.8942) | 170,990 | 170,990 / **0** |
| 2026-02-13 R051 | GS2B (0.0193) | GS2A (0.0191) | 72,971 | 72,971 / **0** |

- On every pass, the stored SCL equals the kept datatake's own mosaic on 100% of domain pixels. No pixel comes from the other datatake, so there is no seam.
- Coverage and valid fraction match my independent values to 4 decimals for both the kept datatake and the `alternatives` entry.
- The rule matters on 2024-11-08: S2C at 0.3328 is listed, while S2A alone, at 0.2930, would have fallen under the 0.30 threshold.
- Correction to my round-1 report: for 2026-02-13 R051 I swapped the per-satellite fractions. S2A is 0.0958 / 0.0191 and S2B is 0.0947 / 0.0193. The builder's `feb.log` is right.

## Round-1 major 2 and deliberate breaks

`mutations.py` makes 23 single-string mutations plus one unmutated baseline row (22 passed). Each mutation runs in a fresh copy of `pipelines/`, `tests/` and `data/basins.geojson`, against `tests/s2` (`mutations.txt`). **18 of 23 are caught.**

- **All 3 round-1 survivors are now caught:**
  - threshold 0.30 → 0.05: caught by `test_listing_follows_the_30_percent_rule…`;
  - scale/offset from `items[0]`: caught by `test_each_granule_uses_its_own_raster_bands_offset`;
  - footprint filter removed from `run()`: caught by `test_incomplete_date_is_reprocessed…`.
- **The round-1 major 1, reintroduced, is caught.** Two breaks fail both datatake tests: ignoring the datatake in grouping, and keeping the baseline suffix in the datatake id. So do keeping the murkiest datatake, ranking by coverage first, keeping the first datatake without ranking, reporting the chosen datatake as an alternative, and giving alternatives the chosen datatake's valid fraction.
- Also caught: `is_current` ignoring the input key, a reprocessing window of 0 or 3 days, `listed` ignoring `complete`, a decision not rewritten on rebuild, a wrong `code_version` in the decision, SCL 2 counted as not valid, and every baseline kept.
- **5 survive** (finding 1): G6, K1, K3, K4 and L4.

The builder's 15/15 is consistent with this: their 15 do not include my 5 survivors.

## Builder claims rechecked

- **Late granule or newer baseline reopens a complete date:** the two tests use the real 2026-11-17 and 2021-06-07 items and pass. Mutations K2, K5 and K6 are caught.
- **No needless rebuild:** I reran on dates that were already built, now with `catalogue_root` (`decisions_rerun.txt`). Zero records were rebuilt (process never called, no `record.json` mtime changed), and the missing decisions were written.
- **Listed implies complete:** `is_listed` requires `complete`, and mutation L1 is caught.
- **T0.4 `s2_decision` objects:** 10 decisions from my rerun and the builder's 5 samples all validate against `plan/t04-qa:pipelines/catalog/s2_decision.schema.json` with jsonschema Draft 2020-12 and format checking (`validate_decisions.py`).

## Rubric

- **Tests:** `pytest tests/s2` gives 22 passed in a venv with T0.6's pins (ruff 0.17.6, mypy 1.20.2, pytest 9.2.0, numpy 2.4.6, rasterio 1.4.4). `pytest tests backend/tests` gives **67 passed** (`tooling.txt`). CI is not judged: T0.6 is pending.
- **Lint and types:** with `pyproject.toml` from `plan/t06-ci`, `ruff check` and `ruff format --check` are clean on `pipelines/s2` and `tests/s2`, and `mypy pipelines/s2` is clean. The project-wide `mypy` reports 16 errors, all outside `pipelines/s2`, in legacy files this PR does not touch.
- **Interface additions:**
  - `Record.datatake`, `input_key` and `alternatives` are typed fields of a frozen dataclass and are described in the module docstring and the PR text.
  - `run(catalogue_root: Path | None, version: str | None)` is typed and covered by `test_late_split_granule…`.
  - The `alternatives` contents are tested; `version` is undocumented (finding 2).
- **Code quality:** the change stays in card scope (grouping, completeness, reprocessing) plus the pass decision that T0.4's freshness monitor reads, written in T0.4's schema and only with `--catalogue-root`. There is no dead code, no `except` and no speculative abstraction. Names read well, and the comments give the why (datatake suffix, split granules, the 10-day margin over README section 5's 5 days). The round-1 mosaic docstring is now correct.
- **Secrets and personal data:** a grep over the diff, the PR body, the builder's reply and the `t11/round2` evidence finds no keys, tokens, emails or local paths.
- **Dependencies:** none added. The only imports are stdlib, numpy and rasterio, all already in T0.6's lock.

## Findings

1. **Minor: five deliberate breaks on the new paths survive the tests.** The code is correct on each, as my live runs show; the tests just do not pin these paths:
   - **G6:** `missing` taken from the union of all datatakes' tiles instead of the kept one's. A clear but partial datatake would then be marked `complete` and `listed` with a tile missing.
   - **K3:** `is_current` ignoring expected tiles. The PR says a change in expected tiles reopens a date; nothing tests it.
   - **L4:** the decision's `listed` always False. The freshness monitor (F1) reads it.
   - **K1:** the input key from the kept datatake only. Two-datatake passes would be rebuilt on every run.
   - **K4:** the input key from baselines only. Swapping one granule for another with the same baseline is not detected.

   To pass (any round): add tests for each.
2. **Minor:** `run()`'s docstring does not mention `catalogue_root` or `version`, and `version` is documented nowhere (`ingest.py:344-355`). To pass: one line each.
3. **Minor:** `record.json`'s `input_key` hashes the granule ids and baselines only. README D3 and T0.3's `publish.input_key` define the input key as the scene ids, baseline **and code version** (plus prior state). Same name, different meaning. To pass: rename it, or document that it is the ingest's reprocessing key and that T1.2 publishes with T0.3's key.

## Follow-ups
- No S2B + S2C same-orbit pair exists over the domain in 2024-10..2026-11, so S2A + S2C (2024-11/12) stood in. If S2B and S2C ever share an orbit and day, the same code path applies.
- Every run also processes the 10 days before `today`, including backfill runs over an old range. This is by design (README section 5) and covered by a test; noted only for backfill cost planning (T1.6/T1.7).
