# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 INV-1 matrix — a direct address is ALWAYS answered, never silence (BOB-066 2.2).

The load-bearing invariant of the whole reflective seam, pinned as an explicit matrix:

    {focus triggers} x {conditions that exist today} → the gate yields a ``_ReplyGate``.

* FOCUS TRIGGERS — the three raw ways a turn is directed straight AT Bob: an ``@mention``,
  a reply targeting Bob's own message, and an «Боб, …» name-address. Each classifies to
  ``Addressivity.DIRECTED_TO_BOB`` (proved here against the REAL detector), which the gate
  short-circuits at the very top of the reflective fork.
* CONDITIONS — every situation that can surround that focal turn TODAY: an empty floor, an
  ambient burst around it, Bob sulking (обида), a turn-local dispatch RNG (batch/dispatch,
  Срез 2.1), the reflective reader scripted to IGNORE, and the reflective reader raising /
  timing out. In EVERY cell the gate returns a ``_ReplyGate`` — never ``None``/silence.

The share-of-voice CEILING dimension does NOT exist yet (it lands in Срез 2.3), so it is
deliberately absent from the matrix — noted, not faked.

Two structural guarantees ride every cell:

* the focal path takes NO random draw (a :class:`_BoomRandom` is threaded in and never
  touched — that RNG-free property IS part of INV-1/INV-4);
* the focal path bypasses the reflective read entirely, so a reader scripted to IGNORE or
  raising cannot silence a direct address (contrast: the SAME raising reader on the
  PERIPHERY safe-defaults to silence — the two-class failure split).

The downstream «OR an honest GUPPI notice» half of INV-1 is BOB-049's UNCHANGED essential
seam: focus returns a plain ``_ReplyGate`` (``force_web=False``, ``history=None``) — the
exact shape the compose→essential→notice path already handles — so a generation failure
becomes a GUPPI outage notice, never silence, by construction (pinned there, not re-tested).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.conversation.addressivity import Addressivity, classify_addressivity
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
from bob.kernel.events import MessageReceived
from bob.kernel.interlocutor import Interlocutor, InterlocutorKind, Trust
from bob.kernel.modulators import RuleModulators
from bob.personality.expression import ExpressionMode, ExpressionPlan, FormHint
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.taste import TasteAxis, TasteEngine

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# --- Bob's own resolved id (for the reply-to-Bob trigger) ---------------------
_BOB_ID = 999


# --- test doubles -------------------------------------------------------------


class _StubPerceiver:
    """Returns scripted addressivity signals — the reflective gate reads ``signals``."""

    def __init__(self, signals: _AddressivitySignals) -> None:
        self._signals = signals

    async def signals(self, event: MessageReceived) -> _AddressivitySignals:
        return self._signals


class _RecordingFloor:
    """Records every after-turn floor advance (a FOCUS turn must record NONE)."""

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


class _BoomReader:
    """Fails the test if read at all — proves the FOCUS path bypasses the reflection."""

    async def read(self, ctx: RoomReadingContext) -> RoomReading:
        raise AssertionError("focus turn must NOT run the reflective read")


class _IgnoreReader:
    """A reader scripted to a low-salience IGNORE — must still not silence a focus turn."""

    async def read(self, ctx: RoomReadingContext) -> RoomReading:
        return RoomReading(
            situation="болтают",
            pairings=(),
            room_mood=RoomMood.NEUTRAL,
            intent=ReflectiveIntent.IGNORE,
            addressee_id=None,
            salience=0.0,
            emoji=None,
            wants_web=False,
            reason="ignore",
        )


class _RaisingReader:
    """A reader that raises — on FOCUS it is never called; on PERIPHERY it → silence."""

    async def read(self, ctx: RoomReadingContext) -> RoomReading:
        raise RuntimeError("model down")


class _BoomRandom:
    """A Random stand-in that EXPLODES on any draw — pins the focal RNG-free invariant."""

    def random(self) -> float:
        raise AssertionError("the focal path must take NO random draw (INV-1/INV-4)")


