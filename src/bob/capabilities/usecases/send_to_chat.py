# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``send_to_chat`` — написать в УКАЗАННЫЙ чат, а не туда, откуда пришёл ход (BOB-090.B1).

Корень эпика: исходящего адреса не существовало как понятия — ответ всегда уходил в
``chat_id`` текущего хода, поэтому просьба из лички «расскажи Норману в нашей группе»
была невыполнима (эпизоды 3088 / 3091). Этот инструмент — недостающая половина.

Почему инструмент, а не перенаправление готового ответа: реплика, сочинённая для owner'а
в личке, комнате не адресована. Аргументом ``text`` модель пишет то, что должно появиться
ИМЕННО ТАМ, а вердикты «переспроси» / «нужно согласие» возвращаются ей же — и Боб
переспрашивает СВОИМИ словами, без единой скриптованной реплики.

Политика вся вынесена в чистые ядра и лишь собирается здесь:

* :func:`~bob.social.destination.resolve_destination` — адрес или «переспроси»
  (при неоднозначности не угадывает; не-owner отказ; тот же чат — отказ);
* :func:`~bob.social.disclosure.transfer_needs_consent` — нужен ли перенос согласия
  (ПО МАТЕРИАЛУ, а не по форме — и по ВСЕМУ материалу хода, из единого следа
  :class:`~bob.capabilities.usecases.turn_material.TurnMaterial`) — и тогда его даёт
  существующий consent-контур BOB-082.4;
* :func:`~bob.social.mention.ground_mentions` — заземление упоминаний на ростер, чтобы
  «@Норман» стал ``@NormanGri``, а неподтверждённый тег потерял «собаку».

🔴 Никакой автономии (урок BOB-076): обстоятельства хода приходят из
:class:`~bob.capabilities.usecases.delivery_scope.DeliveryScope`, и без армированного хода
— как и на ходе не-owner'а — инструмент не отправляет НИЧЕГО. Транспорт инжектится портом
:class:`~bob.capabilities.ports.OutboundMessenger` (поверх существующего rich-шва, нового
транспорта в эпике нет). Регистрируется за флагом ``social.delivery`` (default OFF).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.social.destination import (
    DestinationKind,
    DestinationOutcome,
    resolve_destination,
)
from bob.social.disclosure import transfer_needs_consent
from bob.social.mention import ground_mentions, handles_from

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from bob.capabilities.ports import Capability, OutboundMessenger, Permission
    from bob.capabilities.usecases.delivery_scope import DeliveryScope
    from bob.social.destination import KnownDestination
    from bob.social.first_impression import FirstImpression
    from bob.social.mention import PersonHandle

logger = logging.getLogger(__name__)

__all__ = ["make_send_to_chat_capability"]

# Сколько знакомых Боб держит «в голове», проверяя упоминания. Тот же порядок, что у
# ростера (BOB-080): свежие лица, а не вся история знакомств.
_DIRECTORY_LIMIT = 30

_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "place": {"type": "string", "enum": ["group", "owner_dm"]},
        "text": {"type": "string"},
    },
    "required": ["place", "text"],
}

_DESCRIPTION = (
    "Отправить сообщение в ДРУГОЙ чат: 'group' — общая комната, 'owner_dm' — личка "
    "Вовы. Вызывай ТОЛЬКО когда Вова прямо просит написать куда-то ещё («напиши в "
    "группу», «расскажи Норману в нашей группе»). Никогда по своей инициативе и никогда "
    "для обычного ответа — обычный ответ и так уходит туда, где вы говорите. В 'text' "
    "пиши сообщение целиком и так, как оно должно выглядеть В ТОЙ комнате: там прочтут "
    "только его, без этого разговора. Если в ответе сказано, что отправка не состоялась, "
    "не выдумывай, что отправил, — сделай то, о чём там сказано."
)

# Подсказки Бобу (не готовые реплики человеку): почему отправка не состоялась.
_NO_TURN = (
    "Не отправляй: сейчас нет хода, в котором тебя об этом просили. "
    "Писать в другие чаты можно только по просьбе Вовы."
)
_EMPTY_TEXT = "Не отправляй: сообщение пустое. Напиши, что именно передать."
_NEEDS_CONSENT = (
    "Не отправляй. В этом материале есть то, что говорилось наедине, а чат публичный — "
    "спроси у Вовы согласие вынести это туда и отправь только после явного «да»."
)


class _PersonDirectory(Protocol):
    """Узкий срез ростера: недавние знакомые (реализует ``SqliteFirstImpressionStore``)."""

    async def recent(self, *, limit: int) -> list[FirstImpression]:
        """Вернуть ``limit`` самых свежих знакомств, новые первыми."""
        ...


class _ConsentGate(Protocol):
    """Существующий шов согласия owner'а (BOB-082 .4) — структурно, без импорта."""

    async def owner_consents(
        self, *, text: str, to_room: bool, is_owner: bool, recent_thread: str = ""
    ) -> bool:
        """Разрешил ли owner ЭТИМ ходом вынести приватное людям в комнате."""
        ...


