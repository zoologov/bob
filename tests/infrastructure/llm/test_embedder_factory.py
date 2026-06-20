# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Embedder factory (built from the ``embeddings`` config section)."""

from __future__ import annotations

import pytest

from bob.domain.ports import Embedder
from bob.infrastructure.config.loader import DEFAULT_CONFIG
from bob.infrastructure.llm.embedder_factory import build_embedder
from bob.infrastructure.llm.ollama_embedder import OllamaEmbedder


def test_builds_ollama_embedder_from_config() -> None:
    # Arrange
    config = {
        "embeddings": {
            "base_url": "http://localhost:11434",
            "model": "bge-m3",
            "dim": 1024,
        }
    }

    # Act
    embedder = build_embedder(config)

    # Assert
    assert isinstance(embedder, OllamaEmbedder)
    assert isinstance(embedder, Embedder)


def test_defaults_provide_a_complete_embeddings_section() -> None:
    # The shipped defaults alone must build a working embedder (local Ollama).
    embedder = build_embedder(DEFAULT_CONFIG)
    assert isinstance(embedder, OllamaEmbedder)


def test_default_embeddings_values_are_local_bge_m3_1024() -> None:
    section = DEFAULT_CONFIG["embeddings"]
    assert section["base_url"] == "http://localhost:11434"
    assert section["model"] == "bge-m3"
    assert section["dim"] == 1024


def test_missing_embeddings_section_is_an_error() -> None:
    with pytest.raises(KeyError, match="embeddings"):
        build_embedder({})


def test_blank_base_url_is_an_error() -> None:
    config = {"embeddings": {"base_url": "", "model": "bge-m3", "dim": 1024}}
    with pytest.raises(KeyError, match="base_url"):
        build_embedder(config)


def test_non_integer_dim_is_an_error() -> None:
    config = {"embeddings": {"base_url": "http://h", "model": "bge-m3", "dim": "wide"}}
    with pytest.raises(KeyError, match="dim"):
        build_embedder(config)


def test_boolean_dim_is_an_error() -> None:
    # ``True`` is an int subtype but never a valid dimension.
    config = {"embeddings": {"base_url": "http://h", "model": "bge-m3", "dim": True}}
    with pytest.raises(KeyError, match="dim"):
        build_embedder(config)


def test_missing_dim_is_an_error() -> None:
    config = {"embeddings": {"base_url": "http://h", "model": "bge-m3"}}
    with pytest.raises(KeyError, match="dim"):
        build_embedder(config)


def test_dim_accepts_env_string_value() -> None:
    # Env overrides arrive as strings (BOB_EMBEDDINGS__DIM=1024); tolerate that.
    config = {
        "embeddings": {
            "base_url": "http://localhost:11434",
            "model": "bge-m3",
            "dim": "1024",
        }
    }
    embedder = build_embedder(config)
    assert isinstance(embedder, OllamaEmbedder)
