from collections.abc import Mapping
from typing import Any


def get_path(value: Any, path: str, default: Any = None) -> Any:
    """Resolve a dotted path without evaluating provider-controlled expressions."""
    if not path:
        return default
    current = value
    for part in path.split("."):
        if isinstance(current, Mapping):
            current = current.get(part, default)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return default
            current = current[index]
        else:
            return default
        if current is default:
            return default
    return current


def map_payload(source: Mapping[str, Any], mapping: Mapping[str, str]) -> dict:
    """Build a provider request from an explicit canonical-to-provider mapping."""
    result: dict[str, Any] = {}
    for target_path, source_path in mapping.items():
        value = get_path(source, source_path)
        if value is None:
            continue
        cursor = result
        parts = target_path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return result

