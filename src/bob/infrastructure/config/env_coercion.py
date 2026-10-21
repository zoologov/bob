# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:component=config

"""Env coercion — an env string takes the type of the built-in default at its path.

The environment carries strings only. Before BOB-116 they reached the config as
strings and every consumer's reader guessed the type; ``_int`` accepted only
``str.isdigit`` and so turned a NEGATIVE Telegram group id into its default ``0``.
The production config is now tracked in the (public) repository without any
identifiers, so ids arrive from ``/opt/bob/.env`` — and must arrive typed.

The rule is the type of the default, checked in this order (``bool`` before ``int``,
because ``bool`` is an ``int`` subclass):

* ``bool`` — ``true/false``, ``1/0``, ``yes/no``, ``on/off``, case-insensitive;
* ``int`` — an integer literal (a fraction is refused, not truncated);
* ``float`` — any float literal;
* ``list`` — comma-separated items, each coerced to the element type: the type of the
  default's elements, else the caller-declared type for an empty default, else ``str``;
  a blank value is the empty list;
* anything else, and a path with no default — the raw string, as before.

A value that cannot be coerced raises :class:`ValueError` naming the env key and the
config path, so a typo in ``.env`` stops the start instead of becoming a silent default.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_TRUE_SPELLINGS = frozenset({"true", "1", "yes", "on"})
_FALSE_SPELLINGS = frozenset({"false", "0", "no", "off"})
_LIST_SEPARATOR = ","

# The element types a list item may be coerced to.
type ElementType = type[bool] | type[int] | type[float] | type[str]

# A path with no built-in default: the env value keeps today's raw-string behaviour.
_NO_DEFAULT = object()


def coerce_env_value(
    env_key: str,
    path: Sequence[str],
    raw: str,
    *,
    defaults: Mapping[str, Any],
    list_element_types: Mapping[tuple[str, ...], ElementType],
) -> Any:
    """Return ``raw`` coerced to the type of ``defaults`` at ``path``.

    ``env_key`` and ``path`` only name the value in the error; ``list_element_types``
    declares the element type of a list whose default is empty (and so carries none).
    """
    default = _default_at(defaults, path)
    try:
        if isinstance(default, list):
            element_type = _element_type(default, list_element_types.get(tuple(path)))
            return _coerce_list(raw, element_type)
        if isinstance(default, bool | int | float):
            return _coerce_scalar(raw, _scalar_type(default))
    except ValueError as exc:
        dotted = ".".join(path)
        raise ValueError(f"{env_key}={raw!r} cannot be read as {dotted}: {exc}") from exc
    return raw


def _default_at(defaults: Mapping[str, Any], path: Sequence[str]) -> Any:
    cursor: Any = defaults
    for segment in path:
        if not isinstance(cursor, Mapping) or segment not in cursor:
            return _NO_DEFAULT
        cursor = cursor[segment]
    return cursor


def _element_type(default: list[Any], declared: ElementType | None) -> ElementType:
    if default:
        return _scalar_type(default[0])
    return declared if declared is not None else str


def _scalar_type(value: object) -> ElementType:
    if isinstance(value, bool):
        return bool
    if isinstance(value, int):
        return int
    if isinstance(value, float):
        return float
    return str


def _coerce_list(raw: str, element_type: ElementType) -> list[Any]:
    if not raw.strip():
        return []
    items = [item.strip() for item in raw.split(_LIST_SEPARATOR)]
    if any(not item for item in items):
        raise ValueError("an empty item in the comma-separated list")
    return [_coerce_scalar(item, element_type) for item in items]


def _coerce_scalar(raw: str, target: ElementType) -> bool | int | float | str:
    text = raw.strip()
    if target is bool:
        return _coerce_bool(text)
    if target is int:
        return int(text)
    if target is float:
        return float(text)
    return text


def _coerce_bool(text: str) -> bool:
    lowered = text.lower()
    if lowered in _TRUE_SPELLINGS:
        return True
    if lowered in _FALSE_SPELLINGS:
        return False
    raise ValueError(
        f"expected one of {sorted(_TRUE_SPELLINGS | _FALSE_SPELLINGS)}, got {text!r}"
    )
