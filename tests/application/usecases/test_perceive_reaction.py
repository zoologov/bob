# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for PerceiveReaction — Bob feels a reaction on his message (BOB-050 .2).

The heart of the feature: a reaction's MEANING (from an injected judge) changes Bob —
mood (bounded, BOB-033 path), relationship warmth (BOB-014), a per-person memory
(BOB-045), and a being-received note. 🔴 The whole path is decorative: any failure is
dropped silently. Anonymous reactions lift mood only; a guest is felt + remembered
keyed to the guest with no owner-private leak.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.usecases.perceive_reaction import PerceiveReaction
from bob.kernel.events import BobMessageReaction
from bob.kernel.interlocutor import Interlocutor, InterlocutorKind, Trust
from bob.kernel.relationship import Relationship
from bob.personality.disposition import DEFAULT_DISPOSITION
from bob.personality.mood import Mood, MoodDelta
from bob.personality.reaction_meaning import ReactionMeaning
from bob.personality.soul import SOUL
from bob.personality.state import PersonalityState
from bob.personality.taste import TasteEngine

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.personality.reaction_effect import NotableReaction
    from bob.personality.reaction_meaning import ReactionContext

_BOB_MESSAGE_ID = 555
_REACTOR_ID = 42
_CHAT_ID = 100


class _FakeJudge:
    def __init__(self, meaning: ReactionMeaning | None, *, raises: bool = False) -> None:
        self._meaning = meaning
        self._raises = raises
        self.ctx: ReactionContext | None = None

    async def interpret(self, ctx: ReactionContext) -> ReactionMeaning:
        self.ctx = ctx
        if self._raises or self._meaning is None:
            raise RuntimeError("judge down")
        return self._meaning


class _FakeLookup:
    def __init__(self, episode: Mapping[str, object] | None) -> None:
        self._episode = episode
        self.asked: int | None = None

    async def episode_by_bob_message_id(
        self, bob_message_id: int
    ) -> Mapping[str, object] | None:
        self.asked = bob_message_id
        return self._episode


class _FakeResolver:
    def __init__(self, interlocutor: Interlocutor) -> None:
        self._interlocutor = interlocutor
        self.chat_id: int | None = None

    async def resolve(
        self, *, sender_id: int | None, sender_name: str | None, chat_id: int
    ) -> Interlocutor:
        self.chat_id = chat_id
        return self._interlocutor


class _FakeRelationships:
    def __init__(self, rel: Relationship | None = None) -> None:
        self.stored: Relationship | None = rel
        self.saved: list[Relationship] = []

    async def load(self, sender_id: int) -> Relationship | None:
        return self.stored

    async def save(self, relationship: Relationship) -> None:
        self.stored = relationship
        self.saved.append(relationship)


class _FakeMemory:
    def __init__(self) -> None:
        self.episodes: list[Mapping[str, object]] = []

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        self.episodes.append(episode)


class _FakeNotable:
    def __init__(self) -> None:
        self.recorded: list[NotableReaction] = []

    async def record(self, note: NotableReaction) -> None:
        self.recorded.append(note)

    async def latest(self) -> NotableReaction | None:
        return self.recorded[-1] if self.recorded else None

    async def clear(self) -> None:
        self.recorded.clear()


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def _soul(*, mood: Mood) -> SOUL:
    return SOUL(
        identity="Bob",
        mood=mood,
        mood_baseline=Mood(valence=0.5),
        taste=TasteEngine(),
        disposition=DEFAULT_DISPOSITION,
    )


def _interlocutor(
    kind: InterlocutorKind = InterlocutorKind.KNOWN,
    *,
    name: str = "Боб-старший",
) -> Interlocutor:
    trust = Trust.GUEST if kind is InterlocutorKind.GUEST else Trust.TRUSTED
    return Interlocutor(sender_id=_REACTOR_ID, display_name=name, kind=kind, trust=trust)


