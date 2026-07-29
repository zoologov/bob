# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the reflective focus/periphery split in the turn gate (BOB-066 Срез 2.2).

🔴 The heart of the epic — the «два-скорости-внимания» fork at the top of
``TurnGate.gate()``:

* FOCUS (INV-1): a RAW ``DIRECTED_TO_BOB`` short-circuits to a DETERMINISTIC reply,
  bypassing the reflective read entirely — even a reader that would IGNORE never fires,
  and the gate NEVER returns silence on a direct address.
* PERIPHERY: an ambient turn takes the rich reflective read → pure verdict (reply /
  react / silent). A read FAILURE safe-defaults to a silent IGNORE (advance the floor,
  no notice) — never a guessed reply, never a GUPPI notice.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.events import MessageReceived
from bob.conversation.addressivity import Addressivity, ResponseOutcome
from bob.conversation.conversation_floor import FloorHolder
from bob.conversation.room_reading import (
    ReflectiveIntent,
    RoomMood,
    RoomReader,
    RoomReading,
    RoomReadingContext,
)
from bob.conversation.usecases.addressivity_perceiver import _AddressivitySignals
from bob.conversation.usecases.read_the_room import ReadTheRoom
from bob.conversation.usecases.turn_gate import TurnGate, _ReplyGate
from bob.personality.expression import ExpressionMode, ExpressionPlan, FormHint
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.taste import TasteAxis, TasteEngine
from bob.proactivity.self_improvement import RuleModulators
from bob.social.interlocutor import Interlocutor, InterlocutorKind, Trust

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# --- test doubles -------------------------------------------------------------


class _StubPerceiver:
    """Returns scripted addressivity signals; the reflective gate reads ``signals``."""

    def __init__(self, signals: _AddressivitySignals) -> None:
        self._signals = signals

    async def signals(self, event: MessageReceived) -> _AddressivitySignals:
        return self._signals


class _RecordingFloor:
    """Records every after-turn floor advance the gate performs."""

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


class _EmptyAssembler:
    async def replay_recent_thread(
        self, interlocutor: Interlocutor | None
    ) -> Sequence[Mapping[str, object]]:
        return []


class _RecordingReactor:
    def __init__(self) -> None:
        self.reactions: list[tuple[int, int, str]] = []

    async def react(self, *, chat_id: int, message_id: int, emoji: str) -> None:
        self.reactions.append((chat_id, message_id, emoji))


class _ScriptedReader:
    """A RoomReader returning a fixed reading — or raising, to model a failure."""

    def __init__(self, reading: RoomReading | None) -> None:
        self._reading = reading

    async def read(self, ctx: RoomReadingContext) -> RoomReading:
        if self._reading is None:
            raise RuntimeError("model down")
        return self._reading


class _NeverReader:
    """Fails the test if read at all — proves the FOCUS path bypasses the reflection."""

    async def read(self, ctx: RoomReadingContext) -> RoomReading:
        raise AssertionError("focus turn must NOT run the reflective read")


async def _boom_persist(
    event: MessageReceived, reply: str, soul: SOUL, *, bob_message_id: int | None = None
) -> None:
    raise AssertionError("reflective periphery/focus must not persist here")


async def _noop_owner_activity() -> None:
    return None


class _Essential:
    async def run[T](self, operation: object, *, step: str) -> T:  # pragma: no cover
        raise AssertionError("reflective path does not use the essential runner")


class _FakeCeiling:
    """A share-of-voice ceiling stub: records each consult, returns a fixed verdict."""

    def __init__(self, *, admits: bool) -> None:
        self._admits = admits
        self.calls: list[tuple[int, bool, float, float]] = []

    async def admits_barge(
        self, *, chat_id: int, focused: bool, base_probability: float, draw: float
    ) -> bool:
        self.calls.append((chat_id, focused, base_probability, draw))
        return self._admits


# --- builders -----------------------------------------------------------------


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
    *, signals: _AddressivitySignals, reader: RoomReader, floor: _RecordingFloor,
    reactor: _RecordingReactor,
    barge_ceiling: _FakeCeiling | None = None,
) -> TurnGate:
    # The nominal collaborators (perceiver / floor / assembler) are concrete classes, so
    # the structural test doubles are injected via a justified arg-type ignore; the reader
    # satisfies the RoomReader Protocol structurally (no ignore needed).
    return TurnGate(
        decide_response=None,
        addressivity=_StubPerceiver(signals),  # type: ignore[arg-type]  # test double
        floor=floor,  # type: ignore[arg-type]  # test double
        essential=_Essential(),
        assembler=_EmptyAssembler(),  # type: ignore[arg-type]  # test double
        reactor=reactor,
        persist=_boom_persist,
        record_owner_activity=_noop_owner_activity,
        read_the_room=ReadTheRoom(reader=reader),
        barge_ceiling=barge_ceiling,
    )


