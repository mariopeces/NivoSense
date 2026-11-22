"""Checks of one RGB date against the L2A bands of the same acquisition (pipelines.s2 output):
snow saturation and geometric alignment with the 20 m grid of the snow masks."""

from pathlib import Path

import numpy as np

from pipelines.s2.mosaic import SCL_NOT_VALID

# Snow stand-in until the observed snow masks exist: pass 1 of the Theia LIS snow detection
# (Gascoin et al. 2019, Hydrol. Earth Syst. Sci. 23, 2513), NDSI > 0.4 and red > 0.2, on
# clear-sky SCL pixels of the L2A bottom-of-atmosphere reflectance.
NDSI_SNOW = 0.4
RED_SNOW = 0.2
SATURATED = 255
# Accept line of the layer: RGB and snow masks align within one 20 m pixel.
ALIGNED_M = 20.0
CHIP = 256
MIN_CHIP_VALID = 0.9
# A chip without texture gives a meaningless correlation peak (flat water, uniform cloud).
MIN_CHIP_STD = 0.01


def read_l2a(folder: Path) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Reflectance (green, red, swir16) and SCL of one pipelines.s2 acquisition folder."""
    import rasterio

    with rasterio.open(folder / "reflectance.tif") as source:
        reflectance = {source.descriptions[i]: source.read(i + 1) for i in range(source.count)}
    with rasterio.open(folder / "classes.tif") as source:
        scl = source.read(1)
    return reflectance, scl


def snow_mask(reflectance: dict[str, np.ndarray], scl: np.ndarray) -> np.ndarray:
    green, red, swir = reflectance["green"], reflectance["red"], reflectance["swir16"]
    with np.errstate(invalid="ignore", divide="ignore"):
        ndsi = (green - swir) / (green + swir)
        return (ndsi > NDSI_SNOW) & (red > RED_SNOW) & ~np.isin(scl, SCL_NOT_VALID)


def blocks(array: np.ndarray, factor: int) -> np.ndarray:
    """(rows, cols, factor * factor) view of the factor x factor blocks of a 2-D array."""
    rows, cols = array.shape[0] // factor, array.shape[1] // factor
    return array.reshape(rows, factor, cols, factor).swapaxes(1, 2).reshape(rows, cols, factor * factor)


def snow_saturation(rgb: np.ndarray, snow: np.ndarray) -> dict[str, float]:
    """Share of the 10 m RGB pixels under 20 m snow pixels that sit at 255, per band and in all
    three bands at once."""
    factor = rgb.shape[1] // snow.shape[0]
    under = [blocks(band, factor)[snow] for band in rgb]
    count = under[0].size
    if count == 0:
        return {"snow_pixels_10m": 0.0}
    at_max = [values == SATURATED for values in under]
    scores = {"snow_pixels_10m": float(count)}
    for name, flags in zip(("red", "green", "blue"), at_max):
        scores[f"snow_saturated_{name}"] = float(flags.mean())
    scores["snow_saturated_all"] = float(np.stack(at_max).all(axis=0).mean())
    return scores


def phase_shift(reference: np.ndarray, moving: np.ndarray) -> tuple[float, float]:
    """(rows, cols) displacement of `moving` relative to `reference`, in pixels, by phase
    correlation (Kuglin and Hines 1975) with a parabolic fit of the peak for the sub-pixel part."""
    window = np.outer(np.hanning(reference.shape[0]), np.hanning(reference.shape[1]))
    a = np.fft.fft2((reference - reference.mean()) * window)
    b = np.fft.fft2((moving - moving.mean()) * window)
    cross = b * np.conj(a)
    surface = np.fft.ifft2(cross / np.maximum(np.abs(cross), 1e-12)).real
    peak = np.unravel_index(np.argmax(surface), surface.shape)
    shift = []
    for axis, index in enumerate(peak):
        size = surface.shape[axis]
        before = surface[tuple((index - 1) % size if a == axis else peak[a] for a in range(2))]
        after = surface[tuple((index + 1) % size if a == axis else peak[a] for a in range(2))]
        centre = surface[peak]
        denominator = before - 2 * centre + after
        fraction = 0.5 * (before - after) / denominator if denominator != 0 else 0.0
        value = index + fraction
        shift.append(value - size if value > size / 2 else value)
    return shift[0], shift[1]


def chip_shifts(
    reference: np.ndarray, moving: np.ndarray, valid: np.ndarray, edges: np.ndarray | None = None
) -> list[tuple[float, float]]:
    """Phase shift of every CHIP x CHIP chip where both images are valid and textured; with
    `edges` (a boolean mask), only chips holding 5% to 95% of it, so an edge exists to align."""
    shifts = []
    for row in range(0, reference.shape[0] - CHIP + 1, CHIP):
        for col in range(0, reference.shape[1] - CHIP + 1, CHIP):
            window = (slice(row, row + CHIP), slice(col, col + CHIP))
            ok = valid[window]
            if ok.mean() < MIN_CHIP_VALID:
                continue
            if edges is not None and not 0.05 <= edges[window][ok].mean() <= 0.95:
                continue
            a, b = reference[window].copy(), moving[window].copy()
            a[~ok], b[~ok] = a[ok].mean(), b[ok].mean()
            if a.std() < MIN_CHIP_STD or b.std() < MIN_CHIP_STD:
                continue
            shifts.append(phase_shift(a, b))
    return shifts


def alignment(rgb: np.ndarray, l2a: dict[str, np.ndarray], snow: np.ndarray, resolution: float) -> dict[str, float]:
    """Displacement of the RGB against the 20 m L2A grid, in metres, over chips: the RGB green
    against the L2A green, and the RGB brightness against the snow stand-in mask (only chips
    with a snow edge). Scores per check: chip count, median, 90th percentile and largest chip
    shift, and the share of chips within one 20 m pixel. A single chip can fail to correlate
    (a weak or cloud-confused snow edge), so the median and the share carry the verdict."""
    factor = rgb.shape[1] // snow.shape[0]
    valid_rgb = blocks(np.asarray((rgb > 0).all(axis=0)), factor).all(axis=2)
    green = blocks(rgb[1].astype("float32"), factor).mean(axis=2) / 255
    brightness = blocks(rgb.astype("float32").mean(axis=0), factor).mean(axis=2) / 255
    l2a_green = l2a["green"]
    valid = valid_rgb & ~np.isnan(l2a_green)
    scores: dict[str, float] = {}
    for name, reference, moving, edges in (
        ("l2a_green", np.nan_to_num(l2a_green), green, None),
        ("snow_mask", snow.astype("float32"), brightness, snow),
    ):
        shifts = chip_shifts(reference, moving, valid, edges)
        scores[f"shift_{name}_chips"] = float(len(shifts))
        if shifts:
            metres = np.hypot(*np.array(shifts).T) * resolution
            scores[f"shift_{name}_median_m"] = round(float(np.median(metres)), 2)
            scores[f"shift_{name}_p90_m"] = round(float(np.percentile(metres, 90)), 2)
            scores[f"shift_{name}_max_m"] = round(float(metres.max()), 2)
            scores[f"shift_{name}_within_20m"] = round(float(np.mean(metres < ALIGNED_M)), 4)
    return scores
