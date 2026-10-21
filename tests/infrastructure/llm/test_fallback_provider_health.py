# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Дублёр-обёртка докладывает облако и дублёра ПО ОТДЕЛЬНОСТИ (BOB-116 D3).

Ключ облака, мёртвый при живом дублёре, должен дать ``DEGRADED tier0-primary`` — владелец
узнаёт, что облако надо чинить, пока дублёр держит. Поэтому обёртка докладывает
``tier0-primary`` на каждую попытку облака и ``tier0-understudy`` на каждую попытку дублёра;
класс отказа — :func:`~bob.application.router.fallback_policy.classify_failure`.

🔴 Контракт D5: отказ записан ДО того, как исключение ушло вызывающему.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from bob.application.router.health_monitor import (
    TIER0_PRIMARY,
    TIER0_UNDERSTUDY,
    ProviderHealthMonitor,
)
from bob.infrastructure.llm.fallback_provider import (
    FallbackLLMProvider,
    ToolCallingFallbackLLMProvider,
    build_fallback_provider,
)
from bob.kernel.ports import ToolCallResult
from bob.kernel.provider_health import HealthPolicy

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from bob.kernel.ports import LLMMessage, ToolDefinition, ToolLoopMessage

_MESSAGES: list[LLMMessage] = [{"role": "user", "content": "привет"}]
_TOOL_MESSAGES: list[ToolLoopMessage] = [{"role": "user", "content": "почитай код"}]
_TOOLS: list[ToolDefinition] = [{"type": "function", "function": {"name": "read_code"}}]


def _http_error(status: int) -> aiohttp.ClientResponseError:
    url = URL("http://cloud.example/v1/chat/completions")
    headers: CIMultiDictProxy[str] = CIMultiDictProxy(CIMultiDict())
    request_info = aiohttp.RequestInfo(url, "POST", headers, url)
    return aiohttp.ClientResponseError(request_info, (), status=status, message="boom")


class _Provider:
    def __init__(self, *, reply: str = "ok", error: BaseException | None = None) -> None:
        self._reply = reply
        self._error = error
        self.calls = 0

    async def complete(
        self, messages: Sequence[LLMMessage], *, stream: bool = False
    ) -> str | AsyncIterator[str]:
        del messages, stream  # отвечает одинаково на любой запрос
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._reply


class _ToolProvider(_Provider):
    def __init__(
        self, *, reply: str = "ok", error: BaseException | None = None, tool_error: bool = False
    ) -> None:
        super().__init__(reply=reply, error=error)
        self._tool_error = error if tool_error else None
        self.tool_calls = 0

    async def complete_with_tools(
        self, messages: Sequence[ToolLoopMessage], *, tools: Sequence[ToolDefinition]
    ) -> ToolCallResult:
        del messages, tools  # отвечает одинаково на любой запрос
        self.tool_calls += 1
        if self._tool_error is not None:
            raise self._tool_error
        return ToolCallResult(text="final")


class _Recorder:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, str | None]] = []

    async def record_success(self, provider_id: str) -> None:
        self.records.append(("success", provider_id, None))

    async def record_failure(self, provider_id: str, failure_class: str) -> None:
        self.records.append(("failure", provider_id, failure_class))


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 1, 6, 10, tzinfo=UTC)


class _Sink:
    async def notify_owner(self, text: str) -> None:
        del text  # тексты здесь не проверяются


# --- chat ---------------------------------------------------------------------------


async def test_primary_success_is_reported_as_the_cloud() -> None:
    recorder = _Recorder()
    wrapper = FallbackLLMProvider(primary=_Provider(), fallback=_Provider(), health=recorder)
    await wrapper.complete(_MESSAGES)
    assert recorder.records == [("success", TIER0_PRIMARY, None)]


async def test_cloud_down_understudy_holds_reports_both_separately() -> None:
    recorder = _Recorder()
    wrapper = FallbackLLMProvider(
        primary=_Provider(error=_http_error(403)),
        fallback=_Provider(reply="local"),
        health=recorder,
    )
    assert await wrapper.complete(_MESSAGES) == "local"
    assert recorder.records == [
        ("failure", TIER0_PRIMARY, "auth"),
        ("success", TIER0_UNDERSTUDY, None),
    ]


