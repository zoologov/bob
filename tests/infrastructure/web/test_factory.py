# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``build_url_reader`` — config → SSRF-guarded page reader (BOB-054 .3).

The factory is the ONLY place ``read_url`` limits are chosen, so its config-parsing
contract is locked here: a valid ``read_url`` section yields a :class:`UrlReader`;
native / string-coercible numbers are accepted; a missing section or a malformed value
raises ``KeyError`` rather than silently building a mis-configured reader. Booleans are
never accepted as numbers (Python's ``bool`` is an ``int``). No network is touched — the
reader opens no socket at construction.
"""

from __future__ import annotations

import pytest

from bob.capabilities.adapters.web.factory import build_url_reader
from bob.capabilities.ports import UrlReader


def _config(**read_url: object) -> dict[str, object]:
    return {"read_url": dict(read_url)}


def test_missing_read_url_section_raises_key_error() -> None:
    with pytest.raises(KeyError, match="read_url"):
        build_url_reader({})


def test_non_mapping_read_url_section_raises_key_error() -> None:
    with pytest.raises(KeyError, match="read_url"):
        build_url_reader({"read_url": "not-a-mapping"})


def test_builds_reader_from_minimal_section_with_defaults() -> None:
    reader = build_url_reader(_config(enabled=True))
    assert isinstance(reader, UrlReader)


def test_builds_reader_when_all_limits_supplied_natively() -> None:
    reader = build_url_reader(
        _config(
            timeout_seconds=5.0,
            max_bytes=1_000,
            max_redirects=2,
            max_chars=500,
            user_agent="Custom/1.0",
        )
    )
    assert isinstance(reader, UrlReader)


@pytest.mark.parametrize("timeout", [3, 3.5, "7.5"])
def test_timeout_accepts_int_float_and_numeric_string(timeout: object) -> None:
    reader = build_url_reader(_config(timeout_seconds=timeout))
    assert isinstance(reader, UrlReader)


@pytest.mark.parametrize("bad_timeout", ["abc", True, [1.0]])
def test_malformed_timeout_raises_key_error(bad_timeout: object) -> None:
    with pytest.raises(KeyError, match="timeout_seconds"):
        build_url_reader(_config(timeout_seconds=bad_timeout))


@pytest.mark.parametrize("max_bytes", [4096, "8192"])
def test_int_limit_accepts_int_and_numeric_string(max_bytes: object) -> None:
    reader = build_url_reader(_config(max_bytes=max_bytes))
    assert isinstance(reader, UrlReader)


@pytest.mark.parametrize("bad_value", ["not-int", True, 3.5, [1]])
def test_malformed_int_limit_raises_key_error(bad_value: object) -> None:
    with pytest.raises(KeyError, match="max_bytes"):
        build_url_reader(_config(max_bytes=bad_value))


def test_blank_user_agent_falls_back_to_default() -> None:
    reader = build_url_reader(_config(user_agent=""))
    assert isinstance(reader, UrlReader)


def test_omitted_user_agent_falls_back_to_default() -> None:
    reader = build_url_reader(_config(enabled=True))
    assert isinstance(reader, UrlReader)


def test_non_string_user_agent_raises_key_error() -> None:
    with pytest.raises(KeyError, match="user_agent"):
        build_url_reader(_config(user_agent=123))
