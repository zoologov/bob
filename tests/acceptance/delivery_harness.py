# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Boundary-харнесс сценариев «Боб пишет туда, куда просят» (BOB-090.B, US-2/US-3).

Гоняет ОДИН ход через живой композиционный корень (:mod:`tests.acceptance.live_app_harness`)
и возвращает только наблюдаемое: что ушло, каким ботом, в какой чат и в какой топик, и что
инструмент отправки сказал самой модели (её единственный источник правды о том, состоялась
ли отправка). Приватного состояния инструмента, реестра и хода сценарии не касаются.

Два входа — по двум сторонам решения owner'а (BOB-076):

* :func:`run_owner_dm_request` — owner просит ИЗ ЛИЧКИ (главный сценарий эпика);
* :func:`run_trusted_peer_request` — просит доверенный участник из общей комнаты; он не
  гость, инструменты Боб ему даёт охотно, и тем строже проверка, что распорядиться
  отправкой в другой чат он всё равно не может.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.application.runtime.events import MessageReceived
from tests.acceptance.live_app_harness import (
    BOB_TOPIC_ID,
    GROUP_CHAT_ID,
    NORMAN_ID,
    NORMAN_NAME,
    NORMAN_USERNAME,
    OWNER_DM_CHAT_ID,
    OWNER_ID,
    RecordingBot,
    SentLine,
    Tier0Provider,
    Tier1Provider,
    build_live_app,
    offers_tool,
    remember_norman,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    "DeliveryOutcome",
    "run_owner_dm_request",
    "run_trusted_peer_request",
]


@dataclass(slots=True)
class DeliveryOutcome:
    """Наблюдаемый итог хода: кто что куда отправил и что инструмент сказал модели."""

    bob: RecordingBot
    guppi: RecordingBot
    tool_results: tuple[str, ...] = ()
    consent_calls: int = 0
    tool_offered: bool = False

    @property
    def group(self) -> tuple[SentLine, ...]:
        """Всё, что вообще прозвучало в общей комнате (любым из двух ботов)."""
        return self.bob.to(GROUP_CHAT_ID) + self.guppi.to(GROUP_CHAT_ID)

    @property
    def dm(self) -> tuple[SentLine, ...]:
        """Всё, что прозвучало в личке owner'а (любым из двух ботов)."""
        return self.bob.to(OWNER_DM_CHAT_ID) + self.guppi.to(OWNER_DM_CHAT_ID)

    @property
    def tool_said(self) -> str:
        """Что инструмент отправки ответил МОДЕЛИ — по-человечески, одной строкой.

        Ответ едет к модели JSON'ом с экранированной кириллицей, поэтому здесь он
        разворачивается обратно: сценарий утверждает про смысл подсказки, а не про
        кодировку транспорта.
        """
        return "\n".join(_readable(result) for result in self.tool_results)

    @property
    def delivered(self) -> bool:
        """Считает ли сам инструмент, что отправка состоялась."""
        return any(
            _decoded(result).get("sent") is True for result in self.tool_results
        )


def _decoded(result: str) -> Mapping[str, object]:
    """Разобрать ответ инструмента (мусор — пустая карта, ассерт тогда честно упадёт)."""
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _readable(result: str) -> str:
    """Ответ инструмента человеческими буквами (значения полей через пробел)."""
    decoded = _decoded(result)
    if not decoded:
        return result
    return " ".join(str(value) for value in decoded.values())


async def run_owner_dm_request(
    tmp_path: Path,
    *,
    request: str,
    tool_call: Mapping[str, object] | None,
    reply: str = "Готово.",
    consent: bool = True,
    norman_username: str | None = NORMAN_USERNAME,
    delivery: bool = True,
) -> DeliveryOutcome:
    """Прогнать ход owner'а ИЗ ЛИЧКИ через живой граф и вернуть наблюдаемое.

    ``tool_call`` — аргументы, с которыми модель зовёт ``send_to_chat`` (``None`` — не
    зовёт вовсе); ``consent`` — что ответит Tier-0 на вопрос «owner разрешает вынести это
    в комнату?»; ``norman_username`` — ник Нормана в ЖИВОМ ростере (``None`` = ника нет,
    нормальное состояние в Telegram); ``delivery`` — флаг ``social.delivery``.
    """
    bob_bot, guppi_bot = RecordingBot("bob"), RecordingBot("guppi")
    tier0 = Tier0Provider(consent=consent)
    tier1 = Tier1Provider(reply=reply, tool_call=tool_call)
    app = build_live_app(
        tmp_path,
        tier0=tier0,
        tier1=tier1,
        bob_bot=bob_bot,
        guppi_bot=guppi_bot,
        delivery=delivery,
    )
    await app.startup()
    try:
        await remember_norman(app, username=norman_username)
        await app.event_bus.publish(
            MessageReceived(
                update_id=1,
                chat_id=OWNER_DM_CHAT_ID,
                message_id=11,
                text=request,
                sender_id=OWNER_ID,
                sender_name="Вова",
                is_group=False,
                topic_id=None,
            )
        )
    finally:
        await app.shutdown()
    return DeliveryOutcome(
        bob=bob_bot,
        guppi=guppi_bot,
        tool_results=tuple(tier1.tool_results),
        consent_calls=tier0.consent_calls,
        tool_offered=offers_tool(app, "send_to_chat"),
    )


async def run_trusted_peer_request(
    tmp_path: Path,
    *,
    request: str,
    tool_call: Mapping[str, object] | None,
    reply: str = "Понял.",
) -> DeliveryOutcome:
    """Прогнать ход ДОВЕРЕННОГО участника (не owner'а) из общей комнаты.

    Норман здесь авторизован — Боб видит в нём своего, а не гостя, и инструменты ему
    доступны. Тем строже проверка: распорядиться отправкой в другой чат вправе только
    owner, и однозначность адреса этого не отменяет (урок BOB-076).
    """
    bob_bot, guppi_bot = RecordingBot("bob"), RecordingBot("guppi")
    tier0 = Tier0Provider(consent=True)
    tier1 = Tier1Provider(reply=reply, tool_call=tool_call)
    app = build_live_app(
        tmp_path,
        tier0=tier0,
        tier1=tier1,
        bob_bot=bob_bot,
        guppi_bot=guppi_bot,
        delivery=True,
    )
    await app.startup()
    try:
        await remember_norman(app, username=NORMAN_USERNAME)
        await app.authorizer.authorize(NORMAN_ID)
        await app.event_bus.publish(
            MessageReceived(
                update_id=1,
                chat_id=GROUP_CHAT_ID,
                message_id=21,
                text=request,
                sender_id=NORMAN_ID,
                sender_name=NORMAN_NAME,
                sender_username=NORMAN_USERNAME,
                is_group=True,
                topic_id=BOB_TOPIC_ID,
            )
        )
    finally:
        await app.shutdown()
    return DeliveryOutcome(
        bob=bob_bot,
        guppi=guppi_bot,
        tool_results=tuple(tier1.tool_results),
        consent_calls=tier0.consent_calls,
        tool_offered=offers_tool(app, "send_to_chat"),
    )
