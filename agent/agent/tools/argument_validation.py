"""Validate tool arguments independently of execution."""

import json
from typing import Any


def parse_arguments(arguments: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return dict(arguments)
    if not isinstance(arguments, str):
        raise ValueError("arguments must be a JSON object or dictionary")
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ValueError("arguments are not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("arguments JSON must contain an object")
    return parsed


def validate_arguments(
    schema: dict[str, Any],
    arguments: dict[str, Any],
) -> None:
    if schema.get("type", "object") != "object":
        raise ValueError("tool parameter schema must describe an object")

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    missing = [name for name in required if name not in arguments]
    if missing:
        raise ValueError(
            f"missing required argument(s): {', '.join(sorted(missing))}"
        )

    if schema.get("additionalProperties") is False:
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise ValueError(f"unknown argument(s): {', '.join(unknown)}")

    for name, value in arguments.items():
        field_schema = properties.get(name)
        if not field_schema:
            continue
        _validate_value(name, value, field_schema)


def _validate_value(
    name: str,
    value: Any,
    schema: dict[str, Any],
) -> None:
    expected = schema.get("type")
    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    python_type = type_map.get(expected)
    if python_type is not None:
        type_matches = isinstance(value, python_type)
        if expected in {"integer", "number"} and isinstance(value, bool):
            type_matches = False
        if not type_matches:
            raise ValueError(f"argument '{name}' must be {expected}")

    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"argument '{name}' is not an allowed value")
    if "minimum" in schema and value < schema["minimum"]:
        raise ValueError(f"argument '{name}' is below the minimum")
    if "maximum" in schema and value > schema["maximum"]:
        raise ValueError(f"argument '{name}' exceeds the maximum")
