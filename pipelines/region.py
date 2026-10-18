import json
from dataclasses import dataclass
from pathlib import Path

from .geo import bbox_from_geojson


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    basins: Path
    bbox: tuple[float, float, float, float]
    settings: dict


def load_region(path: Path) -> Region:
    payload = json.loads(path.read_text(encoding="utf-8"))
    basins = Path(payload["basins"])
    return Region(
        id=payload["id"],
        name=payload["name"],
        basins=basins,
        bbox=bbox_from_geojson(basins),
        settings=payload,
    )
