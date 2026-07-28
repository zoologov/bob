# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the conversation-floor tracker (BOB-025 .1).

Pure, deterministic-by-injected-``now`` unit tests over the floor transitions
(:func:`advance_floor`) and the continuity resolve (:func:`resolve_addressivity`):
a direct turn / a Bob reply glue the floor to Bob; an AMBIENT turn from any
participant holds Bob's floor (refreshing ``since``) while it lives; Bob's silence
on AMBIENT grows ``idle_streak`` and decays to IDLE at ``reset_after_silent``; a
timeout decays to IDLE; a turn to another person hands the floor to OTHER; and the
resolve lifts AMBIENT to DIRECTED_TO_BOB only while Bob holds a live floor.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bob.conversation.addressivity import Addressivity
from bob.conversation.conversation_floor import (
    ConversationFloor,
    FloorConfig,
    FloorHolder,
    advance_floor,
    idle_floor,
    is_floor_participant,
    resolve_addressivity,
)

_NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
_OWNER_ID = 200
_GUEST_ID = 300
_OUTSIDER_ID = 400


def _seconds(after: datetime, secs: int) -> datetime:
    return after + timedelta(seconds=secs)


# --- ConversationFloor / FloorConfig value objects ----------------------------


def test_idle_floor_is_the_default_idle_state() -> None:
    floor = idle_floor()

    assert floor.holder is FloorHolder.IDLE
    assert floor.holder_id is None
    assert floor.since is None
    assert floor.idle_streak == 0


def test_floor_config_defaults() -> None:
    config = FloorConfig()

    assert config.timeout_seconds == 300
    assert config.reset_after_silent == 2


def test_floor_config_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        FloorConfig(timeout_seconds=0)


def test_floor_config_rejects_non_positive_reset() -> None:
    with pytest.raises(ValueError, match="reset_after_silent"):
        FloorConfig(reset_after_silent=0)


# --- advance_floor: direct address + Bob reply glue the floor to Bob ----------


def test_directed_to_bob_takes_the_floor() -> None:
    out = advance_floor(
        idle_floor(),
        addressivity=Addressivity.DIRECTED_TO_BOB,
        sender_id=_OWNER_ID,
        directed_to_id=None,
        bob_replied=False,
        now=_NOW,
        config=FloorConfig(),
    )

    assert out == ConversationFloor(
        holder=FloorHolder.BOB,
        holder_id=None,
        since=_NOW,
        idle_streak=0,
        participants=(_OWNER_ID,),  # BOB-066 .1: the speaker joins Bob's thread
    )


def test_bob_reply_glues_the_floor_to_bob_regardless_of_addressivity() -> None:
    # Even an AMBIENT turn that Bob chose to answer sticks the floor to Bob.
    out = advance_floor(
        idle_floor(),
        addressivity=Addressivity.AMBIENT,
        sender_id=_GUEST_ID,
        directed_to_id=None,
        bob_replied=True,
        now=_NOW,
        config=FloorConfig(),
    )

    assert out.holder is FloorHolder.BOB
    assert out.since == _NOW
    assert out.idle_streak == 0


# --- advance_floor: ambient continuity + decay --------------------------------


def test_ambient_holds_bob_floor_and_refreshes_since() -> None:
    held = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
    )
    later = _seconds(_NOW, 60)

    out = advance_floor(
        held,
        addressivity=Addressivity.AMBIENT,
        sender_id=_GUEST_ID,
        directed_to_id=None,
        bob_replied=False,
        now=later,
        config=FloorConfig(),
    )

    assert out.holder is FloorHolder.BOB
    assert out.since == later  # the in-thread turn refreshes the holder stamp
    assert out.idle_streak == 1  # ... but Bob's silence grows the streak


