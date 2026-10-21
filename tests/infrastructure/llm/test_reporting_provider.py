# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Обёртка-докладчик: исход каждого вызова провайдера — в монитор здоровья (BOB-116 F1).

Одна обёртка для любого тира: её надевает фабрика, и тогда исход видят все, кто зовёт этого
провайдера, — роутер и ToolLoop одинаково. Класс отказа — тот же
:func:`~bob.application.router.fallback_policy.classify_failure`, что выносят роутер и дублёр.

🔴 Контракт D5: отказ записан ДО того, как исключение ушло вызывающему.
🔴 Зеркало возможностей (BOB-087.E1b): обёртка умеет ``complete_with_tools`` ровно тогда,
когда умеет обёрнутый провайдер — шов ToolLoop проверяет это через ``hasattr``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from bob.infrastructure.llm.reporting_provider import (
    ReportingLLMProvider,
    ToolCallingReportingLLMProvider,
    build_reporting_provider,
)
from bob.kernel.ports import (
    SelfReportingProvider,
    ToolCallingProvider,
    ToolCallResult,
    UnderstudyBackedProvider,
)
from bob.kernel.provider_health import TIER1

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from bob.kernel.ports import LLMMessage, ToolDefinition, ToolLoopMessage

_MESSAGES: list[LLMMessage] = [{"role": "user", "content": "привет"}]
_TOOL_MESSAGES: list[ToolLoopMessage] = [{"role": "user", "content": "почитай код"}]
_TOOLS: list[ToolDefinition] = [{"type": "function", "function": {"name": "read_code"}}]


def _http_error(status: int) -> aiohttp.ClientResponseError:
    url = URL("http://tier1.example/v1/chat/completions")
    headers: CIMultiDictProxy[str] = CIMultiDictProxy(CIMultiDict())
    request_info = aiohttp.RequestInfo(url, "POST", headers, url)
    return aiohttp.ClientResponseError(request_info, (), status=status, message="boom")


