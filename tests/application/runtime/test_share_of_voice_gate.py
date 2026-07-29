# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ShareOfVoiceGate — the ambient-barge ceiling decision (INV-1/3/4)."""

from __future__ import annotations

from bob.application.runtime.share_of_voice_gate import ShareOfVoiceGate
from bob.presence.outgoing_activity import OutgoingActivity
from bob.presence.share_of_voice import ShareOfVoicePolicy


class _FakeActivityStore:
    """Serves one fixed activity window regardless of chat_id."""

    def __init__(self, activity: OutgoingActivity) -> None:
        self._activity = activity

    async def load(self, chat_id: int) -> OutgoingActivity:  # noqa: ARG002
        return self._activity


def _gate(activity: OutgoingActivity) -> ShareOfVoiceGate:
    return ShareOfVoiceGate(_FakeActivityStore(activity), ShareOfVoicePolicy())


async def test_focused_bypasses_ceiling_even_when_dominating() -> None:
    # Arrange: Bob has hogged the room, but this is a direct address.
    gate = _gate(OutgoingActivity(bob_sent=10, total_seen=10, distinct_senders=3))

    # Act: a draw right under the base probability.
    admitted = await gate.admits_barge(
        chat_id=1, focused=True, base_probability=0.9, draw=0.5
    )

    # Assert: INV-1 — focus is never throttled (multiplier 1.0 ⇒ 0.5 < 0.9).
    assert admitted is True


async def test_dominating_window_throttles_ambient_barge() -> None:
    # Arrange: Bob over his fair share on an AMBIENT message.
    gate = _gate(OutgoingActivity(bob_sent=9, total_seen=10, distinct_senders=3))

    # Act: a draw that would pass at full probability but not after damping.
    admitted = await gate.admits_barge(
        chat_id=1, focused=False, base_probability=0.8, draw=0.5
    )

    # Assert: the ceiling damps p(barge) below the draw ⇒ Bob stays quiet.
    assert admitted is False


async def test_under_fair_share_barges_at_base_probability() -> None:
    # Arrange: Bob under his fair share ⇒ multiplier 1.0.
    gate = _gate(OutgoingActivity(bob_sent=1, total_seen=10, distinct_senders=3))

    # Act
    admitted = await gate.admits_barge(
        chat_id=1, focused=False, base_probability=0.8, draw=0.5
    )

    # Assert: no damping ⇒ 0.5 < 0.8 admits.
    assert admitted is True


async def test_draw_equal_to_effective_probability_is_refused() -> None:
    # Arrange: under fair share ⇒ multiplier 1.0, so the effective p(barge) == base.
    gate = _gate(OutgoingActivity(bob_sent=1, total_seen=10, distinct_senders=3))

    # Act: the draw lands EXACTLY on the effective probability.
    admitted = await gate.admits_barge(
        chat_id=1, focused=False, base_probability=0.8, draw=0.8
    )

    # Assert: the admit test is a strict `draw < p` — the boundary does not barge.
    assert admitted is False


async def test_ceiling_is_probabilistic_not_a_hard_mute() -> None:
    # Arrange: total dominance on an ambient message.
    gate = _gate(OutgoingActivity(bob_sent=10, total_seen=10, distinct_senders=3))

    # Act: a very low draw still gets through — the ceiling scales, never zeroes.
    admitted = await gate.admits_barge(
        chat_id=1, focused=False, base_probability=1.0, draw=0.001
    )

    # Assert: INV-3 — a nudge, not a wall; a lucky low draw still barges.
    assert admitted is True