def _episode() -> dict[str, object]:
    return {"content": "Боб-старший: привет\nbob: я правда рад, что ты написал"}


def _warm() -> ReactionMeaning:
    return ReactionMeaning(
        interpretation="его тронуло",
        mood_delta=MoodDelta(valence=0.2, social=0.05),
        warmth_nudge=0.1,
        worth_acknowledging=True,
    )


def _dismissive() -> ReactionMeaning:
    return ReactionMeaning(
        interpretation="насмешка",
        mood_delta=MoodDelta(valence=-0.15),
        warmth_nudge=-0.08,
        worth_acknowledging=False,
    )


def _build(
    *,
    judge: _FakeJudge,
    state: PersonalityState,
    lookup: _FakeLookup | None = None,
    resolver: _FakeResolver | None = None,
    relationships: _FakeRelationships | None = None,
    memory: _FakeMemory | None = None,
    notable: _FakeNotable | None = None,
) -> tuple[PerceiveReaction, _FakeRelationships, _FakeMemory, _FakeNotable]:
    rels = relationships or _FakeRelationships()
    mem = memory or _FakeMemory()
    note = notable or _FakeNotable()
    uc = PerceiveReaction(
        judge=judge,
        lookup=lookup or _FakeLookup(_episode()),
        resolver=resolver or _FakeResolver(_interlocutor()),
        state=state,
        relationships=rels,
        memory=mem,
        notable=note,
        clock=_FixedClock(),
        disposition=DEFAULT_DISPOSITION,
    )
    return uc, rels, mem, note


def _event(
    *,
    added: tuple[str, ...] = ("❤",),
    removed: tuple[str, ...] = (),
    reactor_sender_id: int | None = _REACTOR_ID,
    name: str | None = "Боб-старший",
) -> BobMessageReaction:
    return BobMessageReaction(
        chat_id=_CHAT_ID,
        message_id=_BOB_MESSAGE_ID,
        emoji_added=added,
        emoji_removed=removed,
        reactor_sender_id=reactor_sender_id,
        reactor_name=name,
    )


async def test_warm_reaction_lifts_mood_warms_remembers_and_notes() -> None:
    state = PersonalityState(soul=_soul(mood=Mood(valence=-0.2)))
    uc, rels, mem, note = _build(judge=_FakeJudge(_warm()), state=state)

    await uc.perceive(_event())

    # Mood lifted (bounded, still in band).
    assert state.soul.mood.valence > -0.2
    assert -1.0 <= state.soul.mood.valence <= 1.0
    # Relationship warmed toward the reactor.
    assert rels.saved and rels.saved[-1].warmth > 0
    # A per-person memory episode keyed to the reactor was saved.
    assert len(mem.episodes) == 1
    episode = mem.episodes[0]
    assert episode["sender_id"] == _REACTOR_ID
    assert episode["event_type"] == "reaction_received"
    assert "его тронуло" in str(episode["content"])
    assert "❤" in str(episode["content"])
    # Being-received noted (worth acknowledging).
    assert note.recorded and note.recorded[-1].sender_id == _REACTOR_ID


async def test_judge_reads_bobs_message_text() -> None:
    state = PersonalityState(soul=_soul(mood=Mood()))
    judge = _FakeJudge(_warm())
    uc, *_ = _build(judge=judge, state=state)

    await uc.perceive(_event())

    assert judge.ctx is not None
    assert "я правда рад, что ты написал" in judge.ctx.bob_message_text
    assert judge.ctx.added is True


async def test_dismissive_meaning_dips_mood_and_cools_warmth() -> None:
    state = PersonalityState(soul=_soul(mood=Mood(valence=0.3)))
    uc, rels, _mem, note = _build(
        judge=_FakeJudge(_dismissive()),
        state=state,
        relationships=_FakeRelationships(Relationship(sender_id=_REACTOR_ID, warmth=0.2)),
    )

    await uc.perceive(_event(added=("😂",)))

    # The MEANING (not the emoji) drives a negative effect.
    assert state.soul.mood.valence < 0.3
    assert rels.saved[-1].warmth < 0.2
    # Not worth acknowledging -> no being-received note.
    assert note.recorded == []


