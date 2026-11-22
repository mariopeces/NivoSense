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


PANO_W, PANO_H = 2400, 800


def pano_skyline(horizon: wb.Horizon, pose: wb.PanoPose) -> tuple[np.ndarray, np.ndarray]:
    columns = np.arange(0.0, PANO_W, 4.0)
    azimuth = pose.azimuth(columns, PANO_W)
    elevation, _ = horizon.at(azimuth)
    return columns, pose.row(azimuth, elevation, PANO_W)


class PanoramaTest(unittest.TestCase):
    def test_column_inverts_azimuth(self) -> None:
        pose = wb.PanoPose(centre_az=350.0, span=211.0, y0=400.0, vscale=1.0, tilt=1.0, tilt_phase=30.0)
        columns = np.array([0.0, 700.0, 1199.5, 2399.0])
        np.testing.assert_allclose(pose.column(pose.azimuth(columns, PANO_W), PANO_W), columns, atol=1e-6)

    def test_recovers_centre_azimuth(self) -> None:
        dem = synthetic_dem(RANGE)
        horizon = wb.render_horizon(dem, 0.0, 0.0, GROUND_M + 3)
        truth = wb.PanoPose(centre_az=75.0, span=212.0, y0=420.0, vscale=1.0, tilt=0.0, tilt_phase=0.0)
        columns, rows = pano_skyline(horizon, truth)
        pose, cost, alternative = wb.fit_panorama_at(horizon, columns, rows, PANO_W, 211.0)
        self.assertLess(float(wb.angular_gap(pose.centre_az, truth.centre_az)), 0.3)
        self.assertAlmostEqual(pose.span, truth.span, delta=1.0)
        self.assertLess(cost, 1.0)
        self.assertGreater(alternative / cost, wb.UNIQUE_RATIO)

    def test_span_is_held_near_the_published_value(self) -> None:
        pose = wb.PanoPose(centre_az=0.0, span=260.0, y0=400.0, vscale=1.0, tilt=0.0, tilt_phase=0.0)
        horizon = wb.Horizon(np.arange(0.0, 360.0, wb.AZIMUTH_STEP_DEG), np.zeros(7200), np.ones(7200))
        cost = wb.panorama_cost(horizon, np.array([10.0]), np.array([400.0]), PANO_W, pose, 211.0)
        self.assertEqual(cost, math.inf)

    def test_locates_a_view_cut_from_the_panorama(self) -> None:
        rng = np.random.default_rng(3)
        # Smooth random texture, so edges exist at every scale the matcher uses.
        texture = rng.random((PANO_H // 8, PANO_W // 8))
        pano_lum = np.asarray(
            Image.fromarray((texture * 255).astype("uint8")).resize((PANO_W, PANO_H), Image.Resampling.BICUBIC),
            dtype=float,
        )
        panorama = Image.fromarray(pano_lum.astype("uint8")).convert("RGB")
        pano_pose = wb.PanoPose(centre_az=200.0, span=210.0, y0=PANO_H / 2, vscale=1.0, tilt=0.0, tilt_phase=0.0)
        truth = wb.Pose(bearing=160.0, fov=48.0, pitch=2.0, roll=0.0)
        view_w, view_h = 960, 540
        uu, vv = np.meshgrid(np.arange(view_w, dtype=float), np.arange(view_h, dtype=float))
        azimuth, elevation = wb.pixel_rays(uu.ravel(), vv.ravel(), view_w, view_h, truth)
        cols = np.clip(np.round(pano_pose.column(azimuth, PANO_W)).astype(int), 0, PANO_W - 1)
        rows = np.clip(np.round(pano_pose.row(azimuth, elevation, PANO_W)).astype(int), 0, PANO_H - 1)
        view = Image.fromarray(pano_lum[rows, cols].reshape(view_h, view_w).astype("uint8")).convert("RGB")
        match = wb.locate_view(view, (), panorama, pano_pose, fov_range=(36.0, 60.0))
        self.assertLess(float(wb.angular_gap(match.bearing, truth.bearing)), 0.5)
        self.assertAlmostEqual(match.fov, truth.fov, delta=2.0)
        self.assertGreater(match.score - match.alternative_score, wb.MATCH_MARGIN)


class JudgeViewTest(unittest.TestCase):
    match = wb.ViewMatch(bearing=120.0, fov=40.0, pitch=0.0, score=0.9, alternative_score=0.5, pano_column=0.0)

    def verdict(self, **changes: float) -> str | None:
        values = {"fraction": 0.9, "cost": 5.0, "tolerance": 20.0, "bearing": 121.0, "fov": 41.0, **changes}
        pose = wb.Pose(values["bearing"], values["fov"], 0.0, 0.0)
        return wb.judge_view(values["fraction"], self.match, values["cost"], values["tolerance"], pose)

    def test_settles_when_the_skyline_confirms_the_match(self) -> None:
        self.assertIsNone(self.verdict())

    def test_each_disagreement_unsettles(self) -> None:
        self.assertIn("nothing to confirm", self.verdict(fraction=0.1) or "")
        self.assertIn("residual", self.verdict(cost=25.0) or "")
        self.assertIn("moves the matched bearing", self.verdict(bearing=123.0) or "")
        self.assertIn("edge", self.verdict(fov=20.5) or "")
        self.assertIn("field of view disagrees", self.verdict(fov=60.0) or "")

    def test_ambiguous_match_unsettles(self) -> None:
        match = wb.ViewMatch(bearing=120.0, fov=40.0, pitch=0.0, score=0.9, alternative_score=0.85, pano_column=0.0)
        self.assertIn("not unique", wb.judge_view(0.9, match, 5.0, 20.0, wb.Pose(120.0, 40.0, 0.0, 0.0)) or "")


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
