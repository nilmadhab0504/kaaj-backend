"""
Shared case conversion for API request/response normalization.
Uses Pydantic's alias_generators for consistency with schema validation.
"""
from typing import Any

from pydantic.alias_generators import to_camel, to_snake


def to_camel_key(s: str) -> str:
    """Convert a single snake_case key to camelCase (first letter lower)."""
    return to_camel(s)


def to_snake_key(s: str) -> str:
    """Convert a single camelCase key to snake_case."""
    return to_snake(s)


def dict_keys_to_camel(obj: Any) -> Any:
    """Recursively convert dict keys from snake_case to camelCase for API responses."""
    if isinstance(obj, dict):
        return {to_camel_key(k): dict_keys_to_camel(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [dict_keys_to_camel(x) for x in obj]
    return obj


def dict_keys_to_snake(obj: Any) -> Any:
    """Recursively convert dict keys from camelCase to snake_case for API input normalization."""
    if isinstance(obj, dict):
        return {to_snake_key(k): dict_keys_to_snake(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [dict_keys_to_snake(x) for x in obj]
    return obj
