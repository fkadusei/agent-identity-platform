"""Coerce tool arguments to the types their schema declares.

Models frequently emit numbers as strings ("200"), and policy comparisons are
type-sensitive: in Rego a string sorts *after* any number, so `"200" > 500` is
true. Normalising here means policy evaluates the value, not its formatting.
"""
from __future__ import annotations


def _coerce(value, json_type: str | None):
    if value is None:
        return value
    try:
        if json_type == "number":
            return float(value)
        if json_type == "integer":
            return int(value)
        if json_type == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("true", "1", "yes")
        if json_type == "string":
            return value if isinstance(value, str) else str(value)
    except (TypeError, ValueError):
        # Fail closed: an unparseable number becomes None, never the raw value.
        # Policy must not be handed "-" or "lots" and have to reason about it.
        return None if json_type in ("number", "integer") else value
    return value


def coerce_args(properties: dict, args: dict) -> dict:
    """Keep only declared arguments, coerced to their declared types."""
    out: dict = {}
    for key, value in args.items():
        spec = properties.get(key)
        if spec is None:
            continue
        out[key] = _coerce(value, (spec or {}).get("type"))
    return out
