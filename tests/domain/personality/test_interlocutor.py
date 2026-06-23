# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Interlocutor model + pure classification (BOB-019).

The social-identity foundation: WHO is writing — owner / known / guest / bot —
plus a trust level, derived purely from the authz facts already known for the
turn (``is_owner`` / ``is_authorized``) and the Telegram ``is_bot`` flag. No
transport, no SQL, no clock — a pure deterministic function over plain inputs, so
it covers humans AND bots (the foundation for future bot-to-bot) without wiring
any real bot transport. The contract pinned here is the kind/trust mapping; the
display name is carried through unchanged.
"""

from __future__ import annotations

from bob.domain.personality.interlocutor import (
    Interlocutor,
    InterlocutorKind,
    Trust,
    classify,
)


def test_owner_is_classified_owner_and_trusted() -> None:
    who = classify(
        sender_id=42,
        sender_name="Vova",
        is_owner=True,
        is_authorized=True,
    )
    assert who.kind is InterlocutorKind.OWNER
    assert who.trust is Trust.TRUSTED


def test_authorized_non_owner_is_known_and_trusted() -> None:
    who = classify(
        sender_id=7,
        sender_name="Ada",
        is_owner=False,
        is_authorized=True,
    )
    assert who.kind is InterlocutorKind.KNOWN
    assert who.trust is Trust.TRUSTED


def test_unauthorized_non_owner_is_guest_and_guest_trust() -> None:
    who = classify(
        sender_id=999,
        sender_name="Stranger",
        is_owner=False,
        is_authorized=False,
    )
    assert who.kind is InterlocutorKind.GUEST
    assert who.trust is Trust.GUEST


def test_bot_flag_yields_bot_kind() -> None:
    who = classify(
        sender_id=1234,
        sender_name="SomeBot",
        is_owner=False,
        is_authorized=False,
        is_bot=True,
    )
    assert who.kind is InterlocutorKind.BOT


def test_authorized_bot_is_bot_kind_with_trusted_trust() -> None:
    # A bot is a distinct KIND, but trust still follows authorization (foundation
    # for a future allowlisted BobNet peer): authorized bot -> TRUSTED.
    who = classify(
        sender_id=1234,
        sender_name="PeerBot",
        is_owner=False,
        is_authorized=True,
        is_bot=True,
    )
    assert who.kind is InterlocutorKind.BOT
    assert who.trust is Trust.TRUSTED


def test_unauthorized_bot_is_bot_kind_with_guest_trust() -> None:
    who = classify(
        sender_id=1234,
        sender_name="RandoBot",
        is_owner=False,
        is_authorized=False,
        is_bot=True,
    )
    assert who.kind is InterlocutorKind.BOT
    assert who.trust is Trust.GUEST


def test_display_name_and_sender_id_are_carried_through() -> None:
    who = classify(
        sender_id=42,
        sender_name="Vova",
        is_owner=True,
        is_authorized=True,
    )
    assert who.sender_id == 42
    assert who.display_name == "Vova"


def test_missing_name_falls_back_to_a_stable_label() -> None:
    who = classify(
        sender_id=None,
        sender_name=None,
        is_owner=False,
        is_authorized=False,
    )
    # No name from the transport must still yield a usable, non-empty label.
    assert who.display_name
    assert who.kind is InterlocutorKind.GUEST


def test_classify_is_pure_and_deterministic() -> None:
    first = classify(sender_id=7, sender_name="Ada", is_owner=False, is_authorized=True)
    second = classify(sender_id=7, sender_name="Ada", is_owner=False, is_authorized=True)
    assert first == second


def test_interlocutor_is_immutable() -> None:
    who = Interlocutor(
        sender_id=1,
        display_name="X",
        kind=InterlocutorKind.OWNER,
        trust=Trust.TRUSTED,
    )
    try:
        who.kind = InterlocutorKind.GUEST  # type: ignore[misc]
    except AttributeError:
        return
    msg = "Interlocutor must be immutable (frozen dataclass)"
    raise AssertionError(msg)
