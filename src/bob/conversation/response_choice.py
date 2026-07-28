# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Response-judgment seam — its value types and port (BOB-049).

Bob is a person, not a switchboard: on every inbound he should *understand* the
message in context and choose — as character — how to respond socially. This
module defines the shape of that one semantic judgment and the seam through which
it is made, replacing the if/else addressivity ladder
(:func:`~bob.conversation.addressivity.decide_response`) with a single
meaning-based decision that holds for ANY interlocutor (owner / friend / guest).

* :class:`ResponseIntent` — REPLY / REACT / IGNORE: answer in words, set a
  meaning-chosen emoji reaction, or stay silent.
* :class:`ResponseChoice` — the immutable outcome: intent, an optional emoji
  (set on REACT), and a short reason (for logs/transparency, never shown to the
  user).
* :class:`ResponseContext` — the immutable INPUT to the judgment: the message,
  the sender as social context, the recent per-person thread, structural HINTS
  (mentions / reply / addressivity class / others-present / floor) and the mood
  tone. The structural signals are inputs the judge weighs by meaning — never
  overriding rules (there is no ``is_owner -> reply`` shortcut here).
* :class:`ResponseJudge` — the injectable port: ``decide(ctx) -> ResponseChoice``.
  A Tier-0 LLM realisation lives in infrastructure; tests inject a fake for
  determinism.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.conversation.addressivity import Addressivity
    from bob.social.interlocutor import Interlocutor

__all__ = [
    "ResponseChoice",
    "ResponseContext",
    "ResponseIntent",
    "ResponseJudge",
]


class ResponseIntent(StrEnum):
    """How Bob chooses to respond socially to one inbound (decided by meaning).

    * :data:`REPLY` — answer in words (the existing compose+send path).
    * :data:`REACT` — set a meaning-chosen emoji reaction instead of replying
      (read it, marked presence, no words).
    * :data:`IGNORE` — stay silent (read it, no answer expected).
    """

    REPLY = "reply"
    REACT = "react"
    IGNORE = "ignore"


@dataclass(frozen=True, slots=True)
class ResponseChoice:
    """The immutable outcome of one response judgment.

    ``emoji`` is set only when ``intent`` is :data:`ResponseIntent.REACT` (chosen
    by meaning, validated against the Telegram free-reaction set); it is ``None``
    for REPLY/IGNORE. ``reason`` is a short "why" for logs/transparency — internal,
    never surfaced to the user.
    """

    intent: ResponseIntent
    emoji: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class ResponseContext:
    """The immutable input to a response judgment (context + hints, not rules).

    Carries the meaning the judge weighs: the ``text`` of the inbound; the
    ``interlocutor`` as social context (owner / known / guest / bot — NOT an
    override); the ``recent_thread`` per-person snippet (BOB-045); the structural
    HINTS (``mentions_bob``, ``reply_to_bob``, ``addressivity`` class,
    ``others_present``, ``floor_engaged``); and the ``mood_tone`` descriptor.
    Every field is a signal the judge interprets — none forces an outcome.
    """

    text: str
    interlocutor: Interlocutor
    recent_thread: str
    mentions_bob: bool
    reply_to_bob: bool
    addressivity: Addressivity
    others_present: bool
    floor_engaged: bool
    mood_tone: str


@runtime_checkable
class ResponseJudge(Protocol):
    """The seam: decide, by meaning, how Bob responds to one inbound.

    Injectable so the decision is deterministic in tests (a fake returns a
    scripted :class:`ResponseChoice`) and swappable in tier (a Tier-0 LLM here,
    a Tier-1 model later) without touching any consumer.
    """

    async def decide(self, ctx: ResponseContext) -> ResponseChoice:
        """Weigh ``ctx`` and return the chosen :class:`ResponseChoice`."""
        ...
