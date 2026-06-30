# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Acceptance guardrails for reaction perception — PRD US-1..6 (BOB-050 .4).

Companion to ``test_perceive_reaction.py`` (the .2 unit tests). These are the
acceptance/guardrail assertions phrased against the PRD user stories, focused on the
angles the unit tests do NOT pin:

* **US-2 (зашло / не зашло by MEANING, not emoji):** the SAME emoji judged warm vs
  dismissive yields OPPOSITE effects — proving the effect is driven by meaning, never
  an emoji→table lookup.
* **US-1 memory line shape:** the per-person episode names the reactor, the emoji and
  what Bob had said; a long reply is excerpted (truncated), an oddly-shaped episode row
  degrades gracefully.
* **US-6 / regression bound:** even a strong warm read keeps every effect inside the
  BOB-030 band (no swings).

Deterministic — a scripted fake judge, fake stores, a fixed clock. No LLM, no Telegram.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.events import BobMessageReaction
from bob.application.usecases.handle_message import PersonalityState
from bob.application.usecases.perceive_reaction import PerceiveReaction
from bob.domain.personality.disposition import DEFAULT_DISPOSITION
from bob.domain.personality.interlocutor import Interlocutor, InterlocutorKind, Trust
from bob.domain.personality.mood import Mood, MoodDelta
from bob.domain.personality.reaction_meaning import ReactionMeaning
from bob.domain.personality.relationship import Relationship
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteEngine

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.domain.personality.reaction_effect import NotableReaction
    from bob.domain.personality.reaction_meaning import ReactionContext

_BOB_MESSAGE_ID = 555
_REACTOR_ID = 42
_CHAT_ID = 100
_HEART = "❤"  # the SAME emoji used for both warm and dismissive readings (US-2)


class _FakeJudge:
    def __init__(self, meaning: ReactionMeaning) -> None:
        self._meaning = meaning
        self.ctx: ReactionContext | None = None

    async def interpret(self, ctx: ReactionContext) -> ReactionMeaning:
        self.ctx = ctx
        return self._meaning


class _FakeLookup:
    def __init__(self, episode: Mapping[str, object] | None) -> None:
        self._episode = episode

    async def episode_by_bob_message_id(
        self, bob_message_id: int
    ) -> Mapping[str, object] | None:
        return self._episode


class _FakeResolver:
    def __init__(self, interlocutor: Interlocutor) -> None:
        self._interlocutor = interlocutor

    async def resolve(
        self, *, sender_id: int | None, sender_name: str | None, chat_id: int
    ) -> Interlocutor:
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


def _interlocutor(name: str = "Боб-старший") -> Interlocutor:
    return Interlocutor(
        sender_id=_REACTOR_ID,
        display_name=name,
        kind=InterlocutorKind.KNOWN,
        trust=Trust.TRUSTED,
    )


def _warm() -> ReactionMeaning:
    return ReactionMeaning(
        interpretation="его тронуло",
        mood_delta=MoodDelta(valence=0.2, social=0.05),
        warmth_nudge=0.1,
        worth_acknowledging=True,
    )


def _dismissive() -> ReactionMeaning:
    return ReactionMeaning(
        interpretation="холодная отписка",
        mood_delta=MoodDelta(valence=-0.15),
        warmth_nudge=-0.08,
        worth_acknowledging=False,
    )


def _build(
    *,
    meaning: ReactionMeaning,
    state: PersonalityState,
    episode: Mapping[str, object] | None,
    rel_warmth: float = 0.0,
) -> tuple[PerceiveReaction, _FakeRelationships, _FakeMemory, _FakeNotable]:
    rels = _FakeRelationships(Relationship(sender_id=_REACTOR_ID, warmth=rel_warmth))
    mem = _FakeMemory()
    note = _FakeNotable()
    uc = PerceiveReaction(
        judge=_FakeJudge(meaning),
        lookup=_FakeLookup(episode),
        resolver=_FakeResolver(_interlocutor()),
        state=state,
        relationships=rels,
        memory=mem,
        notable=note,
        clock=_FixedClock(),
        disposition=DEFAULT_DISPOSITION,
    )
    return uc, rels, mem, note


def _episode(*, bob_reply: str = "я правда рад, что ты написал") -> dict[str, object]:
    return {"content": f"Боб-старший: привет\nbob: {bob_reply}"}


