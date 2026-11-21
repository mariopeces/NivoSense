import json
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box, shape

from pipelines.domain import build
from pipelines.region import load_region

REPO = Path(__file__).resolve().parents[2]
KM = 1000.0


def subbasin_frame(rows: list[dict]) -> gpd.GeoDataFrame:
    for row in rows:
        row.setdefault("COD_MAR", "M")
        row.setdefault("Cuen_Tipo", None)
        row["Shape_Area"] = row["geometry"].area
    return gpd.GeoDataFrame(rows, crs=build.AREA_CRS, geometry="geometry")


def parks(national, natural, official_national_ha=None, official_natural_ha=None) -> build.Parks:
    return build.Parks(
        national=national,
        natural=natural,
        national_rediam=national,
        national_official_ha=official_national_ha or national.area / 1e4,
        natural_official_ha=official_natural_ha or natural.area / 1e4,
        national_attrs={},
        natural_attrs={},
    )


class OutermostRiversTest(unittest.TestCase):
    def test_keeps_codes_without_a_prefix_among_candidates(self):
        frame = gpd.GeoDataFrame(
            {"pfafrio": ["10094", "100942", "1009484", "200134", "2001342", "200138"]}
        )
        kept = build.outermost_rivers(frame)["pfafrio"].tolist()
        self.assertEqual(kept, ["10094", "200134", "200138"])

    def test_tributary_is_kept_when_its_parent_does_not_touch(self):
        frame = gpd.GeoDataFrame({"pfafrio": ["100942", "100948"]})
        self.assertEqual(build.outermost_rivers(frame)["pfafrio"].tolist(), ["100942", "100948"])


class IntersectSubbasinsTest(unittest.TestCase):
    def setUp(self):
        # Two rivers share the domain; the first has a nested tributary, a third river is outside.
        self.domain = box(0, 0, 10 * KM, 10 * KM)
        self.subbasins = subbasin_frame(
            [
                {
                    "cod_uni": 1,
                    "pfafrio": "10094",
                    "nom_rio_1": "RIO A",
                    "geometry": box(-20 * KM, 0, 4 * KM, 10 * KM),
                },
                {
                    "cod_uni": 2,
                    "pfafrio": "100942",
                    "nom_rio_1": "RIO A1",
                    "geometry": box(0, 0, 4 * KM, 5 * KM),
                },
                {
                    "cod_uni": 3,
                    "pfafrio": "200134",
                    "nom_rio_1": "RIO B",
                    "geometry": box(4 * KM, 0, 30 * KM, 10 * KM),
                },
                {
                    "cod_uni": 4,
                    "pfafrio": "200138",
                    "nom_rio_1": "RIO C",
                    "geometry": box(50 * KM, 0, 60 * KM, 10 * KM),
                },
            ]
        )

    def test_partitions_the_domain_with_outermost_rivers(self):
        result = build.intersect_subbasins(self.subbasins, self.domain)
        self.assertEqual(result["cod_uni"].tolist(), [1, 3])
        self.assertEqual(result["domain_area_km2"].tolist(), [40.0, 60.0])
        self.assertAlmostEqual(result["domain_area_km2"].sum(), self.domain.area / 1e6)

    def test_keeps_codes_and_source_area(self):
        result = build.intersect_subbasins(self.subbasins, self.domain)
        first = result.iloc[0]
        self.assertEqual(first["pfafrio"], "10094")
        self.assertEqual(first["nom_rio_1"], "RIO A")
        self.assertEqual(first["COD_MAR"], "M")
        self.assertEqual(first["source_area_km2"], 240.0)

    def test_clipped_source_rebuilds_the_same_basins(self):
        clipped = build.clip_source(self.subbasins, self.domain)
        self.assertEqual(clipped["cod_uni"].tolist(), [1, 3])
        again = build.intersect_subbasins(clipped, self.domain)
        original = build.intersect_subbasins(self.subbasins, self.domain)
        self.assertEqual(
            again.drop(columns="geometry").to_dict("records"),
            original.drop(columns="geometry").to_dict("records"),
        )


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.national = box(0, 0, 5 * KM, 10 * KM)
        self.natural = box(5 * KM, 0, 10 * KM, 10 * KM)
        self.domain = build.build_domain(self.national, self.natural)
        self.basins = gpd.GeoDataFrame({"domain_area_km2": [100.0]})

    def test_union_of_the_two_parks(self):
        self.assertAlmostEqual(self.domain.area, 100 * KM * KM)

    def test_matching_areas_pass(self):
        report = build.check(parks(self.national, self.natural), self.domain, self.basins)
        self.assertEqual(report["domain_km2"], 100.0)
        self.assertEqual(report["parks_overlap_km2"], 0.0)

    def test_park_off_by_more_than_half_a_percent_fails(self):
        wrong = parks(self.national, self.natural, official_national_ha=5000 * 1.01)
        with self.assertRaisesRegex(ValueError, "national park area off"):
            build.check(wrong, self.domain, self.basins)

    def test_subbasins_not_covering_the_domain_fail(self):
        partial = gpd.GeoDataFrame({"domain_area_km2": [90.0]})
        with self.assertRaisesRegex(ValueError, "sub-basin cover"):
            build.check(parks(self.national, self.natural), self.domain, partial)