# The reflective path never reads the plan (only the legacy path does), so any valid plan
# suffices — a plain full-reply plan with no rare flags.
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


async def _run(
    gate: TurnGate,
    *,
    rng: Random | None = None,
    series_ceiling: ResponseOutcome = ResponseOutcome.ENGAGE,
) -> _ReplyGate | None:
    return await gate.gate(
        _EVENT,
        _soul(),
        _interlocutor(),
        _PLAN,
        0.5,
        RuleModulators(),
        rng=rng,
        series_ceiling=series_ceiling,
    )


# --- FOCUS (INV-1) ------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_address_short_circuits_to_a_reply_bypassing_the_read() -> None:
    # 🔴 INV-1: a raw DIRECTED_TO_BOB replies deterministically — the reader is _NeverReader,
    # so if the read ran the test would fail. Focus is answered, never silent.
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    gate = _gate(
        signals=_signals(Addressivity.DIRECTED_TO_BOB),
        reader=_NeverReader(),
        floor=floor,
        reactor=reactor,
    )
    result = await _run(gate)
    assert isinstance(result, _ReplyGate)
    assert result.force_web is False


@pytest.mark.asyncio
async def test_direct_address_replies_even_when_a_reader_would_ignore() -> None:
    # Focus bypasses the reflection entirely, so even a reader scripted to IGNORE cannot
    # silence a direct address (INV-1).
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    gate = _gate(
        signals=_signals(Addressivity.DIRECTED_TO_BOB),
        reader=_ScriptedReader(
            _reading(intent=ReflectiveIntent.IGNORE, salience=0.0)
        ),
        floor=floor,
        reactor=reactor,
    )
    assert isinstance(await _run(gate), _ReplyGate)


# --- PERIPHERY ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_ambient_high_salience_reply_returns_a_reply_gate() -> None:
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT),
        reader=_ScriptedReader(_reading(intent=ReflectiveIntent.REPLY, salience=0.9)),
        floor=floor,
        reactor=reactor,
    )
    result = await _run(gate)
    assert isinstance(result, _ReplyGate)


@pytest.mark.asyncio
async def test_ambient_low_salience_stays_silent_and_advances_the_floor() -> None:
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT),
        reader=_ScriptedReader(_reading(intent=ReflectiveIntent.REPLY, salience=0.1)),
        floor=floor,
        reactor=reactor,
    )
    assert await _run(gate) is None
    assert floor.advances == [(Addressivity.AMBIENT, False)]
    assert reactor.reactions == []


@pytest.mark.asyncio
async def test_ambient_react_sets_the_emoji_and_advances_the_floor() -> None:
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT),
        reader=_ScriptedReader(
            _reading(intent=ReflectiveIntent.REACT, salience=0.9, emoji="🔥")
        ),
        floor=floor,
        reactor=reactor,
    )
    assert await _run(gate) is None
    assert reactor.reactions == [(42, 7, "🔥")]
    assert floor.advances == [(Addressivity.AMBIENT, False)]


# --- ambient-barge ceiling (BOB-066 Срез W) ----------------------------------


@pytest.mark.asyncio
async def test_ambient_reply_is_dropped_to_silence_when_the_ceiling_denies() -> None:
    # 🔴 Пласт 3: when the share-of-voice ceiling denies the ambient barge, a periphery
    # REPLY verdict is dropped to a silent IGNORE (advance the floor, no reply, no react).
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    ceiling = _FakeCeiling(admits=False)
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT),
        reader=_ScriptedReader(_reading(intent=ReflectiveIntent.REPLY, salience=0.9)),
        floor=floor,
        reactor=reactor,
        barge_ceiling=ceiling,
    )
    assert await _run(gate, rng=Random(0)) is None
    assert floor.advances == [(Addressivity.AMBIENT, False)]
    assert reactor.reactions == []
    # The ceiling was consulted un-focused with the reading's salience as the base p(barge).
    assert len(ceiling.calls) == 1
    chat_id, focused, base_probability, _draw = ceiling.calls[0]
    assert chat_id == 42
    assert focused is False
    assert base_probability == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_ambient_reply_passes_when_the_ceiling_admits() -> None:
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    ceiling = _FakeCeiling(admits=True)
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT),
        reader=_ScriptedReader(_reading(intent=ReflectiveIntent.REPLY, salience=0.9)),
        floor=floor,
        reactor=reactor,
        barge_ceiling=ceiling,
    )
    assert isinstance(await _run(gate, rng=Random(0)), _ReplyGate)
    assert len(ceiling.calls) == 1


