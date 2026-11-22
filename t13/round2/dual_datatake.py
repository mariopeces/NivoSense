"""End-to-end check on a dual-datatake date: the RGB pipeline picks the L1C of the datatake the
L2A record kept, and that RGB agrees with the record's bands better than the other overpass.

    dual_datatake.py <s2 out> <domain geojson> <date> <orbit>
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

from pipelines.rgb_l1c import qa
from pipelines.rgb_l1c.render import domain_mask, grid_10m, read_reflectance, render
from pipelines.rgb_l1c.source import AWS, COLLECTION, find_acquisition
from pipelines.s2.domain import convex_hull, load_domain
from pipelines.s2.stac import group_acquisitions, search_items

s2_out, domain_path, day, orbit = Path(sys.argv[1]), Path(sys.argv[2]), date.fromisoformat(sys.argv[3]), sys.argv[4]
record = json.loads((s2_out / day.isoformat() / orbit / "record.json").read_text())
domain = load_domain(domain_path)
hull = convex_hull(domain.geometries)
grid = grid_10m(domain.grid)
inside = domain_mask(domain.geometries, grid)
l2a, scl = qa.read_l2a(s2_out / day.isoformat() / orbit)

chosen = find_acquisition(hull, day, record["datatake"], domain.touches)
items = [i for i in search_items(hull, day, day, collection=COLLECTION) if domain.touches(i["geometry"])]
all_l1c = [a for a in group_acquisitions(items) if a.orbit == orbit]
out = {
    "date": day.isoformat(),
    "orbit": orbit,
    "record_datatake": record["datatake"],
    "record_scene_ids": record["scene_ids"],
    "record_valid_fraction": record["domain_valid_fraction"],
    "alternatives": record["alternatives"],
    "pipeline_l1c_datatake": chosen.datatake if chosen else None,
    "pipeline_l1c_scene_ids": list(chosen.scene_ids) if chosen else None,
    "per_l1c_datatake": [],
}
green_l2a = l2a["green"]
for acquisition in all_l1c:
    rgb = render(read_reflectance(acquisition, grid, AWS), inside)
    green = qa.blocks(rgb[1].astype("float32"), 2).mean(axis=2)
    valid = qa.blocks((rgb > 0).all(axis=0), 2).all(axis=2) & ~np.isnan(green_l2a) & domain.mask
    r = float(np.corrcoef(green[valid], green_l2a[valid])[0, 1])
    out["per_l1c_datatake"].append(
        {"datatake": acquisition.datatake, "scene_ids": list(acquisition.scene_ids), "pearson_r_green_vs_record": round(r, 4)}
    )
print(json.dumps(out, indent=2))
