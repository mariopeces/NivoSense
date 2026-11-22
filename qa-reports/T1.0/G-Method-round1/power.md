| stratum | scored (draw 1 / 2) | snow (draw 1 / 2) | no_snow | cloud | snow by in_strata membership (scored) |
|---|---|---|---|---|---|
| snowline_band | 299 (268 / 31) | 80 (67 / 13) | 218 | 1 | 100 |
| terrain_shadow | 316 (299 / 17) | 95 (82 / 13) | 221 | 0 | 122 |
| forest | 370 (299 / 71) | 43 (20 / 23) | 323 | 4 | 56 |
| cloud_edge | 237 (189 / 48) | 44 (24 / 20) | 163 | 30 | 52 |
| open_terrain | 362 (330 / 32) | 110 (84 / 26) | 251 | 1 | 110 |

all labels: {'no_snow': 1176, 'unsure': 481, 'cloud': 36, 'snow': 372}

| stratum | n snow | n not snow | true F1 | 95% range of measured F1 | P(measured < 0.70) |
|---|---|---|---|---|---|
| forest | 43 | 327 | 0.70 | 0.588 to 0.804 | 0.49 |
| forest | 43 | 327 | 0.75 | 0.646 to 0.843 | 0.16 |
| forest | 43 | 327 | 0.80 | 0.706 to 0.884 | 0.02 |
| forest | 43 | 327 | 0.85 | 0.765 to 0.921 | 0.00 |
| cloud_edge | 44 | 193 | 0.70 | 0.592 to 0.800 | 0.50 |
| cloud_edge | 44 | 193 | 0.75 | 0.651 to 0.842 | 0.16 |
| cloud_edge | 44 | 193 | 0.80 | 0.705 to 0.884 | 0.02 |
| cloud_edge | 44 | 193 | 0.85 | 0.767 to 0.921 | 0.00 |

| n snow points | true F1 0.80: 95% range | half-width |
|---|---|---|
| 43 | 0.706 to 0.884 | 0.089 |
| 80 | 0.732 to 0.863 | 0.065 |
| 100 | 0.741 to 0.856 | 0.057 |
| 150 | 0.752 to 0.846 | 0.047 |
| 200 | 0.758 to 0.839 | 0.040 |
| 300 | 0.767 to 0.832 | 0.033 |
