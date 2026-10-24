"""Connector options: how a connector describes what it needs, and validating input against that."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from api.connector.connector import InvalidOptionsError


@dataclass(frozen=True)
class Option:
    """Describes one option a connector needs to be created."""

    type: type  # str | int | bool
    description: str
    default: Any = None
    optional: bool = False  # may be omitted even without a default
    secret: bool = False  # e.g. passwords; should be masked when displayed

    @property
    def required(self) -> bool:
        return not self.optional and self.default is None


def validate_options(
    spec: Mapping[str, Option], options: Mapping[str, Any]
) -> dict[str, Any]:
    """Check `options` against `spec`, returning them coerced with defaults filled in."""
    problems = [f"unknown option: {key}" for key in options if key not in spec]
    out: dict[str, Any] = {}
    for key, option in spec.items():
        value = options.get(key)
        if value is None:
            if option.required:
                problems.append(f"missing required option: {key}")
            out[key] = option.default
            continue
        try:
            out[key] = _coerce(value, option.type)
        except (TypeError, ValueError):
            problems.append(f"{key}: expected {option.type.__name__}")
    if problems:
        raise InvalidOptionsError(problems)
    return out


def _coerce(value: Any, expected: type) -> Any:
    # bool is a subclass of int, so check it explicitly in both directions.
    if expected is int and isinstance(value, str):
        return int(value)
    if isinstance(value, expected) and not (
        expected is int and isinstance(value, bool)
    ):
        return value
    raise TypeError(f"expected {expected.__name__}, got {type(value).__name__}")