def _heart_event() -> BobMessageReaction:
    return BobMessageReaction(
        chat_id=_CHAT_ID,
        message_id=_BOB_MESSAGE_ID,
        emoji_added=(_HEART,),
        emoji_removed=(),
        reactor_sender_id=_REACTOR_ID,
        reactor_name="Боб-старший",
    )


# --- US-2: same emoji, opposite MEANING -> opposite effects (not an emoji table) ------


async def test_same_emoji_warm_meaning_lifts_and_warms() -> None:
    state = PersonalityState(soul=_soul(mood=Mood(valence=0.0)))
    uc, rels, _mem, note = _build(meaning=_warm(), state=state, episode=_episode())

    await uc.perceive(_heart_event())

    assert state.soul.mood.valence > 0.0  # зашло -> lifts
    assert rels.saved[-1].warmth > 0.0  # warms toward the reactor
    assert note.recorded  # a being-received moment


async def test_same_emoji_dismissive_meaning_dips_and_cools() -> None:
    # The SAME ❤ emoji, but the judge read it as a cold/dismissive moment: the effect
    # flips negative. Proof the sign comes from MEANING, never the emoji.
    state = PersonalityState(soul=_soul(mood=Mood(valence=0.3)))
    uc, rels, _mem, note = _build(
        meaning=_dismissive(), state=state, episode=_episode(), rel_warmth=0.3
    )

    await uc.perceive(_heart_event())

    assert state.soul.mood.valence < 0.3  # не зашло -> dips
    assert rels.saved[-1].warmth < 0.3  # cools toward the reactor
    assert note.recorded == []  # not a being-received moment


async def test_same_emoji_drives_opposite_warmth_by_meaning() -> None:
    # Side-by-side on identical emoji + identical starting warmth: the two readings move
    # warmth in OPPOSITE directions — a table could not produce this.
    warm_state = PersonalityState(soul=_soul(mood=Mood(valence=0.0)))
    cold_state = PersonalityState(soul=_soul(mood=Mood(valence=0.0)))
    warm_uc, warm_rels, *_ = _build(
        meaning=_warm(), state=warm_state, episode=_episode(), rel_warmth=0.2
    )
    cold_uc, cold_rels, *_ = _build(
        meaning=_dismissive(), state=cold_state, episode=_episode(), rel_warmth=0.2
    )

    await warm_uc.perceive(_heart_event())
    await cold_uc.perceive(_heart_event())

    assert warm_rels.saved[-1].warmth > 0.2 > cold_rels.saved[-1].warmth


# --- US-1: the per-person memory line shape (excerpt + graceful degradation) ----------


async def test_long_reply_is_excerpted_in_the_memory_line() -> None:
    # A long Bob reply is trimmed to a short single-line excerpt (ellipsis) so the
    # memory line stays compact — covers the truncation branch.
    long_reply = "это очень длинный ответ про кофе " * 6  # > 60 chars
    state = PersonalityState(soul=_soul(mood=Mood(valence=0.0)))
    uc, _rels, mem, _note = _build(
        meaning=_warm(), state=state, episode=_episode(bob_reply=long_reply)
    )

    await uc.perceive(_heart_event())

    content = str(mem.episodes[0]["content"])
    assert "…" in content  # the excerpt was truncated
    assert "его тронуло" in content
    assert _HEART in content


async def test_oddly_shaped_episode_without_bob_marker_degrades_gracefully() -> None:
    # An episode row missing the "\nbob: " marker (unusual shape) must not crash — the
    # whole content is used as the best-effort reply text.
    state = PersonalityState(soul=_soul(mood=Mood(valence=0.0)))
    uc, _rels, mem, _note = _build(
        meaning=_warm(),
        state=state,
        episode={"content": "просто какой-то текст без маркера"},
    )

    await uc.perceive(_heart_event())  # must not raise

    assert mem.episodes  # an episode was still saved
    assert "его тронуло" in str(mem.episodes[0]["content"])


# --- US-6 / regression: every effect stays inside the BOB-030 band (no swings) --------


@pytest.mark.parametrize("start", [-0.95, 0.0, 0.95])
async def test_warm_reaction_never_swings_outside_the_band(start: float) -> None:
    state = PersonalityState(soul=_soul(mood=Mood(valence=start)))
    uc, rels, *_ = _build(
        meaning=_warm(), state=state, episode=_episode(), rel_warmth=0.95
    )

    await uc.perceive(_heart_event())

    assert -1.0 <= state.soul.mood.valence <= 1.0
    assert -1.0 <= rels.saved[-1].warmth <= 1.0
