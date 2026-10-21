# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the BOB-062.6b wave-2 mid-tier collaborators.

These pin the SUBTLE 🔴 invariants at the collaborator level (the full handle() suite
covers behaviour end to end):

* the mutable per-boot holders are read/written on the holder PASSED IN per call (never a
  captured reference) — the mood lift / fatigue decay land on ``HandleMessage``'s CURRENT
  holder even when it is re-pointed;
* the being-received acknowledgment is a read → roll → clear consume-once, and spends NO
  seeded draw when there is no marker (so the per-turn draw order is unshifted); and
* Bob's own id degrades gracefully to ``None`` when the source is unwired.
"""

from __future__ import annotations

from datetime import UTC, datetime
from random import Random
from typing import TYPE_CHECKING

import pytest

from bob.conversation.addressivity import AddressivityThresholds
from bob.conversation.brevity import BrevityThresholds
from bob.conversation.conversation_floor import FloorConfig
from bob.conversation.engagement import (
    ConversationalFatigue,
    EngagementThresholds,
    FatigueRates,
)
from bob.conversation.usecases.addressivity_perceiver import AddressivityPerceiver
from bob.conversation.usecases.engagement_model import EngagementModel
from bob.conversation.usecases.floor_manager import FloorManager
from bob.conversation.usecases.recall_assembler import RecallAssembler
from bob.personality.expression import EngagementLevel, ExpressionFreqs
from bob.personality.mood import Mood
from bob.personality.reaction_effect import NotableReaction
from bob.personality.soul import SOUL
from bob.personality.taste import TasteAxis, TasteEngine
from bob.personality.usecases.mood_perceiver import MoodPerceiver

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from bob.conversation.engagement import EngagementState
from bob.personality.state import PersonalityState


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)


class _CountingRandom(Random):
    """A Random that records how many draws were spent + yields a fixed value."""

    def __init__(self, value: float) -> None:
        super().__init__(0)
        self._value = value
        self.draws = 0

    def random(self) -> float:
        self.draws += 1
        return self._value


class _EmptyEpisodes:
    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]:
        del k
        return []

    async def recent_episodes_for(
        self, sender_id: int, k: int
    ) -> Sequence[Mapping[str, object]]:
        del sender_id, k
        return []


class _FakeNotableStore:
    def __init__(self, note: NotableReaction | None) -> None:
        self._note = note
        self.cleared = 0

    async def record(self, note: NotableReaction) -> None:  # pragma: no cover - unused
        self._note = note

    async def latest(self) -> NotableReaction | None:
        return self._note

    async def clear(self) -> None:
        self.cleared += 1


def _soul(valence: float) -> SOUL:
    mood = Mood(valence=valence)
    taste = TasteEngine(axes=(TasteAxis(name="x", value=0.9, conviction=0.9),))
    return SOUL(
        identity="I am the Bob from the book.",
        mood=mood,
        mood_baseline=mood,
        taste=taste,
        phantom_prefs=(),
    )


def _interlocutor(sender_id: int) -> object:
    class _I:
        def __init__(self, sid: int) -> None:
            self.sender_id = sid

    return _I(sender_id)


def _engagement_model() -> EngagementModel:
    return EngagementModel(
        engagement_thresholds=EngagementThresholds(),
        fatigue_rates=FatigueRates(),
        engagement_mood_lift=0.1,
        fascination=None,
        brevity_thresholds=BrevityThresholds(),
        length_guard_enabled=False,
        length_guard_max_chars=280,
        clock=_FixedClock(),
        rng=Random(0),
    )


def test_apply_feedback_mutates_the_holder_passed_in_not_a_captured_ref() -> None:
    # 🔴 The good-exchange mood lift lands on the PASSED state (never a ref captured at
    # construction): a fresh, unrelated holder proves the collaborator writes only the one
    # it is handed this turn — the fix that keeps a re-pointed PersonalityState correct.
    model = _engagement_model()
    passed = PersonalityState(soul=_soul(0.1))
    untouched = PersonalityState(soul=_soul(0.1))
    engagement_state = EngagementState()

    result = model.apply_feedback(
        passed.soul, EngagementLevel.FULL, interest=0.9,
        state=passed, engagement_state=engagement_state,
    )

    assert result.mood.valence > 0.1
    assert passed.soul.mood.valence > 0.1  # the handed holder was written
    assert untouched.soul.mood.valence == 0.1  # a different holder is never touched
    assert engagement_state.last_turn_at is not None  # the fatigue holder was stamped


def test_decide_engagement_decays_the_passed_fatigue_holder() -> None:
    # The elapsed-time fatigue decay is applied to the holder handed in this turn.
    model = _engagement_model()
    engagement_state = EngagementState(
        fatigue=ConversationalFatigue(0.95),
        last_turn_at=datetime(2026, 6, 17, 12, 0, 0, tzinfo=UTC),  # a day earlier
    )

    model.decide_engagement(_soul(0.1), interest=0.0, relationship=None,
                            engagement_state=engagement_state)

    assert engagement_state.fatigue.level < 0.95  # decayed on the passed holder


def test_reengage_for_room_does_not_decay_fatigue_again() -> None:
    # 🔴 BOB-066 Срез W.2: the room-mood re-map re-runs the pure appetite decision over the
    # ALREADY-decayed fatigue, so it NEVER decays a second time (no double-decay bug).
    model = _engagement_model()
    engagement_state = EngagementState(fatigue=ConversationalFatigue(0.4))

    model.reengage_for_room(
        _soul(0.1), 0.5, None, engagement_state, threshold_shift=0.3,
    )

    assert engagement_state.fatigue.level == 0.4  # untouched by the re-map


def test_reengage_for_room_positive_shift_lifts_appetite() -> None:
    # A warm-room positive shift lowers the interest bar so a borderline topic that reads TERSE
    # at the base engages FULLY — the room-mood analogue of a close relationship.
    model = _engagement_model()
    borderline = EngagementThresholds().interesting - 0.1

    base = model.reengage_for_room(
        _soul(0.0), borderline, None, EngagementState(), threshold_shift=0.0,
    )
    warm = model.reengage_for_room(
        _soul(0.0), borderline, None, EngagementState(), threshold_shift=0.3,
    )

    assert base is EngagementLevel.TERSE
    assert warm in (EngagementLevel.FULL, EngagementLevel.PLAYFUL)


@pytest.mark.asyncio
async def test_acknowledgment_spends_no_draw_without_a_marker() -> None:
    # 🔴 Ordering invariant: with no notable reaction on record, NO seeded draw is spent,
    # so the ack's draw slot only consumes when Bob actually acknowledges — the per-turn
    # draw order (…→ surface/ack) is never shifted by an inert acknowledgment.
    rng = _CountingRandom(0.0)
    assembler = RecallAssembler(
        episodes=_EmptyEpisodes(), recent_turns=14, absence_hint_hours=8.0,
        notable_reaction=_FakeNotableStore(None), acknowledge_reaction_freq=0.15,
        clock=_FixedClock(), rng=rng,
    )

    result = await assembler.acknowledgment_for(_interlocutor(99))  # type: ignore[arg-type]

    assert result == ""
    assert rng.draws == 0  # no marker → no roll spent


@pytest.mark.asyncio
async def test_acknowledgment_is_consumed_once_on_a_lucky_roll() -> None:
    # A matching marker + a lucky roll → the marker is CLEARED (consume-once) and a hint
    # returns; an unlucky roll spends the draw but LEAVES the marker for a later turn.
    note = NotableReaction(
        sender_id=99, reactor_name="Ada", emoji="🔥", bob_excerpt="x",
        interpretation="warm", at=datetime(2026, 6, 18, 11, 0, 0, tzinfo=UTC),
    )
    lucky_store = _FakeNotableStore(note)
    lucky = RecallAssembler(
        episodes=_EmptyEpisodes(), recent_turns=14, absence_hint_hours=8.0,
        notable_reaction=lucky_store, acknowledge_reaction_freq=0.15,
        clock=_FixedClock(), rng=_CountingRandom(0.0),
    )
    hint = await lucky.acknowledgment_for(_interlocutor(99))  # type: ignore[arg-type]
    assert hint != ""
    assert lucky_store.cleared == 1

    unlucky_store = _FakeNotableStore(note)
    unlucky_rng = _CountingRandom(0.99)
    unlucky = RecallAssembler(
        episodes=_EmptyEpisodes(), recent_turns=14, absence_hint_hours=8.0,
        notable_reaction=unlucky_store, acknowledge_reaction_freq=0.15,
        clock=_FixedClock(), rng=unlucky_rng,
    )
    result = await unlucky.acknowledgment_for(_interlocutor(99))  # type: ignore[arg-type]
    assert result == ""
    assert unlucky_store.cleared == 0  # not consumed
    assert unlucky_rng.draws == 1  # the roll WAS spent


def test_bob_user_id_degrades_to_none_when_source_unwired() -> None:
    # Bob's own id is read lazily; unwired → None (reply-to-Bob can't fire, @mention still
    # does). The perceiver shares HandleMessage's floor + rng, unchanged.
    perceiver = AddressivityPerceiver(
        floor=FloorManager(
            floor_store=None, floor_config=FloorConfig(),
            floor_enabled=True, clock=_FixedClock(),
        ),
        episodes=_EmptyEpisodes(), recent_turns=14,
        bob_user_id_source=None,
        addressivity_thresholds=AddressivityThresholds(),
        rng=Random(0),
    )

    assert perceiver._bob_user_id() is None


@pytest.mark.asyncio
async def test_mood_perceiver_writes_the_passed_holder() -> None:
    # MoodPerceiver.perceive stores the fresh soul snapshot on the holder handed in.
    class _Updater:
        async def run(self, mood: Mood, signals: object, *, target: Mood) -> Mood:
            del signals, target
            return mood

    perceiver = MoodPerceiver(
        update_mood=_Updater(),  # type: ignore[arg-type]
        expression_freqs=ExpressionFreqs(),
        rng=Random(0),
    )
    state = PersonalityState(soul=_soul(0.2))
    sentinel = state.soul

    class _Event:
        text = "hi"

    result = await perceiver.perceive(_Event(), state)  # type: ignore[arg-type]

    assert result is state.soul  # the holder was written with the fresh snapshot
    assert state.soul is not sentinel or result.mood.valence == 0.2
