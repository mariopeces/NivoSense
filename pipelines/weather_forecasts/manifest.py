import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import COMMON_HORIZONS_HOURS


@dataclass
class Field:
    files: dict[int, Path]
    bounds: list[float]
    images: dict[int, Path] = field(default_factory=dict)
    scale_max_mm: float = 0.0
    maxima: dict[int, float] = field(default_factory=dict)
    missing_reason: str | None = None
    note: str | None = None


@dataclass
class ModelOutput:
    id: str
    name: str
    attribution: str
    source: str
    grid_degrees: float
    cycle: datetime
    precipitation: Field
    snowfall: Field | None = None
    snowfall_reason: str | None = None
    phase_files: dict[int, Path] = field(default_factory=dict)


def _asset(path: Path, root: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _field_entry(item: Field, hours: int, root: Path) -> dict:
    if hours not in item.files:
        return {"available": False, "reason": item.missing_reason}
    return {
        "available": True,
        "units": "mm",
        "basis": "water_equivalent",
        "asset": _asset(item.files[hours], root),
        "visualization": {
            "asset": _asset(item.images[hours], root),
            "bounds": item.bounds,
            "scale_min_mm": 0,
            "scale_max_mm": item.scale_max_mm,
            "region_max_mm": round(item.maxima[hours], 2),
        },
        **({"note": item.note} if item.note else {}),
    }


def _model_entry(model: ModelOutput, root: Path) -> dict:
    cycle = model.cycle.astimezone(timezone.utc)
    horizons = {}
    for hours in COMMON_HORIZONS_HOURS:
        entry = {
            "valid_at": (cycle + timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
            "precipitation_total": _field_entry(model.precipitation, hours, root),
            "snowfall": (
                _field_entry(model.snowfall, hours, root)
                if model.snowfall
                else {"available": False, "reason": model.snowfall_reason}
            ),
        }
        if model.phase_files:
            entry["phase_context"] = {
                "available": hours in model.phase_files,
                "variables": ["temperature_2m", "categorical_rain", "categorical_snow"],
                "asset": _asset(model.phase_files[hours], root) if hours in model.phase_files else None,
            }
        horizons[str(hours)] = entry
    return {
        "id": model.id,
        "name": model.name,
        "attribution": model.attribution,
        "run_at": cycle.isoformat().replace("+00:00", "Z"),
        "source": model.source,
        "grid_degrees": model.grid_degrees,
        "horizons": horizons,
    }


def build_manifest(
    region_id: str,
    bbox: tuple[float, float, float, float],
    output_root: Path,
    models: list[ModelOutput],
    unavailable_models: list[dict],
) -> dict:
    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "region": {"id": region_id, "bbox": list(bbox)},
        "common_horizons_hours": list(COMMON_HORIZONS_HOURS),
        "models": [_model_entry(model, output_root) for model in models],
        "unavailable_models": unavailable_models,
    }


def write_manifest(payload: dict, destination: Path) -> None:
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
