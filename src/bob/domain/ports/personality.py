# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Personality ports — the durable stores + seams behind Bob's character.

Per-persona / per-sender stores for fascination, first impressions, relationships,
notable reactions, and обида (sulk), plus the react-only seam
(:class:`MessageReactor`), the leak-inner-life reader (:class:`ReflectionReader`),
and the negotiation-zone classifier (:class:`ZoneClassifier`). These are
*interfaces only*: structural :class:`typing.Protocol` definitions with no
implementations; the SQLite-backed adapters live in ``bob.infrastructure``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.domain.personality.fascination import Fascination
    from bob.domain.personality.first_impression import FirstImpression
    from bob.domain.personality.negotiation import NegotiationZone
    from bob.domain.personality.reaction_effect import NotableReaction
    from bob.domain.personality.relationship import Relationship
    from bob.domain.personality.sulk import SulkState
    from bob.domain.personality.taste import Verdict


@runtime_checkable
class MessageReactor(Protocol):
    """Set a native reaction on a received message (the react-only seam, BOB-018).

    On a :data:`~bob.domain.personality.expression.ExpressionMode.REACT_ONLY` turn
    Bob acknowledges with a single emoji reaction *instead of* composing a reply —
    cheap, no LLM. The Telegram realisation calls ``set_message_reaction``; the
    ``emoji`` is always one Bob picked from the standard reaction set
    (:func:`~bob.domain.personality.reaction.reaction_emoji_for`). The reaction is
    **best-effort**: an adapter MUST degrade gracefully (a textual ack, or a no-op)
    on any transport error and never raise into the caller, so a failed reaction
    can never break a turn.
    """

    async def react(self, *, chat_id: int, message_id: int, emoji: str) -> None:
        """React to ``message_id`` in ``chat_id`` with ``emoji`` (best-effort)."""
        ...


@runtime_checkable
class ReflectionReader(Protocol):
    """Read the text of Bob's most recent REAL reflection (the leak-inner-life seam).

    On a :data:`~bob.domain.personality.expression.ExpressionPlan.leak_inner_life`
    turn the compose path injects this text so Bob's reply carries a glimpse of what
    he caught himself thinking about — but only from a real, persisted reflection
    (an ``episodic_log`` row whose ``event_type`` is ``reflection`` or
    ``inner_monologue``, already grounded and in the persona language by BOB-012).
    There is NO fabrication: ``None`` means there is no real reflection on record, so
    the leak no-ops. The concrete adapter reads SQLite in ``bob.infrastructure``.
    """

    async def latest_reflection_text(self) -> str | None:
        """Return the most recent real reflection's text, or ``None`` if there is none."""
        ...


@runtime_checkable
class FascinationStore(Protocol):
    """Durable per-persona store for Bob's current fascination (BOB-020).

    Round-trips the :class:`bob.domain.personality.fascination.Fascination` Bob is
    into right now — the grounded topic, its decaying intensity, and when it took
    hold — so his current passion survives a restart and keeps evolving. State is
    per ``persona_id`` so Bobiverse replicas each keep their own. ``load`` returns
    ``None`` when Bob has no current fascination (a fresh persona, or one whose
    passion was retired and not yet replaced). The concrete SQLite-backed adapter
    lives in ``bob.infrastructure.persistence``.
    """

    async def load(self, persona_id: str) -> Fascination | None:
        """Return ``persona_id``'s current fascination, or ``None`` if there is none."""
        ...

    async def save(self, persona_id: str, fascination: Fascination) -> None:
        """Persist ``fascination`` for ``persona_id`` (replacing any prior one)."""
        ...


@runtime_checkable
class FirstImpressionStore(Protocol):
    """Durable per-sender store for Bob's LIGHT first impression (BOB-019).

    Round-trips the :class:`bob.domain.personality.first_impression.FirstImpression`
    Bob forms on first contact with a person — who (``sender_id``), when he first met
    them, and a short impression note — so a returning sender is *recognised*
    ("кажется, мы уже сталкивались"). Keyed by ``sender_id`` it covers owner / known /
    guest / bot alike; this is per-PERSON data (about them), NOT owner-private memory,
    so it is allowed even for a guest. ``load`` returns ``None`` for an unseen sender;
    ``save`` records once and never overwrites a known sender (the impression is formed
    on first contact). The deliberately minimal foundation for multi-party BOB-014, not
    that engine. The concrete SQLite-backed adapter lives in ``bob.infrastructure``.
    """

    async def load(self, sender_id: int) -> FirstImpression | None:
        """Return ``sender_id``'s first impression, or ``None`` if there is none."""
        ...

    async def save(self, impression: FirstImpression) -> None:
        """Record ``impression`` once — a known sender is never overwritten."""
        ...


