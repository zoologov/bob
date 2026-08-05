# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты пути ``@username`` от входящего хода до ростера (BOB-090.B3).

Ник существовал ровно в одном месте — во входящем апдейте — и там же терялся. Здесь
проверяется весь шов: восприятие собеседника несёт ник, трекер кладёт его в ростер, и
🔴 отсутствие ника нигде не превращается в выдуманный тег.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from bob.application.runtime.events import MessageReceived
from bob.social.interlocutor import Interlocutor, InterlocutorKind, Trust, classify
from bob.social.usecases.first_impression_sources import FirstImpressionTracker
from bob.social.usecases.sender_perception import SenderPerception

if TYPE_CHECKING:
    from bob.social.first_impression import FirstImpression
    from bob.social.usecases.authorizer import Authorizer

_NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
_NORMAN_ID = 4242


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


class _FakeStore:
    def __init__(self) -> None:
        self.rows: dict[int, FirstImpression] = {}

    async def load(self, sender_id: int) -> FirstImpression | None:
        return self.rows.get(sender_id)

    async def save(self, impression: FirstImpression) -> None:
        self.rows[impression.sender_id] = impression

    async def recent(self, *, limit: int) -> list[FirstImpression]:
        return list(self.rows.values())[:limit]


class _FakeAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == 1

    async def is_authorized(self, *, user_id: int | None, chat_id: int) -> bool:
        del user_id, chat_id
        return True

    async def authorize(self, user_id: int) -> None:
        del user_id

    async def deauthorize(self, user_id: int) -> None:
        del user_id


def _event(username: str | None) -> MessageReceived:
    return MessageReceived(
        update_id=1,
        chat_id=-100,
        message_id=7,
        text="привет",
        sender_id=_NORMAN_ID,
        sender_name="Норман",
        sender_username=username,
    )


def _person(username: str | None) -> Interlocutor:
    return Interlocutor(
        sender_id=_NORMAN_ID,
        display_name="Норман",
        kind=InterlocutorKind.KNOWN,
        trust=Trust.TRUSTED,
        username=username,
    )


# --- Восприятие ---------------------------------------------------------------


def test_classify_carries_the_handle_beside_the_name() -> None:
    person = classify(
        sender_id=_NORMAN_ID,
        sender_name="Норман",
        is_owner=False,
        is_authorized=True,
        username="NormanGri",
    )

    assert person.display_name == "Норман"
    assert person.username == "NormanGri"


def test_classify_without_a_handle_keeps_none() -> None:
    person = classify(
        sender_id=_NORMAN_ID, sender_name="Норман", is_owner=False, is_authorized=True
    )

    assert person.username is None


async def test_perception_reads_the_handle_off_the_event() -> None:
    perception = SenderPerception(authorizer=cast("Authorizer", _FakeAuthorizer()))

    person = await perception.resolve(_event("NormanGri"))

    assert person.username == "NormanGri"


async def test_perception_without_a_handle_yields_none() -> None:
    perception = SenderPerception(authorizer=cast("Authorizer", _FakeAuthorizer()))

    assert (await perception.resolve(_event(None))).username is None


# --- Запись в ростер ----------------------------------------------------------


async def test_the_handle_reaches_the_roster() -> None:
    store = _FakeStore()
    tracker = FirstImpressionTracker(store=store, clock=_FixedClock())

    await tracker.note_first_contact(_person("NormanGri"))

    assert store.rows[_NORMAN_ID].username == "NormanGri"


async def test_a_person_without_a_handle_is_stored_without_one() -> None:
    # 🔴 «Ника не знаю» пишется как None — не как имя и не как выдуманный тег.
    store = _FakeStore()
    tracker = FirstImpressionTracker(store=store, clock=_FixedClock())

    await tracker.note_first_contact(_person(None))

    saved = store.rows[_NORMAN_ID]
    assert saved.username is None
    assert saved.display_name == "Норман"
