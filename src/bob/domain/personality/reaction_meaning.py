# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality

"""Reaction-judgment seam — its value types and port (BOB-050).

The mirror of the response-judgment seam (BOB-049) for the OTHER direction: when
someone reacts to one of Bob's OWN messages, Bob should *understand* — as a person,
in context — what that reaction MEANS on that message from that person, not look the
emoji up in a table. This module defines the shape of that one semantic judgment and
the seam through which it is made.

* :class:`ReactionContext` — the immutable INPUT: the emoji(s) involved, whether
  the reaction was ADDED or REMOVED, the TEXT of Bob's message it landed on, the
  reactor as social context (:class:`~bob.social.interlocutor.Interlocutor`
  + their current warmth with Bob), and a light thread snippet. Everything the judge
  weighs by meaning — the emoji is a signal, never a lookup key.
* :class:`ReactionMeaning` — the immutable OUTCOME: a short ``interpretation`` (for
  memory/log), a bounded ``mood_delta`` whose sign+magnitude come FROM THE MEANING
  (not the emoji), a bounded ``warmth_nudge`` toward the reactor, and
  ``worth_acknowledging`` (whether this is a moment Bob might mention aloud later).
* :class:`ReactionJudge` — the injectable port: ``interpret(ctx) -> ReactionMeaning``.
  A Tier-0 LLM realisation lives in infrastructure; tests inject a fake for
  determinism.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.domain.personality.mood import MoodDelta
    from bob.social.interlocutor import Interlocutor

__all__ = [
    "ReactionContext",
    "ReactionJudge",
    "ReactionMeaning",
]


@dataclass(frozen=True, slots=True)
class ReactionContext:
    """The immutable input to a reaction judgment (context, not a lookup).

    Carries the meaning the judge weighs: the ``emoji`` involved (one or more); the
    ``added`` flag (``True`` = the reactor PLACED it, ``False`` = they REMOVED a
    reaction they had — a removal leans mildly negative/uncertain); the
    ``bob_message_text`` the reaction landed on (what was received); the ``reactor``
    as social context (owner / known / guest — NOT an override) plus their
    ``reactor_warmth`` (Bob's current warmth with them, ``None`` for a new person);
    and a light ``recent_thread`` snippet. Every field is a signal the judge
    interprets by meaning — none forces an outcome, and the emoji is never a table key.
    """

    emoji: tuple[str, ...]
    added: bool
    bob_message_text: str
    reactor: Interlocutor
    reactor_warmth: float | None
    recent_thread: str


@dataclass(frozen=True, slots=True)
class ReactionMeaning:
    """The immutable outcome of one reaction judgment (effects come from MEANING).

    ``interpretation`` is a short phrase naming what the reaction meant on that
    message from that person (folded into the per-person memory and logs).
    ``mood_delta`` is the bounded affective nudge whose sign and magnitude come from
    the MEANING, not the emoji (a warm read lifts, a dismissive or withdrawn one
    dips). ``warmth_nudge`` is the bounded move to Bob's warmth toward the reactor
    (someone who resonates → warmer). ``worth_acknowledging`` marks a moment notable
    enough that Bob might naturally mention being received aloud later (BOB-050 .3).
    """

    interpretation: str
    mood_delta: MoodDelta
    warmth_nudge: float
    worth_acknowledging: bool


@runtime_checkable
class ReactionJudge(Protocol):
    """The seam: understand, by meaning, what a reaction on Bob's message means.

    Injectable so the judgment is deterministic in tests (a fake returns a scripted
    :class:`ReactionMeaning`) and swappable in tier (a Tier-0 LLM here, a richer
    model later) without touching the perceiving use-case. The realisation RAISES on
    failure (it never returns a silent default): the perceiving path is decorative,
    so the caller drops a failed judgment rather than acting on a guess.
    """

    async def interpret(self, ctx: ReactionContext) -> ReactionMeaning:
        """Weigh ``ctx`` and return the chosen :class:`ReactionMeaning`."""
        ...
