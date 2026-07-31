# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""The holistic stream-read врезка into the turn gate (BOB-072).

🔴 The batch «read the stream» seam feeds the gate a PRE-COMPUTED per-message
:class:`RoomReading` (one Tier-1 read over the whole ambient burst, decided upstream in
the intake worker). When ``ambient_reading`` rides the gate call the reflective apply path
uses it DIRECTLY — it never runs the per-message reflective read:

* the pure verdict (reply / react / silent) is projected from the supplied reading, exactly
  as the per-message reflective path does — so persist + floor advance for EVERY ambient
  message including a silent IGNORE (INV-S2, BOB-071 Seam B);
* 🔴 it works even when the per-message reflective reader is UNWIRED (``read_the_room=None``)
  — the reading is supplied from outside, so the batch path does not depend on the
  single-message reflective seam being on;
* 🔴 a RAW direct address still short-circuits to a deterministic reply ABOVE the supplied
  reading (INV-1) — the focal guarantee is never overridden by a batch verdict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.events import MessageReceived
from bob.conversation.addressivity import Addressivity
from bob.conversation.conversation_floor import FloorHolder
from bob.conversation.room_reading import ReflectiveIntent, RoomMood, RoomReading
from bob.conversation.usecases.addressivity_perceiver import _AddressivitySignals
from bob.conversation.usecases.turn_gate import TurnGate, _ReplyGate
from bob.personality.expression import ExpressionMode, ExpressionPlan, FormHint
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.taste import TasteAxis, TasteEngine
from bob.proactivity.self_improvement import RuleModulators
from bob.social.interlocutor import Interlocutor, InterlocutorKind, Trust

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class _StubPerceiver:
    def __init__(self, signals: _AddressivitySignals) -> None:
        self._signals = signals

    async def signals(self, event: MessageReceived) -> _AddressivitySignals:
        return self._signals


class _RecordingFloor:
    def __init__(self) -> None:
        self.advances: list[tuple[Addressivity, bool]] = []

    async def advance_after_turn(
        self,
        *,
        chat_id: int,
        sender_id: int | None,
        per_message: Addressivity,
        directed_to_id: int | None,
        bob_replied: bool,
    ) -> None:
        self.advances.append((per_message, bob_replied))


class _ExplodingAssembler:
    async def replay_recent_thread(
        self, interlocutor: Interlocutor | None
    ) -> Sequence[Mapping[str, object]]:  # pragma: no cover - must never be called
        raise AssertionError("the ambient-reading path must NOT replay a per-message thread")


class _RecordingReactor:
    def __init__(self) -> None:
        self.reactions: list[tuple[int, int, str]] = []

    async def react(self, *, chat_id: int, message_id: int, emoji: str) -> None:
        self.reactions.append((chat_id, message_id, emoji))


class _RecordingPersist:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    async def __call__(
        self,
        event: MessageReceived,
        reply: str,
        soul: SOUL,
        *,
        bob_message_id: int | None = None,
    ) -> None:
        self.calls.append((event.message_id, reply))


async def _noop_owner_activity() -> None:
    return None


class _Essential:
    async def run[T](self, operation: object, *, step: str) -> T:  # pragma: no cover
        raise AssertionError("reflective path does not use the essential runner")


def _soul() -> SOUL:
    mood = Mood(valence=0.2)
    taste = TasteEngine(axes=(TasteAxis(name="x", value=0.5, conviction=0.5),))
    return SOUL(identity="Bob", mood=mood, mood_baseline=mood, taste=taste)


def _signals(per_message: Addressivity) -> _AddressivitySignals:
    return _AddressivitySignals(
        per_message=per_message,
        effective=per_message,
        others_present=True,
        floor_engaged=False,
        reply_to_bob=False,
        directed_to_id=None,
        floor_holder=FloorHolder.OTHER,
        floor_participant=True,
    )


def _reading(
    *, intent: ReflectiveIntent, salience: float, emoji: str | None = None
) -> RoomReading:
    return RoomReading(
        situation="болтают",
        pairings=(),
        room_mood=RoomMood.WARM,
        intent=intent,
        addressee_id=None,
        salience=salience,
        emoji=emoji,
        wants_web=False,
        reason="r",
    )


def _interlocutor() -> Interlocutor:
    return Interlocutor(
        sender_id=6,
        display_name="Norman",
        kind=InterlocutorKind.KNOWN,
        trust=Trust.TRUSTED,
    )


