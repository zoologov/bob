# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Опрос на сетевом сбое паузит, а не хот-лупит (BOB-103).

Корень (BOB-103, измерен по коду): ``periodic(poll, interval_seconds=0.0)`` +
``_poll_bot`` на сетевом сбое делал ``return 0`` НЕОТЛИЧИМО от «нет обновлений» →
на обрыве сети внешний цикл бил снова сразу (~30 тыс. строк «poll failed» в сутки
на бота). Здесь мы воспроизводим хот-луп через границу (фейковый бот, чей
``get_updates`` бросает ``ServerDisconnectedError``/``OSError``) и показываем:

* **бэкофф.** Каждый подряд идущий сетевой сбой паузит опрос на растущее число
  секунд (``next_backoff``) через ИНЖЕКТИРОВАННЫЙ ``poll_sleep`` — без реального
  ожидания. Частота попыток падает (пауза растёт), а не остаётся нулевой.
* **лечение не хуже болезни.** Первый УСПЕШНЫЙ опрос сбрасывает счётчик → после
  возврата сети следующий сбой снова начинается с базовой паузы, а успешный опрос
  вообще не паузит (доставка мгновенна).
* **схлопывание лога.** Первый одинаковый сбой — WARNING; повторные — не строкой
  на попытку (DEBUG), пока состояние не сменится успехом.
* **байт-в-байт при живой сети.** Успешный опрос НЕ вызывает ``poll_sleep`` — на
  штатном пути бэкоффа нет.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetUpdates

from bob.application.runtime.event_bus import AsyncEventBus
from bob.infrastructure.telegram.multibot import (
    BotIdentity,
    BotRegistry,
    BotScope,
    MultiBotGateway,
)
from bob.kernel.poll_backoff import next_backoff

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from aiogram.types import InputRichMessage

    from bob.infrastructure.telegram.gateway import MessageLike, UpdateLike

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32


@dataclass
class _FakeUpdate:
    update_id: int
    message: None = None
    effective_chat: None = None
    effective_user: None = None


@dataclass
class _ScriptedBot:
    """``get_updates`` следует scripted-плану: каждый шаг — либо батч, либо сбой.

    ``plan`` — список шагов. ``None`` = бросить сетевой сбой (обрыв long-poll);
    список апдейтов = успешный батч. Исчерпав план, отдаёт пустой батч (успех).
    """

    plan: list[list[_FakeUpdate] | None] = field(default_factory=list)
    error_factory: Callable[[], BaseException] | None = None
    calls: int = 0
    offsets: list[int] = field(default_factory=list)

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[_FakeUpdate]:
        del timeout  # long-poll timeout не влияет на scripted-план
        self.offsets.append(offset)
        step = self.plan[self.calls] if self.calls < len(self.plan) else []
        self.calls += 1
        if step is None:
            raise self._make_error()
        return step

    def _make_error(self) -> BaseException:
        if self.error_factory is not None:
            return self.error_factory()
        return TelegramNetworkError(
            method=GetUpdates(), message="ServerDisconnectedError"
        )

    # --- send-surface (не вызывается: route застаблен / нет апдейтов) ---------
    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,
        reply_parameters: object = None,
    ) -> MessageLike:  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
        reply_parameters: object = None,
    ) -> MessageLike:  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> MessageLike:  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> MessageLike:  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def set_message_reaction(
        self,
        *,
        chat_id: int,
        message_id: int,
        reaction: object,
        message_thread_id: int | None = None,
    ) -> bool:  # pragma: no cover - not exercised here
        raise NotImplementedError


def _registry(bob: _ScriptedBot) -> BotRegistry:
    registry = BotRegistry()
    registry.register(
        identity=BotIdentity.BOB,
        bot=bob,
        scope=BotScope(chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID),
    )
    return registry


def _gateway_with_recorded_sleep(
    bob: _ScriptedBot,
) -> tuple[MultiBotGateway, list[float]]:
    """Собрать шлюз с ИНЖЕКТИРОВАННЫМ poll_sleep, пишущим паузы (без ожидания)."""
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    gateway = MultiBotGateway(
        registry=_registry(bob),
        bus=AsyncEventBus(),
        poll_timeout=10,
        poll_sleep=record_sleep,
    )
    return gateway, slept


# --- Хот-луп: сетевой сбой теперь паузит, пауза растёт -------------------------


@pytest.mark.asyncio
async def test_network_failure_backs_off_and_pause_grows() -> None:
    # Arrange: пять подряд обрывов сети (long-poll бросает мгновенно).
    bob = _ScriptedBot(plan=[None, None, None, None, None])
    gateway, slept = _gateway_with_recorded_sleep(bob)

    # Act: пять тиков подряд (симуляция сети-вниз под periodic(interval=0)).
    for _ in range(5):
        published = await gateway.poll_once()
        assert published == 0

    # Assert: КАЖДЫЙ сбой спаузил опрос — раньше пауз не было вовсе (хот-луп).
    assert len(slept) == 5
    # Пауза растёт с числом подряд идущих сбоев (частота попыток падает).
    assert slept == [next_backoff(n) for n in range(1, 6)]
    # И она строго возрастает, пока не упрётся в потолок.
    assert slept[0] < slept[1] < slept[2]


@pytest.mark.asyncio
async def test_live_network_success_never_pauses() -> None:
    # Arrange: успешные пустые батчи (живая сеть, long-poll сам держит темп).
    bob = _ScriptedBot(plan=[[], [], []])
    gateway, slept = _gateway_with_recorded_sleep(bob)

    # Act
    for _ in range(3):
        await gateway.poll_once()

    # Assert: на штатном пути бэкоффа нет — poll_sleep не вызван ни разу.
    assert slept == []


