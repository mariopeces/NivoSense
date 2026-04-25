# Bucket Inventory — Sierra Nevada
**Date checked:** 2026-04-25

---

## Climate Variables

All four variables share the same structure: **7 years × 5 periods = 35 files each** (140 files total across all variables).

**Pattern:** `easyclimate_{variable}_{year}_{period}_sierra_nevada.tif`

### Coverage

| Year | annual | spring | summer | autumn | winter |
|------|--------|--------|--------|--------|--------|
| 2018 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2019 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2020 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2021 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2022 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2023 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2024 | ✓ | ✓ | ✓ | ✓ | ✓ |

### Variables

| Variable | Description | Files |
|----------|-------------|-------|
| `prcp` | Precipitation | 35 |
| `tavg` | Average temperature | 35 |
| `tmin` | Minimum temperature | 35 |
| `tmax` | Maximum temperature | 35 |

> Note: `prcp/2018/summer` also contains additional tiled files for `portugal_maxent` and `spain_maxent` regions (not sierra_nevada).

---

## Sentinel-2 Raw Images (`s2_raw_images`)

**Total:** 4,935 TIF files (+ companion `.json` metadata per file)  
**All files are Sierra Nevada only.**

**Pattern:** `s2_raw_images_{band}_{year}_{month}_sierra_nevada_{timestamp}Z.tif`

### Bands

| Band | Description |
|------|-------------|
| `b02` | Blue |
| `b03` | Green |
| `b04` | Red |
| `b08` | NIR |
| `b11` | SWIR 1 |
| `b12` | SWIR 2 |
| `scl` | Scene Classification Layer |

### Coverage by Year

| Year | Months Available | TIF Files |
|------|-----------------|-----------|
| 2018 | jan, feb, mar, apr, may, jun, jul, aug, sep, oct | 707 |
| 2019 | jan, feb, mar, apr, may, jun, jul, aug, sep, oct | 770 |
| 2020 | jan, feb, mar, apr, may, jun, jul, aug, sep, oct | 756 |
| 2021 | jan, feb, mar, apr, may, jun, jul, aug, sep, oct | 721 |
| 2022 | jan, feb, mar, apr, may, jun, jul, aug, sep | 644 |
| 2023 | jan, feb, mar, apr, may, jun, jul, aug, sep | 686 |
| 2024 | jan, feb, mar, apr, may, jun, jul, aug, sep | 651 |

> `oct` is present for 2018–2021 only. `nov` and `dec` are absent across all years.

---

## Modelo Digital del Terreno

| Atributo | Valor |
|----------|-------|
| **Fuente** | CNIG (Centro Nacional de Información Geográfica) |
| **Resolución** | 5 m |
| **Área** | Sierra Nevada |
| **Formato** | GeoTIFF |

---

# NO Bucket Inventory — Sierra Nevada

interesant git: https://github.com/KiKeMerino/Snow-Cover-Forecasting-with-LSTM-Remote-Sensing-Time-Series-ML

papers:
- 1-s2.0-S2214581824004348-main.pdf
- Downscaling MODIS NDSI to Sentinel-2 fractional snow cover by random forest regression.pdf
