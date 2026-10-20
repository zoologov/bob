# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=domain

"""Personality ports — the durable stores + seams behind Bob's character.

The per-persona fascination store and the light notable-reaction store, plus the
react-only seam (:class:`MessageReactor`) and the leak-inner-life reader
(:class:`ReflectionReader`). These are *interfaces only*: structural
:class:`typing.Protocol` definitions with no implementations; the SQLite-backed
adapters live in ``bob.personality.adapters``. The negotiation-zone classifier
(:class:`~bob.conversation.ports.ZoneClassifier`) moved to :mod:`bob.conversation.ports`
(a turn decision, BOB-062.6a); the social identity stores moved to
:mod:`bob.social.ports` (BOB-062.5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.personality.fascination import Fascination
    from bob.personality.reaction_effect import NotableReaction


@runtime_checkable
class MessageReactor(Protocol):
    """Set a native reaction on a received message (the react-only seam, BOB-018).

    On a :data:`~bob.personality.expression.ExpressionMode.REACT_ONLY` turn
    Bob acknowledges with a single emoji reaction *instead of* composing a reply —
    cheap, no LLM. The Telegram realisation calls ``set_message_reaction``; the
    ``emoji`` is always one Bob picked from the standard reaction set
    (:func:`~bob.personality.reaction.reaction_emoji_for`). The reaction is
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

    On a :data:`~bob.personality.expression.ExpressionPlan.leak_inner_life`
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

    Round-trips the :class:`bob.personality.fascination.Fascination` Bob is
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


class CurrentFascinationReader(Protocol):
    """Read seam: Bob's CURRENT fascination, aged and still-alive (BOB-020 wave 2).

    On a :data:`~bob.personality.expression.ExpressionPlan.mention_fascination`
    turn the compose path folds the topic in so Bob can drop it à propos — but only a
    REAL, persisted passion that has not yet faded. ``None`` means Bob has no current
    fascination, so the mention no-ops (never a fabricated interest). The concrete
    adapter loads the :class:`~bob.personality.ports.FascinationStore`, ages the stored
    passion against the clock, and drops a faded one.
    """

    async def current_fascination(self) -> Fascination | None:
        """Return Bob's current, non-faded fascination, or ``None`` if there is none."""
        ...


@runtime_checkable
class NotableReactionStore(Protocol):
    """Light durable store for the most recent "being-received" reaction (BOB-050).

    When someone reacts to one of Bob's messages in a way worth acknowledging, the
    perceiving use-case records a :class:`bob.personality.reaction_effect.NotableReaction`
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
