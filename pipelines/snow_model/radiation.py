import numpy as np

SAMPLE_STEP_DAYS = 4
HOUR_ANGLES = np.linspace(-np.pi, np.pi, 48, endpoint=False) + np.pi / 48
MAX_INDEX = 3.0


def _daily_sum(latitude: float, declination: float, slope: np.ndarray, azimuth_from_south: np.ndarray):
    phi = np.radians(latitude)
    sin_d, cos_d = np.sin(declination), np.cos(declination)
    total = np.zeros(slope.shape, dtype="float32")
    flat = 0.0
    cos_slope, sin_slope = np.cos(slope), np.sin(slope)
    cos_az, sin_az = np.cos(azimuth_from_south), np.sin(azimuth_from_south)
    constant = sin_d * np.sin(phi) * cos_slope - sin_d * np.cos(phi) * sin_slope * cos_az
    for omega in HOUR_ANGLES:
        cos_w, sin_w = np.cos(omega), np.sin(omega)
        incidence = (
            constant
            + cos_d * np.cos(phi) * cos_slope * cos_w
            + cos_d * np.sin(phi) * sin_slope * cos_az * cos_w
            + cos_d * sin_slope * sin_az * sin_w
        )
        total += np.maximum(incidence, 0)
        flat += max(sin_d * np.sin(phi) + cos_d * np.cos(phi) * cos_w, 0.0)
    return total, flat


def radiation_index(latitude: float, slope: np.ndarray, aspect: np.ndarray):
    """Ratio of clear-sky direct radiation on each slope to that on flat ground.

    Returned for a set of sample days of the year; use `index_for_day` to interpolate.
    Aspect is the downslope azimuth clockwise from north.
    """
    azimuth_from_south = aspect - np.pi
    sample_days = np.arange(1, 366, SAMPLE_STEP_DAYS)
    samples = np.empty((len(sample_days), slope.size), dtype="float32")
    for index, day in enumerate(sample_days):
        declination = np.radians(23.45) * np.sin(2 * np.pi * (284 + day) / 365)
        total, flat = _daily_sum(latitude, declination, slope, azimuth_from_south)
        samples[index] = 1.0 if flat <= 1e-6 else np.clip(total / flat, 0.0, MAX_INDEX)
    return samples


def index_for_day(samples: np.ndarray, day_of_year: int) -> np.ndarray:
    position = (min(day_of_year, 365) - 1) / SAMPLE_STEP_DAYS
    lower = int(np.floor(position))
    fraction = position - lower
    upper = (lower + 1) % samples.shape[0]
    return samples[lower] * (1 - fraction) + samples[upper] * fraction