@pytest.mark.asyncio
async def test_focus_bypasses_the_ceiling_entirely() -> None:
    # 🔴 INV-1: a direct address short-circuits ABOVE the ceiling — even a denying ceiling
    # never throttles focus, and it is never even consulted (no draw taken).
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    ceiling = _FakeCeiling(admits=False)
    gate = _gate(
        signals=_signals(Addressivity.DIRECTED_TO_BOB),
        reader=_NeverReader(),
        floor=floor,
        reactor=reactor,
        barge_ceiling=ceiling,
    )
    assert isinstance(await _run(gate, rng=Random(0)), _ReplyGate)
    assert ceiling.calls == []


@pytest.mark.asyncio
async def test_ambient_react_never_consults_the_ceiling() -> None:
    # The ceiling gates only the barge (REPLY); a REACT verdict is un-throttled.
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    ceiling = _FakeCeiling(admits=False)
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT),
        reader=_ScriptedReader(
            _reading(intent=ReflectiveIntent.REACT, salience=0.9, emoji="🔥")
        ),
        floor=floor,
        reactor=reactor,
        barge_ceiling=ceiling,
    )
    assert await _run(gate, rng=Random(0)) is None
    assert reactor.reactions == [(42, 7, "🔥")]
    assert ceiling.calls == []


# --- series budget ceiling (batch top-k, BOB-066 Срез W.2) -------------------


@pytest.mark.asyncio
async def test_series_silent_ceiling_drops_an_ambient_reply_to_silence() -> None:
    # 🔴 Пласт 3: when the batch top-k plan marked THIS message SILENT (the burst already spent
    # its reply + like), a periphery REPLY verdict stays quiet (advance the floor, no reply).
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT),
        reader=_ScriptedReader(_reading(intent=ReflectiveIntent.REPLY, salience=0.9)),
        floor=floor,
        reactor=reactor,
    )
    result = await _run(gate, rng=Random(0), series_ceiling=ResponseOutcome.SILENT)
    assert result is None
    assert reactor.reactions == []
    assert floor.advances == [(Addressivity.AMBIENT, False)]


@pytest.mark.asyncio
async def test_series_react_ceiling_downgrades_an_ambient_reply_to_a_like() -> None:
    # A message the plan marked REACT downgrades a REPLY verdict to a like — a REPLY reading
    # carries no chosen emoji, so the like falls back to a mood emoji (still a real like).
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT),
        reader=_ScriptedReader(_reading(intent=ReflectiveIntent.REPLY, salience=0.9)),
        floor=floor,
        reactor=reactor,
    )
    result = await _run(gate, rng=Random(0), series_ceiling=ResponseOutcome.REACT)
    assert result is None
    assert len(reactor.reactions) == 1
    chat_id, message_id, emoji = reactor.reactions[0]
    assert (chat_id, message_id) == (42, 7)
    assert emoji  # a real like was set (the mood emoji)
    assert floor.advances == [(Addressivity.AMBIENT, False)]


@pytest.mark.asyncio
async def test_series_engage_ceiling_leaves_the_reply_intact() -> None:
    # ENGAGE (the default / one addressed reply) is no cap — the ambient REPLY still replies.
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT),
        reader=_ScriptedReader(_reading(intent=ReflectiveIntent.REPLY, salience=0.9)),
        floor=floor,
        reactor=reactor,
    )
    result = await _run(gate, rng=Random(0), series_ceiling=ResponseOutcome.ENGAGE)
    assert isinstance(result, _ReplyGate)


@pytest.mark.asyncio
async def test_focus_is_never_capped_by_the_series_ceiling() -> None:
    # 🔴 INV-1: a direct address is answered ABOVE the budget — even a SILENT ceiling cannot
    # drop it (the focal short-circuit returns before the ceiling is ever consulted).
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    gate = _gate(
        signals=_signals(Addressivity.DIRECTED_TO_BOB),
        reader=_NeverReader(),
        floor=floor,
        reactor=reactor,
    )
    result = await _run(gate, rng=Random(0), series_ceiling=ResponseOutcome.SILENT)
    assert isinstance(result, _ReplyGate)


@pytest.mark.asyncio
async def test_periphery_read_failure_safe_defaults_to_silent_ignore() -> None:
    # 🔴 INV-2: a reflection failure on the periphery is a tidy silent skip (advance the
    # floor, no reply, no reaction) — NOT a GUPPI notice.
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    gate = _gate(
        signals=_signals(Addressivity.AMBIENT),
        reader=_ScriptedReader(None),  # raises inside read
        floor=floor,
        reactor=reactor,
    )
    assert await _run(gate) is None
    assert floor.advances == [(Addressivity.AMBIENT, False)]
    assert reactor.reactions == []