async def test_removal_leans_negative() -> None:
    state = PersonalityState(soul=_soul(mood=Mood(valence=0.3)))
    # The judge (semantic) reads a removal as mildly negative; the use-case applies it.
    uc, *_ = _build(judge=_FakeJudge(_dismissive()), state=state)

    await uc.perceive(_event(added=(), removed=("❤",)))

    assert state.soul.mood.valence < 0.3


async def test_anonymous_reaction_lifts_mood_only() -> None:
    state = PersonalityState(soul=_soul(mood=Mood(valence=0.0)))
    judge = _FakeJudge(_warm())
    uc, rels, mem, note = _build(judge=judge, state=state)

    await uc.perceive(_event(reactor_sender_id=None, name=None))

    # A light lift happened, but no who -> no judge, memory, relationship, or note.
    assert state.soul.mood.valence > 0.0
    assert judge.ctx is None
    assert rels.saved == []
    assert mem.episodes == []
    assert note.recorded == []


async def test_missing_message_is_dropped_silently() -> None:
    state = PersonalityState(soul=_soul(mood=Mood(valence=0.1)))
    judge = _FakeJudge(_warm())
    uc, rels, mem, _note = _build(
        judge=judge, state=state, lookup=_FakeLookup(None)
    )

    await uc.perceive(_event())  # must not raise

    # No episode for the message -> soft skip; nothing changed, judge never called.
    assert judge.ctx is None
    assert state.soul.mood.valence == 0.1
    assert mem.episodes == []
    assert rels.saved == []


async def test_judge_failure_is_dropped_silently() -> None:
    state = PersonalityState(soul=_soul(mood=Mood(valence=0.1)))
    uc, rels, mem, note = _build(judge=_FakeJudge(None, raises=True), state=state)

    await uc.perceive(_event())  # 🔴 must not raise (decorative)

    # Effects were never applied (the failure dropped the whole perception).
    assert state.soul.mood.valence == 0.1
    assert mem.episodes == []
    assert rels.saved == []
    assert note.recorded == []


async def test_guest_reaction_is_felt_and_kept_keyed_to_the_guest() -> None:
    state = PersonalityState(soul=_soul(mood=Mood(valence=0.0)))
    guest = _interlocutor(InterlocutorKind.GUEST, name="незнакомец")
    uc, rels, mem, _note = _build(
        judge=_FakeJudge(_warm()), state=state, resolver=_FakeResolver(guest)
    )

    await uc.perceive(_event(name="незнакомец"))

    # Bob feels it (mood) and remembers it keyed to the GUEST — per-person, about
    # Bob's OWN message; no owner-fact write, no owner-private content.
    assert state.soul.mood.valence > 0.0
    assert mem.episodes[0]["sender_id"] == _REACTOR_ID
    assert mem.episodes[0]["event_type"] == "reaction_received"
    assert rels.saved[-1].sender_id == _REACTOR_ID
    # The reactor was resolved with the reaction's chat scope (authz BOB-019).
    assert "незнакомец" in str(mem.episodes[0]["content"])


async def test_effects_stay_in_bounded_band() -> None:
    state = PersonalityState(soul=_soul(mood=Mood(valence=0.9)))
    uc, rels, *_ = _build(
        judge=_FakeJudge(_warm()),
        state=state,
        relationships=_FakeRelationships(Relationship(sender_id=_REACTOR_ID, warmth=0.9)),
    )

    await uc.perceive(_event())

    assert -1.0 <= state.soul.mood.valence <= 1.0
    assert -1.0 <= rels.saved[-1].warmth <= 1.0
