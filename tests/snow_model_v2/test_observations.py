import json
from datetime import date

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from pipelines.catalog.storage import LocalStorage
from pipelines.snow_model.grid import Grid
from pipelines.snow_model_v2.contract import ClassDomain
from pipelines.snow_model_v2.observations import (
    ERROR_FLOOR,
    class_fractions,
    load_observations,
    observation_error,
)
from pipelines.snow_obs import classify as c

LEFT, TOP = 442600.0, 4123200.0
GRID = Grid("EPSG:32630", LEFT, TOP, 100.0, 4, 2)  # 4 x 2 cells of 5 x 5 pixels


def domain_of_two_classes() -> ClassDomain:
    index = np.array([0, 0, 1, 1, 0, 0, 1, 1], dtype="int32")  # left half class 0, right half class 1
    return ClassDomain(
        class_of_cell=index,
        elevation=np.array([2000.0, 2600.0], dtype="float32"),
        aspect=np.array([0, 0], dtype="int8"),
        neighbours=np.zeros((2, 1), dtype="int32"),
        weights=np.ones((2, 1), dtype="float32"),
        radiation=np.ones((1, 2), dtype="float32"),
        cell_count=np.array([4, 4], dtype="int32"),
        cell_area_m2=1e4,
    )


def raster(classes: np.ndarray, confidence=None, flags=None) -> bytes:
    confidence = np.full(classes.shape, c.CONFIDENCE_HIGH, dtype="uint8") if confidence is None else confidence
    flags = np.zeros(classes.shape, dtype="uint8") if flags is None else flags
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=classes.shape[0],
            width=classes.shape[1],
            count=3,
            dtype="uint8",
            crs="EPSG:32630",
            transform=from_origin(LEFT, TOP, 20.0, 20.0),
        ) as target:
            for band, values in enumerate((classes, confidence, flags), start=1):
                target.write(values, band)
        return memory.read()


def publish(storage: LocalStorage, day: str, data: bytes) -> None:
    key = f"layers/snow_obs/{day}.tif"
    storage.write(key, data, "image/tiff", "no-cache")
    entry = {"cog": key, "pixel_hash": "x"}
    storage.write(f"catalog/entries/snow_obs/{day}.json", json.dumps(entry).encode(), "application/json", "no-cache")


def scene() -> np.ndarray:
    classes = np.full((10, 20), c.NO_SNOW, dtype="uint8")  # 2 x 4 cells of 5 x 5 pixels
    classes[:, :5] = c.SNOW  # cell column 0: all snow
    classes[:, 5:10] = np.where(np.arange(5)[None, :] < 1, c.SNOW, c.NO_SNOW)  # column 1: 20 % snow
    classes[:, 10:15] = c.CLOUD  # column 2: cloud, not decisive
    return classes  # column 3: bare


def test_error_formula():
    assert observation_error(np.array([100.0]))[0] == pytest.approx(np.sqrt(0.01 + 0.0025))
    assert observation_error(np.array([1e9]))[0] == pytest.approx(ERROR_FLOOR, abs=1e-4)
    assert observation_error(np.array([1.0]))[0] > observation_error(np.array([4.0]))[0]


def test_class_fractions_pool_decisive_pixels_and_skip_cloud(tmp_path):
    storage = LocalStorage(tmp_path)
    publish(storage, "2025-03-20", raster(scene()))
    observations = load_observations(
        storage, [date(2025, 3, 20), date(2025, 3, 21)], domain_of_two_classes(), GRID, np.arange(8)
    )
    assert observations.days == [date(2025, 3, 20)]
    # class 0 = columns 0 and 1: (25 + 5) snow pixels of 50 decisive; class 1 = cloud column (skipped) + bare column
    assert observations.fraction[:, 0] == pytest.approx([0.6, 0.0])
    assert observations.n_cells[:, 0].tolist() == [4.0, 2.0]  # two rows of two decisive cells; class 1 loses the cloud
    assert observations.sigma[1, 0] == pytest.approx(observation_error(np.array([2.0]))[0])


def test_cells_below_half_decisive_and_excluded_cells_do_not_count(tmp_path):
    classes = scene()
    classes[:, 0:3] = c.CLOUD  # column 0 keeps only 2 of 5 decisive pixels per row: below half
    storage = LocalStorage(tmp_path)
    publish(storage, "2025-03-20", raster(classes))
    exclude = np.zeros(8, dtype=bool)
    exclude[[1]] = True  # a cell of the first row, column 1
    from pipelines.snow_model.insertion import load_observation

    fraction, n_cells, _, _ = class_fractions(
        load_observation(storage, "2025-03-20"), GRID, np.arange(8), domain_of_two_classes(), exclude
    )
    assert n_cells.tolist() == [1.0, 2.0]  # only the second-row cell of column 1 remains in class 0
    assert fraction[0] == pytest.approx(0.2)


def test_unobserved_class_is_nan_and_dropped_date(tmp_path):
    classes = np.full((10, 20), c.CLOUD, dtype="uint8")
    storage = LocalStorage(tmp_path)
    publish(storage, "2025-03-20", raster(classes))
    observations = load_observations(storage, [date(2025, 3, 20)], domain_of_two_classes(), GRID, np.arange(8))
    assert observations.days == [] and observations.fraction.shape == (2, 0)


def test_shadow_inheritance_is_flagged_and_off_by_default(tmp_path):
    classes = scene()
    classes[:, 15:20] = c.UNKNOWN  # column 3 in terrain shadow instead of bare
    flags = np.zeros(classes.shape, dtype="uint8")
    flags[:, 15:20] = c.FLAG_TERRAIN_SHADOW
    classes[:, :5] = c.NO_SNOW  # snow free below and above: clear band evidence
    classes[:, 5:10] = c.NO_SNOW
    storage = LocalStorage(tmp_path)
    publish(storage, "2025-03-20", raster(classes, flags=flags))
    from pipelines.snow_model.insertion import load_observation

    observation = load_observation(storage, "2025-03-20")
    base = class_fractions(observation, GRID, np.arange(8), domain_of_two_classes())
    assert np.isnan(base[0][1]) and base[3].tolist() == [0.0, 0.0]
    elevation = np.tile(np.array([2000.0, 2000.0, 2600.0, 2600.0], dtype="float32"), (2, 1))
    inherited = class_fractions(
        observation, GRID, np.arange(8), domain_of_two_classes(), elevation_grid=elevation, use_shadow=True
    )
    assert inherited[0][0] == 0.0
    assert inherited[3].sum() <= 2.0
