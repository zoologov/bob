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

from bob.domain.personality.addressivity import Addressivity
from bob.domain.personality.conversation_floor import (
    ConversationFloor,
    FloorConfig,
    FloorHolder,
    advance_floor,
    idle_floor,
    resolve_addressivity,
)

_NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
_OWNER_ID = 200
_GUEST_ID = 300


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
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
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
            Addressivity.DIRECTED_TO_BOB, held, now=_NOW, config=FloorConfig()
        )
        is Addressivity.DIRECTED_TO_BOB
    )


def test_resolve_passes_directed_to_other_through_unchanged() -> None:
    held = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_NOW, idle_streak=0
    )

    assert (
        resolve_addressivity(
            Addressivity.DIRECTED_TO_OTHER, held, now=_NOW, config=FloorConfig()
        )
        is Addressivity.DIRECTED_TO_OTHER
    )
