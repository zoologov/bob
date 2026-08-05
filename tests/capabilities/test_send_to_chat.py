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
from bob.capabilities.usecases.turn_material import MaterialOrigin, TurnMaterial
from bob.social.destination import DestinationKind, KnownDestination
from bob.social.disclosure import VISIBILITY_OWNER_PRIVATE, VISIBILITY_PUBLIC
from bob.social.first_impression import FirstImpression

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.capabilities.ports import Capability

_DM_CHAT = 555
_OWNER_ID = 27468732
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
        self.limits: list[int] = []

    async def recent(self, *, limit: int) -> list[FirstImpression]:
        self.limits.append(limit)
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
        self, *, text: str, to_room: bool, is_owner: bool, recent_thread: str = ""
    ) -> bool:
        self.calls.append(
            {
                "text": text,
                "to_room": to_room,
                "is_owner": is_owner,
                "recent_thread": recent_thread,
            }
        )
        return self.verdict


def _person(*, sender_id: int, name: str, username: str | None) -> FirstImpression:
    return FirstImpression(
        sender_id=sender_id,
        first_seen_at=datetime(2026, 8, 1, tzinfo=UTC),
        note=f"{name} — знакомый",
        display_name=name,
        username=username,
    )


def _norman(username: str | None = "NormanGri") -> FirstImpression:
    return _person(sender_id=7, name="Норман", username=username)


def _material(
    *, private: bool, origin: MaterialOrigin = MaterialOrigin.MEMORY
) -> TurnMaterial:
    """След материала хода: что попало в контекст генерации и какой дверью."""
    trail = TurnMaterial()
    # Живая нить приватного разговора отмечается на КАЖДОМ ходу из лички — ровно как в
    # проде: ход в личке приватен целиком, и переносом он от этого не становится.
    trail.note_visibility(VISIBILITY_OWNER_PRIVATE, origin=MaterialOrigin.LIVE_THREAD)
    trail.note(
        (
            {"content": "личное", "visibility": VISIBILITY_OWNER_PRIVATE}
            if private
            else {"content": "публичное", "visibility": VISIBILITY_PUBLIC},
        ),
        origin=origin,
    )
    return trail


def _scope(
    *,
    from_owner: bool = True,
    material_private: bool = False,
    material_origin: MaterialOrigin = MaterialOrigin.MEMORY,
    recent_thread: str = "",
) -> DeliveryScope:
    return DeliveryScope(
        from_owner=from_owner,
        here_chat_id=_DM_CHAT,
        request_text="расскажи Норману в нашей группе про релиз",
        material=_material(private=material_private, origin=material_origin),
        recent_thread=recent_thread,
    )


