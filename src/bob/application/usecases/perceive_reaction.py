# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases
# beadloom:layer=application

"""PerceiveReaction — Bob feels a reaction on one of his own messages (BOB-050).

The application heart of the feature: it subscribes to the
:class:`~bob.kernel.events.BobMessageReaction` event, looks up what Bob
SAID (by ``bob_message_id``), asks the injected
:class:`~bob.personality.reaction_meaning.ReactionJudge` what the reaction
MEANS on that message from that person, and lets the meaning change him — bounded,
along the BOB-033 social-contagion path:

* **Mood** — a warm reaction lifts (displacing accumulated low), a cold/withdrawn one
  dips, all inside the BOB-030 band (no swings).
* **Relationship** (BOB-014) — a bounded warmth nudge toward the reactor.
* **Memory** (BOB-045) — a per-person episode «<кто> отреагировал <emoji> на моё
  „<кратко>" — <смысл>», keyed to the REACTOR so Bob can recall it later.
* **Being received** — when the meaning is worth acknowledging, a light durable note
  the rare-aloud hint (BOB-050 .3) reads.

🔴 **Decorative / optional.** The WHOLE path is wrapped so any failure (judge error,
missing message, store error) is caught and DROPPED silently — it is never essential,
never triggers a GUPPI outage notice, and never blocks Bob's normal replies. An
ANONYMOUS reaction (no reactor id) gets a light "someone reacted" mood lift only — no
per-person memory or relationship (there is no who). 🔴 **Authz (BOB-019):** a guest
reacting is felt and remembered keyed to the GUEST; this path writes no owner facts
and leaks no owner-private material (it is about Bob's OWN message).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.kernel.relationship import Relationship
from bob.personality.mood import MoodDelta
from bob.personality.reaction_effect import (
    NotableReaction,
    apply_reaction_to_mood,
    nudge_relationship_warmth,
)
from bob.personality.reaction_meaning import ReactionContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.kernel.events import BobMessageReaction
    from bob.kernel.interlocutor import Interlocutor
    from bob.kernel.ports import Clock
    from bob.personality.disposition import Disposition
    from bob.personality.ports import NotableReactionStore
    from bob.personality.reaction_meaning import ReactionJudge, ReactionMeaning
    from bob.personality.state import PersonalityState
    from bob.social.ports import RelationshipStore

logger = logging.getLogger(__name__)

# A light, fixed lift for an ANONYMOUS reaction (no who): Bob feels received, but
# without a person there is no memory or relationship to move. Small and bounded.
_ANON_VALENCE_LIFT = 0.05
_ANON_SOCIAL_LIFT = 0.05

# How much of Bob's reply to keep in the memory line / being-received excerpt.
_EXCERPT_LIMIT = 60

# The marker separating the speaker prefix from Bob's reply in an episode's content.
_BOB_REPLY_MARKER = "\nbob: "


class BobMessageLookup(Protocol):
    """Read seam: find the episode that recorded one of Bob's outgoing messages."""

    async def episode_by_bob_message_id(
        self, bob_message_id: int
    ) -> Mapping[str, object] | None: ...


class ReactionMemoryWriter(Protocol):
    """Write seam: append the per-person episode about a received reaction (BOB-045)."""

    async def save_episode(self, episode: Mapping[str, object]) -> None: ...


class ReactorResolver(Protocol):
    """Perception seam: resolve a reactor's id+name into an Interlocutor (BOB-019)."""

    async def resolve(
        self, *, sender_id: int | None, sender_name: str | None, chat_id: int
    ) -> Interlocutor: ...