class OutputTest(unittest.TestCase):
    def test_feature_collection_is_wgs84_with_rounded_coordinates(self):
        frame = gpd.GeoDataFrame(
            {"id": ["x"]}, geometry=[box(450000, 4100000, 451000, 4101000)], crs=build.AREA_CRS
        )
        collection = build.feature_collection(frame, "test", {"source": "unit"})
        self.assertEqual(collection["metadata"], {"source": "unit"})
        ring = collection["features"][0]["geometry"]["coordinates"][0]
        for longitude, latitude in ring:
            self.assertTrue(-4 < longitude < -3 and 37 < latitude < 38)
            self.assertEqual(round(longitude, build.COORDINATE_DECIMALS), longitude)

    def test_write_json_writes_identical_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / "data" / "a.geojson", Path(tmp) / "public" / "a.geojson"]
            build.write_json({"type": "FeatureCollection", "features": []}, paths)
            self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
            self.assertNotIn(b"\r\n", paths[0].read_bytes())

    def test_outward_bbox_contains_the_geometry(self):
        geometry = box(450000, 4100000, 460000, 4110000)
        west, south, east, north = build.outward_bbox(geometry)
        exact = gpd.GeoSeries([geometry], crs=build.AREA_CRS).to_crs(build.OUTPUT_CRS).total_bounds
        self.assertTrue(west <= exact[0] and south <= exact[1])
        self.assertTrue(east >= exact[2] and north >= exact[3])

    def test_update_region_keeps_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "region.json"
            path.write_text(
                json.dumps({"id": "r", "name": "R", "basins": "b.geojson", "snow_model": {"x": 1}}),
                encoding="utf-8",
            )
            build.update_region(path, [-3.6, 36.9, -2.6, 37.3])
            region = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(region["bbox"], [-3.6, 36.9, -2.6, 37.3])
            self.assertEqual(region["domain"], "data/domain.geojson")
            self.assertEqual(region["snow_model"], {"x": 1})


class LoadRegionTest(unittest.TestCase):
    def test_bbox_from_the_region_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "region.json"
            path.write_text(
                json.dumps(
                    {
                        "id": "r",
                        "name": "R",
                        "basins": "missing.geojson",
                        "bbox": [-3.6, 36.9, -2.6, 37.3],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_region(path).bbox, (-3.6, 36.9, -2.6, 37.3))


class CommittedOutputsTest(unittest.TestCase):
    """The committed files are the ones the script writes, with the card's guarantees."""

    def load(self, name: str) -> dict:
        return json.loads((REPO / "data" / name).read_text(encoding="utf-8"))

    def test_frontend_copies_are_identical(self):
        for name in ("basins.geojson", "domain.geojson"):
            self.assertEqual(
                (REPO / "data" / name).read_bytes(),
                (REPO / "frontend" / "public" / "data" / name).read_bytes(),
            )

    def test_every_subbasin_carries_codes_and_both_areas(self):
        for feature in self.load("basins.geojson")["features"]:
            properties = feature["properties"]
            for key in ("cod_uni", "pfafrio", "nom_rio_1", "source_area_km2", "domain_area_km2"):
                self.assertIn(key, properties)
            self.assertLessEqual(properties["domain_area_km2"], properties["source_area_km2"])

    def test_domain_parts_match_the_official_surfaces(self):
        collection = self.load("domain.geojson")
        areas = collection["metadata"]["areas"]
        official = {
            "national_park": areas["national_park_official_km2"],
            "natural_park": areas["natural_park_official_km2"],
            "domain": areas["national_park_official_km2"] + areas["natural_park_official_km2"],
        }
        frame = gpd.GeoDataFrame(
            [
                {"part": f["properties"]["part"], "geometry": shape(f["geometry"])}
                for f in collection["features"]
            ],
            crs=build.OUTPUT_CRS,
        ).to_crs(build.AREA_CRS)
        for _, row in frame.iterrows():
            measured = row.geometry.area / 1e6
            self.assertLess(build.area_error(measured, official[row["part"]]), build.MAX_AREA_ERROR)

    def test_subbasins_cover_the_domain(self):
        total = sum(
            f["properties"]["domain_area_km2"] for f in self.load("basins.geojson")["features"]
        )
        domain = self.load("domain.geojson")["metadata"]["areas"]["domain_km2"]
        self.assertLess(build.area_error(total, domain), build.MAX_AREA_ERROR)

    def test_region_bbox_contains_the_domain(self):
        region = load_region(REPO / "regions" / "sierra-nevada.json")
        domain = next(
            shape(f["geometry"])
            for f in self.load("domain.geojson")["features"]
            if f["properties"]["part"] == "domain"
        )
        west, south, east, north = domain.bounds
        self.assertTrue(region.bbox[0] <= west and region.bbox[1] <= south)
        self.assertTrue(region.bbox[2] >= east and region.bbox[3] >= north)


if __name__ == "__main__":
    unittest.main()
