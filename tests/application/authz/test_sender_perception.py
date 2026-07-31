# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SenderPerception — Authorizer → Interlocutor adapter (BOB-019).

The perception adapter composes the unchanged access policy (:class:`Authorizer`)
with the pure :func:`classify` so a received message becomes an
:class:`Interlocutor` (owner / known / guest + trust). It is the wiring seam
:class:`HandleMessage` uses to perceive WHO is writing; the authz decision itself
is untouched (perception, not a gate). Exercised over a fake allowlist store — no
SQL, no transport.
"""

from __future__ import annotations

from bob.application.runtime.events import MessageReceived
from bob.social.gender import Gender
from bob.social.interlocutor import InterlocutorKind, Trust
from bob.social.usecases import Authorizer, SenderPerception

_OWNER = 1
_CHAT = 100


class _FakeGenderStore:
    """In-memory gender-memory double: accrues self-presentation per sender."""

    def __init__(self) -> None:
        self.observed: list[tuple[int, str]] = []
        self._gender: dict[int, Gender] = {}

    def set(self, sender_id: int, gender: Gender) -> None:
        self._gender[sender_id] = gender

    async def load_gender(self, sender_id: int) -> Gender:
        return self._gender.get(sender_id, Gender.UNKNOWN)

    async def observe_gender(self, sender_id: int, text: str) -> None:
        self.observed.append((sender_id, text))


class _FakeAllowlistStore:
    """In-memory AllowlistStore double."""

    def __init__(self, initial: set[int] | None = None) -> None:
        self.users: set[int] = set(initial) if initial else set()

    async def load(self) -> set[int]:
        return set(self.users)

    async def add(self, user_id: int) -> None:
        self.users.add(user_id)

    async def remove(self, user_id: int) -> None:
        self.users.discard(user_id)


def _perception(*, allowlist: set[int] | None = None) -> SenderPerception:
    authorizer = Authorizer(
        owner_id=_OWNER,
        allowed_chat_ids=[_CHAT],
        store=_FakeAllowlistStore(allowlist),
    )
    return SenderPerception(authorizer=authorizer)


def _event(*, sender_id: int | None, name: str | None = "Someone") -> MessageReceived:
    return MessageReceived(
        update_id=1,
        chat_id=_CHAT,
        message_id=1,
        text="hi",
        sender_id=sender_id,
        sender_name=name,
    )


async def test_owner_message_resolves_to_owner_trusted() -> None:
    who = await _perception().resolve(_event(sender_id=_OWNER, name="Vova"))
    assert who.kind is InterlocutorKind.OWNER
    assert who.trust is Trust.TRUSTED
    assert who.display_name == "Vova"


async def test_allowlisted_user_resolves_to_known_trusted() -> None:
    perception = _perception(allowlist={7})
    who = await perception.resolve(_event(sender_id=7, name="Ada"))
    assert who.kind is InterlocutorKind.KNOWN
    assert who.trust is Trust.TRUSTED


async def test_unknown_user_resolves_to_guest() -> None:
    who = await _perception().resolve(_event(sender_id=999, name="Rando"))
    assert who.kind is InterlocutorKind.GUEST
    assert who.trust is Trust.GUEST


async def test_owner_outside_allowed_chat_is_still_recognised_as_owner() -> None:
    # is_owner is identity (not chat-scoped), so even outside the allowed chat Bob
    # still recognises his owner AS owner — perception, not the access gate.
    perception = _perception()
    event = MessageReceived(
        update_id=1,
        chat_id=999,  # not an allowed chat
        message_id=1,
        text="hi",
        sender_id=_OWNER,
        sender_name="Vova",
    )
    who = await perception.resolve(event)
    assert who.kind is InterlocutorKind.OWNER


async def test_missing_sender_id_resolves_to_guest() -> None:
    who = await _perception().resolve(_event(sender_id=None, name=None))
    assert who.kind is InterlocutorKind.GUEST


async def test_gender_defaults_unknown_without_a_gender_store() -> None:
    who = await _perception().resolve(_event(sender_id=999))
    assert who.gender is Gender.UNKNOWN


async def test_resolve_observes_then_reads_gender_from_the_store() -> None:
    gender_store = _FakeGenderStore()
    authorizer = Authorizer(
        owner_id=_OWNER, allowed_chat_ids=[_CHAT], store=_FakeAllowlistStore()
    )
    perception = SenderPerception(authorizer=authorizer, gender_store=gender_store)
    gender_store.set(5, Gender.FEM)

    event = MessageReceived(
        update_id=1,
        chat_id=_CHAT,
        message_id=1,
        text="Пошла учить Python",
        sender_id=5,
        sender_name="Лиля",
    )
    who = await perception.resolve(event)

    assert gender_store.observed == [(5, "Пошла учить Python")]
    assert who.gender is Gender.FEM


async def test_resolve_skips_gender_when_sender_has_no_id() -> None:
    gender_store = _FakeGenderStore()
    authorizer = Authorizer(
        owner_id=_OWNER, allowed_chat_ids=[_CHAT], store=_FakeAllowlistStore()
    )
    perception = SenderPerception(authorizer=authorizer, gender_store=gender_store)

    who = await perception.resolve(_event(sender_id=None))

    assert gender_store.observed == []
    assert who.gender is Gender.UNKNOWN


# --- perceive_kind (BOB-078 B: kind for the stream-read, no gender side-effect) ---------


async def test_perceive_kind_returns_the_social_kind_only() -> None:
    perception = _perception(allowlist={7})
    assert (
        await perception.perceive_kind(_event(sender_id=_OWNER))
        is InterlocutorKind.OWNER
    )
    assert await perception.perceive_kind(_event(sender_id=7)) is InterlocutorKind.KNOWN
    assert await perception.perceive_kind(_event(sender_id=999)) is InterlocutorKind.GUEST


async def test_perceive_kind_does_not_accrue_gender() -> None:
    # 🔴 The stream-read only needs the KIND; it must NOT re-observe self-presentation
    # (gender is already accrued on the main handle path — no double-count).
    gender_store = _FakeGenderStore()
    authorizer = Authorizer(
        owner_id=_OWNER, allowed_chat_ids=[_CHAT], store=_FakeAllowlistStore()
    )
    perception = SenderPerception(authorizer=authorizer, gender_store=gender_store)

    kind = await perception.perceive_kind(
        _event(sender_id=5, name="Лиля")
    )

    assert kind is InterlocutorKind.GUEST
    assert gender_store.observed == []
