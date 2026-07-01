# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Composition-root gating of the ``web_search`` skill (BOB-053 .2).

``_build_registry`` registers ``web_search`` ONLY when ``search.enabled`` — the
guardrail that keeps the Qwen-native search provider behind an explicit flag.
These tests drive that gate directly over a duck-typed recall fake (the
memory-capability factories only hold the reference; the gate never invokes
recall), with introspection + diagrams off so the registry holds EXACTLY the
memory capabilities ± web_search. The provider is constructed but spawns no
network call at construction, so this stays deterministic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.app import _build_registry

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class _FakeRecall:
    """A duck-typed MemoryRecall: never called by the registration gate."""

    async def recall(
        self, query: str, *, k: int = 5  # noqa: ARG002
    ) -> Sequence[object]:
        return []


def _llm() -> dict[str, object]:
    # The search provider defaults its base_url/api_key to the Tier-1 Qwen MaaS
    # values, so the gate needs a minimal llm section to build the provider.
    return {
        "tier1_base_url": "https://example.com/compatible-mode/v1",
        "tier1_model": "qwen3.7-plus",
        "tier1_api_key": "sk-test",
    }


def _config(*, search: Mapping[str, object] | None = None) -> dict[str, object]:
    # Introspection + diagrams off so the registry holds only memory caps ±
    # web_search — isolates the search gate from the unrelated skills.
    cfg: dict[str, object] = {
        "introspection": {"enabled": False},
        "diagrams": {"enabled": False},
        "llm": _llm(),
    }
    if search is not None:
        cfg["search"] = search
    return cfg


def _names(config: Mapping[str, object]) -> list[str]:
    registry, _sink, _renderer = _build_registry(config, recall=_FakeRecall())  # type: ignore[arg-type]
    return [
        str(tool["function"]["name"])  # type: ignore[index]
        for tool in registry.manifest()
    ]


def test_web_search_registered_when_search_enabled() -> None:
    names = _names(_config(search={"enabled": True}))

    assert "web_search" in names


def test_web_search_absent_when_search_disabled() -> None:
    names = _names(_config(search={"enabled": False}))

    assert "web_search" not in names


def test_web_search_absent_by_default_no_search_section() -> None:
    # No ``search`` section at all → the flag defaults False → skill not registered.
    names = _names(_config())

    assert "web_search" not in names
