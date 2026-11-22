# G-Method, T2.1 Domain, round 1

PR #15, head `2095dc9` (plan/t21-domain, one commit on `51aa990`). **Verdict: pass.** I found 0 blockers, 0 majors and 4 minors.

I fetched every number below myself on 2026-11-22: the REDIAM RENPA WFS (`ms:eennpp`, served as EPSG:3042) and MITECO `Enp2025_shp.zip` (sha256 `5bd7d4d2…dcabe`, the same value the PR's `domain.geojson` metadata records). I wrote my own scripts; I did not import `build.py`. Scripts and logs are in `qa-reports/T2.1/G-Method-round1/` on branch `mariopeces/g-t21-gmethod-r1`.

## Accept lines

### 1. The polygons match the official layers (area within 0.5%)
Areas are planar in EPSG:25830. Symmetric differences are between the PR's GeoJSON and my own fetch.

| Part | PR km² | Mine km² | Symmetric difference | Legal surface |
|---|---|---|---|---|
| Parque Nacional (MITECO ES610002) | 858.829 | 858.829 | 0.0086 km² (0.0010%) | 85,883 ha (0.0001% off) |
| Parque Natural (REDIAM 72) | 863.552 | 863.552 | 0.0176 km² (0.0020%) | 86,355 ha (0.0002% off) |
| Domain (union) | 1722.381 | 1722.380 | 0.0101 km² (0.0006%) | 172,238 ha (0.0000% off) |

The PR's symmetric differences come from the 6-decimal rounding (about 0.1 m).

Independent cross-checks of the domain against two official polygons the build does not use:
- My union vs the REDIAM "Espacio Natural Sierra Nevada" polygon (8372, Decreto 24/2007): symmetric difference 0.00006 km².
- My union vs MITECO ZEC ES6140004: 0.00011 km².
- Parque Nacional, MITECO vs REDIAM: 0.0016 km² (matches the PR).
- Parque Natural, REDIAM vs MITECO ES610001: 0.00014 km².
- Overlap between the parks: 0.0000 km².

Geometry:
- All outputs are valid.
- The domain is 1 part with 0 holes. My raw union has 5,983 interior slivers, all under 0.4 m², at the shared edge between the parks; the PR's `set_precision` closes them all.
- The Parque Natural has 5 parts, as in the source.
- The basins' union vs the domain: symmetric difference 10 m². Pairwise overlap between basins: 0 m².
- My maps over Esri World Topo (`map_overview.png`, plus zooms of the shared park edge in `map_shared_edge.png`) show no gaps or slivers between the boundaries.

### 2. Every sub-basin carries `source_area_km2` and `domain_area_km2`, and the area projection is stated
- All 4 features have both fields.
- `domain_area_km2` equals the feature's geometry area in EPSG:25830 to 0.001 km².
- `area_crs: EPSG:25830` is in the metadata.
- `source_area_km2` is MITECO `Shape_Area`. It equals the `Shape_Area` of the pre-PR file on main (57077.931 / 1302.072 / 749.391 / 2157.284).
- Geodesic areas (GRS80) are +0.078% above planar: domain 1723.730 vs 1722.380 km². This confirms the PR's "~0.07%" statement and is far inside the tolerance.

### 3. Nothing hand-edited
- I reran `python -m pipelines.domain.build --retrieved 2026-11-22` with a fresh cache, which fetches REDIAM and MITECO live. All 6 outputs came out **byte-identical** (sha256 `-c` OK): both GeoJSONs, both frontend copies, the clipped source and `regions/sierra-nevada.json`.
- The frontend copies are byte-identical to `data/`. So are the `dist/` copies after `npm run build`.
- The region bbox `[-3.6433, 36.9129, -2.5885, 37.2532]` is the domain bounds `[-3.643279, 36.912905, -2.588546, 37.253185]` rounded outward.
- 19 tests in `tests/domain` pass.

## G-Method rubric
- **Method vs README section 3 decision 5.** I read the decree text (BOJA 155, 9/8/2011, Decreto 238/2011, `fasciculo` d3):
  - The Exposición de motivos (BOJA p. 114) and the PORN (p. 154) say "una zona periférica, a modo de zona de amortiguación, que incluye al Parque Natural".
  - The zoning table on p. 154 gives "Total Ámbito PORN 172.238" ha = Parque Nacional 85,883 + Parque Natural 86,355.
  - Ley 3/1999 (BOE-A-1999-782), art. 3, defines only an "área de influencia socioeconómica" made of whole municipalities. Nothing defines a separate protection perimeter polygon.
  - So domain = Parque Nacional ∪ Parque Natural is the correct legal reading. Excerpts are in `logs/`.
- **Sub-basins.**
  - The outermost-Pfafstetter partition keeps the 4 codes the site uses.
  - Independent check: the PR basins clipped to the National Park match the pre-PR hand-clipped `data/basins.geojson`, which came from a separate earlier MITECO download, within 0.0003 to 0.0017 km² per basin (≤0.001%).
- **Licences.**
  - The REDIAM WFS AccessConstraints read "se puede usar de modo libre y gratuito siempre que se mencione a los autores y propietarios".
  - The MITECO cuencas page "Condiciones" allow free use citing MITECO as author and owner, so the attributed clipped copy in `data/sources/` is allowed.
  - Both attributions are in the output metadata.
- **CRS and resampling.**
  - Areas are computed in the sources' projection.
  - Output is EPSG:4326 at 6 decimals, with no simplification.
- **Site.** I ran `vite preview` at 1440×900:
  - `data/basins.geojson` loads with 200.
  - A map click selects "Río Adra o Grande o Verde" and fits the view to it (`preview_basin_selected.png`).
  - The only console error is the existing `favicon.ico` 404.
  - "No rivers available" in the panel comes from the backend `/rivers` API, which is not deployed; it was already like this before the PR.
- **CI.** Under the stacked-branch rule, CI evidence arrives with T0.6 after the rebase. `gh pr checks 15` reports no checks yet. This is a merge precondition, not a finding.

## Minor findings (follow-ups, non-blocking)
1. **The sub-basin zip sha256 values were not re-hashed independently.**
   - The two MITECO zips are not on disk anywhere I could find. The download host serves an ALTCHA page to scripts, and a ~600 MB browser download needs approval I don't have as a gauntlet.
   - What I could check:
     - the recorded sha256 values agree across `build.py`, the clipped source metadata and the output metadata;
     - `--subbasin-zips` enforces them;
     - the clipped geometry is independently corroborated (the check against the pre-PR file above).
   - To close: keep a copy of the two zips in `nivosense-data/sources/` (or another private store) so future gauntlets can re-hash them.
2. **Five sliver parts in the basins.**
   - 604361 has parts of 691 and 144 m²; 604370 has parts of 67, 384 and 1,999 m². That is 3,285 m² in total.
   - They are thin strips along the domain edge, where a 1:25,000 MITECO divide runs along the 1:10,000 park boundary (`map_tiny_parts.png`).
   - The area effect is negligible, but they make these basins MultiPolygons with specks.
   - To close: when T2.x rasterises per-basin masks, drop parts under about 1 ha or assign them to the neighbouring basin.
3. **The PR text and the module docstring say EPSG:25830 is "the native CRS of all three sources".** The REDIAM WFS serves EPSG:3042: the same ETRS89 / UTM 30N projection with northing-easting axis order. There is no numeric effect; fix the wording.
4. **The PR cites the decree at "BOJA p. 2 and p. 42".** Those are page numbers of the PDF fascicle. The BOJA page numbers are 114 and 154.

```json
{
  "gauntlet": "G-Method",
  "task": "T2.1",
  "round": 1,
  "verdict": "pass",
  "findings": [
    {
      "severity": "minor",
      "where": "pipelines/domain/build.py MITECO_SUBBASIN_FILES; data/sources/miteco_subcuencas_rios_completos_sierra_nevada.geojson",
      "what": "sha256 of the MITECO sub-basin zips not re-hashed independently (zips not retained; host serves ALTCHA to scripts)",
      "observed": "hashes consistent across build.py, source metadata, output metadata; clipped geometry matches pre-PR MITECO-derived basins within 0.001% inside the National Park",
      "to_pass": "store the two zips privately (e.g. nivosense-data/sources/) so they can be re-hashed"
    },
    {
      "severity": "minor",
      "where": "data/basins.geojson cod_uni 604361 (2 parts) and 604370 (3 parts)",
      "what": "sliver parts of 67 to 1999 m2 along the domain edge (1:25k divide vs 1:10k park boundary)",
      "observed": "shapely get_parts + zoom renders over Esri World Topo (map_tiny_parts.png); total 3285 m2",
      "to_pass": "drop or reassign parts under ~1 ha when per-basin masks are built (T2.x)"
    },
    {
      "severity": "minor",
      "where": "pipelines/domain/build.py docstring; PR #15 body, Method decision 3",
      "what": "says EPSG:25830 is native CRS of all sources; REDIAM WFS serves EPSG:3042 (same projection, N-E axis order)",
      "observed": "geopandas read of own WFS fetch reports EPSG:3042",
      "to_pass": "correct the wording"
    },
    {
      "severity": "minor",
      "where": "PR #15 body, Method decision 1",
      "what": "decree cited at BOJA p. 2 and p. 42 (PDF pages); BOJA pages are 114 and 154",
      "observed": "BOJA 155/2011 fascicle d3.pdf page headers",
      "to_pass": "cite BOJA 155, pp. 114 and 154"
    }
  ],
  "followups": [
    "Keep the MITECO sub-basin zips in a private store for re-hashing",
    "Handle sliver basin parts when rasterising per-basin masks"
  ]
}
```
