# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Tier 0 / Tier 1 provider factory (built from config)."""

from __future__ import annotations

import pytest

from bob.infrastructure.llm.factory import build_tier_providers
from bob.infrastructure.llm.fallback_provider import FallbackLLMProvider
from bob.infrastructure.llm.openai_compat import OpenAICompatProvider
from bob.kernel.ports import LLMProvider


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


def test_tier0_picks_up_configured_api_key() -> None:
    # Arrange: Tier 0 points at a keyed/remote endpoint (e.g. Qwen API).
    config = {
        "llm": {
            "tier0_base_url": "https://api.qwen.example/v1",
            "tier0_model": "remote",
            "tier0_api_key": "sk-tier0",
            "tier1_base_url": "https://api.qwen.example/v1",
            "tier1_model": "remote",
            "tier1_api_key": "sk-qwen",
        }
    }

    # Act
    providers = build_tier_providers(config)

    # Assert: Tier 0 uses its configured key.
    tier0 = providers[0]
    assert isinstance(tier0, OpenAICompatProvider)
    assert tier0._api_key == "sk-tier0"


def test_tier0_api_key_absent_stays_keyless() -> None:
    # Arrange: no tier0_api_key -> keyless local mlx (backward compat).
    providers = build_tier_providers({"llm": _full_llm()})

    # Assert
    tier0 = providers[0]
    assert isinstance(tier0, OpenAICompatProvider)
    assert tier0._api_key is None


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


def test_timeout_seconds_threaded_into_both_providers() -> None:
    # Arrange: a generous timeout for slow reasoning models.
    config = {"llm": {**_full_llm(), "timeout_seconds": 180}}

    # Act
    providers = build_tier_providers(config)

    # Assert: both tiers carry the configured timeout.
    tier0, tier1 = providers[0], providers[1]
    assert isinstance(tier0, OpenAICompatProvider)
    assert isinstance(tier1, OpenAICompatProvider)
    assert tier0._timeout.total == 180.0
    assert tier1._timeout.total == 180.0


def test_timeout_seconds_defaults_when_absent() -> None:
    # Arrange: no timeout configured -> a safe reasoning-friendly default.
    providers = build_tier_providers({"llm": _full_llm()})

    # Assert
    tier1 = providers[1]
    assert isinstance(tier1, OpenAICompatProvider)
    assert tier1._timeout.total == 180.0


def test_disable_thinking_flag_threaded_into_providers() -> None:
    # Arrange: thinking disabled for cheap/fast non-reasoning replies.
    config = {"llm": {**_full_llm(), "disable_thinking": True}}

    # Act
    providers = build_tier_providers(config)

    # Assert
    tier0, tier1 = providers[0], providers[1]
    assert isinstance(tier0, OpenAICompatProvider)
    assert isinstance(tier1, OpenAICompatProvider)
    assert tier0._disable_thinking is True
    assert tier1._disable_thinking is True


def test_disable_thinking_defaults_off_when_absent() -> None:
    # Arrange: backward compat — no flag means thinking stays enabled.
    providers = build_tier_providers({"llm": _full_llm()})

    # Assert
    tier1 = providers[1]
    assert isinstance(tier1, OpenAICompatProvider)
    assert tier1._disable_thinking is False


def test_per_tier_temperature_threaded_into_providers() -> None:
    # BOB-022: a steadier Tier 0 (classification) and a more varied Tier 1
    # (user-facing replies) temperature reach the right provider.
    config = {"llm": {**_full_llm(), "tier0_temperature": 0.5, "tier1_temperature": 0.8}}

    # Act
    providers = build_tier_providers(config)

    # Assert
    tier0, tier1 = providers[0], providers[1]
    assert isinstance(tier0, OpenAICompatProvider)
    assert isinstance(tier1, OpenAICompatProvider)
    assert tier0._temperature == 0.5
    assert tier1._temperature == 0.8


def test_temperature_absent_stays_none() -> None:
    # Arrange: no temperature configured -> the provider forces nothing (endpoint
    # keeps its own default).
    providers = build_tier_providers({"llm": _full_llm()})

    # Assert
    tier0, tier1 = providers[0], providers[1]
    assert isinstance(tier0, OpenAICompatProvider)
    assert isinstance(tier1, OpenAICompatProvider)
    assert tier0._temperature is None
    assert tier1._temperature is None


def test_temperature_parses_from_env_string() -> None:
    # Env overlays arrive as strings; the factory tolerates a numeric string.
    config = {"llm": {**_full_llm(), "tier1_temperature": "0.8"}}

    # Act
    providers = build_tier_providers(config)

    # Assert
    tier1 = providers[1]
    assert isinstance(tier1, OpenAICompatProvider)
    assert tier1._temperature == 0.8


# --- Tier-0 local fallback (BOB-087.E1) -------------------------------------------


def _fallback_llm() -> dict[str, object]:
    return {
        **_full_llm(),
        "timeout_seconds": 90,
        "disable_thinking": True,
        "tier0_temperature": 0.5,
        "tier0_fallback": "ollama",
        "tier0_fallback_base_url": "http://localhost:11434/v1",
        "tier0_fallback_model": "qwen2.5:0.5b",
    }


