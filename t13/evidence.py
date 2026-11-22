"""Evidence for T1.3, computed from the pipelines.s2 records and the local catalogue the run wrote.

    python evidence.py <s2 out> <catalog root> <run log> <out dir>

Writes coverage.md (every listed date vs a published rgb entry), qa.md (snow saturation and
chip shifts from each entry), timing.md (per date, from the run log), mask_offsets.md (snow
stand-in mask vs a bright-RGB mask at 10 m offsets) and thumbnails (whole domain, and the
crest Veleta-Mulhacen at full resolution).
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import transform
from rasterio.windows import from_bounds

from pipelines.rgb_l1c import qa

s2_out, root, log_path, out = (Path(arg) for arg in sys.argv[1:5])
out.mkdir(parents=True, exist_ok=True)
entries = {
    json.loads(p.read_text())["date"]: json.loads(p.read_text())
    for p in sorted((root / "catalog/entries/rgb").glob("*.json"))
}
records = [json.loads(p.read_text()) for p in sorted(s2_out.glob("*/*/record.json"))]

# Coverage: every listed date has an entry or a logged missing L1C.
log_text = log_path.read_text()
missing_logged = set(re.findall(r"(\d{4}-\d{2}-\d{2}) R\d{3}: no L1C granule", log_text))
listed = sorted({r["date"] for r in records if r["listed"]})
with open(out / "coverage.md", "w") as f:
    f.write("| date | orbits (listed) | valid fraction | rgb entry | L1C scenes |\n|---|---|---|---|---|\n")
    for day in listed:
        rs = [r for r in records if r["date"] == day and r["listed"]]
        e = entries.get(day)
        state = e["cog"] if e else ("L1C missing (logged)" if day in missing_logged else "**MISSING**")
        f.write(f"| {day} | {','.join(r['orbit'] for r in rs)} | "
                f"{max(r['domain_valid_fraction'] for r in rs):.4f} | {state} | "
                f"{', '.join(e['source_ids']) if e else '-'} |\n")
    unlisted = sorted({r["date"] for r in records} - set(listed))
    extra = sorted(set(entries) - set(listed))
    f.write(f"\nListed dates: {len(listed)}; rgb entries: {len(entries)}; L1C missing logged: "
            f"{sorted(missing_logged) or 'none'}; entries for unlisted dates: {extra or 'none'}; "
            f"unlisted acquisition dates (no rgb by design): {', '.join(unlisted)}\n")

# QA scores from the entries.
with open(out / "qa.md", "w") as f:
    f.write("| date | snow px 10 m | saturated red / green / blue / all | L2A green shift median / p90 / max (m), "
            "share < 20 m, chips | snow mask shift median / p90 / max (m), share < 20 m, chips | flags |\n")
    f.write("|---|---|---|---|---|---|\n")
    for day, e in sorted(entries.items()):
        s = e["qa"]["scores"]
        sat = " / ".join(f"{100 * s[k]:.3f}%" if k in s else "n/a" for k in
                         ("snow_saturated_red", "snow_saturated_green", "snow_saturated_blue", "snow_saturated_all"))

        def shift(n: str) -> str:
            if f"shift_{n}_median_m" not in s:
                return f"no chip ({int(s.get(f'shift_{n}_chips', 0))})"
            return (f"{s[f'shift_{n}_median_m']} / {s.get(f'shift_{n}_p90_m')} / {s[f'shift_{n}_max_m']}, "
                    f"{100 * s.get(f'shift_{n}_within_20m', float('nan')):.1f}%, {int(s[f'shift_{n}_chips'])}")

        f.write(f"| {day} | {int(s['snow_pixels_10m'])} | {sat} | {shift('l2a_green')} | {shift('snow_mask')} | "
                f"{','.join(e['qa']['flags']) or '-'} |\n")

# Timing per date from the run log.
with open(out / "timing.md", "w") as f:
    f.write("| date | search s | read JP2 s | publish (COG + PMTiles) s | total s |\n|---|---|---|---|---|\n")
    for line in log_text.splitlines():
        if " INFO {" in line:
            r = json.loads(line.split(" INFO ", 1)[1])
            if r["status"] == "published":
                f.write(f"| {r['date']} | {r['search_s']} | {r['read_s']} | {r['publish_s']} | {r['total_s']} |\n")

# Mask offsets: agreement of the 20 m snow stand-in (upsampled to 10 m) with a bright-RGB mask
# (mean DN >= 140, i.e. about 0.4 reflectance through the stretch) at 10 m offsets -3..3.
OFFSETS = range(-3, 4)
with open(out / "mask_offsets.md", "w") as f:
    f.write("Intersection over union of the L2A snow stand-in mask (NDSI > 0.4, red > 0.2, clear SCL; 20 m, "
            "each pixel repeated 2x2) and the RGB bright mask (mean DN >= 140) with the RGB shifted by (rows, cols) "
            "10 m pixels. Aligned data peak at (0, 0).\n\n")
    f.write("| date | snow px 20 m | IoU at (0,0) | best offset (rows, cols) | best IoU | IoU at +-1 px (10 m) |\n")
    f.write("|---|---|---|---|---|---|\n")
    for day, e in sorted(entries.items()):
        rec = max((r for r in records if r["date"] == day and r["listed"]), key=lambda r: r["domain_valid_fraction"])
        l2a, scl = qa.read_l2a(s2_out / day / rec["orbit"])
        snow20 = qa.snow_mask(l2a, scl)
        if snow20.sum() < 1000:
            f.write(f"| {day} | {int(snow20.sum())} | too little snow | | | |\n")
            continue
        with rasterio.open(root / e["cog"]) as src:
            rgb = src.read()
        valid = (rgb > 0).all(axis=0)
        bright = (rgb.astype("float32").mean(axis=0) >= 140) & valid
        snow = np.repeat(np.repeat(snow20, 2, axis=0), 2, axis=1) & valid
        m = 3
        core = (slice(m, -m), slice(m, -m))
        ious = {}
        for dy in OFFSETS:
            for dx in OFFSETS:
                moved = np.roll(bright, (dy, dx), axis=(0, 1))[core]
                ref = snow[core]
                ious[(dy, dx)] = float((moved & ref).sum() / max((moved | ref).sum(), 1))
        best = max(ious, key=ious.get)
        neighbours = [ious[k] for k in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        f.write(f"| {day} | {int(snow20.sum())} | {ious[(0, 0)]:.4f} | {best} | {ious[best]:.4f} | "
                f"{min(neighbours):.4f} to {max(neighbours):.4f} |\n")

# Thumbnails.
for day, e in sorted(entries.items()):
    with rasterio.open(root / e["cog"]) as src:
        width = 1600
        height = int(src.height * width / src.width)
        rgb = src.read(out_shape=(3, height, width), resampling=Resampling.average)
        Image.fromarray(np.moveaxis(rgb, 0, -1)).save(out / f"rgb_{day}.png")
        xs, ys = transform("EPSG:4326", src.crs, [-3.42, -3.30], [37.01, 37.07])
        crop = src.read(window=from_bounds(xs[0], ys[0], xs[1], ys[1], src.transform))
        Image.fromarray(np.moveaxis(crop, 0, -1)).save(out / f"crest_{day}.png")
for name in ("coverage", "timing", "qa", "mask_offsets"):
    print(f"## {name}\n" + (out / f"{name}.md").read_text())
