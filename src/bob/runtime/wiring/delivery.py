# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root delivery wiring — инструмент отправки за ``social.delivery``.

Единственное место, где ``send_to_chat`` (BOB-090.B1) вообще появляется: флаг OFF (по
умолчанию — эпик отгружается целиком) → capability не зарегистрирована, значит её нет в
манифесте, модель физически не может её вызвать, и ход байт-в-байт прежний.

Здесь же собираются ИЗВЕСТНЫЕ адреса — из того же конфига, которым живёт двухботовый
гейтвей: общая комната (чат + топик Боба, а не General) и личка owner'а. Список намеренно
закрытый: чистое ядро выбора адреса умеет отвечать «переспроси», а откуда взяться
адресу — решает композиционный корень, не модель.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.usecases.delivery_scope import current_delivery_scope
from bob.capabilities.usecases.send_to_chat import make_send_to_chat_capability
from bob.infrastructure.telegram.outbound_messenger import TelegramOutboundMessenger
from bob.runtime.config import _flag, _int, _section
from bob.social.destination import DestinationKind, KnownDestination

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.usecases.disclosure_consent_gate import DisclosureConsentGate
    from bob.capabilities.usecases.registry import CapabilityRegistry
    from bob.capabilities.usecases.send_to_chat import _PersonDirectory
    from bob.infrastructure.telegram.gateway import BotLike

__all__ = ["build_send_to_chat", "known_destinations"]

# Человеческие метки известных мест: их Боб произносит, переспрашивая «в какой именно».
_GROUP_LABEL = "наша группа"
_OWNER_DM_LABEL = "личка Вовы"


def known_destinations(config: Mapping[str, object]) -> tuple[KnownDestination, ...]:
    """Адреса, которые Боб знает, из конфига гейтвея (ничего не выдумывая).

    Комната берётся вместе с ТОПИКОМ Боба: в форум-группе отправка без треда попадает в
    General, то есть «не туда, где говорят» (тот же дефект, что и у ack, B5). Личка
    owner'а по умолчанию равна его user id — 1:1-чат в Telegram имеет id пользователя, —
    и топика у неё нет. Ненастроенный чат (``0``) не превращается ни во что: пустой
    список означает «адресов не знаю», и ядро тогда переспрашивает.
    """
    telegram = _section(config, "telegram")
    chat_id = _int(telegram, "chat_id", 0)
    owner_id = _int(telegram, "owner_id", 0)
    dm_chat_id = _int(telegram, "owner_dm_chat_id", owner_id)
    destinations: list[KnownDestination] = []
    if chat_id:
        destinations.append(
            KnownDestination(
                chat_id=chat_id,
                topic_id=_int(_section(telegram, "bob"), "topic_id", 0) or None,
                label=_GROUP_LABEL,
                kind=DestinationKind.GROUP,
            )
        )
    if dm_chat_id:
        destinations.append(
            KnownDestination(
                chat_id=dm_chat_id,
                topic_id=None,
                label=_OWNER_DM_LABEL,
                kind=DestinationKind.OWNER_DM,
            )
        )
    return tuple(destinations)


def build_send_to_chat(
    config: Mapping[str, object],
    *,
    registry: CapabilityRegistry,
    bot: BotLike,
    directory: _PersonDirectory,
    consent: DisclosureConsentGate | None,
) -> bool:
    """Зарегистрировать ``send_to_chat``, когда ``social.delivery`` включён.

    Возвращает, была ли capability зарегистрирована. Не регистрируется совсем, если
    адресов нет: инструмент, который может только переспрашивать, модели не нужен —
    он лишь занимал бы место в манифесте.

    Транспорт — :class:`TelegramOutboundMessenger` над ботом БОБА (в комнате появляется
    он); ростер даёт настоящие ``@ник``; ``consent`` — существующий контур согласия
    (BOB-082.4), и его отсутствие означает «приватное не выносим», а не «выносим молча».
    Обстоятельства хода читаются из :func:`current_delivery_scope`, поэтому вне хода
    инструмент не отправляет ничего.

    🔴 Связь флагов: сам контур согласия собирается ТОЛЬКО за ``coder.dev_dm``. При
    ``social.delivery`` ON и ``coder.dev_dm`` OFF отправка обычных сообщений работает, а
    приватное, поднятое памятью, не уедет никуда — спросить разрешения не у кого, и
    безопасное умолчание отказывает. Флаги имеет смысл включать вместе (описано в
    ``config/bob.example.yaml``).
    """
    if not _flag(_section(config, "social"), "delivery"):
        return False
    known = known_destinations(config)
    if not known:
        return False
    registry.register(
        make_send_to_chat_capability(
            messenger=TelegramOutboundMessenger(bot),
            known=known,
            directory=directory,
            consent=consent,
            scope_source=current_delivery_scope,
            owner_id=_int(_section(config, "telegram"), "owner_id", 0) or None,
        )
    )
    return True