@runtime_checkable
class RelationshipStore(Protocol):
    """Durable per-sender store for Bob's relationship quality (BOB-014).

    Round-trips the :class:`bob.domain.personality.relationship.Relationship` Bob has
    with each person — the four bounded axes (trust / respect / warmth /
    compatibility) — so a relationship accrued over many turns survives a restart and
    keeps shaping his tone + willingness to compromise. Keyed by ``sender_id`` it
    covers owner / known / guest / bot alike; this is per-PERSON data (about THEM),
    NOT owner-private memory, so it is allowed even for a guest. ``load`` returns
    ``None`` for an unknown sender (Bob has formed no read on them yet). Unlike the
    formed-once :class:`FirstImpressionStore`, ``save`` UPSERTs — a relationship
    evolves, so each turn re-saves the newer state. The concrete SQLite-backed adapter
    lives in ``bob.infrastructure``.
    """

    async def load(self, sender_id: int) -> Relationship | None:
        """Return ``sender_id``'s relationship, or ``None`` if there is none yet."""
        ...

    async def save(self, relationship: Relationship) -> None:
        """Persist ``relationship`` (UPSERT — an evolving relationship is updated)."""
        ...


@runtime_checkable
class NotableReactionStore(Protocol):
    """Light durable store for the most recent "being-received" reaction (BOB-050).

    When someone reacts to one of Bob's messages in a way worth acknowledging, the
    perceiving use-case records a :class:`bob.domain.personality.reaction_effect.NotableReaction`
    here; the rare-aloud hint (BOB-050 .3) reads the latest one so Bob can naturally
    mention being received. Deliberately tiny — a single most-recent record, not a
    log — and per-PERSON about Bob's OWN message, never owner-private material.
    :meth:`latest` returns ``None`` when nothing notable is on record. The concrete
    SQLite-backed adapter lives in ``bob.infrastructure``.
    """

    async def record(self, note: NotableReaction) -> None:
        """Persist ``note`` as the most recent being-received reaction (overwrites)."""
        ...

    async def latest(self) -> NotableReaction | None:
        """Return the most recent recorded reaction, or ``None`` if there is none."""
        ...

    async def clear(self) -> None:
        """Consume the recorded reaction so the rare-aloud hint surfaces it at most once."""
        ...


@runtime_checkable
class SulkStore(Protocol):
    """Durable per-persona store for Bob's обида state (BOB-014 .2b).

    Round-trips the :class:`bob.domain.personality.sulk.SulkState` Bob carries — the
    active flag, the decaying intensity, the low/hostile streak, the entry stamp, and
    the one-shot ``announced`` flag — so an обида (and its recovery progress) survives
    a restart. State is per ``persona_id`` so Bobiverse replicas each keep their own.
    ``load`` returns the fresh, not-sulking default for an unseen persona, so the
    application always has something to read. Crucially this carries NO memory and NO
    soul (anti-Exodus) — only the affect state. The concrete SQLite-backed adapter
    lives in ``bob.infrastructure.persistence``.
    """

    async def load(self, persona_id: str) -> SulkState:
        """Return the persisted обида state for ``persona_id`` (fresh if unseen)."""
        ...

    async def save(self, persona_id: str, state: SulkState) -> None:
        """Persist ``state`` for ``persona_id`` (replacing any prior обида state)."""
        ...


@runtime_checkable
class ZoneClassifier(Protocol):
    """Classify a topic into a :class:`NegotiationZone` for Bob's stance.

    Decides *who owns the matter at hand* — Bob's own territory of opinions
    (``BOB_PERSONAL``), the user's own business (``USER_DOMAIN``), or jointly
    owned (``SHARED``) — so :class:`Negotiation` can pick how firmly Bob holds.
    The contract is abstract on purpose: the default realisation is a
    deterministic taste/keyword heuristic, but a Tier-0 LLM classifier swaps in
    later without any consumer change.
    """

    def classify(
        self,
        topic: str,
        *,
        taste_verdict: Verdict,
        conviction: float,
    ) -> NegotiationZone:
        """Return the negotiation zone that owns ``topic``."""
        ...
