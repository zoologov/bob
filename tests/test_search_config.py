# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``search.*`` config section (BOB-053 .1, web_search provider).

The web-search skill is owner-only via authz, so the provider may default ON; the
key/host default to the Tier-1 Qwen MaaS values (verify .1 proved the Responses
API returns sources on the workspace key).
"""

from __future__ import annotations

from bob.infrastructure.config.loader import ConfigLoader


def _config() -> dict[str, object]:
    return ConfigLoader(yaml_path=None, env={}).load()


def test_search_section_present_with_enabled_flag() -> None:
    section = _config()["search"]
    assert isinstance(section, dict)
    assert section["enabled"] is True


def test_search_defaults_model_to_qwen37_plus() -> None:
    section = _config()["search"]
    assert isinstance(section, dict)
    assert section["model"] == "qwen3.7-plus"


def test_search_base_url_and_key_blank_by_default_for_tier1_fallback() -> None:
    # Blank by default -> the factory falls back to the Tier-1 Qwen MaaS host + key.
    section = _config()["search"]
    assert isinstance(section, dict)
    assert section["base_url"] == ""
    assert section["api_key"] == ""


def test_search_carries_generous_timeout() -> None:
    section = _config()["search"]
    assert isinstance(section, dict)
    assert section["timeout_seconds"] == 180