class PerceiveReaction:
    """Feel a reaction on one of Bob's messages — decorative, bounded, per-person."""

    def __init__(
        self,
        *,
        judge: ReactionJudge,
        lookup: BobMessageLookup,
        resolver: ReactorResolver,
        state: PersonalityState,
        relationships: RelationshipStore,
        memory: ReactionMemoryWriter,
        notable: NotableReactionStore,
        clock: Clock,
        disposition: Disposition,
    ) -> None:
        self._judge = judge
        self._lookup = lookup
        self._resolver = resolver
        self._state = state
        self._relationships = relationships
        self._memory = memory
        self._notable = notable
        self._clock = clock
        self._disposition = disposition

    async def perceive(self, event: BobMessageReaction) -> None:
        """Perceive ``event`` — 🔴 decorative: any failure is caught and dropped.

        Never raises into the bus: the whole perception is optional flavour, so a
        judge error, a missing message, or a store failure is logged and dropped (it
        must never trip a GUPPI outage notice or break Bob's normal replies).
        """
        try:
            await self._perceive(event)
        except Exception:
            logger.exception(
                "perceiving reaction on message %s dropped (decorative)",
                event.message_id,
            )

    async def _perceive(self, event: BobMessageReaction) -> None:
        """The real perception (wrapped by :meth:`perceive` so failure is dropped)."""
        if event.reactor_sender_id is None:
            # Anonymous "someone reacted": a light mood lift only — no who, so no
            # per-person memory or relationship (authz/defensive degradation).
            self._apply_anonymous_lift()
            return
        episode = await self._lookup.episode_by_bob_message_id(event.message_id)
        if episode is None:
            return  # not Bob's message (old / gone) — soft skip
        bob_text = _bob_reply_text(episode)
        emoji = _primary_emoji(event)
        reactor = await self._resolver.resolve(
            sender_id=event.reactor_sender_id,
            sender_name=event.reactor_name,
            chat_id=event.chat_id,
        )
        rel = await self._relationships.load(event.reactor_sender_id)
        warmth = rel.warmth if rel is not None else None
        ctx = ReactionContext(
            emoji=_reaction_emoji(event),
            added=bool(event.emoji_added),
            bob_message_text=bob_text,
            reactor=reactor,
            reactor_warmth=warmth,
            recent_thread="",
        )
        meaning = await self._judge.interpret(ctx)
        self._apply_mood(meaning)
        await self._nudge_relationship(event.reactor_sender_id, rel, meaning)
        await self._remember(event, reactor, emoji, bob_text, meaning)
        if meaning.worth_acknowledging:
            await self._note_being_received(event, reactor, emoji, bob_text, meaning)

    def _apply_anonymous_lift(self) -> None:
        """Apply the small fixed "someone reacted" lift to Bob's shared mood state."""
        soul = self._state.soul
        delta = MoodDelta(valence=_ANON_VALENCE_LIFT, social=_ANON_SOCIAL_LIFT)
        self._state.soul = soul.with_mood(soul.mood.update(delta))

    def _apply_mood(self, meaning: ReactionMeaning) -> None:
        """Apply the meaning's bounded mood effect to Bob's shared in-memory state."""
        soul = self._state.soul
        new_mood = apply_reaction_to_mood(
            soul.mood,
            meaning,
            baseline=soul.mood_baseline,
            lift_rate=self._disposition.social_lift_rate(),
        )
        self._state.soul = soul.with_mood(new_mood)

    async def _nudge_relationship(
        self, sender_id: int, rel: Relationship | None, meaning: ReactionMeaning
    ) -> None:
        """Move Bob's warmth toward the reactor by the bounded nudge (BOB-014)."""
        current = rel if rel is not None else Relationship(sender_id=sender_id)
        await self._relationships.save(nudge_relationship_warmth(current, meaning))

    async def _remember(
        self,
        event: BobMessageReaction,
        reactor: Interlocutor,
        emoji: str,
        bob_text: str,
        meaning: ReactionMeaning,
    ) -> None:
        """Save the per-person episode about the reaction, keyed to the REACTOR."""
        excerpt = _excerpt(bob_text)
        content = (
            f"{reactor.display_name} отреагировал {emoji} на моё «{excerpt}» "
            f"— {meaning.interpretation}"
        )
        await self._memory.save_episode(
            {
                "ts": self._clock.now().isoformat(),
                "event_type": "reaction_received",
                "content": content,
                "mood_snapshot": self._state.soul.mood.tone(),
                "tags": "reaction",
                "sender_id": event.reactor_sender_id,
                "bob_message_id": event.message_id,
            }
        )

    async def _note_being_received(
        self,
        event: BobMessageReaction,
        reactor: Interlocutor,
        emoji: str,
        bob_text: str,
        meaning: ReactionMeaning,
    ) -> None:
        """Record the light durable "being-received" note for the .3 aloud hint."""
        await self._notable.record(
            NotableReaction(
                sender_id=event.reactor_sender_id,
                reactor_name=reactor.display_name,
                emoji=emoji,
                bob_excerpt=_excerpt(bob_text),
                interpretation=meaning.interpretation,
                at=self._clock.now(),
            )
        )


def _bob_reply_text(episode: Mapping[str, object]) -> str:
    """Extract Bob's reply text from an episode's ``content`` (best-effort).

    Episodes store ``"<sender>: <text>\\nbob: <reply>"`` (BOB-045); the part after the
    last ``bob:`` marker is what Bob said. Falls back to the whole content if the
    marker is absent (an unusually-shaped row).
    """
    content = str(episode.get("content", ""))
    marker = content.rfind(_BOB_REPLY_MARKER)
    if marker == -1:
        return content.strip()
    return content[marker + len(_BOB_REPLY_MARKER) :].strip()


def _reaction_emoji(event: BobMessageReaction) -> tuple[str, ...]:
    """Return the emoji that drives the meaning — the added ones, else the removed."""
    return event.emoji_added or event.emoji_removed


def _primary_emoji(event: BobMessageReaction) -> str:
    """Return a single representative emoji for the memory/being-received line."""
    emoji = _reaction_emoji(event)
    return emoji[0] if emoji else "?"


def _excerpt(text: str) -> str:
    """Trim Bob's reply to a short, single-line excerpt for a memory line."""
    flat = " ".join(text.split())
    if len(flat) <= _EXCERPT_LIMIT:
        return flat
    return flat[: _EXCERPT_LIMIT - 1].rstrip() + "…"
