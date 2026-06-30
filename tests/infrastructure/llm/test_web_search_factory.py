# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the web-search provider factory (built from config, BOB-053 .1).

The ``search.*`` section builds a :class:`QwenWebSearchProvider`. ``base_url`` /
``api_key`` default to the Tier-1 (Qwen MaaS) values — the same workspace host +
``sk`` key verify .1 proved returns sources via the Responses API.
"""

from __future__ import annotations

import pytest

from bob.domain.ports import WebSearchProvider
from bob.infrastructure.llm.factory import build_web_search_provider
from bob.infrastructure.llm.web_search_qwen import QwenWebSearchProvider


def _llm() -> dict[str, object]:
    return {
        "tier1_base_url": "https://maas.example/compatible-mode/v1",
        "tier1_api_key": "sk-qwen",
    }


def test_builds_provider_from_search_section() -> None:
    config = {"llm": _llm(), "search": {"enabled": True, "model": "qwen3.7-plus"}}

    provider = build_web_search_provider(config)

    assert isinstance(provider, QwenWebSearchProvider)
    assert isinstance(provider, WebSearchProvider)


def test_search_defaults_base_url_and_key_to_tier1() -> None:
    # search.base_url / search.api_key unset -> fall back to the Tier-1 Qwen MaaS values.
    config = {"llm": _llm(), "search": {"enabled": True}}

    provider = build_web_search_provider(config)

    assert isinstance(provider, QwenWebSearchProvider)
    assert provider._base_url == "https://maas.example/compatible-mode/v1"
    assert provider._api_key == "sk-qwen"
    # Default model when unset.
    assert provider._model == "qwen3.7-plus"


def test_search_section_overrides_base_url_and_key() -> None:
    config = {
        "llm": _llm(),
        "search": {
            "enabled": True,
            "model": "qwen3.7-max",
            "base_url": "https://other.example/compatible-mode/v1",
            "api_key": "sk-other",
        },
    }

    provider = build_web_search_provider(config)

    assert isinstance(provider, QwenWebSearchProvider)
    assert provider._base_url == "https://other.example/compatible-mode/v1"
    assert provider._api_key == "sk-other"
    assert provider._model == "qwen3.7-max"


def test_search_timeout_defaults_to_generous_value() -> None:
    config = {"llm": _llm(), "search": {"enabled": True}}

    provider = build_web_search_provider(config)

    assert isinstance(provider, QwenWebSearchProvider)
    assert provider._timeout.total == 180.0


def test_search_timeout_threaded_from_config() -> None:
    config = {"llm": _llm(), "search": {"enabled": True, "timeout_seconds": 240}}

    provider = build_web_search_provider(config)

    assert isinstance(provider, QwenWebSearchProvider)
    assert provider._timeout.total == 240.0


def test_missing_search_section_raises() -> None:
    with pytest.raises(KeyError, match="search"):
        build_web_search_provider({"llm": _llm()})


def test_missing_base_url_raises_when_no_tier1_fallback() -> None:
    # No search.base_url and no tier1_base_url -> a configuration error.
    with pytest.raises(KeyError):
        build_web_search_provider({"llm": {}, "search": {"enabled": True}})