class _RecordingPersist:
    """Records persists of the user's turn — a FOCUS turn records NONE (persist rides the
    caller's compose path); a reflective PERIPHERY non-reply persists here (BOB-071 Seam B)."""

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
        raise AssertionError("the reflective path does not use the essential runner")


# --- builders -----------------------------------------------------------------


def _soul(*, valence: float = 0.2) -> SOUL:
    mood = Mood(valence=valence)
    taste = TasteEngine(axes=(TasteAxis(name="x", value=0.5, conviction=0.5),))
    return SOUL(identity="Bob", mood=mood, mood_baseline=mood, taste=taste)


def _sulking_soul() -> SOUL:
    """Bob mid-обида — a hurt, low-valence mood (the focus decision must ignore it)."""
    return _soul(valence=-0.8)


def _focus_signals(
    *,
    trigger: str,
    floor_holder: FloorHolder | None,
    others_present: bool,
    floor_engaged: bool,
) -> _AddressivitySignals:
    """Raw signals for a DIRECTED_TO_BOB turn, tagged by the trigger + surrounding floor."""
    directed = Addressivity.DIRECTED_TO_BOB
    return _AddressivitySignals(
        per_message=directed,
        effective=directed,
        others_present=others_present,
        floor_engaged=floor_engaged,
        reply_to_bob=trigger == "reply_to_bob",
        directed_to_id=None,
        floor_holder=floor_holder,
        floor_participant=True,
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
    reader: RoomReader,
    floor: _RecordingFloor,
    reactor: _RecordingReactor,
    persist: _RecordingPersist | None = None,
) -> TurnGate:
    return TurnGate(
        decide_response=None,
        addressivity=_StubPerceiver(signals),  # type: ignore[arg-type]  # test double
        floor=floor,  # type: ignore[arg-type]  # test double
        essential=_Essential(),
        assembler=_EmptyAssembler(),  # type: ignore[arg-type]  # test double
        reactor=reactor,
        persist=persist or _RecordingPersist(),
        record_owner_activity=_noop_owner_activity,
        read_the_room=ReadTheRoom(reader=reader),
    )


_PLAN = ExpressionPlan(
    mode=ExpressionMode.REPLY,
    leak_inner_life=False,
    callback=False,
    mention_fascination=False,
    form_hint=FormHint.NORMAL,
)


def _event(*, text: str = "Bob, что думаешь?") -> MessageReceived:
    return MessageReceived(
        update_id=1,
        chat_id=42,
        message_id=7,
        text=text,
        sender_id=6,
        sender_name="Norman",
    )


# --- the three focus triggers classify to DIRECTED_TO_BOB (the REAL detector) --


@pytest.mark.parametrize(
    ("trigger", "text", "mentions_bob", "reply_to_sender_id"),
    [
        ("@mention", "что там по зондам?", True, None),
        ("reply-to-Bob", "согласен", False, _BOB_ID),
        ("«Боб,» name-address", "Боб, что думаешь?", False, None),
    ],
)
def test_focus_trigger_classifies_as_directed_to_bob(
    trigger: str, text: str, mentions_bob: bool, reply_to_sender_id: int | None
) -> None:
    # The trigger DIMENSION of the matrix, grounded against the real pure detector: each
    # of the three ways a turn is directed at Bob yields DIRECTED_TO_BOB — which the gate's
    # reflective fork short-circuits at the top (INV-1). (`trigger` labels the case.)
    assert trigger  # readability: the parametrize id names the trigger
    result = classify_addressivity(
        text=text,
        mentions_bob=mentions_bob,
        reply_to_sender_id=reply_to_sender_id,
        bob_user_id=_BOB_ID,
        others_present=True,
    )
    assert result is Addressivity.DIRECTED_TO_BOB


# --- the matrix: {triggers} x {conditions} → a reply, NEVER silence -----------