async def test_both_down_reports_both_failures_before_the_error_reaches_the_caller() -> None:
    monitor = ProviderHealthMonitor(
        clock=_Clock(), policy=HealthPolicy(), sink=_Sink(), has_understudy=True
    )
    wrapper = FallbackLLMProvider(
        primary=_Provider(error=_http_error(503)),
        fallback=_Provider(error=ConnectionRefusedError("ollama is not running")),
        health=monitor,
    )
    with pytest.raises(aiohttp.ClientResponseError):
        await wrapper.complete(_MESSAGES)
    snapshot = monitor.snapshot()
    assert snapshot[TIER0_PRIMARY].consecutive_failures == 1
    assert snapshot[TIER0_PRIMARY].failure_class == "server"
    assert snapshot[TIER0_UNDERSTUDY].consecutive_failures == 1
    assert snapshot[TIER0_UNDERSTUDY].failure_class == "connection"


async def test_contract_failure_is_reported_and_the_understudy_is_not_asked() -> None:
    recorder = _Recorder()
    local = _Provider()
    wrapper = FallbackLLMProvider(
        primary=_Provider(error=_http_error(400)), fallback=local, health=recorder
    )
    with pytest.raises(aiohttp.ClientResponseError):
        await wrapper.complete(_MESSAGES)
    assert local.calls == 0
    assert recorder.records == [("failure", TIER0_PRIMARY, "contract")]


async def test_stream_is_not_reported() -> None:
    """Стрим Tier-0 сегодня никто не зовёт, а исход стрима виден только по ходу итерации."""
    recorder = _Recorder()
    wrapper = FallbackLLMProvider(primary=_Provider(), fallback=_Provider(), health=recorder)
    await wrapper.complete(_MESSAGES, stream=True)
    assert recorder.records == []


async def test_wrapper_without_a_monitor_still_falls_back() -> None:
    wrapper = FallbackLLMProvider(
        primary=_Provider(error=_http_error(503)), fallback=_Provider(reply="local")
    )
    assert await wrapper.complete(_MESSAGES) == "local"


# --- tool-calling -------------------------------------------------------------------


async def test_tool_turn_reports_cloud_and_understudy_separately() -> None:
    recorder = _Recorder()
    wrapper = ToolCallingFallbackLLMProvider(
        primary=_ToolProvider(error=_http_error(429), tool_error=True),
        fallback=_ToolProvider(),
        health=recorder,
    )
    await wrapper.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS)
    assert recorder.records == [
        ("failure", TIER0_PRIMARY, "rate"),
        ("success", TIER0_UNDERSTUDY, None),
    ]


async def test_tool_turn_success_is_reported_as_the_cloud() -> None:
    recorder = _Recorder()
    wrapper = ToolCallingFallbackLLMProvider(
        primary=_ToolProvider(), fallback=_ToolProvider(), health=recorder
    )
    await wrapper.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS)
    assert recorder.records == [("success", TIER0_PRIMARY, None)]


async def test_tool_turn_without_a_tool_capable_understudy_reports_only_the_cloud() -> None:
    recorder = _Recorder()
    wrapper = ToolCallingFallbackLLMProvider(
        primary=_ToolProvider(error=_http_error(503), tool_error=True),
        fallback=_Provider(),
        health=recorder,
    )
    with pytest.raises(aiohttp.ClientResponseError):
        await wrapper.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS)
    assert recorder.records == [("failure", TIER0_PRIMARY, "server")]


async def test_tool_turn_with_both_down_reports_both() -> None:
    recorder = _Recorder()
    wrapper = ToolCallingFallbackLLMProvider(
        primary=_ToolProvider(error=_http_error(503), tool_error=True),
        fallback=_ToolProvider(error=TimeoutError(), tool_error=True),
        health=recorder,
    )
    with pytest.raises(aiohttp.ClientResponseError):
        await wrapper.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS)
    assert recorder.records == [
        ("failure", TIER0_PRIMARY, "server"),
        ("failure", TIER0_UNDERSTUDY, "timeout"),
    ]


