import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import COMMON_HORIZONS_HOURS, MODEL_ID, REGION_ID


def _asset(path: Path, root: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def build_manifest(
    cycle: datetime,
    bbox: tuple[float, float, float, float],
    output_root: Path,
    precipitation_files: dict[int, Path],
    phase_files: dict[int, Path],
    visualization_files: dict[int, Path],
    visualization_bounds: list[float],
    visualization_scale_max_mm: float,
) -> dict:
    cycle = cycle.astimezone(timezone.utc)
    horizons = {}
    for hours in COMMON_HORIZONS_HOURS:
        valid_at = cycle + timedelta(hours=hours)
        horizons[str(hours)] = {
            "valid_at": valid_at.isoformat().replace("+00:00", "Z"),
            "precipitation_total": {
                "available": True,
                "units": "mm",
                "asset": _asset(precipitation_files[hours], output_root),
                "visualization": {
                    "asset": _asset(visualization_files[hours], output_root),
                    "bounds": visualization_bounds,
                    "scale_min_mm": 0,
                    "scale_max_mm": visualization_scale_max_mm,
                },
            },
            "phase_context": {
                "available": hours in phase_files,
                "variables": ["temperature_2m", "categorical_rain", "categorical_snow"],
                "asset": _asset(phase_files[hours], output_root) if hours in phase_files else None,
            },
            "snowfall": {
                "available": False,
                "reason": "Instantaneous phase indicators do not provide an accumulated snowfall field",
            },
        }

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "region": {"id": REGION_ID, "bbox": list(bbox)},
        "common_horizons_hours": list(COMMON_HORIZONS_HOURS),
        "models": [
            {
                "id": MODEL_ID,
                "run_at": cycle.isoformat().replace("+00:00", "Z"),
                "source": "https://nomads.ncep.noaa.gov/",
                "grid_degrees": 0.25,
                "horizons": horizons,
            }
        ],
    }


def write_manifest(payload: dict, destination: Path) -> None:
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
