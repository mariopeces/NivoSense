# Round 2 rerun on the PR head

Same probe and dates as `t13/`, rerun on PR #22 head `9f3f51d` (stack: main + T1.1 `dafc7f3` + T0.3 `a509e11`;
L1C matched by the record's datatake) by throwaway PR #32, run
https://github.com/mariopeces/NivoSense/actions/runs/44993030654 (ubuntu-latest, 4 CPU, 16 GB).

- `coverage.md`: 16 listed dates, 16 rgb entries, no L1C missing.
- `timing.md`: 41.2 to 113.7 s per date (read 12.6 to 84.5 s, publish 25 to 26 s); whole run 13 min 31 s, peak RSS 2.4 GB.
- `qa.md`, `mask_offsets.md`: identical to round 1.
- `entries/`: for all 16 dates, `pixel_hash`, the COG and PMTiles names (content-addressed) and the L1C scene ids equal
  round 1 (`t13/entries/`). `input_key` differs only because it includes the code version.

- `dual_datatake_2026-02-06.json` (`dual_datatake.py`, run locally on PR head `25102f2` with T1.1 `dafc7f3`): on 2026-02-06 R094 (S2A and S2B on one orbit) the record keeps GS2B; the RGB pipeline takes the four S2B L1C granules, and their green agrees with the record's L2A green at r = 0.982 against r = 0.941 for the S2A overpass.
