# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Factory building the ``read_url`` page reader from configuration (BOB-054).

Reads the ``read_url`` section of the merged config (defaults -> YAML -> env, see
:mod:`bob.infrastructure.config.loader`) and constructs an :class:`HttpUrlReader`.
Mirrors :func:`bob.infrastructure.llm.factory.build_web_search_provider`: every limit
is threaded from config with a sane default, nothing hardcoded in the reader.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from bob.infrastructure.web.http_url_reader import HttpUrlReader

if TYPE_CHECKING:
    from bob.domain.ports import UrlReader

_DEFAULT_TIMEOUT_SECONDS = 15.0
_DEFAULT_MAX_BYTES = 2_000_000
_DEFAULT_MAX_REDIRECTS = 5
_DEFAULT_MAX_CHARS = 10_000
_DEFAULT_USER_AGENT = "BobBot/0.1 (+https://github.com/vzoologov/bob)"


def build_url_reader(config: Mapping[str, object]) -> UrlReader:
    """Build the SSRF-guarded HTTP page reader from ``config['read_url']`` (BOB-054)."""
    section = config.get("read_url")
    if not isinstance(section, Mapping):
        raise KeyError("config is missing the 'read_url' section")

    return HttpUrlReader(
        timeout_seconds=_optional_float(section, "timeout_seconds", _DEFAULT_TIMEOUT_SECONDS),
        max_bytes=_optional_int(section, "max_bytes", _DEFAULT_MAX_BYTES),
        max_redirects=_optional_int(section, "max_redirects", _DEFAULT_MAX_REDIRECTS),
        max_chars=_optional_int(section, "max_chars", _DEFAULT_MAX_CHARS),
        user_agent=_optional_str(section, "user_agent") or _DEFAULT_USER_AGENT,
    )


def _optional_str(section: Mapping[str, object], key: str) -> str | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise KeyError(f"read_url.{key} must be a string when set")
    return value or None


def _optional_float(section: Mapping[str, object], key: str, default: float) -> float:
    value = section.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        raise KeyError(f"read_url.{key} must be a number")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise KeyError(f"read_url.{key} must be a number") from exc
    raise KeyError(f"read_url.{key} must be a number")


def _optional_int(section: Mapping[str, object], key: str, default: int) -> int:
    value = section.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        raise KeyError(f"read_url.{key} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise KeyError(f"read_url.{key} must be an integer") from exc
    raise KeyError(f"read_url.{key} must be an integer")
