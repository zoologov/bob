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


def test_load_returns_defaults_when_no_yaml_no_env() -> None:
    # Arrange
    loader = ConfigLoader(yaml_path=None, env={})

    # Act
    config = loader.load()

    # Assert: pure defaults are returned (and not the module-level object).
    assert config == DEFAULT_CONFIG
    assert config is not DEFAULT_CONFIG


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
