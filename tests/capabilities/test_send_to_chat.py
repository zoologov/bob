# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты инструмента отправки в указанный чат (BOB-090.B1).

Симптом эпика: просьба из лички «расскажи Норману в нашей группе» невыполнима — ответ
всегда уходил туда, откуда пришёл ход. Инструмента отправки не существовало.

Здесь проверяется весь контур инструмента:

* отправка уходит по ТОЧНОМУ адресу (чат + форум-топик), а не «в чат вообще»;
* 🔴 писать в другой чат можно ТОЛЬКО по просьбе owner'а (урок BOB-076) — и без
  армированного хода (никто ничего не просил) инструмент не отправляет ничего;
* при неоднозначности адресата инструмент НЕ угадывает, а возвращает Бобу «переспроси»;
* 🔴 приватный материал не уезжает в публичный чат без согласия owner'а НА ЭТОТ ход;
* упоминания в исходящем тексте заземляются на ростер: «@Норман» → «@NormanGri», а
  неподтверждённый тег теряет «собаку».
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from bob.capabilities.usecases.delivery_scope import DeliveryScope
from bob.capabilities.usecases.send_to_chat import make_send_to_chat_capability
from bob.social.destination import DestinationKind, KnownDestination
from bob.social.disclosure import VISIBILITY_OWNER_PRIVATE, VISIBILITY_PUBLIC
from bob.social.first_impression import FirstImpression

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.capabilities.ports import Capability

_DM_CHAT = 555
_GROUP = KnownDestination(
    chat_id=-1004372947307,
    topic_id=32,
    label="наша группа",
    kind=DestinationKind.GROUP,
)
_OWNER_DM = KnownDestination(
    chat_id=_DM_CHAT, topic_id=None, label="личка", kind=DestinationKind.OWNER_DM
)
_OTHER_GROUP = KnownDestination(
    chat_id=-100999, topic_id=None, label="рабочий чат", kind=DestinationKind.GROUP
)


class _FakeMessenger:
    def __init__(self) -> None:
        self.sent: list[tuple[int, int | None, str]] = []

    async def send(self, *, chat_id: int, topic_id: int | None, markdown: str) -> None:
        self.sent.append((chat_id, topic_id, markdown))


class _FakeDirectory:
    def __init__(self, people: Sequence[FirstImpression] = ()) -> None:
        self._people = list(people)

    async def recent(self, *, limit: int) -> list[FirstImpression]:
        return self._people[:limit]


class _BrokenDirectory:
    async def recent(self, *, limit: int) -> list[FirstImpression]:
        del limit
        raise RuntimeError("ростер недоступен")


class _FakeConsent:
    def __init__(self, verdict: bool) -> None:
        self.verdict = verdict
        self.calls: list[Mapping[str, object]] = []

    async def owner_consents(
        self, *, text: str, is_group: bool, is_owner: bool, recent_thread: str = ""
    ) -> bool:
        self.calls.append(
            {
                "text": text,
                "is_group": is_group,
                "is_owner": is_owner,
                "recent_thread": recent_thread,
            }
        )
        return self.verdict


def _norman(username: str | None = "NormanGri") -> FirstImpression:
    return FirstImpression(
        sender_id=7,
        first_seen_at=datetime(2026, 8, 1, tzinfo=UTC),
        note="Норман — знакомый",
        display_name="Норман",
        username=username,
    )


def _scope(
    *,
    from_owner: bool = True,
    material_private: bool = False,
    turn_visibility: str | None = VISIBILITY_PUBLIC,
) -> DeliveryScope:
    return DeliveryScope(
        from_owner=from_owner,
        here_chat_id=_DM_CHAT,
        request_text="расскажи Норману в нашей группе про релиз",
        turn_visibility=turn_visibility,
        recalled=(
            ({"content": "личное", "visibility": VISIBILITY_OWNER_PRIVATE},)
            if material_private
            else ({"content": "публичное", "visibility": VISIBILITY_PUBLIC},)
        ),
    )


