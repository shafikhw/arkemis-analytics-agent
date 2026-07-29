"""Allow-listed tool routing with lightweight schema validation."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Dict, Mapping

from src.tools.energy_tools import EnergyTools
from src.tools.schemas import build_tool_schemas


class ToolValidationError(ValueError):
    """Malformed or unsupported model tool request."""


class ToolRegistry:
    def __init__(self, tools: EnergyTools) -> None:
        self.tools = tools
        self.schemas = build_tool_schemas()
        self._schema_by_name = {schema["name"]: schema for schema in self.schemas}
        self._handlers: Dict[str, Callable[..., Dict[str, Any]]] = {
            name: getattr(tools, name) for name in self._schema_by_name
        }

    def execute(self, name: str, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        prepared = self.prepare(name, arguments)
        return self._handlers[name](**prepared)

    def prepare(self, name: str, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        """Validate and resolve entity aliases to stable cached IDs."""
        if name not in self._handlers:
            raise ToolValidationError(f"Unsupported tool: {name!r}.")
        if not isinstance(arguments, Mapping):
            raise ToolValidationError("Tool arguments must be a JSON object.")
        schema = self._schema_by_name[name]["parameters"]
        _validate_object(arguments, schema, path=name)
        prepared = dict(arguments)
        for argument, kind in (
            ("organization", "organization"),
            ("site", "site"),
            ("meter", "meter"),
        ):
            value = prepared.get(argument)
            if isinstance(value, str) and value.strip():
                try:
                    identifiers = self.tools.cache.resolve_entity_ids(kind, value)
                except ValueError as exc:
                    raise ToolValidationError(str(exc)) from exc
                if len(identifiers) != 1:
                    raise ToolValidationError(
                        f"Ambiguous {kind} alias {value!r}; use a stable ID."
                    )
                prepared[argument] = identifiers[0]
        return prepared


def _validate_object(
    value: Mapping[str, Any], schema: Dict[str, Any], *, path: str
) -> None:
    properties = schema["properties"]
    extra = sorted(set(value) - set(properties))
    if extra:
        raise ToolValidationError(
            f"{path} received unsupported argument(s): {', '.join(extra)}."
        )
    missing = [name for name in schema.get("required", []) if name not in value]
    if missing:
        raise ToolValidationError(
            f"{path} is missing required argument(s): {', '.join(missing)}."
        )
    for name, field_schema in properties.items():
        if name in value:
            _validate_value(value[name], field_schema, path=f"{path}.{name}")


def _validate_value(value: Any, schema: Dict[str, Any], *, path: str) -> None:
    expected = schema.get("type")
    types = expected if isinstance(expected, list) else [expected]
    if value is None:
        if "null" not in types:
            raise ToolValidationError(f"{path} cannot be null.")
        return
    valid = (
        ("string" in types and isinstance(value, str))
        or ("boolean" in types and isinstance(value, bool))
        or (
            "integer" in types
            and isinstance(value, int)
            and not isinstance(value, bool)
        )
        or (
            "number" in types
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        )
        or ("object" in types and isinstance(value, Mapping))
    )
    if not valid:
        raise ToolValidationError(f"{path} has the wrong JSON type.")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolValidationError(
            f"{path} must be one of: {', '.join(map(str, schema['enum']))}."
        )
    if isinstance(value, (int, float)):
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolValidationError(f"{path} is below the allowed minimum.")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolValidationError(f"{path} exceeds the allowed maximum.")
    if schema.get("format") == "date" and isinstance(value, str):
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ToolValidationError(f"{path} must use YYYY-MM-DD.") from exc
    if (
        isinstance(value, str)
        and "date" in path
        and value
        and value is not None
        and schema.get("type") == ["string", "null"]
    ):
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ToolValidationError(f"{path} must use YYYY-MM-DD.") from exc
