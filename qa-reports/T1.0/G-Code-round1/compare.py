import json, sys
fz = json.load(open(sys.argv[1], encoding="utf-8"))
rr = json.load(open(sys.argv[2], encoding="utf-8"))
keys = ["id","draw","date","orbit","x","y","stratum","elevation_band","cell_pixels","elevation_m","cos_incidence","cast_shadow","tree_fraction","in_strata","chip_scene_id"]
a = {f["properties"]["id"]: f for f in fz["features"]}
b = {f["properties"]["id"]: f for f in rr["features"]}
print("frozen", len(a), "rerun", len(b), "same ids", set(a) == set(b))
diff = {}
for i in set(a) & set(b):
    for k in keys:
        if a[i]["properties"][k] != b[i]["properties"][k]:
            diff.setdefault(k, []).append(i)
    if a[i]["geometry"] != b[i]["geometry"]:
        diff.setdefault("geometry", []).append(i)
print("field mismatches", {k: len(v) for k, v in diff.items()}, {k: sorted(v)[:3] for k, v in diff.items()})
for k in ["seed","points_per_stratum","stratum_pixels","dates","supplement","supplements","cells"]:
    print(k, "equal" if fz["metadata"].get(k) == rr["metadata"].get(k) else "DIFFERENT")
