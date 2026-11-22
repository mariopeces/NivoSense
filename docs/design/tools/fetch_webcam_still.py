"""Save one Cetursa webcam still for the webcam-live mockup, with its real capture time.

Usage: python -I docs/design/tools/fetch_webcam_still.py
Writes docs/design/mockups/data/cetursa_pradollano_snap_c1_<Last-Modified, UTC>.jpg and
cetursa_pradollano.json. The capture time is the HTTP Last-Modified header: the camera page shows
no other timestamp, and it matches the time burned into the image. The image is stored as served.
A rerun fetches the current still, so the file name and the mockup age change; replace the old JPG.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

URL = "https://recursos.sierranevada.es/_extras/fotos_camaras/pradollano/snap_c1.jpg"
OUT = Path(__file__).resolve().parents[1] / "mockups" / "data"
CREDIT = "Imagen: Cetursa Sierra Nevada / feratel"


def main() -> None:
    with urllib.request.urlopen(URL, timeout=30) as r:
        body = r.read()
        modified = parsedate_to_datetime(r.headers["Last-Modified"]).astimezone(UTC)
    fetched = datetime.now(UTC)
    name = f"cetursa_pradollano_snap_c1_{modified:%Y%m%dT%H%M%SZ}.jpg"
    (OUT / name).write_bytes(body)
    meta = {
        "camera": "Pradollano (snap_c1)",
        "url": URL,
        "file": name,
        "http_last_modified": f"{modified:%Y-%m-%dT%H:%M:%SZ}",
        "fetched_at": f"{fetched:%Y-%m-%dT%H:%M:%SZ}",
        "credit": CREDIT,
        "note": (
            "Still saved with the H4 credit for the design mockup only; "
            "capture time is the HTTP Last-Modified header at fetch time."
        ),
    }
    (OUT / "cetursa_pradollano.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    print("ok", name)


if __name__ == "__main__":
    main()