class _Journal:
    """Что монитор услышал — и что вызывающий уже видел в этот момент."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str | None]] = []

    async def record_success(self, provider_id: str) -> None:
        self.records.append((provider_id, None))

    async def record_failure(self, provider_id: str, failure_class: str) -> None:
        self.records.append((provider_id, failure_class))


class _Provider:
    def __init__(self, *, reply: str = "ok", error: BaseException | None = None) -> None:
        self._reply = reply
        self._error = error
        self.calls = 0

    async def complete(
        self, messages: Sequence[LLMMessage], *, stream: bool = False
    ) -> str | AsyncIterator[str]:
        del messages
        self.calls += 1
        if self._error is not None:
            raise self._error
        if stream:
            return _tokens(self._reply)
        return self._reply


async def _tokens(text: str) -> AsyncIterator[str]:
    yield text


class _ToolProvider(_Provider):
    def __init__(self, *, reply: str = "ok", error: BaseException | None = None) -> None:
        super().__init__(reply=reply, error=error)
        self.tool_calls = 0

    async def complete_with_tools(
        self, messages: Sequence[ToolLoopMessage], *, tools: Sequence[ToolDefinition]
    ) -> ToolCallResult:
        del messages, tools
        self.tool_calls += 1
        if self._error is not None:
            raise self._error
        return ToolCallResult(text=self._reply)


# --- чат ---------------------------------------------------------------------------


async def test_success_is_reported_under_the_given_id() -> None:
    journal = _Journal()
    provider = build_reporting_provider(
        inner=_Provider(reply="да"), health=journal, provider_id=TIER1
    )

    assert await provider.complete(_MESSAGES) == "да"
    assert journal.records == [(TIER1, None)]


@pytest.mark.parametrize(
    ("status", "failure_class"),
    [(401, "auth"), (403, "auth"), (429, "rate"), (503, "server"), (400, "contract")],
)
async def test_failure_is_reported_with_its_class_and_propagates(
    status: int, failure_class: str
) -> None:
    journal = _Journal()
    error = _http_error(status)
    provider = build_reporting_provider(
        inner=_Provider(error=error), health=journal, provider_id=TIER1
    )

    with pytest.raises(aiohttp.ClientResponseError) as raised:
        await provider.complete(_MESSAGES)

    assert raised.value is error  # тот же отказ, без обёрток и подмен
    assert journal.records == [(TIER1, failure_class)]


async def test_failure_is_recorded_before_the_caller_sees_it() -> None:
    journal = _Journal()
    provider = build_reporting_provider(
        inner=_Provider(error=_http_error(403)), health=journal, provider_id=TIER1
    )

    try:
        await provider.complete(_MESSAGES)
    except aiohttp.ClientResponseError:
        seen_when_raised = list(journal.records)

    assert seen_when_raised == [(TIER1, "auth")]


async def test_one_call_is_one_record() -> None:
    journal = _Journal()
    inner = _Provider()
    provider = build_reporting_provider(inner=inner, health=journal, provider_id="tier0-primary")

    for _ in range(3):
        await provider.complete(_MESSAGES)

    assert inner.calls == 3
    assert journal.records == [("tier0-primary", None)] * 3


async def test_stream_is_delegated_and_not_reported() -> None:
    journal = _Journal()
    inner = _Provider(reply="поток")
    provider = build_reporting_provider(inner=inner, health=journal, provider_id=TIER1)

    stream = await provider.complete(_MESSAGES, stream=True)

    assert not isinstance(stream, str)
    assert [token async for token in stream] == ["поток"]
    assert inner.calls == 1
    assert journal.records == []  # исход потока известен только посреди итерации


# --- инструменты -------------------------------------------------------------------


async def test_tool_turn_success_is_reported() -> None:
    journal = _Journal()
    inner = _ToolProvider(reply="готово")
    provider = build_reporting_provider(inner=inner, health=journal, provider_id=TIER1)
    assert isinstance(provider, ToolCallingProvider)

    result = await provider.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS)

    assert result == ToolCallResult(text="готово")
    assert inner.tool_calls == 1
    assert journal.records == [(TIER1, None)]


async def test_tool_turn_failure_is_reported_before_it_propagates() -> None:
    journal = _Journal()
    error = _http_error(403)
    provider = build_reporting_provider(
        inner=_ToolProvider(error=error), health=journal, provider_id=TIER1
    )
    assert isinstance(provider, ToolCallingProvider)

    with pytest.raises(aiohttp.ClientResponseError) as raised:
        await provider.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS)

    assert raised.value is error
    assert journal.records == [(TIER1, "auth")]


# --- зеркало возможностей и маркер ------------------------------------------------


def test_a_tool_calling_inner_yields_the_tool_calling_wrapper() -> None:
    provider = build_reporting_provider(
        inner=_ToolProvider(), health=_Journal(), provider_id=TIER1
    )

    assert type(provider) is ToolCallingReportingLLMProvider
    assert hasattr(provider, "complete_with_tools")


def test_a_plain_inner_yields_a_wrapper_without_tools() -> None:
    provider = build_reporting_provider(inner=_Provider(), health=_Journal(), provider_id=TIER1)

    assert type(provider) is ReportingLLMProvider
    # Шов ToolLoop смотрит hasattr: обёртка не выдумывает возможность, которой нет.
    assert not hasattr(provider, "complete_with_tools")


def test_the_tool_wrapper_refuses_a_plain_inner() -> None:
    with pytest.raises(TypeError, match="build_reporting_provider"):
        ToolCallingReportingLLMProvider(inner=_Provider(), health=_Journal(), provider_id=TIER1)


def test_the_wrapper_declares_that_it_reports_itself_and_under_which_id() -> None:
    provider = build_reporting_provider(
        inner=_ToolProvider(), health=_Journal(), provider_id=TIER1
    )

    assert isinstance(provider, SelfReportingProvider)
    assert provider.reported_id == TIER1


def test_the_wrapper_is_not_an_understudy_composite() -> None:
    # Иначе роутер увёл бы голос Боба к «голому» провайдеру мимо доклада (without_understudy).
    provider = build_reporting_provider(
        inner=_ToolProvider(), health=_Journal(), provider_id=TIER1
    )

    assert not isinstance(provider, UnderstudyBackedProvider)


def test_a_bare_provider_does_not_claim_to_report_itself() -> None:
    assert not isinstance(_ToolProvider(), SelfReportingProvider)
