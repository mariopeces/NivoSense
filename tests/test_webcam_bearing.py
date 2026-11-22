import math
import unittest

import numpy as np
from PIL import Image

from scripts import webcam_bearing as wb

WIDTH, HEIGHT = 1920, 1080
GROUND_M = 1000.0
SIZE = 700  # cells of 30 m: 21 km square, camera in the middle


def synthetic_dem(peaks: list[tuple[float, float, float, float]]) -> wb.Dem:
    """Gaussian hills (east offset m, north offset m, height m, sigma m) on a flat plain."""
    half = SIZE * wb.DEM_RESOLUTION_M / 2
    centres = (np.arange(SIZE) + 0.5) * wb.DEM_RESOLUTION_M - half
    east, north = np.meshgrid(centres, -centres)
    elevation = np.full((SIZE, SIZE), GROUND_M)
    for dx, dy, top, sigma in peaks:
        elevation += top * np.exp(-((east - dx) ** 2 + (north - dy) ** 2) / (2 * sigma**2))
    return wb.Dem(elevation.astype("float32"), -half, half, wb.DEM_RESOLUTION_M)


def photo_skyline(horizon: wb.Horizon, pose: wb.Pose) -> tuple[np.ndarray, np.ndarray]:
    """Columns and rows where a camera with this pose would see the rendered skyline."""
    azimuth = (pose.bearing + np.arange(-pose.fov, pose.fov, wb.AZIMUTH_STEP_DEG)) % 360.0
    elevation, _ = horizon.at(azimuth)
    u, v = wb.project(azimuth, elevation, WIDTH, HEIGHT, pose)
    keep = np.isfinite(u) & (u >= 0) & (u < WIDTH)
    order = np.argsort(u[keep])
    columns = np.arange(0, WIDTH, 4, dtype=float)
    rows = np.interp(columns, u[keep][order], v[keep][order])
    return columns, rows


RANGE = [
    (2500, 6000, 900, 900),
    (4500, 4200, 1200, 1200),
    (6500, 1500, 700, 700),
    (-3000, -5000, 600, 1500),
    (-6000, 2000, 400, 800),
]


class HorizonTest(unittest.TestCase):
    def test_single_hill_peaks_at_its_azimuth(self) -> None:
        dem = synthetic_dem([(3000, 3000, 800, 600)])
        horizon = wb.render_horizon(dem, 0.0, 0.0, GROUND_M + 3)
        peak = float(horizon.azimuth[int(np.argmax(horizon.elevation_deg))])
        self.assertAlmostEqual(peak, 45.0, delta=0.5)
        expected = math.degrees(math.atan2(800 - 3, math.hypot(3000, 3000)))
        self.assertAlmostEqual(float(horizon.elevation_deg.max()), expected, delta=0.3)

    def test_project_inverts_pixel_rays(self) -> None:
        pose = wb.Pose(bearing=310.0, fov=48.0, pitch=4.0, roll=2.5)
        columns = np.array([0.0, 500.0, 960.0, 1919.0])
        rows = np.array([100.0, 540.0, 800.0, 20.0])
        azimuth, elevation = wb.pixel_rays(columns, rows, WIDTH, HEIGHT, pose)
        u, v = wb.project(azimuth, elevation, WIDTH, HEIGHT, pose)
        np.testing.assert_allclose(u, columns, atol=1e-6)
        np.testing.assert_allclose(v, rows, atol=1e-6)


