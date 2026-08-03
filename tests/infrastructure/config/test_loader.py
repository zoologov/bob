# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ConfigLoader (layered: defaults -> YAML -> env)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.config.loader import DEFAULT_CONFIG, ConfigLoader

if TYPE_CHECKING:
    from pathlib import Path

# Fake tokens for the env-mapping tests (not real credentials).
_BOB_TOKEN = "bob-secret"  # noqa: S105 — test fixture, not a credential
_GUPPI_TOKEN = "guppi-secret"  # noqa: S105 — test fixture, not a credential


def test_load_returns_defaults_when_no_yaml_no_env() -> None:
    # Arrange
    loader = ConfigLoader(yaml_path=None, env={})

    # Act
    config = loader.load()

    # Assert: pure defaults are returned (and not the module-level object).
    assert config == DEFAULT_CONFIG
    assert config is not DEFAULT_CONFIG


def test_runtime_language_defaults_to_russian() -> None:
    # Self-generated text (proactive/monologue/reflection) defaults to Russian so
    # Bob does not drift to English when there is no user message to mirror (BOB-012).
    loader = ConfigLoader(yaml_path=None, env={})

    config = loader.load()

    assert config["runtime"]["language"] == "ru"


def test_yaml_overrides_defaults(tmp_path: Path) -> None:
    # Arrange
    yaml_file = tmp_path / "bob.yaml"
    yaml_file.write_text("llm:\n  tier1_model: qwen-max\n", encoding="utf-8")
    loader = ConfigLoader(yaml_path=yaml_file, env={})

    # Act
    config = loader.load()

    # Assert: the YAML value wins; untouched defaults remain.
    assert config["llm"]["tier1_model"] == "qwen-max"
    assert "tier0_model" in config["llm"]


def test_yaml_deep_merges_into_defaults(tmp_path: Path) -> None:
    # Arrange: YAML sets one nested key; sibling default keys must survive.
    yaml_file = tmp_path / "bob.yaml"
    yaml_file.write_text("runtime:\n  heartbeat_seconds: 5\n", encoding="utf-8")
    loader = ConfigLoader(yaml_path=yaml_file, env={})

    # Act
    config = loader.load()

    # Assert
    assert config["runtime"]["heartbeat_seconds"] == 5
    assert "log_level" in config["runtime"]


def test_env_overrides_yaml_and_defaults(tmp_path: Path) -> None:
    # Arrange
    yaml_file = tmp_path / "bob.yaml"
    yaml_file.write_text("llm:\n  tier1_model: from-yaml\n", encoding="utf-8")
    env = {"BOB_LLM__TIER1_MODEL": "from-env"}
    loader = ConfigLoader(yaml_path=yaml_file, env=env)

    # Act
    config = loader.load()

    # Assert: env (highest precedence) wins.
    assert config["llm"]["tier1_model"] == "from-env"


def test_env_keys_without_prefix_are_ignored() -> None:
    # Arrange
    env = {"PATH": "/usr/bin", "BOB_RUNTIME__LOG_LEVEL": "DEBUG"}
    loader = ConfigLoader(yaml_path=None, env=env)

    # Act
    config = loader.load()

    # Assert: only the BOB_-prefixed key is applied.
    assert config["runtime"]["log_level"] == "DEBUG"


def test_env_double_underscore_denotes_nesting() -> None:
    # Arrange
    env = {"BOB_TELEGRAM__POLL_TIMEOUT": "30"}
    loader = ConfigLoader(yaml_path=None, env=env)

    # Act
    config = loader.load()

    # Assert: BOB_<section>__<key> maps to config[section][key].
    assert config["telegram"]["poll_timeout"] == "30"


def test_missing_yaml_file_falls_back_to_defaults(tmp_path: Path) -> None:
    # Arrange: a path that does not exist must not raise.
    loader = ConfigLoader(yaml_path=tmp_path / "absent.yaml", env={})

    # Act
    config = loader.load()

    # Assert
    assert config == DEFAULT_CONFIG


def test_empty_yaml_file_is_treated_as_no_overrides(tmp_path: Path) -> None:
    # Arrange
    yaml_file = tmp_path / "empty.yaml"
    yaml_file.write_text("", encoding="utf-8")
    loader = ConfigLoader(yaml_path=yaml_file, env={})

    # Act
    config = loader.load()

    # Assert
    assert config == DEFAULT_CONFIG


def test_non_mapping_yaml_raises_value_error(tmp_path: Path) -> None:
    # Arrange: a YAML list is not a valid config root.
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text("- just\n- a\n- list\n", encoding="utf-8")
    loader = ConfigLoader(yaml_path=yaml_file, env={})

    # Act / Assert
    with pytest.raises(ValueError, match="mapping"):
        loader.load()