def test_ambient_silence_decays_to_idle_at_reset_after_silent() -> None:
    config = FloorConfig(reset_after_silent=2)
    floor = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
    )

    # First silent ambient: streak -> 1, still Bob.
    floor = advance_floor(
        floor,
        addressivity=Addressivity.AMBIENT,
        sender_id=_GUEST_ID,
        directed_to_id=None,
        bob_replied=False,
        now=_seconds(_NOW, 30),
        config=config,
    )
    assert floor.holder is FloorHolder.BOB
    assert floor.idle_streak == 1

    # Second silent ambient: streak hits reset_after_silent -> decay to IDLE.
    floor = advance_floor(
        floor,
        addressivity=Addressivity.AMBIENT,
        sender_id=_GUEST_ID,
        directed_to_id=None,
        bob_replied=False,
        now=_seconds(_NOW, 60),
        config=config,
    )
    assert floor.holder is FloorHolder.IDLE
    assert floor.idle_streak == 0


def test_ambient_when_floor_not_bob_is_idle() -> None:
    out = advance_floor(
        idle_floor(),
        addressivity=Addressivity.AMBIENT,
        sender_id=_GUEST_ID,
        directed_to_id=None,
        bob_replied=False,
        now=_NOW,
        config=FloorConfig(),
    )

    assert out.holder is FloorHolder.IDLE


def test_ambient_past_timeout_decays_to_idle() -> None:
    config = FloorConfig(timeout_seconds=300)
    held = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
    )

    out = advance_floor(
        held,
        addressivity=Addressivity.AMBIENT,
        sender_id=_GUEST_ID,
        directed_to_id=None,
        bob_replied=False,
        now=_seconds(_NOW, 301),  # past the 300s timeout
        config=config,
    )

    assert out.holder is FloorHolder.IDLE


def test_ambient_at_exact_timeout_boundary_still_holds() -> None:
    config = FloorConfig(timeout_seconds=300)
    held = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
    )

    out = advance_floor(
        held,
        addressivity=Addressivity.AMBIENT,
        sender_id=_GUEST_ID,
        directed_to_id=None,
        bob_replied=False,
        now=_seconds(_NOW, 300),  # exactly at the boundary: not expired
        config=config,
    )

    assert out.holder is FloorHolder.BOB
    assert out.idle_streak == 1


# --- advance_floor: turn to another person ------------------------------------


def test_directed_to_other_hands_the_floor_to_other() -> None:
    held = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
    )

    out = advance_floor(
        held,
        addressivity=Addressivity.DIRECTED_TO_OTHER,
        sender_id=_OWNER_ID,
        directed_to_id=_GUEST_ID,
        bob_replied=False,
        now=_seconds(_NOW, 10),
        config=FloorConfig(),
    )

    assert out.holder is FloorHolder.OTHER
    assert out.holder_id == _GUEST_ID
    assert out.since == _seconds(_NOW, 10)
    assert out.idle_streak == 0


def test_directed_to_bob_reclaims_an_other_floor() -> None:
    other = ConversationFloor(
        holder=FloorHolder.OTHER, holder_id=_GUEST_ID, since=_NOW, idle_streak=0
    )

    out = advance_floor(
        other,
        addressivity=Addressivity.DIRECTED_TO_BOB,
        sender_id=_OWNER_ID,
        directed_to_id=None,
        bob_replied=False,
        now=_seconds(_NOW, 5),
        config=FloorConfig(),
    )

    assert out.holder is FloorHolder.BOB
    assert out.holder_id is None


# --- resolve_addressivity: continuity lift ------------------------------------


def test_resolve_lifts_ambient_to_bob_while_floor_lives() -> None:
    held = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
    )

    resolved = resolve_addressivity(
        Addressivity.AMBIENT,
        held,
        sender_id=_GUEST_ID,
        now=_seconds(_NOW, 60),
        config=FloorConfig(),
    )

    assert resolved is Addressivity.DIRECTED_TO_BOB


def test_resolve_leaves_ambient_when_floor_not_bob() -> None:
    other = ConversationFloor(
        holder=FloorHolder.OTHER, holder_id=_GUEST_ID, since=_NOW, idle_streak=0
    )

    resolved = resolve_addressivity(
        Addressivity.AMBIENT,
        other,
        sender_id=_GUEST_ID,
        now=_seconds(_NOW, 10),
        config=FloorConfig(),
    )

    assert resolved is Addressivity.AMBIENT


