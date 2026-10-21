# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""LLMRouter докладывает исход каждой попытки тира монитору здоровья (BOB-116 D3).

Кто докладывает что — так, чтобы ни один вызов провайдера не был учтён дважды и ни один не
пропал: роутер — ``tier1`` всегда и Tier-0, только когда вызванный провайдер НЕ дублёр-обёртка
(обёртка докладывает ``tier0-primary``/``tier0-understudy`` сама). Голос Боба на Tier-0 идёт
мимо обёртки — к «голому» primary (``without_understudy``), и этот вызов докладывает роутер.

🔴 Контракт D5: отказ записан в монитор ДО того, как исключение дошло до вызывающего — гейт
дорожек heartbeat сравнивает ``consecutive_failures`` в снимке до и после тика.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from bob.application.router.health_monitor import (
    TIER0_PRIMARY,
    TIER1,
    ProviderHealthMonitor,
)
from bob.application.router.llm_router import LLMRequest, LLMRouter, TaskType
from bob.kernel.provider_health import HealthPolicy

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from bob.kernel.ports import LLMMessage, LLMProvider

_ROUTER_LOGGER = "bob.application.router.llm_router"


def _http_error(status: int) -> aiohttp.ClientResponseError:
    url = URL("http://llm.example/v1/chat/completions")
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


class _UnderstudyBacked(_Provider):
    """Обёртка с дублёром: докладывает сама, роутер её вызовы не учитывает."""

    def __init__(self, *, primary: _Provider, reply: str = "ok") -> None:
        super().__init__(reply=reply)
        self.primary = primary

    def without_understudy(self) -> LLMProvider:
        return self.primary


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


def _request(
    task: TaskType = TaskType.WORK_TALK, *, tier_override: int | None = None
) -> LLMRequest:
    return LLMRequest(
        task_type=task,
        messages=[{"role": "user", "content": "привет"}],
        tier_override=tier_override,
    )


def _monitor() -> ProviderHealthMonitor:
    return ProviderHealthMonitor(clock=_Clock(), policy=HealthPolicy(), sink=_Sink())


# --- что докладывается ---------------------------------------------------------------


async def test_tier1_success_is_reported() -> None:
    recorder = _Recorder()
    router = LLMRouter(providers={0: _Provider(), 1: _Provider()}, health=recorder)
    await router.run(_request(TaskType.ROOM_READ))
    assert recorder.records == [("success", TIER1, None)]


async def test_tier1_outage_and_the_tier0_rescue_are_both_reported() -> None:
    recorder = _Recorder()
    router = LLMRouter(
        providers={0: _Provider(reply="t0"), 1: _Provider(error=_http_error(503))},
        health=recorder,
    )
    assert await router.run(_request(TaskType.ROOM_READ)) == "t0"
    assert recorder.records == [("failure", TIER1, "server"), ("success", TIER0_PRIMARY, None)]


async def test_tier1_auth_failure_is_reported_as_auth() -> None:
    recorder = _Recorder()
    router = LLMRouter(
        providers={0: _Provider(reply="t0"), 1: _Provider(error=_http_error(403))},
        health=recorder,
    )
    await router.run(_request(TaskType.ROOM_READ))
    assert recorder.records[0] == ("failure", TIER1, "auth")


async def test_plain_tier0_failure_is_reported_by_the_router() -> None:
    recorder = _Recorder()
    router = LLMRouter(
        providers={0: _Provider(error=_http_error(403)), 1: _Provider()}, health=recorder
    )
    with pytest.raises(aiohttp.ClientResponseError):
        await router.run(_request())
    assert recorder.records == [("failure", TIER0_PRIMARY, "auth")]


async def test_understudy_backed_tier0_is_left_to_the_wrapper() -> None:
    recorder = _Recorder()
    wrapper = _UnderstudyBacked(primary=_Provider())
    router = LLMRouter(providers={0: wrapper, 1: _Provider()}, health=recorder)
    await router.run(_request())
    assert wrapper.calls == 1
    assert recorder.records == []


async def test_bobs_voice_on_tier0_goes_to_the_bare_primary_and_the_router_reports_it() -> None:
    recorder = _Recorder()
    primary = _Provider(error=_http_error(403))
    wrapper = _UnderstudyBacked(primary=primary)
    router = LLMRouter(providers={0: wrapper, 1: _Provider(reply="t1")}, health=recorder)
    assert await router.run(_request(TaskType.REPLY_TO_USER, tier_override=0)) == "t1"
    assert primary.calls == 1
    assert wrapper.calls == 0
    assert recorder.records == [("failure", TIER0_PRIMARY, "auth"), ("success", TIER1, None)]