# The focus TRIGGERS (each already proven to classify as DIRECTED_TO_BOB above).
_TRIGGERS = ["@mention", "reply_to_bob", "name_address"]

# The CONDITIONS that exist today, each a factory for (signals, soul, reader). Every cell
# threads a _BoomRandom (no draw) and asserts a reply — the ceiling dimension (Срез 2.3)
# is deliberately absent.
_CONDITIONS: dict[str, dict[str, object]] = {
    "empty_floor": {
        "floor_holder": None,
        "others_present": False,
        "floor_engaged": False,
        "reader": _BoomReader(),
        "soul": _soul(),
    },
    "ambient_burst_around_it": {
        "floor_holder": FloorHolder.OTHER,
        "others_present": True,
        "floor_engaged": True,
        "reader": _BoomReader(),
        "soul": _soul(),
    },
    "sulk_active": {
        "floor_holder": FloorHolder.OTHER,
        "others_present": True,
        "floor_engaged": False,
        "reader": _BoomReader(),
        "soul": _sulking_soul(),
    },
    "batch_dispatch_mode": {
        "floor_holder": FloorHolder.BOB,
        "others_present": True,
        "floor_engaged": False,
        "reader": _BoomReader(),
        "soul": _soul(),
    },
    "reflective_judge_ignores": {
        "floor_holder": FloorHolder.OTHER,
        "others_present": True,
        "floor_engaged": False,
        "reader": _IgnoreReader(),
        "soul": _soul(),
    },
    "reflective_judge_raises": {
        "floor_holder": FloorHolder.OTHER,
        "others_present": True,
        "floor_engaged": False,
        "reader": _RaisingReader(),
        "soul": _soul(),
    },
}


@pytest.mark.parametrize("trigger", _TRIGGERS)
@pytest.mark.parametrize("condition", list(_CONDITIONS))
@pytest.mark.asyncio
async def test_inv1_direct_address_is_always_answered(
    trigger: str, condition: str
) -> None:
    # 🔴 INV-1 matrix cell: a direct-address turn (this trigger) under this condition MUST
    # yield a _ReplyGate — never None/silence, never a reaction, never a persist, and with
    # NO random draw. The reflective read is bypassed, so even an IGNORE/raising reader
    # cannot silence the focus.
    spec = _CONDITIONS[condition]
    floor, reactor, persist = _RecordingFloor(), _RecordingReactor(), _RecordingPersist()
    signals = _focus_signals(
        trigger=trigger,
        floor_holder=spec["floor_holder"],  # type: ignore[arg-type]
        others_present=bool(spec["others_present"]),
        floor_engaged=bool(spec["floor_engaged"]),
    )
    gate = _gate(
        signals=signals,
        reader=spec["reader"],  # type: ignore[arg-type]
        floor=floor,
        reactor=reactor,
        persist=persist,
    )
    result = await gate.gate(
        _event(),
        spec["soul"],  # type: ignore[arg-type]
        _interlocutor(),
        _PLAN,
        0.5,
        RuleModulators(),
        rng=_BoomRandom(),  # type: ignore[arg-type]  # any draw fails the test
    )
    assert isinstance(result, _ReplyGate), f"{trigger}x{condition} was silenced (INV-1)"
    # A focus reply is deterministic: it does NOT force web (the verify judge decides
    # normally on the reply path) and carries no prefetched history.
    assert result.force_web is False
    assert result.history is None
    # The focal reply advances the floor in the CALLER (bob_replied=True), so the gate
    # itself neither advances the floor nor sets a reaction on a focus turn — and does NOT
    # persist here (the compose path persists the focal turn; BOB-071 Seam B is periphery-only).
    assert floor.advances == []
    assert reactor.reactions == []
    assert persist.calls == []


# --- the two-class failure split: focus → reply, periphery → silence ----------


