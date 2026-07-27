# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the page-reader factory (built from config, BOB-054 .1).

The ``read_url.*`` section builds an :class:`HttpUrlReader`; every limit is threaded
from config (with sane defaults), nothing hardcoded in the reader.
"""

from __future__ import annotations

import pytest

from bob.capabilities.adapters.web.factory import build_url_reader
from bob.capabilities.adapters.web.http_url_reader import HttpUrlReader
from bob.domain.ports import UrlReader


def test_builds_reader_from_read_url_section() -> None:
    config = {"read_url": {"enabled": True}}

    reader = build_url_reader(config)

    assert isinstance(reader, HttpUrlReader)
    assert isinstance(reader, UrlReader)


def test_threads_limits_from_config() -> None:
    config = {
        "read_url": {
            "enabled": True,
            "timeout_seconds": 30,
            "max_bytes": 500,
            "max_redirects": 2,
            "max_chars": 42,
            "user_agent": "Custom/9.9",
        }
    }

    reader = build_url_reader(config)

    assert isinstance(reader, HttpUrlReader)
    assert reader._timeout.total == 30.0
    assert reader._max_bytes == 500
    assert reader._max_redirects == 2
    assert reader._max_chars == 42
    assert reader._user_agent == "Custom/9.9"


def test_falls_back_to_defaults_when_unset() -> None:
    reader = build_url_reader({"read_url": {"enabled": True}})

    assert isinstance(reader, HttpUrlReader)
    assert reader._max_bytes == 2_000_000
    assert reader._max_redirects == 5
    assert reader._max_chars == 10_000
    assert reader._user_agent


def test_missing_read_url_section_raises() -> None:
    with pytest.raises(KeyError, match="read_url"):
        build_url_reader({})
