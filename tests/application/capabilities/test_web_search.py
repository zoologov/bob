# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``web_search`` — the grounded web-search skill (BOB-053 .2).

A thin wrapper over the :class:`~bob.domain.ports.WebSearchProvider` port: it
exposes the stable :class:`Capability` contract, validates the ``query``,
delegates to the port and projects the grounded answer + sources COMPACTLY into
the tool-loop (Bob synthesises the final reply in his own voice). It never
fabricates a "found" answer — a provider failure PROPAGATES (.3 owns
fault-tolerance), and an empty/whitespace query is answered honestly WITHOUT
calling the provider. Deterministic on a fake port — no network, no disk.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from bob.application.capabilities.web_search import make_web_search_capability
from bob.domain.ports import WebSearchResult, WebSource


class _FakeWebSearchProvider:
    """A scripted :class:`WebSearchProvider`: records queries, returns canned result."""

    def __init__(
        self,
        *,
        result: WebSearchResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result if result is not None else WebSearchResult(answer="")
        self._error = error
        self.queries: list[str] = []

    async def search(self, query: str) -> WebSearchResult:
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        return self._result


def test_capability_advertises_the_web_search_contract() -> None:
    cap = make_web_search_capability(_FakeWebSearchProvider())

    assert cap.name == "web_search"
    assert cap.description
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["query"] == {"type": "string"}
    assert schema["required"] == ["query"]


async def test_execute_projects_answer_and_sources_compactly() -> None:
    provider = _FakeWebSearchProvider(
        result=WebSearchResult(
            answer="Боб родился из Bobiverse.",
            sources=(
                WebSource(title="Wiki", url="https://example.com/a"),
                WebSource(title="", url="https://example.com/b"),
            ),
        )
    )
    cap = make_web_search_capability(provider)

    result = await cap.execute({"query": "кто такой Боб"})

    assert provider.queries == ["кто такой Боб"]
    assert isinstance(result, Mapping)
    assert result["answer"] == "Боб родился из Bobiverse."
    sources = result["sources"]
    assert sources == [
        {"title": "Wiki", "url": "https://example.com/a"},
        {"title": "", "url": "https://example.com/b"},
    ]


async def test_execute_with_empty_sources_still_returns_the_answer() -> None:
    provider = _FakeWebSearchProvider(
        result=WebSearchResult(answer="Обоснованный ответ без ссылок.")
    )
    cap = make_web_search_capability(provider)

    result = await cap.execute({"query": "что-то"})

    assert isinstance(result, Mapping)
    assert result["answer"] == "Обоснованный ответ без ссылок."
    assert result["sources"] == []


async def test_execute_with_empty_query_is_honest_and_skips_the_provider() -> None:
    provider = _FakeWebSearchProvider()
    cap = make_web_search_capability(provider)

    result = await cap.execute({"query": "   "})

    assert provider.queries == []  # provider NOT called on an empty query
    assert isinstance(result, Mapping)
    assert "запрос" in str(result["answer"]).lower()
    assert result["sources"] == []


async def test_execute_requires_a_string_query() -> None:
    cap = make_web_search_capability(_FakeWebSearchProvider())

    with pytest.raises(ValueError, match="query"):
        await cap.execute({"query": 123})


async def test_execute_with_missing_query_key_raises() -> None:
    cap = make_web_search_capability(_FakeWebSearchProvider())

    with pytest.raises(ValueError, match="query"):
        await cap.execute({})


async def test_execute_propagates_provider_failure_without_fabricating() -> None:
    # 🔴 Invariant: the skill NEVER swallows a provider failure to confabulate a
    # "found" answer — the error propagates and .3 owns fault-tolerance.
    provider = _FakeWebSearchProvider(error=RuntimeError("network down"))
    cap = make_web_search_capability(provider)

    with pytest.raises(RuntimeError, match="network down"):
        await cap.execute({"query": "свежие новости"})
