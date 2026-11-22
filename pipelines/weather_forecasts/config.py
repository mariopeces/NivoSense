import json
from pathlib import Path

COMMON_HORIZONS_HOURS = (24, 48, 72, 120)

# Shared with the frontend legend through palettes.json.
_PALETTES = json.loads(Path(__file__).with_name("palettes.json").read_text(encoding="utf-8"))
MIN_VISIBLE_MM = float(_PALETTES["min_visible_mm"])
MIN_SCALE_MM = 1.0

UNAVAILABLE_MODELS = (
    {
        "id": "weathernext",
        "name": "WeatherNext 3",
        "reason": "Data buckets require a Google account on the WeatherNext allowlist",
    },
)
