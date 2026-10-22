# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ConfigLoader (layered: defaults -> YAML -> env)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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

    # Assert: BOB_<section>__<key> maps to config[section][key], typed like the default.
    assert config["telegram"]["poll_timeout"] == 30


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

    # Assert: env wins, coerced to the float type of the default (BOB-116).
    assert llm["tier1_temperature"] == 0.9


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


def test_owner_address_defaults_to_empty_and_comes_from_env_as_text() -> None:
    # BOB-126: «как обращаться к владельцу» — необязательная строка из .env; пусто — по
    # первому слову owner_name. Строковый дефолт держит тип: «Вова» не превращается в число.
    default = ConfigLoader(yaml_path=None, env={}).load()["telegram"]
    configured = ConfigLoader(
        yaml_path=None, env={"BOB_TELEGRAM__OWNER_ADDRESS": "Вова"}
    ).load()["telegram"]

    assert default["owner_address"] == ""
    assert configured["owner_address"] == "Вова"


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
    assert consolidation["enabled"] is True
    assert consolidation["max_age_days"] == 7.0
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
    assert diagrams["scale"] == 2
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


# --- Env values typed like the default at their path (BOB-116 D8a) -------------
#
# Env carries strings only. Before BOB-116 they landed in the config as strings, and the
# consumers' readers guessed: ``_int`` took ``str.isdigit`` and so turned a NEGATIVE group
# id (every Telegram supergroup) into the default ``0``. The loader now coerces each env
# value to the type of the built-in default at the same path, and refuses a value it
# cannot coerce by naming the env key.


def _load_env(env: dict[str, str]) -> dict[str, Any]:
    return ConfigLoader(yaml_path=None, env=env).load()


def test_env_negative_group_id_becomes_an_int() -> None:
    telegram = _load_env({"BOB_TELEGRAM__CHAT_ID": "-100123"})["telegram"]

    assert telegram["chat_id"] == -100123


def test_env_owner_id_becomes_an_int() -> None:
    telegram = _load_env({"BOB_TELEGRAM__OWNER_ID": "123"})["telegram"]

    assert telegram["owner_id"] == 123
    assert type(telegram["owner_id"]) is int


def test_env_nested_topic_id_spelled_with_double_separators_becomes_an_int() -> None:
    telegram = _load_env({"BOB_TELEGRAM__BOB__TOPIC_ID": "32"})["telegram"]

    assert telegram["bob"]["topic_id"] == 32
    assert type(telegram["bob"]["topic_id"]) is int


def test_env_allowed_chat_ids_csv_becomes_a_list_of_ints() -> None:
    telegram = _load_env({"BOB_TELEGRAM__ALLOWED_CHAT_IDS": "-100123, -100456"})["telegram"]

    assert telegram["allowed_chat_ids"] == [-100123, -100456]


def test_env_single_allowed_chat_id_is_a_one_element_list() -> None:
    telegram = _load_env({"BOB_TELEGRAM__ALLOWED_CHAT_IDS": "-100123"})["telegram"]

    assert telegram["allowed_chat_ids"] == [-100123]


def test_env_blank_list_is_an_empty_list() -> None:
    telegram = _load_env({"BOB_TELEGRAM__ALLOWED_CHAT_IDS": "  "})["telegram"]

    assert telegram["allowed_chat_ids"] == []


def test_env_list_with_int_default_elements_becomes_a_list_of_ints() -> None:
    health = _load_env({"BOB_LLM__HEALTH__PROBE_SECONDS": "30,90"})["llm"]["health"]

    assert health["probe_seconds"] == [30, 90]


def test_env_empty_list_default_with_no_declared_element_type_is_a_list_of_strings() -> None:
    coder = _load_env({"BOB_CODER__EXTRA_DIRS": "/srv/a, /srv/b"})["coder"]

    assert coder["extra_dirs"] == ["/srv/a", "/srv/b"]