def _capability(
    *,
    messenger: _FakeMessenger,
    scope: DeliveryScope | None,
    known: tuple[KnownDestination, ...] = (_GROUP, _OWNER_DM),
    directory: Any = None,
    consent: Any = None,
) -> Capability:
    return make_send_to_chat_capability(
        messenger=messenger,
        known=known,
        directory=directory if directory is not None else _FakeDirectory((_norman(),)),
        consent=consent,
        scope_source=lambda: scope,
    )


async def _execute(capability: Capability, *, place: str, text: str) -> Mapping[str, object]:
    """Вызвать инструмент и вернуть его отчёт как словарь (контракт tool-результата)."""
    result = await capability.execute({"place": place, "text": text})
    assert isinstance(result, Mapping)
    return result


# --- Отправка по точному адресу -----------------------------------------------


async def test_the_message_lands_in_the_exact_chat_and_topic() -> None:
    messenger = _FakeMessenger()
    capability = _capability(messenger=messenger, scope=_scope())

    result = await _execute(capability, place="group", text="Всем привет")

    assert messenger.sent == [(_GROUP.chat_id, 32, "Всем привет")]
    assert result == {"sent": True, "place": "наша группа", "text": "Всем привет"}


async def test_the_tool_is_named_and_described_for_the_model() -> None:
    capability = _capability(messenger=_FakeMessenger(), scope=_scope())

    assert capability.name == "send_to_chat"
    assert "Вов" in capability.description  # только по просьбе owner'а
    assert capability.permission == "confirm"


async def test_an_empty_text_sends_nothing() -> None:
    messenger = _FakeMessenger()
    capability = _capability(messenger=messenger, scope=_scope())

    result = await _execute(capability, place="group", text="   ")

    assert messenger.sent == []
    assert result["sent"] is False


@pytest.mark.parametrize(
    "args", [{}, {"place": "group"}, {"text": "ok"}, {"place": 1, "text": "x"}]
)
async def test_malformed_arguments_are_rejected(args: Mapping[str, object]) -> None:
    messenger = _FakeMessenger()
    capability = _capability(messenger=messenger, scope=_scope())

    with pytest.raises(ValueError, match="send_to_chat"):
        await capability.execute(args)
    assert messenger.sent == []


# --- Только по просьбе owner'а ------------------------------------------------


async def test_a_non_owner_turn_sends_nothing() -> None:
    messenger = _FakeMessenger()
    capability = _capability(messenger=messenger, scope=_scope(from_owner=False))

    result = await _execute(capability, place="group", text="привет")

    assert messenger.sent == []
    assert result["sent"] is False
    assert result["note"]


async def test_without_an_armed_turn_nothing_is_ever_sent() -> None:
    # 🔴 Реестр capability общий и живёт всё время процесса. Нет хода — нет отправки:
    # инструмент структурно не может выстрелить сам по себе (урок BOB-076).
    messenger = _FakeMessenger()
    capability = _capability(messenger=messenger, scope=None)

    result = await _execute(capability, place="group", text="привет")

    assert messenger.sent == []
    assert result["sent"] is False


# --- Неоднозначность: переспросить --------------------------------------------


async def test_two_groups_are_never_guessed_between() -> None:
    messenger = _FakeMessenger()
    capability = _capability(
        messenger=messenger, scope=_scope(), known=(_GROUP, _OTHER_GROUP)
    )

    result = await _execute(capability, place="group", text="привет")

    assert messenger.sent == []
    assert result["sent"] is False
    assert "наша группа" in str(result["note"])


async def test_the_same_chat_is_refused_instead_of_echoed() -> None:
    messenger = _FakeMessenger()
    capability = _capability(messenger=messenger, scope=_scope())

    result = await _execute(capability, place="owner_dm", text="привет")

    assert messenger.sent == []
    assert result["sent"] is False


# --- Перенос приватного -------------------------------------------------------


