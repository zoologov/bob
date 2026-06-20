# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for build_reranker: config -> optional Reranker (additive, off-by-default).

The reranker is an ADDITIVE boost, so "off" is a first-class state: an absent
section or ``enabled`` false yields ``None`` (the recall pipeline skips reranking),
never an error. When enabled, the factory reads the provider-agnostic
``base_url`` / ``model`` / ``top_n`` settings, tolerating env-string values.
"""

from __future__ import annotations

import pytest

from bob.domain.ports import Reranker
from bob.infrastructure.llm.ollama_reranker import OllamaReranker
from bob.infrastructure.llm.reranker_factory import build_reranker


def _section(**overrides: object) -> dict[str, object]:
    section: dict[str, object] = {
        "enabled": True,
        "base_url": "http://localhost:11434",
        "model": "bge-reranker-v2-m3",
        "top_n": 8,
    }
    section.update(overrides)
    return section


def test_absent_section_returns_none() -> None:
    assert build_reranker({}) is None


def test_disabled_returns_none() -> None:
    assert build_reranker({"reranker": _section(enabled=False)}) is None


def test_enabled_builds_ollama_reranker() -> None:
    reranker = build_reranker({"reranker": _section()})
    assert isinstance(reranker, OllamaReranker)
    assert isinstance(reranker, Reranker)


def test_env_string_enabled_is_truthy() -> None:
    reranker = build_reranker({"reranker": _section(enabled="true")})
    assert isinstance(reranker, OllamaReranker)


def test_env_string_top_n_is_parsed() -> None:
    reranker = build_reranker({"reranker": _section(top_n="5")})
    assert isinstance(reranker, OllamaReranker)


def test_missing_model_raises() -> None:
    section = _section()
    del section["model"]
    with pytest.raises(KeyError, match=r"reranker\.model"):
        build_reranker({"reranker": section})


def test_non_integer_top_n_raises() -> None:
    with pytest.raises(KeyError, match=r"reranker\.top_n"):
        build_reranker({"reranker": _section(top_n="not-a-number")})