def test_resolve_leaves_ambient_when_floor_expired() -> None:
    held = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
    )

    resolved = resolve_addressivity(
        Addressivity.AMBIENT,
        held,
        sender_id=_GUEST_ID,
        now=_seconds(_NOW, 301),  # past timeout
        config=FloorConfig(timeout_seconds=300),
    )

    assert resolved is Addressivity.AMBIENT


def test_resolve_passes_direct_address_through_unchanged() -> None:
    held = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
    )

    assert (
        resolve_addressivity(
            Addressivity.DIRECTED_TO_BOB,
            held,
            sender_id=_OWNER_ID,
            now=_NOW,
            config=FloorConfig(),
        )
        is Addressivity.DIRECTED_TO_BOB
    )


def test_resolve_passes_directed_to_other_through_unchanged() -> None:
    held = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
    )

    assert (
        resolve_addressivity(
            Addressivity.DIRECTED_TO_OTHER,
            held,
            sender_id=_OWNER_ID,
            now=_NOW,
            config=FloorConfig(),
        )
        is Addressivity.DIRECTED_TO_OTHER
    )


# --- Floor-по-говорящему: participants set (BOB-066 .1) -----------------------


def _bob_floor_with(*participants: int) -> ConversationFloor:
    return ConversationFloor(
        holder=FloorHolder.BOB,
        holder_id=None,
        since=_NOW,
        idle_streak=0,
        participants=tuple(participants),
    )


def test_conversation_floor_participants_default_empty_is_legacy() -> None:
    # 🔴 The additive default MUST keep every legacy construction valid: no participants
    # argument => empty tuple => legacy mode.
    floor = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
    )

    assert floor.participants == ()
    assert idle_floor().participants == ()


def test_resolve_legacy_empty_participants_lifts_any_sender() -> None:
    # Empty set = legacy: an ambient reply from ANYONE in a live Bob floor still lifts
    # (exactly the pre-BOB-066 behaviour), whatever the sender id.
    held = _bob_floor_with()  # empty participants

    for sender in (_OWNER_ID, _GUEST_ID, _OUTSIDER_ID, None):
        assert (
            resolve_addressivity(
                Addressivity.AMBIENT,
                held,
                sender_id=sender,
                now=_seconds(_NOW, 30),
                config=FloorConfig(),
            )
            is Addressivity.DIRECTED_TO_BOB
        )


def test_resolve_lifts_ambient_for_a_recognised_participant() -> None:
    held = _bob_floor_with(_OWNER_ID, _GUEST_ID)

    assert (
        resolve_addressivity(
            Addressivity.AMBIENT,
            held,
            sender_id=_GUEST_ID,  # in the set → continues the thread
            now=_seconds(_NOW, 30),
            config=FloorConfig(),
        )
        is Addressivity.DIRECTED_TO_BOB
    )


def test_resolve_leaves_ambient_for_an_outsider() -> None:
    # 🔴 The core new guard: an unlabeled reply from someone NOT in Bob's live exchange
    # is NOT lifted — Bob does not wrongly take it.
    held = _bob_floor_with(_OWNER_ID)

    assert (
        resolve_addressivity(
            Addressivity.AMBIENT,
            held,
            sender_id=_OUTSIDER_ID,
            now=_seconds(_NOW, 30),
            config=FloorConfig(),
        )
        is Addressivity.AMBIENT
    )


def test_resolve_lifts_ambient_for_unknown_sender_fail_safe() -> None:
    # A None sender (unresolved id) is fail-safe: never mute Bob on his own live floor.
    held = _bob_floor_with(_OWNER_ID)

    assert (
        resolve_addressivity(
            Addressivity.AMBIENT,
            held,
            sender_id=None,
            now=_seconds(_NOW, 30),
            config=FloorConfig(),
        )
        is Addressivity.DIRECTED_TO_BOB
    )


