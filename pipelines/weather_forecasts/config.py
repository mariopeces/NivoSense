COMMON_HORIZONS_HOURS = (24, 48, 72, 120)

REGION_ID = "sierra-nevada"

MIN_VISIBLE_MM = 0.1
MIN_SCALE_MM = 1.0

UNAVAILABLE_MODELS = (
    {
        "id": "weathernext",
        "name": "WeatherNext 3",
        "reason": "Operational access requires an approved external request",
    },
    {
        "id": "aemet",
        "name": "AEMET",
        "reason": "No official numerical-output endpoint with a verified licence",
    },
)
