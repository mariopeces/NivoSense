"""build_ramps.py must refuse to publish a broken ramp (G-Code T4.0 round 1, finding 2)."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import numpy as np
import pytest

TOOL = Path(__file__).resolve().parents[2] / "docs" / "design" / "tools" / "build_ramps.py"
spec = importlib.util.spec_from_file_location("build_ramps", TOOL)
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    """Offline stand-ins for the three source maps: smooth tables in the same light/dark direction as the real maps."""
    d = tmp_path / "cache"
    d.mkdir()
    t = np.linspace(0, 1, 256)[:, None]
    # Near-black to near-white, slightly tinted: lightness spans the whole range like the real maps.
    tables = {
        "cmocean_ice": np.hstack([0.9 * t, 0.02 + 0.93 * t, 0.1 + 0.88 * t]),
        "cmocean_deep": np.hstack([0.95 - 0.9 * t, 0.99 - 0.97 * t, 0.8 - 0.7 * t]),  # light to dark, like deep
        "crameri_acton": np.hstack([0.1 + 0.8 * t, 0.02 + 0.9 * t, 0.15 + 0.8 * t]),
    }
    for name, table in tables.items():
        np.savetxt(d / f"{name}.txt", table)
    return d


def run(monkeypatch, tmp_path: Path, cache: Path, layers: dict) -> tuple[int, Path]:
    monkeypatch.setattr(br, "LAYERS", layers)
    out = tmp_path / "out"
    bg = tmp_path / "bg.png"
    from PIL import Image

    Image.new("RGB", (1600, 1000), (200, 200, 200)).save(bg)  # the size fetch_backgrounds.py writes
    code = br.main(
        [
            "--cache",
            str(cache),
            "--l1c",
            str(bg),
            "--basemap",
            str(bg),
            "--out",
            str(out),
        ]
    )
    return code, out


def test_valid_ramps_are_written_with_lf_source_and_licence(monkeypatch, tmp_path, cache):
    code, out = run(monkeypatch, tmp_path, cache, copy.deepcopy(br.LAYERS))
    assert code == 0
    raw = (out / "ramps.json").read_bytes()
    assert b"\r\n" not in raw
    import json

    doc = json.loads(raw)
    for layer in doc["layers"].values():
        assert layer["source_url"].startswith("https://raw.githubusercontent.com/")
        assert "MIT" in layer["source_licence"]


def test_faded_class_breaks_order_and_nothing_is_written(monkeypatch, tmp_path, cache):
    # The G-Code reproduction: SWE 50-100 mm alpha 0.40 -> 0.05 makes it lighter than 25-50 mm.
    layers = copy.deepcopy(br.LAYERS)
    swe = next(c for c in layers["swe"]["classes"] if c["label_es"].startswith("50"))
    swe["alpha"] = 0.05
    code, out = run(monkeypatch, tmp_path, cache, layers)
    assert code == 1
    assert not (out / "ramps.json").exists()
    assert not (out / "simulations").exists()


def test_reordered_positions_fail(monkeypatch, tmp_path, cache):
    layers = copy.deepcopy(br.LAYERS)
    cls = layers["snow_depth"]["classes"]
    cls[2]["t"], cls[3]["t"] = cls[3]["t"], cls[2]["t"]
    code, out = run(monkeypatch, tmp_path, cache, layers)
    assert code == 1
    assert not (out / "ramps.json").exists()


@pytest.mark.parametrize(
    "breakage",
    [
        lambda L: L["swe"]["classes"].__setitem__(slice(3, None), []),  # too few classes
        lambda L: L["swe"]["classes"][2].__setitem__("min", 999),  # bounds not contiguous
        lambda L: L["snow_cover_probability"]["classes"][-1].__setitem__("max", 1.0),  # last class closed
        lambda L: L["snow_cover_probability"]["classes"][1].__setitem__("alpha", 1.5),  # alpha out of range
    ],
)
def test_structural_breakage_fails(monkeypatch, tmp_path, cache, breakage):
    layers = copy.deepcopy(br.LAYERS)
    breakage(layers)
    code, out = run(monkeypatch, tmp_path, cache, layers)
    assert code == 1
    assert not (out / "ramps.json").exists()