def test_is_floor_participant_matches_the_resolve_guard() -> None:
    held = _bob_floor_with(_OWNER_ID)

    assert is_floor_participant(held, _OWNER_ID, now=_NOW, config=FloorConfig())
    assert not is_floor_participant(held, _OUTSIDER_ID, now=_NOW, config=FloorConfig())
    # A dead (expired) Bob floor recognises no one, even a listed participant.
    assert not is_floor_participant(
        held, _OWNER_ID, now=_seconds(_NOW, 301), config=FloorConfig(timeout_seconds=300)
    )


# --- Floor-по-говорящему: advance unions / resets participants ----------------


def test_directed_to_bob_adds_sender_to_participants() -> None:
    out = advance_floor(
        idle_floor(),
        addressivity=Addressivity.DIRECTED_TO_BOB,
        sender_id=_OWNER_ID,
        directed_to_id=None,
        bob_replied=False,
        now=_NOW,
        config=FloorConfig(),
    )

    assert out.participants == (_OWNER_ID,)


def test_bob_reply_unions_new_speaker_into_participants() -> None:
    held = _bob_floor_with(_OWNER_ID)

    out = advance_floor(
        held,
        addressivity=Addressivity.AMBIENT,
        sender_id=_GUEST_ID,
        directed_to_id=None,
        bob_replied=True,  # Bob answered the guest → guest joins the thread
        now=_seconds(_NOW, 20),
        config=FloorConfig(),
    )

    assert out.participants == (_OWNER_ID, _GUEST_ID)


def test_participants_dedup_on_repeat_speaker() -> None:
    held = _bob_floor_with(_OWNER_ID)

    out = advance_floor(
        held,
        addressivity=Addressivity.DIRECTED_TO_BOB,
        sender_id=_OWNER_ID,  # already present → no duplicate
        directed_to_id=None,
        bob_replied=False,
        now=_seconds(_NOW, 5),
        config=FloorConfig(),
    )

    assert out.participants == (_OWNER_ID,)


def test_participants_are_capped_dropping_the_oldest() -> None:
    held = _bob_floor_with(*range(1, 9))  # already at the cap of 8

    out = advance_floor(
        held,
        addressivity=Addressivity.DIRECTED_TO_BOB,
        sender_id=99,
        directed_to_id=None,
        bob_replied=False,
        now=_NOW,
        config=FloorConfig(),
    )

    assert len(out.participants) == 8
    assert out.participants == (2, 3, 4, 5, 6, 7, 8, 99)  # oldest (1) evicted


def test_ambient_continuity_preserves_participants() -> None:
    held = _bob_floor_with(_OWNER_ID, _GUEST_ID)

    out = advance_floor(
        held,
        addressivity=Addressivity.AMBIENT,
        sender_id=_GUEST_ID,
        directed_to_id=None,
        bob_replied=False,  # silent ambient in a live floor
        now=_seconds(_NOW, 30),
        config=FloorConfig(),
    )

    assert out.holder is FloorHolder.BOB
    assert out.participants == (_OWNER_ID, _GUEST_ID)  # thread membership survives


def test_directed_to_other_resets_participants() -> None:
    held = _bob_floor_with(_OWNER_ID, _GUEST_ID)

    out = advance_floor(
        held,
        addressivity=Addressivity.DIRECTED_TO_OTHER,
        sender_id=_OWNER_ID,
        directed_to_id=_GUEST_ID,
        bob_replied=False,
        now=_seconds(_NOW, 10),
        config=FloorConfig(),
    )

    assert out.holder is FloorHolder.OTHER
    assert out.participants == ()  # a turn to another wipes Bob's thread membership


def test_decay_to_idle_resets_participants() -> None:
    config = FloorConfig(reset_after_silent=2)
    held = ConversationFloor(
        holder=FloorHolder.BOB,
        holder_id=None,
        since=_NOW,
        idle_streak=1,  # one more silent ambient decays it
        participants=(_OWNER_ID, _GUEST_ID),
    )

    out = advance_floor(
        held,
        addressivity=Addressivity.AMBIENT,
        sender_id=_GUEST_ID,
        directed_to_id=None,
        bob_replied=False,
        now=_seconds(_NOW, 30),
        config=config,
    )

    assert out.holder is FloorHolder.IDLE
    assert out.participants == ()  # decay wipes the thread membership
