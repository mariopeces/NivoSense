"""G-Method T1.3 round 2: render one date through the PR's own run.process() (head 25102f2),
bypassing only the `listed` filter, into a local catalogue; then check which overpass the RGB
came from against T1.1's stored record and SCL.

    python gmethod_render.py <s2_out> <domain> <date> <orbit> <outdir> [--also-other]

Checks written to <outdir>/<date>_<orbit>.json:
- L1C datatake of the published source_ids vs record["datatake"];
- Pearson r of the RGB green (10 m averaged to 20 m, TOA reflectance) against T1.1's stored
  L2A green, and, with --also-other, the same for the other datatake's L1C;
- cloud agreement: share of T1.1 SCL cloud pixels (8, 9, 10) that are bright in the RGB;
- stretch stats over the L2A snow stand-in mask (percentiles, 255 share) for regressions;
- a thumbnail.
"""

import hashlib
import json
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

from pipelines.catalog.storage import LocalStorage
from pipelines.rgb_l1c import qa, run
from pipelines.rgb_l1c.render import domain_mask, grid_10m, read_reflectance
from pipelines.rgb_l1c.source import AWS, COLLECTION, find_acquisition
from pipelines.s2.domain import convex_hull, load_domain
from pipelines.s2.stac import datatake_of, group_acquisitions, search_items

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
s2_out, domain_path, day_s, orbit, outdir = sys.argv[1:6]
also_other = "--also-other" in sys.argv
s2_out, outdir = Path(s2_out), Path(outdir)
outdir.mkdir(parents=True, exist_ok=True)
day = date.fromisoformat(day_s)
record = json.loads((s2_out / day_s / orbit / "record.json").read_text(encoding="utf-8"))
domain = load_domain(Path(domain_path))
grid = grid_10m(domain.grid)
hull = convex_hull(domain.geometries)
inside = domain_mask(domain.geometries, grid)

captured: dict = {}
real_render = run.render
real_read = run.read_reflectance


def capture_render(reflectance: dict, mask: np.ndarray) -> np.ndarray:
    captured["refl"] = {k: v.copy() for k, v in reflectance.items()}
    captured["rgb"] = real_render(reflectance, mask)
    return captured["rgb"]


run.render = capture_render  # type: ignore[assignment]
storage = LocalStorage(outdir / "catalog")
summary = run.process(record, domain, hull, inside, s2_out, storage, AWS)

out: dict = {
    "date": day_s,
    "orbit": orbit,
    "record_datatake": record["datatake"],
    "record_listed": record["listed"],
    "record_valid_fraction": record["domain_valid_fraction"],
    "record_scene_ids": record["scene_ids"],
    "record_alternatives": [a["datatake"] for a in record.get("alternatives", [])],
    "process_status": summary["status"],
    "process_timing": {k: summary.get(k) for k in ("search_s", "read_s", "publish_s", "total_s")},
}
l1c_items = [i for i in search_items(hull, day, day, collection=COLLECTION) if domain.touches(i["geometry"])]
by_id = {i["id"]: i for i in l1c_items}
out["l1c_datatakes_that_day"] = sorted({(i["properties"]["s2:datatake_id"]) for i in l1c_items})
if summary["status"] == "published":
    out["published_source_ids"] = summary["source_ids"]
    out["published_source_datatakes"] = sorted({datatake_of(by_id[s]) for s in summary["source_ids"]})
    out["rgb_datatake_matches_record"] = out["published_source_datatakes"] == [record["datatake"]]
    out["qa"] = summary["qa"]

    l2a, scl = qa.read_l2a(s2_out / day_s / orbit)
    rgb = captured["rgb"]
    refl = captured["refl"]
    out["rgb_pixel_sha256"] = hashlib.sha256(rgb.tobytes()).hexdigest()

    def green20(reflectance: dict) -> np.ndarray:
        g = reflectance["green"]
        return np.nanmean(qa.blocks(g, 2), axis=2)

    def corr(a: np.ndarray, b: np.ndarray) -> tuple[float, int]:
        ok = np.isfinite(a) & np.isfinite(b) & domain.mask
        return float(np.corrcoef(a[ok], b[ok])[0, 1]), int(ok.sum())

    with np.errstate(all="ignore"):
        r_kept, n = corr(green20(refl), l2a["green"])
    out["green_r_vs_l2a"] = {"record_datatake_l1c": round(r_kept, 4), "pixels_20m": n}

    # Clouds in T1.1's SCL (8, 9, 10) should be bright in the RGB of the same overpass.
    cloud = np.isin(scl, (8, 9, 10)) & domain.mask
    bright20 = np.nanmean(qa.blocks(refl["green"], 2), axis=2) > 0.25
    out["scl_cloud_pixels_20m"] = int(cloud.sum())
    if cloud.any():
        out["scl_cloud_bright_in_rgb"] = round(float(bright20[cloud].mean()), 4)
        clear = np.isin(scl, (4, 5)) & domain.mask
        out["scl_veg_bare_bright_in_rgb"] = round(float(bright20[clear].mean()), 4) if clear.any() else None

    if also_other:
        others = [a for a in group_acquisitions(l1c_items) if a.day == day and a.orbit == orbit and a.datatake != record["datatake"]]
        for other in others:
            other_refl = real_read(other, grid, AWS)
            with np.errstate(all="ignore"):
                r_other, _ = corr(green20(other_refl), l2a["green"])
                b_other = np.nanmean(qa.blocks(other_refl["green"], 2), axis=2) > 0.25
            out["green_r_vs_l2a"][other.datatake] = round(r_other, 4)
            if cloud.any():
                out.setdefault("scl_cloud_bright_in_other_rgb", {})[other.datatake] = round(float(b_other[cloud].mean()), 4)

    snow20 = qa.snow_mask(l2a, scl) & domain.mask
    valid = (rgb > 0).all(axis=0)
    snow10 = np.repeat(np.repeat(snow20, 2, 0), 2, 1) & valid
    out["snow_px_10m"] = int(snow10.sum())
    for i, band in enumerate(("red", "green", "blue")):
        stats: dict = {"all8_p": {p: int(np.percentile(rgb[i][valid], p)) for p in (1, 5, 50, 95)}}
        if snow10.any():
            s8 = rgb[i][snow10]
            stats["snow8_p"] = {p: int(np.percentile(s8, p)) for p in (1, 5, 50, 95, 99)}
            stats["snow_sat_255"] = round(float((s8 == 255).mean()), 5)
        out[band] = stats
    thumb = np.moveaxis(rgb[:, ::8, ::8], 0, 2)
    Image.fromarray(thumb).save(outdir / f"{day_s}_{orbit}.png")

(outdir / f"{day_s}_{orbit}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out, indent=1))
