import unittest
from importlib.metadata import entry_points, version


class PinnedToolchainTests(unittest.TestCase):
    """The lockfile pins GDAL through the rasterio wheel; these fail if an install drifts from it."""

    def test_gdal_is_the_build_bundled_with_the_pinned_rasterio(self) -> None:
        import rasterio

        self.assertEqual(version("rasterio"), "1.4.4")
        self.assertEqual(rasterio.__gdal_version__, "3.10.3")

    def test_pmtiles_builder_is_registered_with_the_rasterio_cli(self) -> None:
        plugins = {entry.name for entry in entry_points(group="rasterio.rio_plugins")}
        self.assertIn("pmtiles", plugins)
        self.assertEqual(version("rio-pmtiles"), "1.2.2")


if __name__ == "__main__":
    unittest.main()
