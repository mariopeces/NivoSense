import json, subprocess, sys
import geopandas as gpd
from shapely.geometry import shape
def load(rev, path):
    return json.loads(subprocess.check_output(["git", "show", f"{rev}:{path}"]))
for rev in sys.argv[1:]:
    d = load(rev, "data/domain.geojson"); b = load(rev, "data/basins.geojson")
    f = gpd.GeoDataFrame([{**x["properties"], "geometry": shape(x["geometry"])} for x in d["features"]], crs=4326).to_crs(25830)
    print(rev, {r["part"]: round(r.geometry.area/1e6, 5) for _, r in f.iterrows()}, "metadata:", d["metadata"]["areas"])
    g = gpd.GeoDataFrame([{**x["properties"], "geometry": shape(x["geometry"])} for x in b["features"]], crs=4326).to_crs(25830)
    for _, r in g.iterrows():
        print("  ", r["cod_uni"], r["nom_rio_1"], "geom", round(r.geometry.area/1e6, 5), "prop", r["domain_area_km2"], "src", r["source_area_km2"], "parts", len(r.geometry.geoms) if r.geometry.geom_type=="MultiPolygon" else 1)
    print("   basin sum geom", round(g.geometry.area.sum()/1e6,5), "union", round(g.union_all().area/1e6,5))
