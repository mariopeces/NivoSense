"""JSON Schema validation of catalogue entries and the index, against schema.json."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("schema.json")


@cache
def _validator(definition: str) -> Any:
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]}, format_checker=FormatChecker()
    )


def validate_entry(entry: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if the entry does not match the schema."""
    _validator("entry").validate(entry)


def validate_index(index: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if the index does not match the schema."""
    _validator("index").validate(index)