@pytest.mark.asyncio
async def test_same_raising_reader_silences_periphery_but_never_focus() -> None:
    # 🔴 The two-class split in one assertion: a reader that RAISES yields a reply on a
    # FOCUS turn (the read is bypassed) but a SILENT skip on the PERIPHERY (safe IGNORE,
    # no reply, no reaction) — a peripheral reflection failure is a tidy skip, not a
    # silenced direct address.
    focus_floor, focus_reactor = _RecordingFloor(), _RecordingReactor()
    focus_persist = _RecordingPersist()
    focus_gate = _gate(
        signals=_focus_signals(
            trigger="@mention",
            floor_holder=FloorHolder.OTHER,
            others_present=True,
            floor_engaged=False,
        ),
        reader=_RaisingReader(),
        floor=focus_floor,
        reactor=focus_reactor,
        persist=focus_persist,
    )
    focus_result = await focus_gate.gate(
        _event(), _soul(), _interlocutor(), _PLAN, 0.5, RuleModulators(),
        rng=_BoomRandom(),  # type: ignore[arg-type]
    )
    assert isinstance(focus_result, _ReplyGate)
    assert focus_persist.calls == []  # focus does not persist in the gate

    ambient = _AddressivitySignals(
        per_message=Addressivity.AMBIENT,
        effective=Addressivity.AMBIENT,
        others_present=True,
        floor_engaged=False,
        reply_to_bob=False,
        directed_to_id=None,
        floor_holder=FloorHolder.OTHER,
        floor_participant=True,
    )
    peri_floor, peri_reactor = _RecordingFloor(), _RecordingReactor()
    peri_persist = _RecordingPersist()
    peri_gate = _gate(
        signals=ambient,
        reader=_RaisingReader(),
        floor=peri_floor,
        reactor=peri_reactor,
        persist=peri_persist,
    )
    peri_result = await peri_gate.gate(
        _event(text="сегодня дождь весь день"),
        _soul(),
        _interlocutor(),
        _PLAN,
        0.5,
        RuleModulators(),
    )
    assert peri_result is None
    assert peri_floor.advances == [(Addressivity.AMBIENT, False)]
    assert peri_reactor.reactions == []
    # 🔴 BOB-071 Seam B: the periphery safe-IGNORE persists the incoming turn (thread intact).
    assert len(peri_persist.calls) == 1


# --- periphery C11: a reflective wants_web rides the reply as force_web --------


@pytest.mark.parametrize(
    ("wants_web", "expected_force_web"),
    [(True, True), (False, False)],
)
@pytest.mark.asyncio
async def test_periphery_reply_carries_wants_web_as_force_web(
    wants_web: bool, expected_force_web: bool
) -> None:
    # A periphery REPLY read that set wants_web forces the EXISTING verify pass by riding
    # the gate as force_web (C11); a reply without it leaves force_web False (the verify
    # judge decides as before).
    class _WebReader:
        async def read(self, ctx: RoomReadingContext) -> RoomReading:
            return RoomReading(
                situation="спорят о ставке ЦБ",
                pairings=(),
                room_mood=RoomMood.NEUTRAL,
                intent=ReflectiveIntent.REPLY,
                addressee_id=None,
                salience=0.9,
                emoji=None,
                wants_web=wants_web,
                reason="freshness",
            )

    ambient = _AddressivitySignals(
        per_message=Addressivity.AMBIENT,
        effective=Addressivity.AMBIENT,
        others_present=True,
        floor_engaged=False,
        reply_to_bob=False,
        directed_to_id=None,
        floor_holder=FloorHolder.OTHER,
        floor_participant=True,
    )
    floor, reactor = _RecordingFloor(), _RecordingReactor()
    gate = _gate(
        signals=ambient, reader=_WebReader(), floor=floor, reactor=reactor
    )
    result = await gate.gate(
        _event(text="какая сейчас ставка?"),
        _soul(),
        _interlocutor(),
        _PLAN,
        0.5,
        RuleModulators(),
    )
    assert isinstance(result, _ReplyGate)
    assert result.force_web is expected_force_web