def _gate(
    *,
    signals: _AddressivitySignals,
    floor: _RecordingFloor,
    reactor: _RecordingReactor,
    persist: _RecordingPersist,
) -> TurnGate:
    # 🔴 read_the_room=None — the per-message reflective seam is UNWIRED; the batch врезка
    # supplies the reading from outside. The assembler EXPLODES if consulted, proving the
    # supplied reading replaces the per-message read.
    return TurnGate(
        decide_response=None,
        addressivity=_StubPerceiver(signals),  # type: ignore[arg-type]  # test double
        floor=floor,  # type: ignore[arg-type]  # test double
        essential=_Essential(),
        assembler=_ExplodingAssembler(),  # type: ignore[arg-type]  # test double
        reactor=reactor,
        persist=persist,
        record_owner_activity=_noop_owner_activity,
        read_the_room=None,
        barge_ceiling=None,
    )


_PLAN = ExpressionPlan(
    mode=ExpressionMode.REPLY,
    leak_inner_life=False,
    callback=False,
    mention_fascination=False,
    form_hint=FormHint.NORMAL,
)
_EVENT = MessageReceived(
    update_id=1, chat_id=42, message_id=7, text="да ну", sender_id=6, sender_name="Norman"
)


async def _run(gate: TurnGate, *, ambient_reading: RoomReading | None) -> _ReplyGate | None:
    return await gate.gate(
        _EVENT,
        _soul(),
        _interlocutor(),
        _PLAN,
        0.5,
        RuleModulators(),
        rng=None,
        ambient_reading=ambient_reading,
    )


@pytest.mark.asyncio
async def test_supplied_reply_reading_returns_a_reply_gate_without_a_read() -> None:
    floor, reactor, persist = _RecordingFloor(), _RecordingReactor(), _RecordingPersist()
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT), floor=floor, reactor=reactor, persist=persist
    )
    result = await _run(
        gate, ambient_reading=_reading(intent=ReflectiveIntent.REPLY, salience=0.9)
    )
    assert isinstance(result, _ReplyGate)
    # A reply persists on the compose path, not in the gate.
    assert persist.calls == []


@pytest.mark.asyncio
async def test_supplied_react_reading_sets_emoji_and_persists_the_incoming() -> None:
    # 🔴 INV-S2: a batch REACT still persists the incoming (Seam B) + advances the floor.
    floor, reactor, persist = _RecordingFloor(), _RecordingReactor(), _RecordingPersist()
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT), floor=floor, reactor=reactor, persist=persist
    )
    result = await _run(
        gate, ambient_reading=_reading(intent=ReflectiveIntent.REACT, salience=0.9, emoji="🔥")
    )
    assert result is None
    assert reactor.reactions == [(42, 7, "🔥")]
    assert len(persist.calls) == 1
    assert floor.advances == [(Addressivity.AMBIENT, False)]


@pytest.mark.asyncio
async def test_supplied_ignore_reading_persists_the_incoming_and_advances() -> None:
    # 🔴 INV-S2: a batch IGNORE (or a below-salience read) still persists the incoming so the
    # thread stays intact — the whole point of «читаю комнату, но помню разговор».
    floor, reactor, persist = _RecordingFloor(), _RecordingReactor(), _RecordingPersist()
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT), floor=floor, reactor=reactor, persist=persist
    )
    result = await _run(
        gate, ambient_reading=_reading(intent=ReflectiveIntent.IGNORE, salience=0.0)
    )
    assert result is None
    assert reactor.reactions == []
    assert len(persist.calls) == 1
    assert floor.advances == [(Addressivity.AMBIENT, False)]


@pytest.mark.asyncio
async def test_direct_address_short_circuits_above_a_supplied_ignore_reading() -> None:
    # 🔴 INV-1: even with a supplied IGNORE reading, a RAW direct address replies — the focal
    # guarantee sits ABOVE the batch verdict.
    floor, reactor, persist = _RecordingFloor(), _RecordingReactor(), _RecordingPersist()
    gate = _gate(
        signals=_signals(Addressivity.DIRECTED_TO_BOB),
        floor=floor,
        reactor=reactor,
        persist=persist,
    )
    result = await _run(
        gate, ambient_reading=_reading(intent=ReflectiveIntent.IGNORE, salience=0.0)
    )
    assert isinstance(result, _ReplyGate)


@pytest.mark.asyncio
async def test_no_supplied_reading_and_no_reader_falls_through_to_legacy() -> None:
    # Without a supplied reading AND without a reflective reader, the gate does NOT enter the
    # reflective path — it falls through to the legacy addressivity ladder (byte-identical).
    floor, reactor, persist = _RecordingFloor(), _RecordingReactor(), _RecordingPersist()
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT), floor=floor, reactor=reactor, persist=persist
    )
    # The legacy path consults the addressivity perceiver's ``decide`` (not on our stub) — so a
    # None reading must NOT reach the reflective branch; assert it raises AttributeError, proving
    # the reflective branch was skipped.
    with pytest.raises(AttributeError):
        await _run(gate, ambient_reading=None)
