"""Build docs/design/ramps.json and the colour checks for the NivoSense map ramps.

Each ramp samples a published perceptually uniform colour map (cmocean, Crameri)
at fixed positions, then this script checks, in OKLab:
  - lightness is monotonic for normal vision, deuteranopia, protanopia, tritanopia
    and in greyscale, so class order survives all of them;
  - adjacent classes stay distinguishable (OKLab distance) under each simulation;
  - every class is visible over the real S2 L1C true colour and over the IGN light basemap.

Usage:
  python -I docs/design/tools/build_ramps.py --cache <dir> --l1c <tci.png> --basemap <ign.png>
The L1C and basemap PNGs come from fetch_backgrounds.py.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]

# Pinned commits so the sampled colours never drift.
SOURCES = {
    "cmocean_ice": (
        "https://raw.githubusercontent.com/matplotlib/cmocean/"
        "59c35002c3aa5296b65d9646e52604c627441eb6/cmocean/rgb/ice-rgb.txt"
    ),
    "cmocean_deep": (
        "https://raw.githubusercontent.com/matplotlib/cmocean/"
        "59c35002c3aa5296b65d9646e52604c627441eb6/cmocean/rgb/deep-rgb.txt"
    ),
    "crameri_acton": (
        "https://raw.githubusercontent.com/callumrollo/cmcrameri/"
        "7670e3cd2a4758c1f355539ad07257d40573adcc/cmcrameri/cmaps/acton.txt"
    ),
}

CITATIONS = {
    "cmocean_ice": (
        "cmocean 'ice' (Thyng, Greene, Hetland, Zimmerle & DiMarco 2016, Oceanography 29(3):9-13, "
        "doi:10.5670/oceanog.2016.66); built in CAM02-UCS for sea ice"
    ),
    "cmocean_deep": (
        "cmocean 'deep' (Thyng et al. 2016, doi:10.5670/oceanog.2016.66); built in CAM02-UCS for water depth"
    ),
    "crameri_acton": (
        "Scientific colour map 'acton' (Crameri 2018, doi:10.5281/zenodo.1243862; "
        "Crameri, Shephard & Heron 2020, Nat. Commun. 11:5444, doi:10.1038/s41467-020-19160-7)"
    ),
}

TRANSPARENT = None

# Stepped classes. min inclusive, max exclusive (None = open). t = position in the source map (0..1).
LAYERS = {
    "snow_cover_probability": {
        "label_es": "Probabilidad de nieve",
        "applies_to": ["gapfill"],
        "unit": "%",
        "value_scale": "probability 0-1 in the raster, shown as %",
        "source": "cmocean_ice",
        "reversed_note": "sampled from light to dark: more probability, darker blue",
        "classes": [
            {"min": 0.0, "max": 0.1, "t": None, "alpha": 0.0, "label_es": "< 10 %"},
            {"min": 0.1, "max": 0.3, "t": 0.86, "alpha": 0.45, "label_es": "10-30 %"},
            {"min": 0.3, "max": 0.5, "t": 0.74, "alpha": 0.6, "label_es": "30-50 %"},
            {"min": 0.5, "max": 0.7, "t": 0.60, "alpha": 0.8, "label_es": "50-70 %"},
            {"min": 0.7, "max": 0.9, "t": 0.46, "alpha": 0.85, "label_es": "70-90 %"},
            {"min": 0.9, "max": None, "t": 0.32, "alpha": 0.9, "label_es": "≥ 90 %"},
        ],
    },
    "snow_cover_observed": {
        "label_es": "Nieve observada",
        "applies_to": ["snow_obs"],
        "unit": None,
        "value_scale": "class keys from the T1.2 classifier; the pipeline maps its codes to these keys",
        "source": "cmocean_ice",
        "categorical": True,
        "classes": [
            {"key": "snow", "t": 0.32, "alpha": 0.9, "label_es": "Nieve"},
            {"key": "snow_low_confidence", "t": 0.60, "alpha": 0.8, "label_es": "Nieve, confianza baja (bosque)"},
            {"key": "no_snow", "t": None, "alpha": 0.0, "label_es": "Sin nieve (se ve la imagen)"},
            {
                "key": "cloud",
                "rgb": "#F4F2EE",
                "alpha": 0.8,
                "pattern": {"kind": "dots", "color": "#6E6A63", "spacing_px": 6, "radius_px": 1},
                "label_es": "Nube",
            },
            {
                "key": "unknown",
                "rgb": None,
                "alpha": 0.0,
                "pattern": {
                    "kind": "hatch",
                    "color": "#2E333B",
                    "alpha": 0.7,
                    "spacing_px": 6,
                    "width_px": 1,
                    "angle_deg": 45,
                },
                "label_es": "Sin dato (sombra del relieve o fuera de la escena)",
            },
        ],
    },
    "swe": {
        "label_es": "Equivalente en agua (SWE)",
        "applies_to": ["swe"],
        "unit": "mm",
        "value_scale": "mm of water, ensemble median",
        "source": "cmocean_deep",
        "transparent_below": 5,
        "transparent_note": (
            "README section 6: SWE under 5 mm is drawn transparent; "
            "the first class is light and translucent so trace snow never reads as solid cover"
        ),
        "classes": [
            {"min": 0, "max": 5, "t": None, "alpha": 0.0, "label_es": "< 5 mm"},
            {"min": 5, "max": 25, "t": 0.10, "alpha": 0.4, "label_es": "5-25 mm"},
            {"min": 25, "max": 50, "t": 0.26, "alpha": 0.75, "label_es": "25-50"},
            {"min": 50, "max": 100, "t": 0.40, "alpha": 0.82, "label_es": "50-100"},
            {"min": 100, "max": 200, "t": 0.54, "alpha": 0.85, "label_es": "100-200"},
            {"min": 200, "max": 400, "t": 0.68, "alpha": 0.88, "label_es": "200-400"},
            {"min": 400, "max": 800, "t": 0.82, "alpha": 0.9, "label_es": "400-800"},
            {"min": 800, "max": None, "t": 0.95, "alpha": 0.9, "label_es": "≥ 800 mm"},
        ],
    },
    "snow_depth": {
        "label_es": "Espesor de nieve",
        "applies_to": ["depth"],
        "unit": "cm",
        "value_scale": "cm, SWE divided by modelled density",
        "source": "crameri_acton",
        "reversed_note": "sampled from light to dark: deeper, darker",
        "transparent_below": None,
        "transparent_note": "depth is drawn only where SWE >= 5 mm, the same mask as the SWE layer",
        "classes": [
            {"min": 0, "max": 25, "t": 0.87, "alpha": 0.5, "label_es": "< 25 cm"},
            {"min": 25, "max": 50, "t": 0.75, "alpha": 0.75, "label_es": "25-50"},
            {"min": 50, "max": 100, "t": 0.63, "alpha": 0.82, "label_es": "50-100"},
            {"min": 100, "max": 150, "t": 0.51, "alpha": 0.85, "label_es": "100-150"},
            {"min": 150, "max": 200, "t": 0.39, "alpha": 0.88, "label_es": "150-200"},
            {"min": 200, "max": 300, "t": 0.25, "alpha": 0.9, "label_es": "200-300"},
            {"min": 300, "max": None, "t": 0.11, "alpha": 0.9, "label_es": "≥ 300 cm"},
        ],
    },
}

# Machado, Oliveira & Fernandes 2009, IEEE TVCG 15(6):1291-1298, severity 1.0, applied in linear sRGB.
CVD = {
    "deuteranopia": np.array(
        [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]]
    ),
    "protanopia": np.array(
        [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]]
    ),
    "tritanopia": np.array(
        [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]]
    ),
}


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def oklab(rgb: np.ndarray) -> np.ndarray:
    """sRGB 0..1 (..., 3) -> OKLab (Ottosson 2020)."""
    lin = srgb_to_linear(rgb)
    m1 = np.array(
        [
            [0.4122214708, 0.5363325363, 0.0514459929],
            [0.2119034982, 0.6806995451, 0.1073969566],
            [0.0883024619, 0.2817188376, 0.6299787005],
        ]
    )
    m2 = np.array(
        [
            [0.2104542553, 0.7936177850, -0.0040720468],
            [1.9779984951, -2.4285922050, 0.4505937099],
            [0.0259040371, 0.7827717662, -0.8086757660],
        ]
    )
    lms = np.cbrt(lin @ m1.T)
    return lms @ m2.T


def simulate(rgb: np.ndarray, kind: str) -> np.ndarray:
    if kind == "normal":
        return rgb
    if kind == "greyscale":
        y = srgb_to_linear(rgb) @ np.array([0.2126, 0.7152, 0.0722])
        g = linear_to_srgb(y)
        return np.stack([g, g, g], axis=-1)
    return linear_to_srgb(srgb_to_linear(rgb) @ CVD[kind].T)


def hex_to_rgb(h: str) -> np.ndarray:
    return np.array([int(h[i : i + 2], 16) for i in (1, 3, 5)]) / 255.0


def rgb_to_hex(c: np.ndarray) -> str:
    return "#" + "".join(f"{int(round(v * 255)):02X}" for v in np.clip(c, 0, 1))


def load_source(cache: Path, name: str) -> np.ndarray:
    path = cache / f"{name}.txt"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SOURCES[name], path)
    return np.loadtxt(path)


def sample(table: np.ndarray, t: float) -> np.ndarray:
    x = t * (len(table) - 1)
    i = int(np.floor(x))
    j = min(i + 1, len(table) - 1)
    f = x - i
    return table[i] * (1 - f) + table[j] * f


def resolve(cache: Path) -> dict:
    out = {}
    for layer_id, spec in LAYERS.items():
        table = load_source(cache, spec["source"])
        classes = []
        for c in spec["classes"]:
            c = dict(c)
            t = c.pop("t", None)
            if "rgb" in c:
                c["color"] = c.pop("rgb")
            elif t is None:
                c["color"] = None
            else:
                c["color"] = rgb_to_hex(sample(table, t))
                c["source_position"] = t
            classes.append(c)
        out[layer_id] = {k: v for k, v in spec.items() if k != "classes"} | {
            "source_citation": CITATIONS[spec["source"]],
            "classes": classes,
        }
    return out


def ordered_colours(layer: dict) -> list[np.ndarray]:
    """Colours of the ramp classes in value order (categorical: only the snow classes are ordered)."""
    if layer.get("categorical"):
        keys = ["snow_low_confidence", "snow"]
        return [hex_to_rgb(c["color"]) for k in keys for c in layer["classes"] if c["key"] == k]
    return [hex_to_rgb(c["color"]) for c in layer["classes"] if c["color"]]


def check(layers: dict) -> dict:
    report = {}
    for layer_id, layer in layers.items():
        cols = np.array(ordered_colours(layer))
        rows = {}
        for kind in ["normal", "deuteranopia", "protanopia", "tritanopia", "greyscale"]:
            lab = oklab(simulate(cols, kind))
            L = lab[:, 0]
            d = np.diff(L)
            mono = bool(np.all(d < 0) or np.all(d > 0))
            de = np.linalg.norm(np.diff(lab, axis=0), axis=1)
            rows[kind] = {
                "L": [round(float(v), 3) for v in L],
                "lightness_monotonic": mono,
                "min_adjacent_deltaE_ok": round(float(de.min()), 3),
            }
        report[layer_id] = rows
    return report


def blend(bg: np.ndarray, rgb: np.ndarray, alpha: float) -> np.ndarray:
    return bg * (1 - alpha) + rgb * alpha


def visibility(layers: dict, backgrounds: dict[str, np.ndarray]) -> dict:
    """Mean OKLab distance between each class composited over a background and the bare background,
    split into bright pixels (snow in the RGB) and the rest."""
    out = {}
    for name, bg in backgrounds.items():
        lab_bg = oklab(bg)
        bright = lab_bg[..., 0] > 0.85
        rows = {}
        for layer_id, layer in layers.items():
            vals = []
            for c in layer["classes"]:
                if not c["color"] or c["alpha"] == 0:
                    continue
                comp = blend(bg, hex_to_rgb(c["color"]), c["alpha"])
                de = np.linalg.norm(oklab(comp) - lab_bg, axis=-1)
                entry = {"class": c.get("label_es"), "all": round(float(de.mean()), 3)}
                if bright.any():
                    entry["over_bright"] = round(float(de[bright].mean()), 3)
                if (~bright).any():
                    entry["over_dark"] = round(float(de[~bright].mean()), 3)
                vals.append(entry)
            rows[layer_id] = vals
        out[name] = {"bright_pixel_share": round(float(bright.mean()), 3), "layers": rows}
    return out


def font(size: int) -> ImageFont.FreeTypeFont:
    for f in ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def draw_pattern(img: Image.Image, box: tuple[int, int, int, int], pattern: dict) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    col = tuple(int(v * 255) for v in hex_to_rgb(pattern["color"])) + (int(255 * pattern.get("alpha", 1.0)),)
    s = pattern["spacing_px"]
    if pattern["kind"] == "dots":
        r = pattern["radius_px"]
        for y in range(s // 2, h, s):
            for x in range(s // 2, w, s):
                d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    else:
        for k in range(-h, w, s):
            d.line([(k, h), (k + h, 0)], fill=col, width=pattern["width_px"])
    img.paste(tile, (x0, y0), tile)


def ladder(layers: dict, path: Path) -> None:
    kinds = ["normal", "deuteranopia", "protanopia", "tritanopia", "greyscale"]
    names_es = {
        "normal": "Visión normal",
        "deuteranopia": "Deuteranopía",
        "protanopia": "Protanopía",
        "tritanopia": "Tritanopía",
        "greyscale": "Escala de grises",
    }
    sw, sh, pad, lw = 64, 36, 24, 190
    blocks = list(layers.items())
    height = pad + sum(48 + len(kinds) * (sh + 6) + 28 for _ in blocks) + pad
    width = lw + 8 * (sw + 4) + pad * 2
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    f, fb = font(15), font(17)
    y = pad
    for layer_id, layer in blocks:
        d.text((pad, y), f"{layer['label_es']} ({layer_id})", fill="#1B2430", font=fb)
        y += 32
        cls = [c for c in layer["classes"] if c["color"] or c.get("pattern")]
        for kind in kinds:
            d.text((pad, y + 9), names_es[kind], fill="#4B5563", font=f)
            for i, c in enumerate(cls):
                x = pad + lw + i * (sw + 4)
                if c["color"]:
                    col = simulate(hex_to_rgb(c["color"])[None, :], kind)[0]
                    d.rectangle([x, y, x + sw, y + sh], fill=tuple(int(v * 255) for v in col))
                else:
                    d.rectangle([x, y, x + sw, y + sh], outline="#9AA3AE")
                if c.get("pattern"):
                    p = dict(c["pattern"])
                    p["color"] = rgb_to_hex(simulate(hex_to_rgb(p["color"])[None, :], kind)[0])
                    draw_pattern(img, (x, y, x + sw, y + sh), p)
            y += sh + 6
        for i, c in enumerate(cls):
            x = pad + lw + i * (sw + 4)
            d.text((x, y), c["label_es"][:9], fill="#4B5563", font=font(12))
        y += 28
    img.save(path)


def overlay(layers: dict, bg_img: Image.Image, title: str, path: Path, kind: str = "normal") -> None:
    """Vertical bands of every class over the background, opaque classes at their real alpha."""
    bg = np.asarray(bg_img.convert("RGB")).astype(float) / 255.0
    rows = [(lid, [c for c in lay["classes"] if c["color"] or c.get("pattern")]) for lid, lay in layers.items()]
    band_h = bg.shape[0] // len(rows)
    out = bg.copy()
    labels = []
    for r, (lid, cls) in enumerate(rows):
        y0, y1 = r * band_h, (r + 1) * band_h
        bw = bg.shape[1] // len(cls)
        for i, c in enumerate(cls):
            x0, x1 = i * bw, (i + 1) * bw
            if c["color"]:
                out[y0:y1, x0 + 6 : x1 - 6] = blend(bg[y0:y1, x0 + 6 : x1 - 6], hex_to_rgb(c["color"]), c["alpha"])
            labels.append((x0 + 8, y0 + 6, c["label_es"][:14], c.get("pattern"), (x0 + 6, y0 + 28, x1 - 6, y1 - 4)))
        labels.append((8, y1 - 26, layers[lid]["label_es"], None, None))
    out = simulate(out, kind)
    img = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))
    for _x, _y, _text, pattern, box in labels:
        if pattern:
            p = dict(pattern)
            p["color"] = rgb_to_hex(simulate(hex_to_rgb(p["color"])[None, :], kind)[0])
            draw_pattern(img, box, p)
    d = ImageDraw.Draw(img, "RGBA")
    for x, y, text, _, _ in labels:
        tw = d.textlength(text, font=font(13))
        d.rectangle([x - 3, y - 2, x + tw + 3, y + 17], fill=(255, 255, 255, 220))
        d.text((x, y), text, fill="#1B2430", font=font(13))
    d.rectangle([0, img.height - 26, img.width, img.height], fill=(255, 255, 255, 230))
    d.text((8, img.height - 22), title, fill="#1B2430", font=font(13))
    img.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--l1c", type=Path, required=True)
    ap.add_argument("--basemap", type=Path, required=True)
    args = ap.parse_args()

    layers = resolve(args.cache)
    l1c = Image.open(args.l1c).convert("RGB")
    base = Image.open(args.basemap).convert("RGB")
    checks = check(layers)
    vis = visibility(
        layers,
        {
            "s2_l1c_tci_2026-02-21": np.asarray(l1c).astype(float)[::4, ::4] / 255.0,
            "ign_base_gris": np.asarray(base).astype(float)[::4, ::4] / 255.0,
        },
    )
    doc = {
        "version": 1,
        "about": (
            "Map colour ramps shared by the pipelines (tile colouring, legend constants) and the frontend legends. "
            "Generated by docs/design/tools/build_ramps.py; do not edit by hand."
        ),
        "class_bounds": "min inclusive, max exclusive; null max means open",
        "colour_checks": {
            "space": "OKLab (Ottosson 2020, https://bottosson.github.io/posts/oklab/)",
            "cvd_model": "Machado, Oliveira & Fernandes 2009, IEEE TVCG 15(6), severity 1.0, linear sRGB",
            "greyscale": "Rec. 709 relative luminance",
            "results": checks,
            "visibility_mean_deltaE_ok": vis,
        },
        "layers": layers,
    }
    (ROOT / "ramps.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sim = ROOT / "simulations"
    sim.mkdir(exist_ok=True)
    ladder(layers, sim / "ramps-cvd-greyscale.png")
    l1c_title = "Fondo: Sentinel-2 L1C TCI, S2C_30SVG_20260221_1_L1C (Earth Search), cresta Veleta-Mulhacén"
    ign_title = "Fondo: IGN Base gris (ign.es WMTS, CC BY 4.0 scne.es), mismo entorno"
    for kind, suffix in [
        ("normal", ""),
        ("deuteranopia", "-deuteranopia"),
        ("protanopia", "-protanopia"),
        ("greyscale", "-greyscale"),
    ]:
        overlay(
            layers,
            l1c,
            l1c_title + (f" · simulación {kind}" if kind != "normal" else ""),
            sim / f"over-l1c{suffix}.png",
            kind,
        )
        overlay(
            layers,
            base,
            ign_title + (f" · simulación {kind}" if kind != "normal" else ""),
            sim / f"over-ign{suffix}.png",
            kind,
        )

    for lid, rows in checks.items():
        bad = [k for k, v in rows.items() if not v["lightness_monotonic"]]
        print(
            lid,
            "monotonic in all" if not bad else f"NOT monotonic in {bad}",
            "min dE:",
            {k: v["min_adjacent_deltaE_ok"] for k, v in rows.items()},
        )


if __name__ == "__main__":
    main()
