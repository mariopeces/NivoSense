# T2.2 forcing study evidence

Produced on 2026-11-22 from branch `plan/t22-forcing` with `python -m pipelines.forcing_study.study`:

| File | Command |
|---|---|
| `inventory.json` | `inventory --end 2026-11-21` (live Open-Meteo queries at 37.06 N, 3.38 W, 2023-09-01 to 2026-11-21) |
| `precip.json` | `precip --years 2023 2024 2025` (6 RIA stations, 2023-10-01 to 2026-09-30; AEMET skipped, no key; ERA5-Land pending, no CDS key) |
| `ria_day_boundary.py`, `ria_day_boundary.md` | day-boundary check of RIA daily totals against forcing lags |
| `snow-2026-interim.json`, `.log` | `snow --years 2026 --reference interim --dates <11 T1.1 dates>`: pipeline test only, NOT a study result (hackathon NDSI masks, no snow-season held-out date) |

Final snow-presence scores and the recommendation are pending on T1.7.
