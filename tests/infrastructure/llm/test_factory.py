# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Tier 0 / Tier 1 provider factory (built from config)."""

from __future__ import annotations

import pytest

from bob.domain.ports import LLMProvider
from bob.infrastructure.llm.factory import build_tier_providers
from bob.infrastructure.llm.openai_compat import OpenAICompatProvider


def test_builds_both_tiers_from_config() -> None:
    # Arrange
    config = {
        "llm": {
            "tier0_base_url": "http://localhost:8080/v1",
            "tier0_model": "qwen2.5:0.5b",
            "tier1_base_url": "https://api.qwen.example/v1",
            "tier1_model": "qwen2.5:7b",
            "tier1_api_key": "sk-qwen",
        }
    }

    # Act
    providers = build_tier_providers(config)

    # Assert
    assert set(providers) == {0, 1}
    assert isinstance(providers[0], OpenAICompatProvider)
    assert isinstance(providers[0], LLMProvider)
    assert isinstance(providers[1], OpenAICompatProvider)


def test_tier0_has_no_api_key_tier1_uses_configured_key() -> None:
    # Arrange
    config = {
        "llm": {
            "tier0_base_url": "http://localhost:8080/v1",
            "tier0_model": "local",
            "tier1_base_url": "https://api.qwen.example/v1",
            "tier1_model": "remote",
            "tier1_api_key": "sk-qwen",
        }
    }

    # Act
    providers = build_tier_providers(config)

    # Assert: Tier 0 local => no auth; Tier 1 => configured key.
    tier0, tier1 = providers[0], providers[1]
    assert isinstance(tier0, OpenAICompatProvider)
    assert isinstance(tier1, OpenAICompatProvider)
    assert tier0._api_key is None
    assert tier1._api_key == "sk-qwen"


def test_missing_required_key_raises() -> None:
    # Arrange: tier1_base_url omitted.
    config = {"llm": {"tier0_base_url": "http://x/v1", "tier0_model": "m", "tier1_model": "r"}}

    # Act / Assert
    with pytest.raises(KeyError):
        build_tier_providers(config)


def test_missing_llm_section_raises() -> None:
    # Act / Assert: no 'llm' section at all is a configuration error.
    with pytest.raises(KeyError, match="llm"):
        build_tier_providers({})


def _full_llm() -> dict[str, object]:
    return {
        "tier0_base_url": "http://localhost:8080/v1",
        "tier0_model": "local",
        "tier1_base_url": "https://api.qwen.example/v1",
        "tier1_model": "remote",
    }


def test_optional_api_key_absent_yields_no_auth() -> None:
    # Arrange: tier1_api_key omitted entirely -> Tier 1 has no key.
    providers = build_tier_providers({"llm": _full_llm()})

    # Assert
    tier1 = providers[1]
    assert isinstance(tier1, OpenAICompatProvider)
    assert tier1._api_key is None


def test_optional_api_key_wrong_type_raises() -> None:
    # Arrange: a non-string tier1_api_key is a configuration error.
    config = {"llm": {**_full_llm(), "tier1_api_key": 123}}

    # Act / Assert
    with pytest.raises(KeyError, match="tier1_api_key"):
        build_tier_providers(config)