class FitTest(unittest.TestCase):
    def test_recovers_bearing_and_field_of_view(self) -> None:
        dem = synthetic_dem(RANGE)
        horizon = wb.render_horizon(dem, 0.0, 0.0, GROUND_M + 3)
        truth = wb.Pose(bearing=52.0, fov=56.0, pitch=2.0, roll=0.0)
        columns, rows = photo_skyline(horizon, truth)
        fit = wb.fit_camera(dem, 0.0, 0.0, GROUND_M, columns, rows, WIDTH, HEIGHT, heights=(3.0,))
        self.assertLess(float(wb.angular_gap(fit.pose.bearing, truth.bearing)), 0.5)
        self.assertAlmostEqual(fit.pose.fov, truth.fov, delta=1.0)
        self.assertLess(fit.cost_px, 2.0)
        self.assertGreater(fit.alternative_cost_px / fit.cost_px, wb.UNIQUE_RATIO)

    def test_featureless_skyline_is_not_unique(self) -> None:
        # A ring of equal hills looks the same at every bearing, so no bearing may be settled.
        ring = [
            (5000 * math.sin(math.radians(a)), 5000 * math.cos(math.radians(a)), 600, 900) for a in range(0, 360, 10)
        ]
        dem = synthetic_dem(ring)
        horizon = wb.render_horizon(dem, 0.0, 0.0, GROUND_M + 3)
        columns, rows = photo_skyline(horizon, wb.Pose(bearing=100.0, fov=50.0, pitch=1.0, roll=0.0))
        fit = wb.fit_camera(dem, 0.0, 0.0, GROUND_M, columns, rows, WIDTH, HEIGHT, heights=(3.0,))
        confidence, reason = wb.judge(fit, 1.0, 50.0, 0.0)
        self.assertEqual(confidence, "unsettled")
        self.assertIn("not unique", reason or "")


class JudgeTest(unittest.TestCase):
    def fit(self, cost: float, alternative: float) -> wb.Fit:
        horizon = wb.Horizon(np.zeros(1), np.zeros(1), np.zeros(1))
        return wb.Fit(wb.Pose(10.0, 50.0, 0.0, 0.0), 3.0, cost, alternative, horizon)

    def test_confidence_levels(self) -> None:
        self.assertEqual(wb.judge(self.fit(2.0, 10.0), 0.9, 5.0, 1.0), ("high", None))
        self.assertEqual(wb.judge(self.fit(2.0, 10.0), 0.9, 5.0, 4.0), ("medium", None))

    def test_unsettled_reasons(self) -> None:
        self.assertIn("skyline found", wb.judge(self.fit(2.0, 10.0), 0.1, 5.0, 1.0)[1] or "")
        self.assertIn("residual", wb.judge(self.fit(8.0, 40.0), 0.9, 5.0, 1.0)[1] or "")
        self.assertIn("not unique", wb.judge(self.fit(2.0, 3.0), 0.9, 5.0, 1.0)[1] or "")
        self.assertIn("moves", wb.judge(self.fit(2.0, 10.0), 0.9, 5.0, 9.0)[1] or "")


class SkylineTest(unittest.TestCase):
    def test_extracts_sky_edge_and_ignores_masked_caption(self) -> None:
        columns = np.arange(WIDTH)
        edge = 400 + 120 * np.sin(columns / 300.0)
        rows = np.arange(HEIGHT)[:, None]
        pixels = np.where(rows < edge[None, :], 1, 0)
        rgb = np.where(pixels[..., None] == 1, np.array([205, 215, 235]), np.array([95, 75, 55])).astype("uint8")
        # A bright caption band at the bottom, as the feratel frames have.
        rgb[int(0.93 * HEIGHT) :, :] = 230
        image = Image.fromarray(rgb)
        found_columns, found_rows = wb.extract_skyline(image, ((0.0, 0.925, 1.0, 1.0),))
        expected = np.interp(found_columns, columns, edge)
        valid = np.isfinite(found_rows)
        self.assertGreater(valid.mean(), 0.95)
        self.assertLess(float(np.max(np.abs(found_rows[valid] - expected[valid]))), 3 * WIDTH / wb.WORK_WIDTH)

    def test_frame_without_sky_has_no_skyline(self) -> None:
        image = Image.new("RGB", (WIDTH, HEIGHT), (95, 75, 55))
        image.paste((200, 200, 200), (0, 900, WIDTH, HEIGHT))
        _, rows = wb.extract_skyline(image, ())
        self.assertEqual(int(np.isfinite(rows).sum()), 0)


if __name__ == "__main__":
    unittest.main()