def test_load_does_not_mutate_default_config(tmp_path: Path) -> None:
    # Arrange
    yaml_file = tmp_path / "bob.yaml"
    yaml_file.write_text("llm:\n  tier1_model: mutated\n", encoding="utf-8")
    loader = ConfigLoader(yaml_path=yaml_file, env={})

    # Act
    loader.load()

    # Assert: the shared defaults are never mutated by a load.
    assert DEFAULT_CONFIG["llm"]["tier1_model"] != "mutated"


# --- Two-bot telegram config (BOB-003 BEAD-01) ------------------------------


def test_telegram_defaults_have_two_bot_shape() -> None:
    # Arrange
    loader = ConfigLoader(yaml_path=None, env={})

    # Act
    telegram = loader.load()["telegram"]

    # Assert: nested bob/guppi sub-bots + shared ids, with sane defaults.
    assert telegram["bob"]["token"] == ""
    assert telegram["bob"]["topic_id"] == 0
    assert telegram["guppi"]["token"] == ""
    assert telegram["chat_id"] == 0
    assert telegram["owner_id"] == 0
    assert telegram["allowed_chat_ids"] == []
    assert telegram["poll_timeout"] == 10


def test_llm_temperature_defaults_steady_tier0_varied_tier1() -> None:
    # BOB-022: a steadier Tier 0 (classification/sentiment) and a more varied Tier 1
    # (user-facing replies) so identical prompts no longer decode to identical text.
    loader = ConfigLoader(yaml_path=None, env={})

    # Act
    llm = loader.load()["llm"]

    # Assert
    assert llm["tier0_temperature"] == 0.5
    assert llm["tier1_temperature"] == 0.8


def test_llm_temperature_overridable_via_env() -> None:
    # Arrange: override the Tier 1 reply temperature via env only.
    loader = ConfigLoader(
        yaml_path=None,
        env={"BOB_LLM__TIER1_TEMPERATURE": "0.9"},
    )

    # Act
    llm = loader.load()["llm"]

    # Assert: env wins (arrives as a string; the factory parses it numerically).
    assert llm["tier1_temperature"] == "0.9"


def test_tier0_fallback_is_off_by_default() -> None:
    # BOB-087.E1: the local emergency model is an OPT-IN degraded mode — a fresh
    # config must build today's Tier 0 with no understudy attached.
    loader = ConfigLoader(yaml_path=None, env={})

    # Act
    llm = loader.load()["llm"]

    # Assert
    assert llm["tier0_fallback"] == ""


def test_tier0_fallback_endpoint_defaults_to_local_ollama() -> None:
    # The endpoint/model are pre-filled so turning the fallback on is a one-key
    # change; ``/v1`` is Ollama's OpenAI-compatible chat surface (unlike the bare
    # ``embeddings``/``reranker`` base_urls, whose adapters append their own paths).
    loader = ConfigLoader(yaml_path=None, env={})

    # Act
    llm = loader.load()["llm"]

    # Assert
    assert llm["tier0_fallback_base_url"] == "http://localhost:11434/v1"
    assert llm["tier0_fallback_model"] == "qwen2.5:0.5b"


def test_tier0_fallback_turned_on_via_env() -> None:
    # Arrange: the owner enables the emergency model without touching YAML.
    loader = ConfigLoader(yaml_path=None, env={"BOB_LLM__TIER0_FALLBACK": "ollama"})

    # Act
    llm = loader.load()["llm"]

    # Assert
    assert llm["tier0_fallback"] == "ollama"


def test_embeddings_defaults_are_local_bge_m3_1024() -> None:
    # Arrange
    loader = ConfigLoader(yaml_path=None, env={})

    # Act
    embeddings = loader.load()["embeddings"]

    # Assert: local Ollama, BGE-M3 dense 1024 (the BOB-011 locked stack).
    assert embeddings["base_url"] == "http://localhost:11434"
    assert embeddings["model"] == "bge-m3"
    assert embeddings["dim"] == 1024


def test_consolidation_defaults_are_conservative_and_off() -> None:
    # Arrange
    loader = ConfigLoader(yaml_path=None, env={})

    # Act
    consolidation = loader.load()["memory"]["consolidation"]

    # Assert: BOB-021 — off by default, conservative age/batch guardrails.
    assert consolidation["enabled"] is False
    assert consolidation["max_age_days"] == 14.0
    assert consolidation["batch_size"] == 50


def test_consolidation_overridable_via_env() -> None:
    # Arrange: switch consolidation on and tighten the age threshold via env only.
    loader = ConfigLoader(
        yaml_path=None,
        env={
            "BOB_MEMORY__CONSOLIDATION__ENABLED": "true",
            "BOB_MEMORY__CONSOLIDATION__MAX_AGE_DAYS": "7",
        },
    )

    # Act
    consolidation = loader.load()["memory"]["consolidation"]

    # Assert: env wins; the rest of the section keeps its defaults.
    assert consolidation["enabled"] == "true"
    assert consolidation["max_age_days"] == "7"
    assert consolidation["batch_size"] == 50