def test_tier0_fallback_off_builds_exactly_todays_provider() -> None:
    # The OFF default must be byte-identical to the pre-BOB-087.E1 wiring: not merely
    # "an OpenAICompatProvider", but one whose every constructed attribute matches a
    # directly-built provider — no wrapper, no drifted knob.
    llm = {**_full_llm(), "timeout_seconds": 90, "disable_thinking": True}

    # Act
    providers = build_tier_providers({"llm": {**llm, "tier0_fallback": ""}})

    # Assert
    tier0 = providers[0]
    assert type(tier0) is OpenAICompatProvider
    assert tier0.__dict__ == _expected_tier0(llm).__dict__


def test_tier0_fallback_absent_builds_exactly_todays_provider() -> None:
    # Same proof for a config that never mentions the fallback key at all.
    llm = _full_llm()

    # Act
    providers = build_tier_providers({"llm": llm})

    # Assert
    tier0 = providers[0]
    assert type(tier0) is OpenAICompatProvider
    assert tier0.__dict__ == _expected_tier0(llm).__dict__


def _expected_tier0(llm: dict[str, object]) -> OpenAICompatProvider:
    """The Tier-0 provider today's (pre-fallback) factory code builds."""
    timeout = llm.get("timeout_seconds", 180)
    assert isinstance(timeout, (int, float))
    return OpenAICompatProvider(
        base_url=str(llm["tier0_base_url"]),
        model=str(llm["tier0_model"]),
        api_key=None,
        timeout_seconds=float(timeout),
        disable_thinking=bool(llm.get("disable_thinking", False)),
        temperature=None,
    )


def test_tier0_fallback_on_wraps_tier0_in_the_composite() -> None:
    # Act
    providers = build_tier_providers({"llm": _fallback_llm()})

    # Assert: Tier 0 is now the composite, still an LLMProvider.
    tier0 = providers[0]
    assert isinstance(tier0, FallbackLLMProvider)
    assert isinstance(tier0, LLMProvider)


def test_tier0_fallback_on_keeps_the_cloud_provider_as_primary() -> None:
    # The wrapped primary must be exactly the provider the OFF path would build.
    llm = _fallback_llm()

    # Act
    tier0 = build_tier_providers({"llm": llm})[0]

    # Assert
    assert isinstance(tier0, FallbackLLMProvider)
    primary = tier0._primary
    assert isinstance(primary, OpenAICompatProvider)
    assert primary._base_url == "http://localhost:8080/v1"
    assert primary._model == "local"
    assert primary._temperature == 0.5


def test_local_fallback_points_at_the_configured_ollama_endpoint() -> None:
    # Act
    tier0 = build_tier_providers({"llm": _fallback_llm()})[0]

    # Assert: keyless local endpoint, its own model.
    assert isinstance(tier0, FallbackLLMProvider)
    local = tier0._fallback
    assert isinstance(local, OpenAICompatProvider)
    assert local._base_url == "http://localhost:11434/v1"
    assert local._model == "qwen2.5:0.5b"
    assert local._api_key is None


def test_local_fallback_inherits_the_tier0_call_knobs() -> None:
    # The understudy must answer like Tier 0: same timeout, thinking policy and
    # sampling temperature — otherwise the degraded mode behaves like a third tier.
    tier0 = build_tier_providers({"llm": _fallback_llm()})[0]

    # Assert
    assert isinstance(tier0, FallbackLLMProvider)
    local = tier0._fallback
    assert isinstance(local, OpenAICompatProvider)
    assert local._timeout.total == 90.0
    assert local._disable_thinking is True
    assert local._temperature == 0.5


def test_tier0_fallback_leaves_tier1_untouched() -> None:
    # Act
    providers = build_tier_providers({"llm": _fallback_llm()})

    # Assert: Tier 1 is the plain cloud provider — the fallback is a Tier-0 affair.
    tier1 = providers[1]
    assert type(tier1) is OpenAICompatProvider
    assert tier1._base_url == "https://api.qwen.example/v1"


@pytest.mark.parametrize("value", ["Ollama", " ollama ", "OLLAMA"])
def test_tier0_fallback_value_is_case_and_space_tolerant(value: str) -> None:
    # Env overlays arrive as raw strings; a stray case/space must not silently
    # disable the emergency model.
    tier0 = build_tier_providers({"llm": {**_fallback_llm(), "tier0_fallback": value}})[0]

    # Assert
    assert isinstance(tier0, FallbackLLMProvider)


def test_unknown_fallback_kind_raises() -> None:
    # A typo must fail loudly at composition, not silently leave Tier 0 unprotected.
    config = {"llm": {**_fallback_llm(), "tier0_fallback": "llamacpp"}}

    # Act / Assert
    with pytest.raises(KeyError, match="tier0_fallback"):
        build_tier_providers(config)


def test_fallback_on_without_endpoint_raises() -> None:
    # Enabled but unconfigured is a configuration error (mirrors the reranker rule).
    llm = {**_fallback_llm()}
    del llm["tier0_fallback_base_url"]

    # Act / Assert
    with pytest.raises(KeyError, match="tier0_fallback_base_url"):
        build_tier_providers({"llm": llm})


def test_fallback_on_without_model_raises() -> None:
    llm = {**_fallback_llm()}
    del llm["tier0_fallback_model"]

    # Act / Assert
    with pytest.raises(KeyError, match="tier0_fallback_model"):
        build_tier_providers({"llm": llm})