@pytest.mark.parametrize("raw", ["true", "TRUE", "1", "yes", "Yes", "on", " true "])
def test_env_truthy_spellings_become_true(raw: str) -> None:
    llm = _load_env({"BOB_LLM__DISABLE_THINKING": raw})["llm"]

    assert llm["disable_thinking"] is True


@pytest.mark.parametrize("raw", ["false", "FALSE", "0", "no", "No", "off"])
def test_env_falsy_spellings_become_false(raw: str) -> None:
    llm = _load_env({"BOB_LLM__DISABLE_THINKING": raw})["llm"]

    assert llm["disable_thinking"] is False


def test_env_float_default_accepts_a_fraction() -> None:
    # The cloud timeout is read as a float by the LLM factory, so its default says so
    # and a sub-second env value (the Tier-0 harness uses one) stays legal.
    llm = _load_env({"BOB_LLM__TIMEOUT_SECONDS": "0.35"})["llm"]

    assert llm["timeout_seconds"] == 0.35


def test_env_float_default_accepts_a_whole_number_as_a_float() -> None:
    llm = _load_env({"BOB_LLM__TIER0_TEMPERATURE": "1"})["llm"]

    assert llm["tier0_temperature"] == 1.0
    assert type(llm["tier0_temperature"]) is float


def test_env_string_default_keeps_a_digit_string_a_string() -> None:
    llm = _load_env({"BOB_LLM__TIER1_MODEL": "7"})["llm"]

    assert llm["tier1_model"] == "7"


def test_env_path_with_no_default_keeps_the_raw_string() -> None:
    # owner_dm_chat_id has no built-in default on purpose (it falls back to owner_id
    # in the consumer), so the loader has no type to coerce to.
    config = _load_env(
        {"BOB_TELEGRAM__OWNER_DM_CHAT_ID": "555", "BOB_UNKNOWN__KNOB": "42"}
    )

    assert config["telegram"]["owner_dm_chat_id"] == "555"
    assert config["unknown"] == {"knob": "42"}


@pytest.mark.parametrize(
    ("env_key", "raw"),
    [
        ("BOB_TELEGRAM__OWNER_ID", "abc"),
        ("BOB_TELEGRAM__OWNER_ID", "1.5"),
        ("BOB_TELEGRAM__OWNER_ID", ""),
        ("BOB_TELEGRAM__OWNER_ID", "true"),
        ("BOB_LLM__DISABLE_THINKING", "maybe"),
        ("BOB_LLM__TIER1_TEMPERATURE", "warm"),
        ("BOB_TELEGRAM__ALLOWED_CHAT_IDS", "-100,x"),
        ("BOB_TELEGRAM__ALLOWED_CHAT_IDS", "-100,,-200"),
        ("BOB_LLM__HEALTH__REMINDERS_SECONDS", "600,1h"),
    ],
)
def test_env_value_that_cannot_be_coerced_raises_naming_the_key(env_key: str, raw: str) -> None:
    with pytest.raises(ValueError, match=env_key):
        _load_env({env_key: raw})


def test_env_coercion_error_names_the_config_path_too() -> None:
    with pytest.raises(ValueError, match=r"telegram\.bob\.topic_id"):
        _load_env({"BOB_TELEGRAM__BOB__TOPIC_ID": "general"})


def test_llm_health_defaults_spell_out_the_rfc_policy() -> None:
    health = _load_env({})["llm"]["health"]

    assert health == {
        "failures_threshold": 5,
        "duration_threshold_seconds": 180,
        "reminders_seconds": [600, 3600, 21600, 86400],
        "probe_seconds": [60, 120, 300],
        "owner_alert": True,
    }


def test_llm_health_owner_alert_can_be_switched_off_from_env() -> None:
    health = _load_env({"BOB_LLM__HEALTH__OWNER_ALERT": "false"})["llm"]["health"]

    assert health["owner_alert"] is False
    assert health["failures_threshold"] == 5
