# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Наблюдаемость «я оглох»: диагноз РОВНО раз, снятие РОВНО раз (BOB-094 срез 2).

Поверх счётчика подряд идущих сбоев (BOB-103) шлюз объявляет НАБЛЮДАЕМЫЙ сигнал
«оглох», когда сбоев набралось ≥ порога (``outage_state``). Через границу
(фейковый бот, чей ``get_updates`` бросает сетевой сбой + ``caplog``) проверяем
поведение собранной системы, а не форму кода (§0.3 п.12):

* **порог, не блип.** Единичный сбой НЕ объявляет «оглох» — WARNING-диагноза нет,
  пока сбоев меньше порога (иначе первый рутинный обрыв long-poll = ложная тревога).
* **диагноз РОВНО раз.** При ПЕРЕХОДЕ в «оглох» — один WARNING-диагноз, а не строка
  на каждый последующий сбой (это BOB-103 уже приглушил в DEBUG).
* **снятие РОВНО раз.** Первый успех ПОСЛЕ «оглох» снимает диагноз одним INFO — и
  не повторяет снятие на каждом следующем успехе.

🔴 Полноценный Telegram-алерт тут НЕ проверяется и не делается: оглохший Боб сам о
себе в Telegram не напишет (RFC BOB-094 «Что НЕ делаем») — сигнал живёт в логе.
"""

from __future__ import annotations

import logging

import pytest

from bob.application.runtime.event_bus import AsyncEventBus
from bob.infrastructure.telegram.multibot import (
    MultiBotGateway,
)
from tests.infrastructure.telegram.test_multibot_poll_backoff import (
    _registry,
    _ScriptedBot,
)

_OUTAGE_MARKER = "went deaf"
_RECOVERY_MARKER = "hearing restored"


def _gateway(bob: _ScriptedBot, *, outage_threshold: int) -> MultiBotGateway:
    """Собрать шлюз с инжектированным no-op poll_sleep и заданным порогом «оглох»."""

    async def no_sleep(seconds: float) -> None:
        del seconds

    return MultiBotGateway(
        registry=_registry(bob),
        bus=AsyncEventBus(),
        poll_timeout=10,
        poll_sleep=no_sleep,
        outage_threshold=outage_threshold,
    )


def _outage_diagnoses(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and _OUTAGE_MARKER in r.getMessage()
    ]


def _recovery_notices(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.levelno == logging.INFO and _RECOVERY_MARKER in r.getMessage()
    ]


@pytest.mark.asyncio
async def test_single_blip_is_not_an_outage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: один сетевой сбой при пороге 3.
    bob = _ScriptedBot(plan=[None])
    gateway = _gateway(bob, outage_threshold=3)

    # Act
    with caplog.at_level(logging.DEBUG):
        await gateway.poll_once()

    # Assert: блип НЕ объявляет «оглох» — диагноза нет.
    assert _outage_diagnoses(caplog) == []


@pytest.mark.asyncio
async def test_outage_is_diagnosed_exactly_once_at_the_transition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: пять подряд обрывов при пороге 3 (переход в «оглох» на третьем).
    bob = _ScriptedBot(plan=[None] * 5)
    gateway = _gateway(bob, outage_threshold=3)

    # Act
    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            await gateway.poll_once()

    # Assert: диагноз РОВНО раз — на переходе, а не на каждом сбое сверх порога.
    diagnoses = _outage_diagnoses(caplog)
    assert len(diagnoses) == 1, "диагноз «оглох» обязан логироваться ровно раз"


@pytest.mark.asyncio
async def test_recovery_lifts_the_outage_exactly_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: оглох (3 сбоя при пороге 3), затем два успеха подряд.
    bob = _ScriptedBot(plan=[None, None, None, [], []])
    gateway = _gateway(bob, outage_threshold=3)

    # Act
    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            await gateway.poll_once()

    # Assert: снятие РОВНО раз — на первом успехе после «оглох», не на каждом.
    recoveries = _recovery_notices(caplog)
    assert len(recoveries) == 1, "снятие «оглох» обязано логироваться ровно раз"
    assert len(_outage_diagnoses(caplog)) == 1


@pytest.mark.asyncio
async def test_recovery_without_a_prior_outage_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: сбои НЕ дошли до порога (2 < 3), потом успех.
    bob = _ScriptedBot(plan=[None, None, []])
    gateway = _gateway(bob, outage_threshold=3)

    # Act
    with caplog.at_level(logging.DEBUG):
        for _ in range(3):
            await gateway.poll_once()

    # Assert: раз «оглох» не объявлялся — и снимать нечего (нет ложного снятия).
    assert _outage_diagnoses(caplog) == []
    assert _recovery_notices(caplog) == []


@pytest.mark.asyncio
async def test_second_outage_episode_diagnoses_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: оглох → восстановился → снова оглох. Второй эпизод — свой диагноз.
    bob = _ScriptedBot(plan=[None, None, None, [], None, None, None])
    gateway = _gateway(bob, outage_threshold=3)

    # Act
    with caplog.at_level(logging.DEBUG):
        for _ in range(7):
            await gateway.poll_once()

    # Assert: два эпизода «оглох» → два диагноза и одно снятие между ними.
    assert len(_outage_diagnoses(caplog)) == 2
    assert len(_recovery_notices(caplog)) == 1
