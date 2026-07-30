# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Приём не теряет сообщения на транзиентных обрывах Telegram (BOB-070).

Модуль закрывает инварианты poll-цикла :meth:`MultiBotGateway._poll_bot`:

* **INV-a / INV-e** — offset за апдейт сдвигается ТОЛЬКО после успешного
  ``route()``; если ``route()`` бросил транзиентно, offset не двигаем и батч
  останавливаем на этом апдейте, поэтому Telegram переприсылает всё ≥ offset
  в исходном порядке (at-least-once, без перестановки/дублей).
* **INV-b** — апдейт, стабильно падающий в ``route()``, после ``_MAX_ROUTE_ATTEMPTS``
  попыток ГРОМКО логируется и пропускается (offset сдвигается за него), а не
  зацикливает приём.
* **INV-c / INV-d** — ``get_updates``, бросивший ``TelegramNetworkError``
  (обёртка ``ServerDisconnectedError`` на рутинном обрыве long-poll), изолирован:
  ``_poll_bot`` вернул 0, не пробросил, offset не тронут, другой бот не задет.

Через границу: фейковый бот (scripted-батчи / бросок ``TelegramNetworkError``) +
стаб ``route`` (успех / транзиентный сбой / стабильный сбой). Без сети.
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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram.types import InputRichMessage

    from bob.infrastructure.telegram.gateway import (
        MessageLike,
        UpdateLike,
    )

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32


# --- Test doubles -------------------------------------------------------------


@dataclass
class _FakeUpdate:
    """Минимальный :class:`UpdateLike` — poll-цикл читает только ``update_id``."""

    update_id: int
    message: None = None
    effective_chat: None = None
    effective_user: None = None


@dataclass
class _FakeBot:
    """Отдаёт scripted-батчи апдейтов; может бросить сетевую ошибку (без сети).

    Реализует полную поверхность :class:`BotLike`; send-методы не вызываются в
    этих тестах (route застаблен), поэтому бросают ``NotImplementedError``.
    """

    updates_batches: list[list[_FakeUpdate]] = field(default_factory=list)
    raise_network_error: bool = False
    get_updates_calls: list[int] = field(default_factory=list)

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[_FakeUpdate]:
        self.get_updates_calls.append(offset)
        if self.raise_network_error:
            # То, что реально прилетает на рутинном обрыве long-poll: aiogram
            # оборачивает aiohttp.ServerDisconnectedError в TelegramNetworkError.
            raise TelegramNetworkError(
                method=GetUpdates(), message="ServerDisconnectedError"
            )
        if not self.updates_batches:
            return []
        return self.updates_batches.pop(0)

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,
        reply_parameters: object = None,
    ) -> MessageLike:  # pragma: no cover - not exercised by the poll-loop tests
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


def _registry(bob: _FakeBot, guppi: _FakeBot | None = None) -> BotRegistry:
    registry = BotRegistry()
    registry.register(
        identity=BotIdentity.BOB,
        bot=bob,
        scope=BotScope(chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID),
    )
    if guppi is not None:
        registry.register(
            identity=BotIdentity.GUPPI,
            bot=guppi,
            scope=BotScope(chat_id=_CHAT_ID, topic_id=None),
        )
    return registry


def _gateway(registry: BotRegistry) -> MultiBotGateway:
    return MultiBotGateway(registry=registry, bus=AsyncEventBus(), poll_timeout=10)


class _RouteStub:
    """Стаб ``route``: решает исход по ``update_id``; пишет порядок вызовов.

    * ``fail_ids`` — эти ``update_id`` бросают всегда (стабильный/poison-сбой);
    * ``fail_once_ids`` — бросают на первом вызове, затем успех (транзиент);
    * ``publish_ids`` — успех, возвращающий ``True`` (был опубликован event).
    """

    def __init__(
        self,
        *,
        fail_ids: set[int] | None = None,
        fail_once_ids: set[int] | None = None,
        publish_ids: set[int] | None = None,
    ) -> None:
        self._fail_ids = fail_ids or set()
        self._fail_once_ids = set(fail_once_ids or set())
        self._publish_ids = publish_ids or set()
        self.calls: list[int] = []

    async def __call__(self, update: UpdateLike, identity: BotIdentity) -> bool:
        self.calls.append(update.update_id)
        if update.update_id in self._fail_ids:
            raise RuntimeError(f"stable route failure for {update.update_id}")
        if update.update_id in self._fail_once_ids:
            self._fail_once_ids.discard(update.update_id)
            raise RuntimeError(f"transient route failure for {update.update_id}")
        return update.update_id in self._publish_ids


# --- INV-a / INV-e: транзиент → offset НЕ сдвинут за упавший апдейт ------------


@pytest.mark.asyncio
async def test_transient_route_failure_keeps_offset_for_redelivery() -> None:
    # Arrange: батч [10, 11, 12]; апдейт 11 падает транзиентно.
    bob = _FakeBot(updates_batches=[[_FakeUpdate(10), _FakeUpdate(11), _FakeUpdate(12)]])
    gateway = _gateway(_registry(bob))
    stub = _RouteStub(fail_once_ids={11}, publish_ids={10})
    gateway.route = stub  # type: ignore[method-assign]

    # Act
    published = await gateway.poll_once()

    # Assert: 10 принят (offset за 10 → 11), 11 упал → батч встал, offset = 11
    # (Telegram переприсылает 11 и 12), опубликован только 10.
    assert published == 1
    assert gateway._offsets[BotIdentity.BOB] == 11
    assert stub.calls == [10, 11]

    # Второй тик: get_updates запрошен с offset=11 (переприсылка 11 и 12).
    bob.updates_batches = [[_FakeUpdate(11), _FakeUpdate(12)]]
    await gateway.poll_once()
    assert bob.get_updates_calls[-1] == 11
    assert gateway._offsets[BotIdentity.BOB] == 13


