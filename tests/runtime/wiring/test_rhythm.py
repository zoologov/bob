# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``build_rhythm_wiring`` — the composition-root switch for the rhythm layer.

The presence rhythm layer (BOB-066 Срез W) ships inert behind ``presence.rhythm``. This
builder is the ONE place the flag is read: off → every consumption seam is ``None`` (Bob is
byte-identical); on → the durable share-of-voice gate + the natural-delay coordinator are
built, with the SAME gate handed to BOTH the reactive ceiling and the proactive throttle so
they damp each other over one per-chat window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.runtime.delayed_turn import DelayedTurn
from bob.application.runtime.share_of_voice_gate import ShareOfVoiceGate
from bob.runtime.wiring.rhythm import build_rhythm_wiring

if TYPE_CHECKING:
    import aiosqlite


class _StubProvider:
    """A connection provider stub — the store is never queried in these wiring tests."""

    @property
    def connection(self) -> aiosqlite.Connection:  # pragma: no cover - never called
        raise AssertionError("the store is not queried during wiring")


def test_flag_off_yields_no_consumption_seams() -> None:
    wiring = build_rhythm_wiring({}, activity_provider=_StubProvider())
    assert wiring.barge_ceiling is None
    assert wiring.reply_delay is None
    assert wiring.share_ceiling is None


def test_flag_off_when_explicitly_false() -> None:
    config = {"presence": {"rhythm": {"enabled": False}}}
    wiring = build_rhythm_wiring(config, activity_provider=_StubProvider())
    assert wiring.barge_ceiling is None
    assert wiring.reply_delay is None
    assert wiring.share_ceiling is None


def test_flag_on_builds_the_gate_and_the_delay_coordinator() -> None:
    config = {"presence": {"rhythm": {"enabled": True}}}
    wiring = build_rhythm_wiring(config, activity_provider=_StubProvider())
    assert isinstance(wiring.barge_ceiling, ShareOfVoiceGate)
    assert isinstance(wiring.reply_delay, DelayedTurn)
    assert isinstance(wiring.share_ceiling, ShareOfVoiceGate)


def test_the_reactive_ceiling_and_proactive_throttle_share_one_gate() -> None:
    # RFC Пласт 3: one per-chat window, so proactive sees a reply Bob just sent and throttles.
    config = {"presence": {"rhythm": {"enabled": True}}}
    wiring = build_rhythm_wiring(config, activity_provider=_StubProvider())
    assert wiring.barge_ceiling is wiring.share_ceiling
