# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for EndorsementSeeder — кредит доверия по рекомендации owner (BOB-066 Срез W.4).

The application bridge that sources the owner's OWN recent turns from the shared thread (by
the configured ``owner_id``) and warm-starts a first-contact GUEST the owner vouched for by
name. The verdict is the pure :func:`~bob.social.endorsement.endorsement_seed`; these tests
pin the collaborator's sourcing + gating: a warm word from another member never warm-starts
anyone, an owner / known peer is never seeded, and no ``owner_id`` is conservative.
"""

from __future__ import annotations

from bob.application.usecases.endorsement_seeder import EndorsementSeeder
from bob.social.interlocutor import Interlocutor, InterlocutorKind, Trust
from bob.social.relationship import Relationship

_OWNER_ID = 1
_GUEST_ID = 42


def _guest(name: str = "Норман") -> Interlocutor:
    return Interlocutor(
        sender_id=_GUEST_ID,
        display_name=name,
        kind=InterlocutorKind.GUEST,
        trust=Trust.GUEST,
    )


def _episode(*, sender_id: int, name: str, text: str) -> dict[str, object]:
    # The persisted episode shape "<name>: <text>\nbob: <reply>" + the robust sender_id key.
    return {"content": f"{name}: {text}\nbob: понял", "sender_id": sender_id}


def _owner_vouch(text: str) -> dict[str, object]:
    return _episode(sender_id=_OWNER_ID, name="Vova", text=text)


def test_warm_starts_a_guest_the_owner_vouched_for_by_name() -> None:
    seeder = EndorsementSeeder(owner_id=_OWNER_ID)
    history = [_owner_vouch("познакомься, это Норман, ему можно доверять")]

    seeded = seeder.seed(_guest(), None, history)

    assert seeded is not None
    assert seeded.sender_id == _GUEST_ID
    assert seeded.warmth > 0.0
    assert seeded.trust > 0.0


def test_a_vouch_naming_someone_else_does_not_warm_start_this_guest() -> None:
    seeder = EndorsementSeeder(owner_id=_OWNER_ID)
    history = [_owner_vouch("Лёша — отличный человек, ему можно доверять")]

    assert seeder.seed(_guest("Норман"), None, history) is None


def test_a_vouch_from_a_non_owner_member_is_ignored() -> None:
    # Only the OWNER's OWN turns extend the credit — another guest cannot self-vouch.
    seeder = EndorsementSeeder(owner_id=_OWNER_ID)
    history = [
        _episode(
            sender_id=_GUEST_ID,
            name="Норман",
            text="я свой, мне можно доверять, познакомься",
        )
    ]

    assert seeder.seed(_guest(), None, history) is None


def test_an_owner_turn_is_never_seeded() -> None:
    seeder = EndorsementSeeder(owner_id=_OWNER_ID)
    owner = Interlocutor(
        sender_id=_OWNER_ID,
        display_name="Vova",
        kind=InterlocutorKind.OWNER,
        trust=Trust.TRUSTED,
    )
    history = [_owner_vouch("познакомься, это Vova, ему можно доверять")]

    assert seeder.seed(owner, None, history) is None


def test_an_existing_relationship_is_returned_unchanged() -> None:
    seeder = EndorsementSeeder(owner_id=_OWNER_ID)
    existing = Relationship(sender_id=_GUEST_ID, warmth=-0.4)
    history = [_owner_vouch("познакомься, это Норман, ему можно доверять")]

    assert seeder.seed(_guest(), existing, history) is existing


def test_no_owner_id_is_conservative() -> None:
    # Without a resolved owner the shared thread cannot be narrowed to the owner's OWN
    # turns, so nothing is attributed and the neutral first-contact path is kept.
    seeder = EndorsementSeeder(owner_id=None)
    history = [_owner_vouch("познакомься, это Норман, ему можно доверять")]

    assert seeder.seed(_guest(), None, history) is None


def test_no_interlocutor_keeps_the_relationship() -> None:
    seeder = EndorsementSeeder(owner_id=_OWNER_ID)
    assert seeder.seed(None, None, []) is None