# --- сборка -------------------------------------------------------------------------


@pytest.mark.parametrize("primary", [_Provider(), _ToolProvider()])
async def test_builder_threads_the_monitor_into_either_variant(primary: _Provider) -> None:
    recorder = _Recorder()
    wrapper = build_fallback_provider(primary=primary, fallback=_Provider(), health=recorder)
    await wrapper.complete(_MESSAGES)
    assert recorder.records == [("success", TIER0_PRIMARY, None)]


# --- breaker: облако признано лежащим — обёртка его не трогает до зонда (R2 N1) -------
# Монитор настоящий: он и наблюдатель, и читатель. Облако объявлено DEGRADED пятью отказами;
# дальше обёртка спрашивает у него, пора ли зонд. Не пора — сразу дублёр, ни вызова облака,
# ни строки лога; пора — вызов облака И ЕСТЬ зонд.

_FALLBACK_LOGGER = "bob.infrastructure.llm.fallback_provider"


class _MovingClock:
    def __init__(self) -> None:
        self.moment = datetime(2026, 10, 1, 6, 10, tzinfo=UTC)

    def now(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += timedelta(seconds=seconds)


async def _monitor_with_a_dead_cloud() -> tuple[ProviderHealthMonitor, _MovingClock]:
    """Монитор, в котором облако уже DEGRADED, а зонд — через минуту (HealthPolicy())."""
    clock = _MovingClock()
    monitor = ProviderHealthMonitor(
        clock=clock, policy=HealthPolicy(), sink=_Sink(), has_understudy=True
    )
    for _ in range(HealthPolicy().failures_threshold):
        await monitor.record_failure(TIER0_PRIMARY, "auth")
    assert monitor.is_degraded(TIER0_PRIMARY)
    assert not monitor.probe_due(TIER0_PRIMARY)
    return monitor, clock


def _fallback_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == _FALLBACK_LOGGER and r.levelno >= logging.WARNING
    ]


async def test_resting_cloud_is_not_called_and_the_understudy_answers_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    monitor, _ = await _monitor_with_a_dead_cloud()
    cloud, local = _Provider(error=_http_error(403)), _Provider(reply="local")
    wrapper = FallbackLLMProvider(primary=cloud, fallback=local, health=monitor)
    caplog.set_level(logging.DEBUG, logger=_FALLBACK_LOGGER)

    replies = [await wrapper.complete(_MESSAGES) for _ in range(25)]

    assert replies == ["local"] * 25
    assert cloud.calls == 0
    assert local.calls == 25
    assert _fallback_warnings(caplog) == []
    threshold = HealthPolicy().failures_threshold
    assert monitor.snapshot()[TIER0_PRIMARY].consecutive_failures == threshold


async def test_resting_cloud_leaves_its_probe_schedule_alone() -> None:
    """Вызовы мимо облака — не попытки облака: расписание зонда не сдвигается."""
    monitor, clock = await _monitor_with_a_dead_cloud()
    wrapper = FallbackLLMProvider(
        primary=_Provider(error=_http_error(403)), fallback=_Provider(), health=monitor
    )
    clock.advance(59)
    await wrapper.complete(_MESSAGES)
    clock.advance(1)
    assert monitor.probe_due(TIER0_PRIMARY)


async def test_due_probe_goes_to_the_cloud_and_a_failure_is_one_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    monitor, clock = await _monitor_with_a_dead_cloud()
    cloud, local = _Provider(error=_http_error(403)), _Provider(reply="local")
    wrapper = FallbackLLMProvider(primary=cloud, fallback=local, health=monitor)
    caplog.set_level(logging.DEBUG, logger=_FALLBACK_LOGGER)
    clock.advance(60)

    assert await wrapper.complete(_MESSAGES) == "local"
    assert await wrapper.complete(_MESSAGES) == "local"  # зонд провален — следующий не пора

    assert cloud.calls == 1
    assert local.calls == 2
    assert len(_fallback_warnings(caplog)) == 1
    snapshot = monitor.snapshot()[TIER0_PRIMARY]
    assert snapshot.consecutive_failures == HealthPolicy().failures_threshold + 1


