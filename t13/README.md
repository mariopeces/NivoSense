# Evidence for T1.3 True colour RGB from L1C

Produced on a GitHub-hosted runner (ubuntu-latest, 4 CPU, 16 GB) by the throwaway probe PR #18,
run https://github.com/mariopeces/NivoSense/actions/runs/44967979166, code at
`plan/t13-rgb-l1c` f0447fe (workflow: `t13-timing.yml`). Domain: `data/domain.geojson` from the
T2.1 branch (`plan/t21-domain`), 4,305,971 pixels at 20 m. Catalogue: a local folder
(`CATALOG_LOCAL_ROOT`), written by `pipelines.catalog.publish`.

Dates: every listed date (README D1) of 2026-10-01..2026-11-21 from `pipelines.s2.ingest`, plus
five winter and spring dates. 2025-12-18, 2026-02-21 and 2026-03-25 are the stretch calibration
dates; 2026-01-12 (full snow) and 2026-04-04 are held out.

| File | What |
|---|---|
| `coverage.md` | every listed date vs its rgb entry and L1C scene ids |
| `timing.md` | seconds per date (search, JP2 read, publish) and COG / PMTiles size |
| `qa.md` | snow saturation and chip shifts against the L2A grid, from each catalogue entry |
| `mask_offsets.md` | IoU of the L2A snow stand-in mask vs the bright-RGB mask at 10 m offsets |
| `thumbs/rgb_<date>.png`, `thumbs/crest_<date>.png` | whole domain (1600 px wide) and crest Veleta-Mulhacen at 10 m |
| `z14_compare.png` | zoom-14 tiles, 2026-01-12 crest: PNG, WebP 75, 85, 90 (centre 256 px, 2x) |
| `calibration.jsonl` | output of `python -m pipelines.rgb_l1c.calibrate` (2026-01-12 line is for reference, not used) |
| `entries/` | the 16 catalogue entries |
| `rgb.log`, `s2.log` | run logs |
| `evidence.py` | the script that wrote the tables and thumbnails |
