import sys, json, geopandas as gpd, shapely
pr, old, dl = sys.argv[1:4]
src = json.load(open(f"{pr}/data/sources/miteco_subcuencas_rios_completos_sierra_nevada.geojson", encoding="utf-8"))
print("source metadata:", json.dumps(src["metadata"], ensure_ascii=False)[:900])
s = gpd.read_file(f"{pr}/data/sources/miteco_subcuencas_rios_completos_sierra_nevada.geojson").to_crs(25830)
print(s.drop(columns="geometry").to_string()); print("valid", s.is_valid.tolist())
o = gpd.read_file(old); print("OLD:", o.drop(columns="geometry").to_string()); o=o.to_crs(25830)
b = gpd.read_file(f"{pr}/data/basins.geojson").to_crs(25830)
e = gpd.read_file(f"zip://{dl}/Enp2025_shp.zip!Enp2025_shp/Enp2025_p.shp").to_crs(25830)
np_ = e[(e.SITE_NAME=="Sierra Nevada")&(e.ODESIGNATE=="Parque Nacional")].geometry.union_all()
for _,r in o.iterrows():
    n = b[b.cod_uni==int(r.cod_uni)]
    if n.empty: print("old", r.cod_uni, "missing in new"); continue
    g = n.geometry.iloc[0].intersection(np_)
    sd = g.symmetric_difference(r.geometry).area
    print("cod", r.cod_uni, "new_x_NP %.3f old %.3f symdiff km2 %.4f (%.3f%%)"%(g.area/1e6, r.geometry.area/1e6, sd/1e6, 100*sd/r.geometry.area))