# --- дублёр снят при старте (BOB-116 D11, bob-i83.15) ---------------------------------
# Сборка проверила дублёр при старте, и он не готов: дальше Tier-0 — «голое» облако, как если
# бы дублёр не был собран вовсе. Служебный ход идёт мимо обёртки, и его исход докладывает
# роутер — иначе отказ облака не увидел бы никто (обёртка больше не зовётся).


async def test_stood_down_understudy_sends_service_turns_to_the_bare_primary() -> None:
    recorder = _Recorder()
    primary = _Provider(error=_http_error(403))
    wrapper = _UnderstudyBacked(primary=primary)
    router = LLMRouter(providers={0: wrapper, 1: _Provider()}, health=recorder)

    router.stand_down_tier0_understudy()
    with pytest.raises(aiohttp.ClientResponseError):
        await router.run(_request())

    assert wrapper.calls == 0
    assert primary.calls == 1
    assert recorder.records == [("failure", TIER0_PRIMARY, "auth")]


async def test_standing_down_a_plain_tier0_changes_nothing() -> None:
    recorder = _Recorder()
    tier0 = _Provider(reply="t0")
    router = LLMRouter(providers={0: tier0, 1: _Provider()}, health=recorder)

    router.stand_down_tier0_understudy()

    assert await router.run(_request()) == "t0"
    assert tier0.calls == 1
    assert recorder.records == [("success", TIER0_PRIMARY, None)]


async def test_router_without_a_monitor_still_routes() -> None:
    router = LLMRouter(providers={0: _Provider(reply="t0"), 1: _Provider(error=_http_error(503))})
    assert await router.run(_request(TaskType.ROOM_READ)) == "t0"


# --- запись видна до того, как исключение дошло до вызывающего (контракт D5) ----------


async def test_tier0_failure_is_in_the_snapshot_when_the_caller_sees_it() -> None:
    monitor = _monitor()
    router = LLMRouter(
        providers={0: _Provider(error=_http_error(503)), 1: _Provider()}, health=monitor
    )
    with pytest.raises(aiohttp.ClientResponseError):
        await router.run(_request())
    view = monitor.snapshot()[TIER0_PRIMARY]
    assert view.consecutive_failures == 1
    assert view.failure_class == "server"


async def test_tier1_contract_failure_is_in_the_snapshot_when_the_caller_sees_it() -> None:
    monitor = _monitor()
    router = LLMRouter(
        providers={0: _Provider(), 1: _Provider(error=_http_error(400))}, health=monitor
    )
    with pytest.raises(aiohttp.ClientResponseError):
        await router.run(_request(TaskType.ROOM_READ))
    assert monitor.snapshot()[TIER1].consecutive_failures == 1


# --- лог при уже признанном простое -------------------------------------------------


async def test_tier0_failure_before_degradation_keeps_the_stack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    router = LLMRouter(
        providers={0: _Provider(error=_http_error(503)), 1: _Provider()}, health=_monitor()
    )
    with pytest.raises(aiohttp.ClientResponseError):
        await router.run(_request())
    records = [r for r in caplog.records if r.name == _ROUTER_LOGGER]
    assert len(records) == 1
    assert records[0].exc_info is not None


async def test_tier0_failure_while_degraded_is_one_line_without_a_stack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    monitor = _monitor()
    for _ in range(5):
        await monitor.record_failure(TIER0_PRIMARY, "auth")
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    router = LLMRouter(
        providers={0: _Provider(error=_http_error(403)), 1: _Provider()}, health=monitor
    )
    with pytest.raises(aiohttp.ClientResponseError):
        await router.run(_request())
    records = [r for r in caplog.records if r.name == _ROUTER_LOGGER]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is None
    assert "\n" not in records[0].getMessage()
    assert "tier0-primary is degraded" in records[0].getMessage()


async def test_observer_that_cannot_read_keeps_the_stack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    router = LLMRouter(
        providers={0: _Provider(error=_http_error(503)), 1: _Provider()}, health=_Recorder()
    )
    with pytest.raises(aiohttp.ClientResponseError):
        await router.run(_request())
    records = [r for r in caplog.records if r.name == _ROUTER_LOGGER]
    assert records[0].exc_info is not None
