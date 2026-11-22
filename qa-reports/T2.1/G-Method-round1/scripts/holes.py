import sys, geopandas as gpd, shapely
pr=sys.argv[1]
for f in ["domain","basins"]:
    g=gpd.read_file(f"{pr}/data/{f}.geojson").to_crs(25830)
    for _,row in g.iterrows():
        parts=shapely.get_parts(row.geometry)
        holes=[shapely.Polygon(i).area for p in parts for i in p.interiors]
        tiny=[p.area for p in parts if p.area<1e4]
        nverts=shapely.get_num_coordinates(row.geometry)
        print(f, row.get("part", row.get("cod_uni")), "parts",len(parts),"part areas km2",sorted(round(p.area/1e6,4) for p in parts)[:6], "holes",len(holes),"hole total m2 %.1f max %.1f"%(sum(holes), max(holes) if holes else 0), "verts", nverts)