# --- INV-b: poison-апдейт пропускается после cap, с громким логом --------------


@pytest.mark.asyncio
async def test_poison_update_is_skipped_after_cap(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: апдейт 5 стабильно падает в route(); переприсылается каждый тик.
    bob = _FakeBot()
    gateway = _gateway(_registry(bob))
    stub = _RouteStub(fail_ids={5})
    gateway.route = stub  # type: ignore[method-assign]

    # Act: три тика с переприсылкой 5 → offset НЕ двигается (≤ cap).
    for _ in range(3):
        bob.updates_batches = [[_FakeUpdate(5)]]
        await gateway.poll_once()
    assert gateway._offsets[BotIdentity.BOB] == 0  # ещё не пропущен

    # Четвёртая встреча 5 → превышен cap → пропуск (offset сдвинут) + error-лог.
    with caplog.at_level(logging.ERROR):
        bob.updates_batches = [[_FakeUpdate(5)]]
        await gateway.poll_once()

    # Assert: offset сдвинут за poison-апдейт, громкий error-лог.
    assert gateway._offsets[BotIdentity.BOB] == 6
    assert any(record.levelno >= logging.ERROR for record in caplog.records)

    # Счётчик сброшен: следующий апдейт после poison обрабатывается штатно.
    bob.updates_batches = [[_FakeUpdate(6)]]
    await gateway.poll_once()
    assert gateway._offsets[BotIdentity.BOB] == 7


@pytest.mark.asyncio
async def test_route_success_resets_poison_counter() -> None:
    # Arrange: апдейт 5 падает дважды (транзиент), затем стабильно проходит —
    # счётчик неудач не должен «докопиться» до cap и пропустить его.
    bob = _FakeBot()
    gateway = _gateway(_registry(bob))

    class _TwoThenOk:
        def __init__(self) -> None:
            self.left = 2
            self.calls: list[int] = []

        async def __call__(self, update: UpdateLike, identity: BotIdentity) -> bool:
            self.calls.append(update.update_id)
            if self.left > 0:
                self.left -= 1
                raise RuntimeError("transient")
            return False

    route = _TwoThenOk()
    gateway.route = route  # type: ignore[method-assign]

    for _ in range(3):
        bob.updates_batches = [[_FakeUpdate(5)]]
        await gateway.poll_once()

    # Assert: третья попытка успешна → offset сдвинут, апдейт НЕ был пропущен как
    # poison (обработан честно), счётчик сброшен.
    assert gateway._offsets[BotIdentity.BOB] == 6
    assert route.calls == [5, 5, 5]


# --- INV-c / INV-d: сетевой сбой изолирован ------------------------------------


@pytest.mark.asyncio
async def test_network_error_is_isolated_and_offset_untouched() -> None:
    # Arrange: get_updates бросает TelegramNetworkError (ServerDisconnectedError).
    bob = _FakeBot(raise_network_error=True)
    gateway = _gateway(_registry(bob))
    gateway._offsets[BotIdentity.BOB] = 42

    # Act: тик не должен пробросить наружу.
    published = await gateway.poll_once()

    # Assert: вернул 0, offset не тронут (ретрай на следующем тике).
    assert published == 0
    assert gateway._offsets[BotIdentity.BOB] == 42


@pytest.mark.asyncio
async def test_one_bot_network_error_does_not_block_the_other() -> None:
    # Arrange: у BOB сеть падает, GUPPI отдаёт валидный батч.
    bob = _FakeBot(raise_network_error=True)
    guppi = _FakeBot(updates_batches=[[_FakeUpdate(7)]])
    gateway = _gateway(_registry(bob, guppi))
    stub = _RouteStub(publish_ids={7})
    gateway.route = stub  # type: ignore[method-assign]

    # Act
    published = await gateway.poll_once()

    # Assert: сбой BOB изолирован, GUPPI обработан (published=1, offset двинут).
    assert published == 1
    assert gateway._offsets[BotIdentity.GUPPI] == 8
    assert stub.calls == [7]


# --- Успешный батч: все по порядку, offset за последним -----------------------


@pytest.mark.asyncio
async def test_successful_batch_advances_offset_past_last_in_order() -> None:
    # Arrange: батч [3, 4, 5] проходит целиком.
    bob = _FakeBot(updates_batches=[[_FakeUpdate(3), _FakeUpdate(4), _FakeUpdate(5)]])
    gateway = _gateway(_registry(bob))
    stub = _RouteStub(publish_ids={3, 4, 5})
    gateway.route = stub  # type: ignore[method-assign]

    # Act
    published = await gateway.poll_once()

    # Assert: все обработаны по возрастанию update_id, offset за последним.
    assert published == 3
    assert stub.calls == [3, 4, 5]
    assert gateway._offsets[BotIdentity.BOB] == 6
