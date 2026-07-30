# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``web_search`` — the grounded web-search skill (BOB-053 .2 + .3).

A thin wrapper over the :class:`~bob.domain.ports.WebSearchProvider` port: it
exposes the stable :class:`Capability` contract, validates the ``query``,
delegates to the port and projects the grounded answer + sources COMPACTLY into
the tool-loop (Bob synthesises the final reply in his own voice with links). It
never fabricates a "found" answer — an empty/whitespace query is answered
honestly WITHOUT calling the provider.

.3 (fault-tolerance, «полный Боб или честный GUPPI-нотис»): ``web_search`` is
ESSENTIAL when the model chose to search, so a provider failure is RETRIED a
bounded number of times (the BOB-049 essential helper) and, if it keeps failing,
the skill returns an HONEST "couldn't search" notice with anti-confabulation
guidance — NEVER a fabricated answer from training presented as if found.
Deterministic on a fake port + an injected sleep — no network, no disk, no delay.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import pytest

from bob.capabilities.ports import (
    ToolCall,
    ToolCallResult,
    ToolDefinition,
    WebSearchResult,
    WebSource,
)
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.capabilities.usecases.web_search import make_web_search_capability

if TYPE_CHECKING:
    from bob.kernel.ports import ToolLoopMessage


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


class _FlakyWebSearchProvider:
    """Fails ``fail_times`` then returns ``result``; records call count + queries."""

    def __init__(
        self,
        *,
        fail_times: int,
        result: WebSearchResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._fail_times = fail_times
        self._result = result if result is not None else WebSearchResult(answer="ok")
        self._error = error if error is not None else RuntimeError("transient")
        self.calls = 0
        self.queries: list[str] = []

    async def search(self, query: str) -> WebSearchResult:
        self.queries.append(query)
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error
        return self._result


class _RecordingSleep:
    """An injectable backoff sleep that records its delays and never really waits."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


class _ScriptedToolProvider:
    """Returns a scripted :class:`ToolCallResult` per turn; records fed messages."""

    def __init__(self, results: Sequence[ToolCallResult]) -> None:
        self._results = list(results)
        self.turns: list[list[dict[str, object]]] = []
        self._call = 0

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],  # noqa: ARG002
    ) -> ToolCallResult:
        self.turns.append([dict(m) for m in messages])
        index = min(self._call, len(self._results) - 1)
        self._call += 1
        return self._results[index]

    @property
    def all_text(self) -> str:
        return "\n".join(str(m.get("content", "")) for turn in self.turns for m in turn)


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


async def test_description_steers_synthesis_with_sources_not_raw_dump() -> None:
    # 🔴 Invariant «синтез, не дамп»: the manifest description tells the model to
    # synthesise in its own voice WITH the source links — not paste raw snippets.
    cap = make_web_search_capability(_FakeWebSearchProvider())

    desc = cap.description.lower()
    assert "synthes" in desc  # steer the model to synthesise, not dump
    assert "source" in desc  # ...and cite the source links


async def test_execute_retries_transient_failure_then_succeeds() -> None:
    # .3: web_search is ESSENTIAL when invoked — a transient provider blip is
    # retried (bounded, with backoff through the injected sleep) before giving up.
    provider = _FlakyWebSearchProvider(
        fail_times=2,
        result=WebSearchResult(
            answer="Свежий ответ.",
            sources=(WebSource(title="W", url="https://example.com/x"),),
        ),
    )
    sleep = _RecordingSleep()
    cap = make_web_search_capability(
        provider, attempts=3, backoff_seconds=0.5, sleep=sleep
    )

    result = await cap.execute({"query": "новости"})

    assert provider.calls == 3  # two failures retried, third succeeds
    assert sleep.delays == [0.5, 0.5]  # backoff awaited BETWEEN attempts only
    assert isinstance(result, Mapping)
    assert result["answer"] == "Свежий ответ."
    assert result["sources"] == [{"title": "W", "url": "https://example.com/x"}]


async def test_execute_exhausts_retries_then_returns_honest_notice() -> None:
    # 🔴 Invariant: a persistent provider failure NEVER yields a fabricated "found"
    # answer. After the bounded retry the skill returns an HONEST "couldn't search"
    # notice with anti-confabulation guidance — Bob tells the user the truth.
    provider = _FlakyWebSearchProvider(
        fail_times=99, error=RuntimeError("network down")
    )
    sleep = _RecordingSleep()
    cap = make_web_search_capability(
        provider, attempts=3, backoff_seconds=0.5, sleep=sleep
    )

    result = await cap.execute({"query": "свежие новости"})

    assert provider.calls == 3  # bounded retry attempted, then gave up
    assert sleep.delays == [0.5, 0.5]
    assert isinstance(result, Mapping)
    # No fabricated sources, and the answer is an explicit "couldn't search" caveat.
    assert result["sources"] == []
    answer = str(result["answer"]).lower()
    assert "поиск" in answer or "не смог" in answer or "не удалось" in answer
    # The projection carries an explicit anti-confabulation steer for synthesis.
    assert "guidance" in result
    assert str(result["guidance"]).strip()


async def test_execute_does_not_confabulate_when_provider_fails() -> None:
    # 🔴 Invariant: even with no retry budget (attempts=1) a provider failure is
    # turned into an honest notice — never a propagated crash, never a confabulation.
    provider = _FakeWebSearchProvider(error=RuntimeError("network down"))
    cap = make_web_search_capability(provider, attempts=1)

    result = await cap.execute({"query": "свежие новости"})

    assert isinstance(result, Mapping)
    assert result["sources"] == []
    assert "guidance" in result


def test_make_capability_rejects_non_positive_attempts() -> None:
    # The bounded-retry budget must be at least one try — a zero/negative budget
    # is a wiring error caught at construction, not a silent no-call.
    with pytest.raises(ValueError, match="attempts"):
        make_web_search_capability(_FakeWebSearchProvider(), attempts=0)


def test_make_capability_rejects_negative_backoff() -> None:
    with pytest.raises(ValueError, match="backoff"):
        make_web_search_capability(_FakeWebSearchProvider(), backoff_seconds=-1.0)


@pytest.mark.parametrize("query", ["", "   ", "\t", "\n", " \t\n "])
async def test_execute_blank_query_variants_are_honest_and_skip_provider(
    query: str,
) -> None:
    # Any whitespace-only query is answered honestly WITHOUT a provider call —
    # Bob never invents a search for a blank request (tab/newline/mixed included).
    provider = _FakeWebSearchProvider()
    cap = make_web_search_capability(provider)

    result = await cap.execute({"query": query})

    assert provider.queries == []
    assert isinstance(result, Mapping)
    assert result["sources"] == []


async def test_execute_blank_query_carries_no_failure_guidance() -> None:
    # The honest empty-query reply is NOT the failure notice: it must NOT carry the
    # anti-confabulation ``guidance`` key (that belongs to a provider failure only).
    cap = make_web_search_capability(_FakeWebSearchProvider())

    result = await cap.execute({"query": "   "})

    assert isinstance(result, Mapping)
    assert "guidance" not in result


async def test_execute_with_none_query_raises() -> None:
    # A null query is not a string -> a validation error (mirrors a non-string int).
    cap = make_web_search_capability(_FakeWebSearchProvider())

    with pytest.raises(ValueError, match="query"):
        await cap.execute({"query": None})


@pytest.mark.parametrize("attempts", [1, 2, 4])
async def test_execute_backoff_is_invoked_attempts_minus_one_times(
    attempts: int,
) -> None:
    # 🔴 Bounded retry: the provider is called exactly ``attempts`` times and the
    # injected backoff is awaited BETWEEN tries only (attempts-1), never confabulating.
    provider = _FlakyWebSearchProvider(fail_times=99, error=RuntimeError("down"))
    sleep = _RecordingSleep()
    cap = make_web_search_capability(
        provider, attempts=attempts, backoff_seconds=0.25, sleep=sleep
    )

    result = await cap.execute({"query": "новости"})

    assert provider.calls == attempts
    assert sleep.delays == [0.25] * (attempts - 1)
    assert isinstance(result, Mapping)
    assert result["sources"] == []
    assert "guidance" in result  # honest notice, never a fabricated answer


async def test_failure_notice_never_leaks_a_fabricated_answer() -> None:
    # 🔴 No confabulation: even though the provider would have a "found" answer were
    # it not erroring, on persistent failure the projection is the FIXED honest
    # notice — it carries no url, no provider answer, only the caveat + guidance.
    would_have = WebSearchResult(
        answer="Президент подписал указ вчера.",
        sources=(WebSource(title="Leak", url="https://leak.example/secret"),),
    )
    provider = _FakeWebSearchProvider(result=would_have, error=RuntimeError("down"))
    cap = make_web_search_capability(provider, attempts=1)

    result = await cap.execute({"query": "свежие новости"})

    assert isinstance(result, Mapping)
    answer = str(result["answer"])
    assert "указ" not in answer  # the would-be answer never surfaces
    assert "leak.example" not in answer
    assert result["sources"] == []  # no fabricated sources
    assert str(result["guidance"]).strip()


async def test_tool_loop_feeds_honest_search_failure_not_generic_error() -> None:
    # 🔴 End-to-end at the seam: a failed web_search reaches the model as the
    # explicit honest notice + anti-confabulation guidance (so Bob can voice the
    # caveat in his own words) — NOT the bare generic "capability failed" error,
    # and NOT a silent answer-from-memory-as-if-found.
    provider = _FakeWebSearchProvider(error=RuntimeError("down"))
    registry = CapabilityRegistry()
    registry.register(make_web_search_capability(provider, attempts=1))
    call = ToolCall(id="c1", name="web_search", arguments={"query": "что нового"})
    model = _ScriptedToolProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="Честно: поискать не вышло.", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=model, registry=registry)

    answer = await loop.run([{"role": "user", "content": "что нового?"}])

    fed = model.all_text
    assert "guidance" in fed  # the anti-confabulation steer reached the model
    assert "error: capability 'web_search' failed" not in fed  # not the bare error
    assert answer == "Честно: поискать не вышло."
