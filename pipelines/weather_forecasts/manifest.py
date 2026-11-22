import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import COARSE_MODELS_ALLOWED, COMMON_HORIZONS_HOURS, MAX_RESOLUTION_KM, VARIABLES


@dataclass
class Field:
    files: dict[int, Path]
    bounds: list[float]
    units: str = "mm"
    images: dict[int, Path] = field(default_factory=dict)
    scale_min: float = 0.0
    scale_max: float = 0.0
    maxima: dict[int, float] = field(default_factory=dict)
    minima: dict[int, float] = field(default_factory=dict)
    missing_reason: str | None = None
    note: str | None = None


@dataclass
class ModelOutput:
    id: str
    name: str
    attribution: str
    source: str
    grid_degrees: float
    resolution_km: float
    cycle: datetime
    fields: dict[str, Field]
    experimental: bool = False
    missing_reasons: dict[str, str] = field(default_factory=dict)


def _asset(path: Path, root: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _field_entry(item: Field | None, hours: int, root: Path, reason: str | None) -> dict:
    if item is None:
        return {"available": False, "reason": reason}
    if hours not in item.files:
        return {"available": False, "reason": item.missing_reason}
    return {
        "available": True,
        "units": item.units,
        "asset": _asset(item.files[hours], root),
        "visualization": {
            "asset": _asset(item.images[hours], root),
            "bounds": item.bounds,
            "scale_min": item.scale_min,
            "scale_max": item.scale_max,
            "region_min": round(item.minima[hours], 2),
            "region_max": round(item.maxima[hours], 2),
        },
        **({"note": item.note} if item.note else {}),
    }


def _model_entry(model: ModelOutput, root: Path) -> dict:
    cycle = model.cycle.astimezone(timezone.utc)
    horizons = {}
    for hours in COMMON_HORIZONS_HOURS:
        horizons[str(hours)] = {
            "valid_at": (cycle + timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
            **{
                variable: _field_entry(
                    model.fields.get(variable), hours, root, model.missing_reasons.get(variable)
                )
                for variable in VARIABLES
            },
        }
    return {
        "id": model.id,
        "name": model.name,
        "attribution": model.attribution,
        "run_at": cycle.isoformat().replace("+00:00", "Z"),
        "source": model.source,
        "grid_degrees": model.grid_degrees,
        "resolution_km": model.resolution_km,
        "experimental": model.experimental,
        "horizons": horizons,
    }


def build_manifest(
    region_id: str,
    bbox: tuple[float, float, float, float],
    output_root: Path,
    models: list[ModelOutput],
    unavailable_models: list[dict],
) -> dict:
    for model in models:
        if model.resolution_km >= MAX_RESOLUTION_KM and model.id not in COARSE_MODELS_ALLOWED:
            raise ValueError(
                f"{model.id} is {model.resolution_km} km, coarser than the {MAX_RESOLUTION_KM} km limit"
            )
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
