"""Compose the side-by-side evidence images: references vs the NivoSense mockup, per viewport.

Usage: python -I docs/design/tools/compose_evidence.py
Reads the PNG screenshots in docs/design/screenshots/{reference,mockups}/, writes the side-by-side sheets,
then converts every PNG under screenshots/ and simulations/ to WebP (q90 / q92) to keep the repo small.
The ramp ladder (simulations/ramps-cvd-greyscale.png) stays lossless PNG.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1] / "screenshots"


def font(size: int) -> ImageFont.FreeTypeFont:
    for f in ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def grid(items: list[tuple[str, Path]], cols: int, scale: float, out: Path) -> None:
    imgs = [(label, Image.open(p).convert("RGB")) for label, p in items]
    w, h = imgs[0][1].size
    tw, th = int(w * scale), int(h * scale)
    pad, cap = 16, 30
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (pad + cols * (tw + pad), pad + rows * (th + cap + pad)), "white")
    d = ImageDraw.Draw(sheet)
    for i, (label, im) in enumerate(imgs):
        x = pad + (i % cols) * (tw + pad)
        y = pad + (i // cols) * (th + cap + pad)
        d.text((x, y), label, fill="#17202B", font=font(16))
        sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y + cap))
        d.rectangle([x - 1, y + cap - 1, x + tw, y + cap + th], outline="#DDE2E8")
    sheet.save(out)


def main() -> None:
    ref, mock = ROOT / "reference", ROOT / "mockups"
    for vw, cols, scale in [(1440, 2, 0.5), (375, 4, 0.75)]:
        grid(
            [
                ("cedar-vista (local build, guest mode, its own public catalogue)", ref / f"cedar-vista-{vw}.png"),
                ("openpas-habitat.web.app (guest)", ref / f"openpas-{vw}.png"),
                ("NivoSense live today (mariopeces.github.io/NivoSense)", ref / f"nivosense-current-{vw}.png"),
                ("NivoSense T4.0 mockup: Nieve", mock / f"nieve-{vw}.png"),
            ],
            cols,
            scale,
            ROOT / f"side-by-side-{vw}.png",
        )
    screens = ["nieve", "capas", "nieve-info", "colapsado", "timeline", "agua", "cuenca", "webcams", "webcam-live", "metodo", "vacio", "cargando", "error"]
    for vw, cols, scale in [(1440, 3, 0.4), (375, 7, 0.5)]:
        grid([(s, mock / f"{s}-{vw}.png") for s in screens], cols, scale, ROOT / f"all-screens-{vw}.png")


def to_webp() -> None:
    sim = ROOT.parent / "simulations"
    for png in list(ROOT.rglob("*.png")) + [p for p in sim.glob("*.png") if p.name != "ramps-cvd-greyscale.png"]:
        Image.open(png).convert("RGB").save(png.with_suffix(".webp"), "WEBP", quality=92 if png.parent == sim else 90)
        png.unlink()


if __name__ == "__main__":
    main()
    to_webp()
