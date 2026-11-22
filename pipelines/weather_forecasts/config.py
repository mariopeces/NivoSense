import json
from pathlib import Path

COMMON_HORIZONS_HOURS = (24, 48, 72, 120)

# Shared with the frontend legend through palettes.json.
_PALETTES = json.loads(Path(__file__).with_name("palettes.json").read_text(encoding="utf-8"))
MIN_VISIBLE_MM = float(_PALETTES["min_visible_mm"])
MIN_SCALE_MM = 1.0

VARIABLES = ("precipitation_total", "temperature_2m", "wind_speed_10m")

# The site shows only high-resolution models: native grid finer than this. The owner granted one exception,
# WeatherNext 3 (0.1 degree surface grid, about 11 km); a new model needs the same explicit decision.
MAX_RESOLUTION_KM = 5.0
COARSE_MODELS_ALLOWED = frozenset({"weathernext"})
