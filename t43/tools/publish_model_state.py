"""T4.3 evidence: publish the real snow model state through publish() into a local catalogue, then check
every pixel of the display raster and of the PMTiles tiles against the legend classes in ramps.json.

Input: snow_state_latest.tif from the live site (pipelines/snow_model, run of 2026-11-20; bands SWE mm, depth
m, spread). Output: <root>/staging/catalog/... (LocalStorage) and a JSON report on stdout.

Usage: python publish_model_state.py <snow_state_latest.tif> <date> <root>
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

from pipelines.catalog.index import rebuild_index
from pipelines.catalog.publish import publish
from pipelines.catalog.storage import LocalStorage
from pipelines.ramps import colour_values, ramps

NODATA = -9999.0


def write(path: Path, profile: dict, bands: list[np.ndarray], dtype: str, nodata: float | None) -> None:
    p = {**profile, "count": len(bands), "dtype": dtype, "nodata": nodata, "compress": "deflate"}
    p.pop("predictor", None)
    with rasterio.open(path, "w", **p) as out:
        for i, band in enumerate(bands, start=1):
            out.write(band.astype(dtype), i)


def legend_colours(ramp_id: str) -> set[tuple[int, int, int, int]]:
    """The RGBA of every coloured class, computed here from ramps.json without pipelines.ramps."""
    out = set()
    for cls in ramps()[ramp_id]["classes"]:
        if cls["color"]:
            n = int(cls["color"][1:], 16)
            out.add((n >> 16, (n >> 8) & 255, n & 255, round(cls["alpha"] * 255)))
    return out


def expected_rgba(values: np.ndarray, ramp_id: str) -> np.ndarray:
    """Independent class lookup (searchsorted on the bounds) to cross-check colour_values()."""
    classes = ramps()[ramp_id]["classes"]
    mins = np.array([c["min"] for c in classes], dtype=float)
    out = np.zeros((*values.shape, 4), dtype="uint8")
    idx = np.searchsorted(mins, values, side="right") - 1
    for i, cls in enumerate(classes):
        sel = np.isfinite(values) & (idx == i)
        if cls["max"] is not None:
            sel &= values < cls["max"]
        if cls["color"]:
            n = int(cls["color"][1:], 16)
            out[sel] = (n >> 16, (n >> 8) & 255, n & 255, round(cls["alpha"] * 255))
    return out


def tile_check(pmtiles: Path, ramp_id: str) -> dict:
    """Decode every tile of the archive and count opaque pixels whose RGBA is a legend class colour."""
    allowed = legend_colours(ramp_id)
    script = (
        "import sys, json, base64\n"
        "from pmtiles.reader import Reader, MmapSource, all_tiles\n"
        "with open(sys.argv[1], 'rb') as f:\n"
        "    r = Reader(MmapSource(f))\n"
        "    for (z, x, y), data in all_tiles(r.get_bytes):\n"
        "        print(json.dumps([z, x, y, base64.b64encode(data).decode()]))\n"
    )
    proc = subprocess.run([sys.executable, "-c", script, str(pmtiles)], capture_output=True, text=True, check=True)
    import base64

    per_zoom: dict[int, Counter] = {}
    offenders: Counter = Counter()
    for line in proc.stdout.splitlines():
        z, _x, _y, data = json.loads(line)
        rgba = np.asarray(Image.open(io.BytesIO(base64.b64decode(data))).convert("RGBA")).reshape(-1, 4)
        opaque = rgba[rgba[:, 3] > 0]
        match = np.array([tuple(p) in allowed for p in map(tuple, opaque)], dtype=bool) if len(opaque) else np.array([], bool)
        c = per_zoom.setdefault(z, Counter())
        c["opaque"] += int(len(opaque))
        c["legend_colour"] += int(match.sum())
        for p in map(tuple, opaque[~match][:50]):
            offenders[p] += 1
    return {
        "per_zoom": {z: {**c, "share": round(c["legend_colour"] / c["opaque"], 4) if c["opaque"] else None} for z, c in sorted(per_zoom.items())},
        "examples_not_in_legend": [list(map(int, p)) for p, _ in offenders.most_common(5)],
    }


def main() -> None:
    source, date, root = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    work = root / "_work"
    work.mkdir(parents=True, exist_ok=True)
    storage = LocalStorage(root / "staging")
    version = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    with rasterio.open(source) as src:
        profile = src.profile
        swe = src.read(1, masked=True).filled(np.nan).astype("float64")
        depth_m = src.read(2, masked=True).filled(np.nan).astype("float64")
    # README section 6: depth only where SWE reaches 5 mm, as pipelines/snow_model/run.py draws it.
    depth_cm = np.where(swe >= ramps()["swe"]["transparent_below"], depth_m * 100.0, np.nan)
    report: dict = {"source": str(source.name), "date": date, "code_version": version, "layers": {}}
    for layer, ramp_id, values, unit in (("swe", "swe", swe, "mm"), ("snow_depth", "snow_depth", depth_cm, "cm")):
        display = colour_values(values, ramp_id)
        independent = expected_rgba(values, ramp_id)
        data = np.where(np.isfinite(values), values, NODATA)
        valid = data[data != NODATA]
        data_path, display_path = work / f"{layer}-data.tif", work / f"{layer}-display.tif"
        write(data_path, profile, [data], "float32", NODATA)
        write(display_path, profile, [display[..., i] for i in range(4)], "uint8", None)
        entry = publish(
            layer,
            date,
            {"data": data_path, "display": display_path},
            {
                "source_ids": [f"nivosense-snow-model:{source.name}:{date}"],
                "bands": [layer],
                "units": [unit],
                "value_range": [[0.0, float(np.ceil(valid.max()))]],
                "code_version": version,
                "qa": {"flags": ["t43_evidence_local_trial"], "scores": {}},
            },
            storage,
        )
        colours = Counter(map(tuple, display.reshape(-1, 4)[display.reshape(-1, 4)[:, 3] > 0].tolist()))
        report["layers"][layer] = {
            "entry": {k: entry[k] for k in ("cog", "pmtiles", "status", "resolution_m", "units", "value_range")},
            "valid_pixels": int(valid.size),
            "value_min_max": [round(float(valid.min()), 2), round(float(valid.max()), 2)],
            "display_equals_independent_lookup": bool((display == independent).all()),
            "display_colours_all_in_legend": all(c in legend_colours(ramp_id) for c in colours),
            "display_pixels_per_class_colour": {"#%02X%02X%02X@%d" % c: n for c, n in sorted(colours.items(), key=lambda kv: -kv[1])},
            "tiles": tile_check(root / "staging" / entry["pmtiles"], ramp_id),
        }
    index = rebuild_index(storage)
    report["index_layers"] = {k: v["dates"] for k, v in index["layers"].items()}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