@pytest.mark.asyncio
async def test_first_success_resets_backoff_so_recovery_is_fast() -> None:
    # Arrange: три обрыва (пауза доросла), потом сеть вернулась (успех), потом
    # снова обрыв. 🔴 Лечение не хуже болезни: успех сбрасывает счётчик, поэтому
    # следующий сбой снова стартует с БАЗОВОЙ паузы, а не с накопленной.
    bob = _ScriptedBot(plan=[None, None, None, [], None])
    gateway, slept = _gateway_with_recorded_sleep(bob)

    # Act
    for _ in range(5):
        await gateway.poll_once()

    # Assert: сбои 1..3 растут; успех (тик 4) НЕ паузит; сбой 5 — снова база.
    assert slept == [
        next_backoff(1),
        next_backoff(2),
        next_backoff(3),
        next_backoff(1),  # счётчик сброшен успехом → снова базовая пауза
    ]
    # Первый успешный опрос после возврата сети — быстрый (без паузы вообще):
    # он не добавил записи в slept (доставка мгновенна, не ждёт потолка).


@pytest.mark.asyncio
async def test_recovered_success_delivers_immediately_after_max_backoff() -> None:
    # Arrange: много обрывов (пауза упёрлась в потолок), затем сеть вернулась и
    # отдаёт РЕАЛЬНЫЙ батч. Успех обязан пройти без паузы, а не ждать потолок.
    bob = _ScriptedBot(plan=[None] * 12 + [[_FakeUpdate(1)]])
    gateway, slept = _gateway_with_recorded_sleep(bob)

    async def route_ok(update: UpdateLike, identity: BotIdentity) -> bool:
        return True

    gateway.route = route_ok  # type: ignore[method-assign]

    # Act: 12 сбоев + 1 успешная доставка.
    published_total = 0
    for _ in range(13):
        published_total += await gateway.poll_once()

    # Assert: доставка случилась (published=1) и НЕ добавила паузы — успех после
    # потолка мгновенен, счётчик сброшен.
    assert published_total == 1
    assert len(slept) == 12  # только сбои паузили; успех — нет
    assert slept[-1] == next_backoff(12)  # последний сбой — на потолке


# --- Часть 2: схлопывание повторов в логе -------------------------------------


@pytest.mark.asyncio
async def test_repeated_failures_do_not_log_a_warning_per_attempt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: шесть подряд одинаковых обрывов сети.
    bob = _ScriptedBot(plan=[None] * 6)
    gateway, _ = _gateway_with_recorded_sleep(bob)

    # Act
    with caplog.at_level(logging.DEBUG):
        for _ in range(6):
            await gateway.poll_once()

    # Assert: НЕ строка WARNING на попытку — первый WARNING, дальше DEBUG.
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "poll failed" in r.getMessage()
    ]
    assert len(warnings) == 1, "повтор одинакового сбоя не должен сыпать WARNING"
    debugs = [
        r for r in caplog.records
        if r.levelno == logging.DEBUG and "poll still failing" in r.getMessage()
    ]
    assert len(debugs) == 5, "повторные сбои схлопнуты в DEBUG"


@pytest.mark.asyncio
async def test_recovery_logs_once_and_re_arms_the_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: сбой, сбой, успех, сбой — смена состояния должна снова дать WARNING.
    bob = _ScriptedBot(plan=[None, None, [], None])
    gateway, _ = _gateway_with_recorded_sleep(bob)

    # Act
    with caplog.at_level(logging.DEBUG):
        for _ in range(4):
            await gateway.poll_once()

    # Assert: два эпизода сбоя (до успеха и после) → два WARNING, не один и не
    # четыре. Успех между ними «перевзводит» первый WARNING следующего эпизода.
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "poll failed" in r.getMessage()
    ]
    assert len(warnings) == 2


# --- Разные боты: счётчик сбоев независим -------------------------------------


@pytest.mark.asyncio
async def test_backoff_counter_is_per_bot() -> None:
    # Arrange: BOB падает, GUPPI-подобный второй бот — успешен. Пауза BOB не должна
    # тормозить общий цикл больше, чем его собственный счётчик сбоев.
    bob = _ScriptedBot(plan=[None, None])
    guppi = _ScriptedBot(plan=[[], []])
    registry = _registry(bob)
    registry.register(
        identity=BotIdentity.GUPPI,
        bot=guppi,
        scope=BotScope(chat_id=_CHAT_ID, topic_id=None),
    )
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    gateway = MultiBotGateway(
        registry=registry,
        bus=AsyncEventBus(),
        poll_timeout=10,
        poll_sleep=record_sleep,
    )

    # Act: два тика (каждый тик опрашивает обоих ботов).
    for _ in range(2):
        await gateway.poll_once()

    # Assert: паузил только сбойный BOB (два раза, растущая), GUPPI не паузил.
    assert slept == [next_backoff(1), next_backoff(2)]


@pytest.mark.asyncio
async def test_os_error_also_backs_off() -> None:
    # Arrange: не только aiogram-обёртка — «голый» OSError тоже сетевой сбой.
    bob = _ScriptedBot(plan=[None, None], error_factory=lambda: OSError("down"))
    gateway, slept = _gateway_with_recorded_sleep(bob)

    # Act
    for _ in range(2):
        await gateway.poll_once()

    # Assert: OSError тоже уводит в бэкофф (частота попыток падает).
    assert slept == [next_backoff(1), next_backoff(2)]