def _capability(
    *,
    messenger: _FakeMessenger,
    scope: DeliveryScope | None,
    known: tuple[KnownDestination, ...] = (_GROUP, _OWNER_DM),
    directory: Any = None,
    consent: Any = None,
    owner_id: int | None = None,
) -> Capability:
    return make_send_to_chat_capability(
        messenger=messenger,
        known=known,
        directory=directory if directory is not None else _FakeDirectory((_norman(),)),
        consent=consent,
        scope_source=lambda: scope,
        owner_id=owner_id,
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
    # Модель узнаёт, ЧТО не так: без подсказки она додумает, будто отправила.
    assert "пуст" in str(result["note"])


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
    assert "нет хода" in str(result["note"])


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
    assert consent.calls[0]["to_room"] is True
    assert consent.calls[0]["is_owner"] is True


async def test_the_consent_question_carries_the_recent_thread() -> None:
    # Судья согласия смотрит на просьбу В СИТУАЦИИ: нить хода доезжает до него, а не
    # теряется по дороге (пустая строка означала бы «контекста нет», а он есть).
    messenger = _FakeMessenger()
    consent = _FakeConsent(verdict=True)
    capability = _capability(
        messenger=messenger,
        scope=_scope(material_private=True, recent_thread="bob: рассказать им про X?"),
        consent=consent,
    )

    await _execute(capability, place="group", text="Вова говорил, что…")

    assert consent.calls[0]["recent_thread"] == "bob: рассказать им про X?"


async def test_a_direct_order_of_the_owner_is_sent_without_asking_consent() -> None:
    # 🔴 Ход owner'а в личке приватен ЦЕЛИКОМ, и пока это считалось переносом, Боб
    # отказывал owner'у в его же распоряжении. Согласие содержится в самой команде:
    # без приватного материала из памяти гейт не зажигается и Tier-0 не горит.
    messenger = _FakeMessenger()
    consent = _FakeConsent(verdict=False)
    capability = _capability(messenger=messenger, scope=_scope(), consent=consent)

    result = await _execute(capability, place="group", text="Вова закончил обзор.")

    assert result["sent"] is True
    assert messenger.sent == [(_GROUP.chat_id, 32, "Вова закончил обзор.")]
    assert consent.calls == [], "у owner'а спросили согласие на его же распоряжение"


async def test_private_raised_by_a_memory_tool_mid_turn_is_gated_the_same() -> None:
    # 🔴 BLOCKER-1: до фикса гейт читал ТОЛЬКО авто-recall, снятый до генерации. Модель
    # же может поднять приватное УЖЕ В ХОДЕ — вызвав search_memory / recall_memory в том
    # же tool-loop, — и такой материал уезжал в комнату без вопроса. След материала не
    # различает, какой дверью память подняли: важна метка, а не момент.
    messenger = _FakeMessenger()
    consent = _FakeConsent(verdict=False)
    trail = TurnMaterial()
    trail.note_visibility(VISIBILITY_OWNER_PRIVATE, origin=MaterialOrigin.LIVE_THREAD)
    scope = DeliveryScope(
        from_owner=True,
        here_chat_id=_DM_CHAT,
        request_text="расскажи Норману в нашей группе",
        material=trail,
    )
    capability = _capability(messenger=messenger, scope=scope, consent=consent)

    # Ход начался с ЧИСТЫМ следом — авто-recall ничего приватного не поднял.
    before = await _execute(capability, place="group", text="привет")
    assert before["sent"] is True

    # …а теперь память подняла приватное прямо посреди хода, инструментом.
    trail.note(
        ({"content": "личное", "visibility": VISIBILITY_OWNER_PRIVATE},),
        origin=MaterialOrigin.MEMORY,
    )
    after = await _execute(capability, place="group", text="а ещё Вова говорил…")

    assert after["sent"] is False
    assert "соглас" in str(after["note"]).lower()
    assert len(messenger.sent) == 1


async def test_a_turn_with_no_trail_at_all_asks_before_it_carries_anything() -> None:
    # Ход, у которого следа нет (никто не армировал), — это «материал неизвестен».
    # Сомнение удерживает: спрашиваем согласие, а не пропускаем молча.
    messenger = _FakeMessenger()
    consent = _FakeConsent(verdict=False)
    scope = DeliveryScope(
        from_owner=True,
        here_chat_id=_DM_CHAT,
        request_text="напиши в группу",
        material=TurnMaterial.unknown(),
    )
    capability = _capability(messenger=messenger, scope=scope, consent=consent)

    result = await _execute(capability, place="group", text="привет")

    assert result["sent"] is False
    assert messenger.sent == []


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


async def test_an_impostor_named_like_the_owner_never_takes_his_tag() -> None:
    # 🔴 BOB-090.B-fix2 (MAJOR-2): ``display_name`` — Telegram full_name, которое человек
    # ставит себе САМ. Владелец опознаётся по ID, поэтому обращение к нему в сообщении,
    # уходящем в КОМНАТУ, не может уехать на постороннего, назвавшегося его именем.
    messenger = _FakeMessenger()
    capability = _capability(
        messenger=messenger,
        scope=_scope(),
        directory=_FakeDirectory(
            (
                _person(sender_id=999, name="Вова", username="evil_guy"),
                _person(sender_id=_OWNER_ID, name="Вова Зоологов", username="vova_real"),
            )
        ),
        owner_id=_OWNER_ID,
    )

    await _execute(capability, place="group", text="@Вова закончил обзор")

    assert messenger.sent[0][2] == "@vova_real закончил обзор"


async def test_without_a_known_owner_id_a_contested_name_gets_no_tag() -> None:
    # Владелец в конфиге не назван — угадывать между тёзками нельзя: обращение по имени.
    messenger = _FakeMessenger()
    capability = _capability(
        messenger=messenger,
        scope=_scope(),
        directory=_FakeDirectory(
            (
                _person(sender_id=999, name="Вова", username="evil_guy"),
                _person(sender_id=_OWNER_ID, name="Вова Зоологов", username="vova_real"),
            )
        ),
    )

    await _execute(capability, place="group", text="@Вова закончил обзор")

    assert messenger.sent[0][2] == "Вова закончил обзор"


async def test_only_the_recent_faces_are_consulted_for_mentions() -> None:
    # Ростер «в голове» ограничен свежими лицами (тот же порядок, что у BOB-080): без
    # капа проверка упоминаний тянула бы всю историю знакомств на каждой отправке.
    directory = _FakeDirectory((_norman(),))
    capability = _capability(
        messenger=_FakeMessenger(), scope=_scope(), directory=directory
    )

    await _execute(capability, place="group", text="@Норман, глянь")

    assert directory.limits == [30]


async def test_a_broken_roster_still_never_lets_an_unverified_tag_out() -> None:
    # Ростер недоступен → подтвердить тег нечем → «собака» снимается, но ход не ломается.
    messenger = _FakeMessenger()
    capability = _capability(
        messenger=messenger, scope=_scope(), directory=_BrokenDirectory()
    )

    result = await _execute(capability, place="group", text="@Норман, глянь")

    assert result["sent"] is True
    assert messenger.sent[0][2] == "Норман, глянь"