async def test_due_probe_that_the_cloud_answers_lifts_the_breaker() -> None:
    monitor, clock = await _monitor_with_a_dead_cloud()
    cloud, local = _Provider(reply="cloud"), _Provider(reply="local")
    wrapper = FallbackLLMProvider(primary=cloud, fallback=local, health=monitor)
    clock.advance(60)

    assert await wrapper.complete(_MESSAGES) == "cloud"
    assert await wrapper.complete(_MESSAGES) == "cloud"

    assert not monitor.is_degraded(TIER0_PRIMARY)
    assert (cloud.calls, local.calls) == (2, 0)


async def test_resting_cloud_with_a_failing_understudy_raises_the_understudy_error() -> None:
    monitor, _ = await _monitor_with_a_dead_cloud()
    cloud = _Provider(error=_http_error(403))
    wrapper = FallbackLLMProvider(
        primary=cloud,
        fallback=_Provider(error=ConnectionRefusedError("ollama is not running")),
        health=monitor,
    )
    with pytest.raises(ConnectionRefusedError):
        await wrapper.complete(_MESSAGES)
    assert cloud.calls == 0
    assert monitor.snapshot()[TIER0_UNDERSTUDY].failure_class == "connection"


async def test_observer_that_cannot_read_keeps_trying_the_cloud_first() -> None:
    """Наблюдатель без чтения (не монитор) — поведение до R2: облако пробуется всегда."""
    recorder = _Recorder()
    cloud = _Provider(error=_http_error(403))
    wrapper = FallbackLLMProvider(primary=cloud, fallback=_Provider(), health=recorder)
    for _ in range(3):
        await wrapper.complete(_MESSAGES)
    assert cloud.calls == 3


async def test_bare_primary_ignores_the_breaker() -> None:
    """Голос Боба просит голое облако — оно не знает о дублёре и не проходит через breaker."""
    monitor, _ = await _monitor_with_a_dead_cloud()
    cloud = _Provider(error=_http_error(403))
    wrapper = FallbackLLMProvider(primary=cloud, fallback=_Provider(), health=monitor)
    with pytest.raises(aiohttp.ClientResponseError):
        await wrapper.without_understudy().complete(_MESSAGES)
    assert cloud.calls == 1


async def test_resting_cloud_tool_turn_goes_straight_to_a_tool_capable_understudy(
    caplog: pytest.LogCaptureFixture,
) -> None:
    monitor, _ = await _monitor_with_a_dead_cloud()
    cloud = _ToolProvider(error=_http_error(403), tool_error=True)
    local = _ToolProvider()
    wrapper = ToolCallingFallbackLLMProvider(primary=cloud, fallback=local, health=monitor)
    caplog.set_level(logging.DEBUG, logger=_FALLBACK_LOGGER)

    result = await wrapper.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS)

    assert result.text == "final"
    assert (cloud.tool_calls, local.tool_calls) == (0, 1)
    assert _fallback_warnings(caplog) == []


async def test_resting_cloud_tool_turn_without_a_tool_capable_understudy_tries_the_cloud() -> None:
    """Дублёр без инструментов ход с инструментами не обслужит: облако — единственный путь."""
    monitor, _ = await _monitor_with_a_dead_cloud()
    cloud = _ToolProvider(error=_http_error(403), tool_error=True)
    wrapper = ToolCallingFallbackLLMProvider(primary=cloud, fallback=_Provider(), health=monitor)
    with pytest.raises(aiohttp.ClientResponseError):
        await wrapper.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS)
    assert cloud.tool_calls == 1


async def test_due_probe_on_a_tool_turn_goes_to_the_cloud() -> None:
    monitor, clock = await _monitor_with_a_dead_cloud()
    cloud = _ToolProvider()
    local = _ToolProvider()
    wrapper = ToolCallingFallbackLLMProvider(primary=cloud, fallback=local, health=monitor)
    clock.advance(60)

    await wrapper.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS)

    assert (cloud.tool_calls, local.tool_calls) == (1, 0)
    assert not monitor.is_degraded(TIER0_PRIMARY)
