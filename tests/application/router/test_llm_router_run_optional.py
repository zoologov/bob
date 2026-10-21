# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""LLMRouter.run_optional — побочный шаг хода переживает недоступность провайдера (BOB-116 D13).

Шаг, который вызывающий объявил необязательным (настроение по реплике, пересмотр черновика
перед отправкой), при отказе ДОСТУПНОСТИ провайдера — 401/403, 429, 5xx, таймаут, обрыв —
возвращает ``None`` вместо исключения: ход идёт дальше, к голосовой двери и честному
уведомлению. Классифицирует тот же роутер, что решает, переходить ли на дублёра: отказ класса
``contract`` (наш дефект: 400, битый ответ) и любая ошибка не провайдера (ошибка БД,
ошибка программы) пропускается наружу — швом «поймать всё» шов не становится. Одна строка лога без
стека: монитор уже записал отказ, второй доклад был бы двойным учётом.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from bob.application.router.health_monitor import TIER0_PRIMARY, ProviderHealthMonitor
from bob.application.router.llm_router import LLMRequest, LLMRouter, TaskType
from bob.kernel.provider_health import HealthPolicy

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from bob.kernel.ports import HealthObserver, LLMMessage

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


class _Recorder:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, str | None]] = []

    async def record_success(self, provider_id: str) -> None:
        self.records.append(("success", provider_id, None))

    async def record_failure(self, provider_id: str, failure_class: str) -> None:
        self.records.append(("failure", provider_id, failure_class))


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 21, 6, 10, tzinfo=UTC)


class _Sink:
    async def notify_owner(self, text: str) -> None:
        del text  # тексты здесь не проверяются


def _sentiment() -> LLMRequest:
    return LLMRequest(
        task_type=TaskType.SENTIMENT, messages=[{"role": "user", "content": "привет"}]
    )


def _router(tier0: _Provider, *, health: HealthObserver | None = None) -> LLMRouter:
    return LLMRouter(providers={0: tier0, 1: _Provider(reply="t1")}, health=health)


def _router_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _ROUTER_LOGGER]


async def test_an_answered_optional_step_returns_the_reply() -> None:
    router = _router(_Provider(reply="positive"))
    assert await router.run_optional(_sentiment()) == "positive"


@pytest.mark.parametrize(
    "error",
    [
        _http_error(401),
        _http_error(403),
        _http_error(429),
        _http_error(503),
        TimeoutError("no answer"),
        ConnectionError("refused"),
    ],
    ids=["401", "403", "429", "503", "timeout", "connection"],
)
async def test_a_provider_that_cannot_serve_skips_the_step(error: BaseException) -> None:
    tier0 = _Provider(error=error)
    router = _router(tier0)
    assert await router.run_optional(_sentiment()) is None
    assert tier0.calls == 1  # спросили один раз, без своего ретрая


async def test_a_skipped_step_is_one_warning_line_without_a_stack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    router = _router(_Provider(error=_http_error(403)))
    await router.run_optional(_sentiment())
    records = _router_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is None
    message = records[0].getMessage()
    assert "\n" not in message
    assert "sentiment" in message
    assert "auth" in message


async def test_a_skipped_step_while_degraded_is_still_one_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    monitor = ProviderHealthMonitor(clock=_Clock(), policy=HealthPolicy(), sink=_Sink())
    for _ in range(5):
        await monitor.record_failure(TIER0_PRIMARY, "auth")
    caplog.set_level(logging.DEBUG, logger=_ROUTER_LOGGER)
    router = _router(_Provider(error=_http_error(403)), health=monitor)
    assert await router.run_optional(_sentiment()) is None
    assert len(_router_records(caplog)) == 1


async def test_the_failure_of_a_skipped_step_is_recorded_once() -> None:
    recorder = _Recorder()
    router = _router(_Provider(error=_http_error(403)), health=recorder)
    await router.run_optional(_sentiment())
    assert recorder.records == [("failure", TIER0_PRIMARY, "auth")]


async def test_a_contract_failure_is_not_skipped() -> None:
    router = _router(_Provider(error=_http_error(400)))
    with pytest.raises(aiohttp.ClientResponseError):
        await router.run_optional(_sentiment())


async def test_a_database_error_is_not_skipped() -> None:
    router = _router(_Provider(error=sqlite3.OperationalError("database is locked")))
    with pytest.raises(sqlite3.OperationalError):
        await router.run_optional(_sentiment())


async def test_a_programming_error_is_not_skipped() -> None:
    router = _router(_Provider(error=TypeError("bad call")))
    with pytest.raises(TypeError):
        await router.run_optional(_sentiment())


async def test_cancellation_is_not_skipped() -> None:
    router = _router(_Provider(error=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await router.run_optional(_sentiment())


async def test_run_itself_still_raises_on_the_same_failure() -> None:
    router = _router(_Provider(error=_http_error(403)))
    with pytest.raises(aiohttp.ClientResponseError):
        await router.run(_sentiment())