def test_diagram_defaults_are_high_quality_and_send_as_document() -> None:
    # BOB-037: max-readability defaults — high deviceScaleFactor, white background, and
    # send-as-document (uncompressed, full-resolution) so dense diagrams stay legible.
    loader = ConfigLoader(yaml_path=None, env={})

    diagrams = loader.load()["diagrams"]

    assert diagrams["enabled"] is True
    assert diagrams["mmdc_bin"] == "mmdc"
    assert diagrams["timeout"] == 30
    assert diagrams["scale"] == 3
    assert diagrams["background"] == "white"
    assert diagrams["send_as"] == "document"


def test_diagram_section_overridable_via_env() -> None:
    loader = ConfigLoader(
        yaml_path=None,
        env={
            "BOB_DIAGRAMS__SEND_AS": "photo",
            "BOB_DIAGRAMS__SCALE": "2",
        },
    )

    diagrams = loader.load()["diagrams"]

    assert diagrams["send_as"] == "photo"
    assert diagrams["scale"] == "2"
    assert diagrams["background"] == "white"


def test_embeddings_section_overridable_via_env() -> None:
    # Arrange: point the embedder at a different local model without code change.
    loader = ConfigLoader(
        yaml_path=None,
        env={"BOB_EMBEDDINGS__MODEL": "qwen3-embedding"},
    )

    # Act
    embeddings = loader.load()["embeddings"]

    # Assert: env wins; the rest of the section keeps its defaults.
    assert embeddings["model"] == "qwen3-embedding"
    assert embeddings["base_url"] == "http://localhost:11434"
    assert embeddings["dim"] == 1024


def test_bob_token_loads_from_bob_telegram_token_env() -> None:
    # Arrange: the existing var maps explicitly onto telegram.bob.token.
    env = {"BOB_TELEGRAM__TOKEN": _BOB_TOKEN}
    loader = ConfigLoader(yaml_path=None, env=env)

    # Act
    telegram = loader.load()["telegram"]

    # Assert
    assert telegram["bob"]["token"] == _BOB_TOKEN


def test_guppi_token_loads_from_guppi_telegram_token_env() -> None:
    # Arrange: the non-standard GUPPI_ prefix needs an explicit mapping.
    env = {"GUPPI_TELEGRAM__TOKEN": _GUPPI_TOKEN}
    loader = ConfigLoader(yaml_path=None, env=env)

    # Act
    telegram = loader.load()["telegram"]

    # Assert
    assert telegram["guppi"]["token"] == _GUPPI_TOKEN


def test_guppi_token_absent_keeps_empty_default() -> None:
    # Arrange: no GUPPI var set — graceful empty default (wired in BEAD-02).
    loader = ConfigLoader(yaml_path=None, env={})

    # Act
    telegram = loader.load()["telegram"]

    # Assert
    assert telegram["guppi"]["token"] == ""


def test_both_bot_tokens_load_together_from_their_env_vars() -> None:
    # Arrange
    env = {
        "BOB_TELEGRAM__TOKEN": _BOB_TOKEN,
        "GUPPI_TELEGRAM__TOKEN": _GUPPI_TOKEN,
    }
    loader = ConfigLoader(yaml_path=None, env=env)

    # Act
    telegram = loader.load()["telegram"]

    # Assert
    assert telegram["bob"]["token"] == _BOB_TOKEN
    assert telegram["guppi"]["token"] == _GUPPI_TOKEN


def test_telegram_ids_parse_from_yaml(tmp_path: Path) -> None:
    # Arrange: the shared/topic ids come from YAML (non-secret).
    yaml_file = tmp_path / "bob.yaml"
    yaml_file.write_text(
        "telegram:\n"
        "  chat_id: -1004372947307\n"
        "  owner_id: 27468732\n"
        "  allowed_chat_ids: [-1004372947307]\n"
        "  bob:\n"
        "    topic_id: 32\n",
        encoding="utf-8",
    )
    loader = ConfigLoader(yaml_path=yaml_file, env={})

    # Act
    telegram = loader.load()["telegram"]

    # Assert: ids parse; the env-fed token default survives the deep-merge.
    assert telegram["chat_id"] == -1004372947307
    assert telegram["owner_id"] == 27468732
    assert telegram["allowed_chat_ids"] == [-1004372947307]
    assert telegram["bob"]["topic_id"] == 32
    assert telegram["bob"]["token"] == ""


def test_guppi_env_token_overrides_yaml_placeholder(tmp_path: Path) -> None:
    # Arrange: env (highest precedence) wins over any YAML value for guppi.token.
    yaml_file = tmp_path / "bob.yaml"
    yaml_file.write_text(
        "telegram:\n  guppi:\n    token: from-yaml\n", encoding="utf-8"
    )
    env = {"GUPPI_TELEGRAM__TOKEN": _GUPPI_TOKEN}
    loader = ConfigLoader(yaml_path=yaml_file, env=env)

    # Act
    telegram = loader.load()["telegram"]

    # Assert
    assert telegram["guppi"]["token"] == _GUPPI_TOKEN