class _SendToChatCapability:
    """Отправка текста по разрешённому адресу — с гейтами адреса, согласия и упоминаний."""

    def __init__(
        self,
        *,
        messenger: OutboundMessenger,
        known: Sequence[KnownDestination],
        directory: _PersonDirectory,
        consent: _ConsentGate | None,
        scope_source: Callable[[], DeliveryScope | None],
        owner_id: int | None = None,
    ) -> None:
        self._messenger = messenger
        self._known = tuple(known)
        self._directory = directory
        self._consent = consent
        self._scope_source = scope_source
        self._owner_id = owner_id

    @property
    def name(self) -> str:
        return "send_to_chat"

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _INPUT_SCHEMA

    @property
    def permission(self) -> Permission:
        # Не «safe»: это действие видно посторонним людям и необратимо, а значит его
        # должен санкционировать человек. Заявление РАБОТАЮЩЕЕ (BOB-090.B-fix): его
        # читает автономная граница (``SafeCapabilityDispatcher``) и на самодвижущемся
        # тике отказывает — даже если имя внесли в ``goals.safe_capabilities``.
        return "confirm"

    async def execute(self, args: Mapping[str, object]) -> object:
        """Отправить ``args['text']`` в ``args['place']`` — или честно объяснить, почему нет."""
        place, text = _read_args(args)
        scope = self._scope_source()
        if scope is None:
            return _refused(_NO_TURN)
        if not text.strip():
            return _refused(_EMPTY_TEXT)
        verdict = resolve_destination(
            place,
            self._known,
            from_owner=scope.from_owner,
            here_chat_id=scope.here_chat_id,
        )
        if verdict.outcome is not DestinationOutcome.RESOLVED or verdict.address is None:
            return _refused(verdict.note)
        address = verdict.address
        if not await self._transfer_allowed(scope, address):
            return _refused(_NEEDS_CONSENT)
        grounded = ground_mentions(text, await self._people())
        await self._messenger.send(
            chat_id=address.chat_id, topic_id=address.topic_id, markdown=grounded
        )
        return {"sent": True, "place": address.label, "text": grounded}

    async def _transfer_allowed(
        self, scope: DeliveryScope, address: KnownDestination
    ) -> bool:
        """Можно ли нести материал ЭТОГО хода по этому адресу (BOB-090.B4/B-fix2).

        Перенос считается по МАТЕРИАЛУ, который Боб ДОБАВЛЯЕТ от себя, и материал берётся
        из ЕДИНОГО следа хода
        (:class:`~bob.capabilities.usecases.turn_material.TurnMaterial`), а не из одной
        двери. 🔴 Это и есть фикс BLOCKER-1: гейт читал только авто-recall, снятый ДО
        генерации, поэтому приватное, поднятое памятью уже в ходе (``search_memory`` /
        ``recall_memory`` в том же tool-loop, grounded-addon callback), уезжало в комнату
        без вопроса. След пополняется на месте сборки порта памяти, значит любая дверь
        доезжает до гейта — включая ту, которой ещё нет.

        🔴 Прямое распоряжение owner'а гейт по-прежнему не зажигает (BOB-090.B-fix):
        живая нить разговора — названное исключение внутри следа, а не пробел в нём;
        согласие содержится в самой команде, и Tier-0 на неё не горит.

        Согласие берёт существующий контур BOB-082.4 (второго не заводим); ``to_room``
        — про АУДИТОРИЮ адресата, а не про канал текущего хода: спрашивают ровно о том,
        выносить ли приватное людям в комнате. Контур не подключён → согласия взять
        неоткуда → перенос не делаем (безопасное умолчание, а не «пропускаем»).
        """
        if not transfer_needs_consent(
            scope.material.transferable(),
            destination_public=address.kind is DestinationKind.GROUP,
        ):
            return True
        if self._consent is None:
            return False
        return await self._consent.owner_consents(
            text=scope.request_text,
            to_room=True,
            is_owner=scope.from_owner,
            recent_thread=scope.recent_thread,
        )

    async def _people(self) -> tuple[PersonHandle, ...]:
        """Знакомые, по которым проверяются упоминания (сбой ростера → пусто).

        🔴 Пустой ростер — консервативная сторона: :func:`ground_mentions` тогда снимает
        «собаку» со ВСЕХ тегов, то есть недоступность ростера приводит к обращению по
        имени, а не к неподтверждённому тегу. Ход при этом не ломается.

        ``owner_id`` из конфига опознаёт владельца в ростере ПО ЛИЧНОСТИ: имя там —
        Telegram full_name, которое человек ставит себе сам, поэтому обращение к owner'у
        среди тёзок не должно решаться строкой (BOB-090.B-fix2, MAJOR-2).
        """
        try:
            return handles_from(
                await self._directory.recent(limit=_DIRECTORY_LIMIT),
                owner_id=self._owner_id,
            )
        except Exception:
            logger.exception("reading the roster for mentions failed (tags demoted)")
            return ()


def _read_args(args: Mapping[str, object]) -> tuple[str, str]:
    """Прочитать ``place`` и ``text`` из аргументов модели (кривой вызов — ``ValueError``)."""
    place = args.get("place")
    text = args.get("text")
    if not isinstance(place, str) or not isinstance(text, str):
        raise ValueError("send_to_chat requires string 'place' and 'text' arguments")
    return place, text


def _refused(note: str) -> Mapping[str, object]:
    """Ответ модели о несостоявшейся отправке — с причиной, что делать дальше."""
    return {"sent": False, "note": note}


def make_send_to_chat_capability(
    *,
    messenger: OutboundMessenger,
    known: Sequence[KnownDestination],
    directory: _PersonDirectory,
    consent: _ConsentGate | None,
    scope_source: Callable[[], DeliveryScope | None],
    owner_id: int | None = None,
) -> Capability:
    """Собрать capability ``send_to_chat`` над транспортом, ростером и гейтом согласия."""
    return _SendToChatCapability(
        messenger=messenger,
        known=known,
        directory=directory,
        consent=consent,
        scope_source=scope_source,
        owner_id=owner_id,
    )
