# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``read_url.*`` config section (BOB-054 .1, page reader).

The read-url skill is owner-only via authz, so the reader may default ON; the limits
(timeout / max_bytes / max_redirects / max_chars) and the fixed User-Agent are threaded
from config into the SSRF-guarded HttpUrlReader.
"""

from __future__ import annotations

from bob.infrastructure.config.loader import ConfigLoader


def _config() -> dict[str, object]:
    return ConfigLoader(yaml_path=None, env={}).load()


def test_read_url_section_present_with_enabled_flag() -> None:
    section = _config()["read_url"]
    assert isinstance(section, dict)
    assert section["enabled"] is True


def test_read_url_carries_all_limits() -> None:
    section = _config()["read_url"]
    assert isinstance(section, dict)
    assert section["timeout_seconds"] == 15
    assert section["max_bytes"] == 2_000_000
    assert section["max_redirects"] == 5
    assert section["max_chars"] == 10_000


def test_read_url_has_fixed_user_agent() -> None:
    section = _config()["read_url"]
    assert isinstance(section, dict)
    user_agent = section["user_agent"]
    assert isinstance(user_agent, str)
    assert user_agent