async def test_private_material_is_not_carried_into_a_room_without_consent() -> None:
    # 🔴 Ровно та дыра, ради которой писан гейт: «расскажи Норману про X», где X — из лички.
    messenger = _FakeMessenger()
    consent = _FakeConsent(verdict=False)
    capability = _capability(
        messenger=messenger, scope=_scope(material_private=True), consent=consent
    )

    result = await _execute(capability, place="group", text="Вова говорил, что…")

    assert messenger.sent == []
    assert result["sent"] is False
    assert "соглас" in str(result["note"]).lower()


async def test_explicit_owner_consent_lets_the_transfer_through() -> None:
    messenger = _FakeMessenger()
    consent = _FakeConsent(verdict=True)
    capability = _capability(
        messenger=messenger, scope=_scope(material_private=True), consent=consent
    )

    result = await _execute(capability, place="group", text="Вова говорил, что…")

    assert result["sent"] is True
    assert len(messenger.sent) == 1
    # Согласие спрашивается про ЭТОТ ход и про эту аудиторию.
    assert consent.calls[0]["text"] == "расскажи Норману в нашей группе про релиз"
    assert consent.calls[0]["is_group"] is True
    assert consent.calls[0]["is_owner"] is True


async def test_a_private_conversation_alone_already_triggers_the_gate() -> None:
    # Материал — это и сам разговор: пересказ лички в комнату остаётся переносом.
    messenger = _FakeMessenger()
    capability = _capability(
        messenger=messenger,
        scope=_scope(turn_visibility=VISIBILITY_OWNER_PRIVATE),
        consent=_FakeConsent(verdict=False),
    )

    result = await _execute(capability, place="group", text="мы тут решили…")

    assert messenger.sent == []
    assert result["sent"] is False


async def test_without_a_consent_seam_private_material_never_leaves() -> None:
    # Гейт не подключён → согласия взять неоткуда → перенос не делаем (не «пропускаем»).
    messenger = _FakeMessenger()
    capability = _capability(
        messenger=messenger, scope=_scope(material_private=True), consent=None
    )

    result = await _execute(capability, place="group", text="Вова говорил…")

    assert messenger.sent == []
    assert result["sent"] is False


async def test_public_material_needs_no_consent_call_at_all() -> None:
    messenger = _FakeMessenger()
    consent = _FakeConsent(verdict=False)
    capability = _capability(messenger=messenger, scope=_scope(), consent=consent)

    result = await _execute(capability, place="group", text="погода отличная")

    assert result["sent"] is True
    assert consent.calls == []  # обычная отправка не жжёт Tier-0


# --- Упоминания ---------------------------------------------------------------


async def test_an_invented_tag_is_repaired_before_the_message_leaves() -> None:
    # Эпизод 3088: «@Норман» → «@NormanGri».
    messenger = _FakeMessenger()
    capability = _capability(messenger=messenger, scope=_scope())

    await _execute(capability, place="group", text="@Норман, глянь")

    assert messenger.sent[0][2] == "@NormanGri, глянь"


async def test_a_person_without_a_handle_is_addressed_by_name() -> None:
    messenger = _FakeMessenger()
    capability = _capability(
        messenger=messenger,
        scope=_scope(),
        directory=_FakeDirectory((_norman(username=None),)),
    )

    await _execute(capability, place="group", text="@Норман, глянь")

    assert messenger.sent[0][2] == "Норман, глянь"


async def test_a_broken_roster_still_never_lets_an_unverified_tag_out() -> None:
    # Ростер недоступен → подтвердить тег нечем → «собака» снимается, но ход не ломается.
    messenger = _FakeMessenger()
    capability = _capability(
        messenger=messenger, scope=_scope(), directory=_BrokenDirectory()
    )

    result = await _execute(capability, place="group", text="@Норман, глянь")

    assert result["sent"] is True
    assert messenger.sent[0][2] == "Норман, глянь"
