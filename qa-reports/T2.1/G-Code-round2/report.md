## G-Code gauntlet, T2.1 round 2 (narrow): **PASS**

I judged head `bad749e`, which is still the PR head. Only T2.1's diff on top of `plan/t06-ci` (`7277965..bad749e`) is in scope, plus the round-1 fixes (`2095dc9..bad749e`, T2.1 files). I ran everything myself in WSL Ubuntu x86_64 on a fresh clone with Python 3.11 (uv 0.13.9). The commands are in `qa-reports/T2.1/G-Code-round2/commands.sh`.

### 1. Round-1 major (geo deps missing from the hashed locks): fixed
- `pipelines/requirements.in` now pins `geopandas==1.2.0`, `pyogrio==0.13.0`, `pyproj==3.7.2` and `shapely==2.2.0`. `pipelines/domain/requirements.txt` is deleted.
- Lock delta against T0.6 only adds packages, with no version changes:
  - runtime: geopandas, pandas, pyogrio, pyproj, python-dateutil, tzdata and packaging;
  - dev lock: the same set without packaging (already present).
- I built a fresh venv from `requirements.lock` alone with `pip install --no-cache-dir --require-hashes`. It installed cleanly. A second fresh venv from `requirements-dev.lock` also installed cleanly.
- **The locks reproduce.** A fresh `uv pip compile … --generate-hashes --python-version 3.11 --python-platform x86_64-manylinux_2_28` into `/tmp` matches both committed locks line for line (header comments excluded).
- **The rebuild is byte-identical.** I ran `python -m pipelines.domain.build` from the runtime-only venv against fresh REDIAM WFS and MITECO ENP downloads. It finished in 23 s and `git status` was clean afterwards. sha256 of each output, mine = committed:

| File | sha256 (prefix) |
|---|---|
| `data/domain.geojson` = `frontend/public/data/domain.geojson` | `2cb504fefb3ad79f` |
| `data/basins.geojson` = `frontend/public/data/basins.geojson` | `6e8754622ad13276` |
| `regions/sierra-nevada.json` | `68f2f91a87a5af9a` |
| `data/sources/miteco_…_sierra_nevada.geojson` (untouched without `--subbasin-zips`) | `ecf252bbfc8ab9c3` |

- The ENP zip I downloaded hashes to `5bd7d4d2…dcabe`, the recorded value.
- The dependency justification is in the PR body. It includes why pyproj is 3.7.2: 3.8 needs Python 3.12, and CI runs 3.11.

### 2. sha256 refusal, checked with deliberately corrupted sources
Each case got its own `--cache` dir. Every run exited 1 before writing anything, and `git status` stayed clean.

| Corruption | Result |
|---|---|
| ENP zip, one byte overwritten at offset 1,000,000 | `ValueError: …Enp2025_shp.zip has sha256 8a02744b…, not the recorded 5bd7d4d2…` |
| REDIAM GML, one coordinate digit changed in a Sierra Nevada feature | `ValueError: REDIAM Parque Nacional feature has sha256 b2249ff4…, not the recorded 8b4bfda1…` |
| 4 KiB of random bytes named `A_cuencas_rios_Atl_Sur.zip`, passed to `--subbasin-zips` | `ValueError: …has sha256 7123f8e4…, not the recorded bdc091bf…` |

I could not hash the real sub-basin zips: they sit behind ALTCHA, the same limit G-Data and G-Method hit in round 1. The refusal path for them is exercised above.

### 3. The sliver merge did not move the areas the other gauntlets passed
My script `areas.py` reprojects the committed GeoJSONs to EPSG:25830 at both heads.

| Part | 2095dc9 (round 1) | bad749e | Legal / official |
|---|---|---|---|
| Domain | 1722.38047 | 1722.38047 | 1722.380 |
| Parque Nacional | 858.82883 | 858.82883 | 858.83 |
| Parque Natural | 863.55157 | 863.55157 | 863.55 |

- **Park and domain geometry is unchanged** to 1e-5 km². The metadata `areas` block is identical, so the merge only touched basins.
- NP and PNat round to 858.829 and 863.551, each 0.001 km² from the legal surface. Unrounded, NP is 0.0012 km² off, which is 0.00014%. It was the same in round 1, so there is no regression.
- **Basins.** The parts per basin went from 1/3/5/1 to 1/1/1/1:

| Basin | Before | After | Change |
|---|---|---|---|
| Guadalquivir | 520.72492 | 520.73645 | +0.0115 |
| Adra | 223.20354 | 223.20271 | −0.0008 |
| Andarax | 486.10588 | 486.09473 | −0.0112 |
| Guadalfeo | 492.34611 | 492.34656 | +0.0005 |

- The sum is conserved (1722.38046 before and after). The union equals the sum, so the basins do not overlap. `domain_area_km2` equals the geometry area to 0.001.

### 4. Tests, lint and types (T0.6 config)
- `ruff check .`: all checks passed. `ruff format --check` on the domain files: already formatted. `mypy`: no issues in 26 source files.
- `pytest -q`: 74 passed, 27 of them domain tests. The domain tests also pass with `-W error`. The 6 warnings come from rasterio internals, not from this diff.
- CI on `bad749e`: python and frontend both pass.
- **Broken-input check (mutants):**
  - turning `verify_sha256` into a no-op fails 2 tests;
  - skipping the `MIN_PART_M2` merge fails `test_detached_fragment_moves_…`;
  - dropping `orient_polygons` fails `test_rings_follow_rfc_7946_orientation`.

### 5. Regression review of `2095dc9..bad749e` (T2.1 files)
- `merge_small_parts` handles fragments under one 100 m cell, which keeps it inside the card. It sends each fragment to the neighbour with the longest shared edge; ties go deterministically to the lowest index. When nothing touches the fragment, it keeps it instead of dropping area. Areas are recomputed after the merge. No silent `except` anywhere.
- I checked the stale `list(geometries)` snapshot in the loop. It is safe: fragments only ever move into a basin, and they arrive attached to it, so the snapshot never misses a part.
- The `--retrieved` flag and its `date.today()` default are gone. Provenance dates are now constants, which is why the rebuild is deterministic.
- The REDIAM pin is a digest of the feature (attributes plus WKB) because the WFS adds a timestamp to each response. That is a sound choice, and the corrupted-GML run shows it detects geometry edits.
- No secrets, tokens or personal data. The User-Agent is generic.
- Nit, not a finding: `MITECO_SUBBASIN_FILES` values keep redundant parentheses `("…")` left over from the line wrap.

```json
{
  "gauntlet": "G-Code",
  "task": "T2.1",
  "round": 2,
  "verdict": "pass",
  "findings": [],
  "followups": [
    "Redundant parentheses around the MITECO_SUBBASIN_FILES hash strings (pipelines/domain/build.py, cosmetic)",
    "Sub-basin zip hashes still not independently re-hashed (ALTCHA); keep a private copy of the two zips (carried over from G-Data/G-Method round 1)"
  ]
}
```
