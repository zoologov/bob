# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Гейт дорожки heartbeat на НАСТОЯЩЕМ мониторе и настоящем 403 (BOB-116 T, риск RFC).

Риск из таблицы RFC: «гейт дорожек спрячет не-LLM ошибки тика (БД)». Юнит-тесты гейта
(``test_heartbeat_health_gated.py``) держат правило на фейковом читателе, где тик сам играет
монитор. Здесь — та же развилка на сборке, которая её и решает в проде: настоящий
:class:`~bob.application.router.health_monitor.ProviderHealthMonitor`, настоящий
:class:`~bob.application.router.LLMRouter` над настоящей фабрикой провайдеров и настоящий
loopback-эндпоинт, отвечающий 403. Гейт отличает проваленный зонд от ошибки БД по росту
серии отказов в снимке монитора; это свойство настоящего монитора, а не фейка, и проверяется
оно только так (П.0.3 п.4).

Наблюдаемое: что увидел оператор в логе (уровень, стек, тип исключения), сколько раз позвали
облако и что ушло владельцу.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from bob.application.router import LLMRequest, LLMRouter, TaskType
from bob.application.router.health_monitor import TIER0_PRIMARY, ProviderHealthMonitor
from bob.application.runtime.heartbeat import health_gated, periodic
from bob.infrastructure.config.loader import ConfigLoader
from bob.infrastructure.llm.factory import build_tier_providers
from bob.kernel.provider_health import HealthPolicy
from tests.acceptance.tier0_fallback_harness import (
    ANSWERS,
    CLOUD_REPLY,
    FORBIDDEN,
    TIER1_REPLY,
    LoopbackEndpoint,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_THRESHOLD = 5
_FIRST_PROBE_SECONDS = 60


class _Clock:
    def __init__(self) -> None:
        self.moment = datetime(2026, 10, 1, 6, 10, tzinfo=UTC)

    def now(self) -> datetime:
        return self.moment


class _OwnerSink:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def notify_owner(self, text: str) -> None:
        self.texts.append(text)


class _MonologueTick:
    """Тик монолога: сначала своя БД, потом Tier-0 через роутер, потом снова БД."""

    def __init__(self, router: LLMRouter) -> None:
        self._router = router
        self.db_breaks_before_the_call = False
        self.db_breaks_after_the_call = False

    async def run(self) -> None:
        if self.db_breaks_before_the_call:
            raise sqlite3.OperationalError("database is locked")
        await self._router.run(
            LLMRequest(
                task_type=TaskType.INNER_MONOLOGUE,
                messages=[{"role": "user", "content": "о чём я думаю?"}],
            )
        )
        if self.db_breaks_after_the_call:
            raise sqlite3.OperationalError("disk I/O error")


@dataclass(frozen=True, slots=True)
class _Stage:
    cloud: LoopbackEndpoint
    clock: _Clock
    sink: _OwnerSink
    monitor: ProviderHealthMonitor
    tick: _MonologueTick


async def _stage() -> AsyncIterator[_Stage]:
    cloud = LoopbackEndpoint(behaviour=FORBIDDEN, reply=CLOUD_REPLY)
    tier1 = LoopbackEndpoint(behaviour=ANSWERS, reply=TIER1_REPLY)
    await cloud.start()
    await tier1.start()
    try:
        config = ConfigLoader(
            yaml_path=None,
            env={
                "BOB_LLM__TIER0_BASE_URL": cloud.base_url,
                "BOB_LLM__TIER0_MODEL": "cloud-tier0",
                "BOB_LLM__TIER1_BASE_URL": tier1.base_url,
                "BOB_LLM__TIER1_MODEL": "cloud-tier1",
                "BOB_LLM__TIMEOUT_SECONDS": "5.0",
            },
        ).load()
        clock, sink = _Clock(), _OwnerSink()
        monitor = ProviderHealthMonitor(clock=clock, policy=HealthPolicy(), sink=sink)
        router = LLMRouter(providers=build_tier_providers(config, health=monitor), health=monitor)
        yield _Stage(cloud, clock, sink, monitor, _MonologueTick(router))
    finally:
        await cloud.stop()
        await tier1.stop()


@pytest.fixture
async def degraded() -> AsyncIterator[_Stage]:
    """Облако отказало пять раз подряд (раз в 30 с) — монитор объявил его лежащим."""
    async for stage in _stage():
        for _ in range(_THRESHOLD):
            with contextlib.suppress(Exception):  # настоящий 403 — то, что здесь и ставится
                await stage.tick.run()
            stage.clock.moment += timedelta(seconds=30)
        stage.clock.moment += timedelta(seconds=_FIRST_PROBE_SECONDS)
        yield stage


async def _stop_after_one_iteration(_seconds: float) -> None:
    raise asyncio.CancelledError


async def _one_lane_iteration(stage: _Stage) -> None:
    """Одна итерация дорожки так, как её собирает ``wiring/proactivity``: гейт внутри periodic."""
    lane = periodic(
        health_gated(stage.tick.run, reader=stage.monitor, provider_id=TIER0_PRIMARY, probe=True),
        interval_seconds=0.0,
        sleep=_stop_after_one_iteration,
    )
    with pytest.raises(asyncio.CancelledError):
        await lane()


def _stacked(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.exc_info is not None]


async def test_db_error_before_the_probe_is_logged_with_its_stack(
    degraded: _Stage, caplog: pytest.LogCaptureFixture
) -> None:
    degraded.tick.db_breaks_before_the_call = True
    calls_before = degraded.cloud.calls

    with caplog.at_level(logging.INFO, logger="bob"):
        await _one_lane_iteration(degraded)

    stacked = _stacked(caplog)
    assert len(stacked) == 1
    assert stacked[0].levelno == logging.ERROR
    assert stacked[0].exc_info is not None
    assert isinstance(stacked[0].exc_info[1], sqlite3.OperationalError)
    assert degraded.cloud.calls == calls_before  # до модели дело не дошло


async def test_db_error_before_the_probe_is_not_told_as_a_failed_probe(
    degraded: _Stage, caplog: pytest.LogCaptureFixture
) -> None:
    degraded.tick.db_breaks_before_the_call = True

    with caplog.at_level(logging.INFO, logger="bob"):
        await _one_lane_iteration(degraded)

    assert not [r for r in caplog.records if "heartbeat probe of" in r.getMessage()]


async def test_real_403_on_the_probe_is_one_info_line_without_a_stack(
    degraded: _Stage, caplog: pytest.LogCaptureFixture
) -> None:
    calls_before = degraded.cloud.calls

    with caplog.at_level(logging.INFO, logger="bob"):
        await _one_lane_iteration(degraded)

    probe_lines = [
        r for r in caplog.records if "heartbeat probe of tier0-primary" in r.getMessage()
    ]
    assert [r.levelno for r in probe_lines] == [logging.INFO]
    assert "auth" in probe_lines[0].getMessage()
    assert _stacked(caplog) == []
    assert degraded.cloud.calls == calls_before + 1


async def test_db_error_after_a_probe_the_model_answered_keeps_its_stack(
    degraded: _Stage, caplog: pytest.LogCaptureFixture
) -> None:
    degraded.cloud.behaviour = ANSWERS
    degraded.tick.db_breaks_after_the_call = True

    with caplog.at_level(logging.INFO, logger="bob"):
        await _one_lane_iteration(degraded)

    stacked = _stacked(caplog)
    assert len(stacked) == 1
    assert stacked[0].exc_info is not None
    assert isinstance(stacked[0].exc_info[1], sqlite3.OperationalError)
    assert any("Я вернулся" in text for text in degraded.sink.texts)
