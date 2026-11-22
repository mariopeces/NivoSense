import sys, json, geopandas as gpd, shapely
from pyproj import Geod
dl, pr = sys.argv[1], sys.argv[2]
r = gpd.read_file(f"{dl}/rediam_eennpp.gml")
print("REDIAM crs", r.crs, len(r)); print(r.columns.tolist())
sn = r[r["NOMBRE"].str.contains("Sierra Nevada", case=False)]
print(sn.drop(columns="geometry").to_string())
e = gpd.read_file(f"zip://{dl}/Enp2025_shp.zip!Enp2025_shp/Enp2025_p.shp")
print("ENP crs", e.crs)
esn = e[e["SITE_NAME"].str.contains("Sierra Nevada", case=False)]
print(esn.drop(columns="geometry").to_string())
U="EPSG:25830"
r=r.to_crs(U); e=e.to_crs(U)
pnat = r[(r.NOMBRE.str.upper()=="SIERRA NEVADA")&(r.FIGURA=="Parque Natural")].geometry.union_all()
pnac_r = r[(r.NOMBRE.str.upper()=="SIERRA NEVADA")&(r.FIGURA=="Parque Nacional")].geometry.union_all()
pnac_m = e[(e.SITE_NAME=="Sierra Nevada")&(e.ODESIGNATE=="Parque Nacional")].geometry.union_all()
for n,g in [("pnat",pnat),("pnac_rediam",pnac_r),("pnac_miteco",pnac_m)]:
    print(n, "valid", g.is_valid, shapely.is_valid_reason(g), "area km2 %.4f"%(g.area/1e6), "parts", len(shapely.get_parts(g)))
print("pnac miteco vs rediam symdiff km2 %.4f"%(pnac_m.symmetric_difference(pnac_r).area/1e6))
print("pnat AND pnac_m km2 %.4f"%(pnat.intersection(pnac_m).area/1e6))
en_r = r[(r.CODIGOESPA.astype(str)=="8372")].geometry.union_all()
zec_m = e[e.SITE_CODE_=="ES6140004"].geometry.union_all()
dom = shapely.union(shapely.make_valid(pnat), shapely.make_valid(pnac_m))
print("my domain km2 %.4f"%(dom.area/1e6))
for n,g in [("REDIAM Espacio Natural 8372",en_r),("MITECO ZEC ES6140004",zec_m)]:
    sd=dom.symmetric_difference(g).area
    print("domain vs",n,"area %.4f symdiff km2 %.5f (%.4f%%)"%(g.area/1e6, sd/1e6, 100*sd/g.area))
pnat_m = e[(e.SITE_NAME=="Sierra Nevada")&(e.ODESIGNATE=="Parque Natural")].geometry.union_all()
sd=pnat.symmetric_difference(pnat_m).area
print("pnat REDIAM vs MITECO ES610001 symdiff km2 %.5f (%.4f%%)"%(sd/1e6,100*sd/pnat.area))
# gaps between parks: holes in union
holes=[shapely.Polygon(i) for p in shapely.get_parts(dom) for i in p.interiors]
print("domain parts", len(shapely.get_parts(dom)), "holes", len(holes), "hole areas m2", sorted([round(h.area,1) for h in holes])[-10:])
# PR outputs
d = gpd.read_file(f"{pr}/data/domain.geojson").to_crs(U)
print(d.drop(columns="geometry").to_string())
for part, mine in [("domain",dom),("national_park",pnac_m),("natural_park",pnat)]:
    g = d[d.part==part].geometry.iloc[0]
    sd = g.symmetric_difference(mine).area
    print(part, "PR area %.4f mine %.4f symdiff km2 %.5f (%.4f%%) valid %s"%(g.area/1e6, mine.area/1e6, sd/1e6, 100*sd/mine.area, g.is_valid))
# ellipsoidal areas
geod=Geod(ellps="GRS80")
d4=d.to_crs(4326)
for _,row in d4.iterrows():
    print(row.part, "geodesic km2 %.3f"%(abs(geod.geometry_area_perimeter(row.geometry)[0])/1e6))
b = gpd.read_file(f"{pr}/data/basins.geojson")
print(b.drop(columns="geometry").to_string())
b=b.to_crs(U)
print("basins valid", b.is_valid.tolist())
bu=b.geometry.union_all()
print("basins union vs domain symdiff km2 %.5f"%(bu.symmetric_difference(d[d.part=='domain'].geometry.iloc[0]).area/1e6))
ov=0
for i in range(len(b)):
    for j in range(i+1,len(b)):
        ov+=b.geometry.iloc[i].intersection(b.geometry.iloc[j]).area
print("pairwise basin overlap m2 %.2f"%ov)
for _,row in b.iterrows():
    print(row.cod_uni, "geom area %.3f prop %.3f"%(row.geometry.area/1e6, row.domain_area_km2))
json.dump(json.load(open(f"{pr}/data/domain.geojson",encoding="utf-8"))["metadata"], sys.stdout, indent=1, ensure_ascii=False)
