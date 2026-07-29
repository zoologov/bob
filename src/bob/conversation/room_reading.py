# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Reflective «read the room» seam — its value types and port (BOB-066 Срез 2.2).

Bob is a living, equal participant in a multi-party thread — not a switchboard and
not a scripted bot. On a PERIPHERY turn (nothing addressed straight at him) he should
*read the room* the way a person does: understand the situation, who is talking to
whom, the room's mood, and — as character — whether to speak, react, stay quiet, or
go look something up. This module defines the shape of that ONE rich reflective read
and the seam through which it is made. It mirrors the response-judgment seam (BOB-049)
one-for-one, but is a distinct, richer Tier-1 pass beside it (the RFC «новый компонент
рядом с судьёй»).

* :class:`ReflectiveIntent` — REPLY / REACT / IGNORE / INITIATE / SELF_CHECK: what Bob
  chooses to do about the room this turn (verbalised by the LLM; the pure verdict core
  in :mod:`~bob.conversation.room_verdict` maps it to the outcome).
* :class:`RoomMood` — the room's overall mood, a single token carrying a ``valence``
  (negative..positive) and a ``polarization`` (how split/heated) as primitives — the
  numbers later slices consume BY VALUE in the tone (no personality import here).
* :class:`RoomReading` — the immutable OUTCOME of one read: the situation, the pairings,
  the room mood, the intent, an optional addressee, a ``salience`` («стоит ли влезть»),
  an optional REACT emoji, a ``wants_web`` autonomous-lookup flag (C11), and a short
  reason (logs only, never shown to the user).
* :class:`RoomReadingContext` — the immutable INPUT: the message, the sender as social
  context, the SHARED author-labelled thread (BOB-058), the mood tone, the structural
  HINTS (addressivity / mention / reply / others-present / floor + the floor-по-говорящему
  hints ``floor_holder`` / ``floor_participant`` from Срез 1.2) and ``interest`` (by
  value). Every field is a signal the reflection weighs — none forces the outcome.
* :class:`RoomReader` — the injectable port: ``read(ctx) -> RoomReading``. A Tier-1 LLM
  realisation lives in infrastructure; tests inject a fake for determinism.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.conversation.addressivity import Addressivity
    from bob.social.interlocutor import Interlocutor

__all__ = [
    "ReflectiveIntent",
    "RoomMood",
    "RoomReader",
    "RoomReading",
    "RoomReadingContext",
]


class ReflectiveIntent(StrEnum):
    """What Bob chooses to do about the room this turn (verbalised by the LLM).

    * :data:`REPLY` — say something in words (join / answer the ambient thread).
    * :data:`REACT` — set a meaning-chosen emoji reaction instead of words.
    * :data:`IGNORE` — stay silent (read it, nothing to add).
    * :data:`INITIATE` — proactively start a line (in a REACTIVE turn this collapses to a
      barge-in REPLY; true self-initiation without an inbound is a separate proactivity
      seam).
    * :data:`SELF_CHECK` — turn inward (metacognition) rather than speak — in a reactive
      turn there is no outward action, so the verdict core reads it as silence.
    """

    REPLY = "reply"
    REACT = "react"
    IGNORE = "ignore"
    INITIATE = "initiate"
    SELF_CHECK = "self_check"


class RoomMood(StrEnum):
    """The room's overall mood — one token carrying primitive valence + polarization.

    ``valence`` runs negative..positive (how warm/positive the room feels);
    ``polarization`` runs calm..split (how heated/divided it is). Both are exposed as
    plain floats so a LATER slice (2.4) can feed them BY VALUE into the personality tone
    without importing this module — keeping the personality↔conversation boundary a
    one-way, value-only edge.
    """

    PLAYFUL = "playful"
    WARM = "warm"
    NEUTRAL = "neutral"
    SOMBRE = "sombre"
    TENSE = "tense"
    HEATED = "heated"

    @property
    def valence(self) -> float:
        """The room's warmth as a primitive in ``[-1, 1]`` (negative..positive)."""
        return _MOOD_VALENCE[self]

    @property
    def polarization(self) -> float:
        """How split/heated the room is as a primitive in ``[0, 1]`` (calm..divided)."""
        return _MOOD_POLARIZATION[self]


# The mood → (valence, polarization) tables. Pure domain constants (a room mood maps to
# the two primitives later slices consume by value); kept beside the enum so the mapping
# is total and mutation-tested against the enum members.
_MOOD_VALENCE: dict[RoomMood, float] = {
    RoomMood.PLAYFUL: 0.8,
    RoomMood.WARM: 0.6,
    RoomMood.NEUTRAL: 0.0,
    RoomMood.SOMBRE: -0.5,
    RoomMood.TENSE: -0.4,
    RoomMood.HEATED: -0.7,
}

_MOOD_POLARIZATION: dict[RoomMood, float] = {
    RoomMood.PLAYFUL: 0.1,
    RoomMood.WARM: 0.1,
    RoomMood.NEUTRAL: 0.0,
    RoomMood.SOMBRE: 0.2,
    RoomMood.TENSE: 0.7,
    RoomMood.HEATED: 0.9,
}


@dataclass(frozen=True, slots=True)
class RoomReading:
    """The immutable outcome of one reflective «read the room» (BOB-066 Срез 2.2).

    ``situation`` is a short phrase of what is going on; ``pairings`` names who is
    talking to whom (author-labelled, participant-agnostic — a replica-Bob is just
    another author). ``room_mood`` carries the room's valence/polarization. ``intent``
    is what Bob chooses to do; ``addressee_id`` is who he'd address (for the floor pass /
    reply-to), or ``None``. ``salience`` in ``[0, 1]`` is «стоит ли влезть». ``emoji`` is
    set only on a REACT intent (validated against the free-reaction set). ``wants_web`` is
    the autonomous-lookup flag (C11) that forces the existing verify pass. ``reason`` is a
    short "why" for logs/transparency — internal, never surfaced to the user.
    """

    situation: str
    pairings: tuple[str, ...]
    room_mood: RoomMood
    intent: ReflectiveIntent
    addressee_id: int | None
    salience: float
    emoji: str | None
    wants_web: bool
    reason: str


@dataclass(frozen=True, slots=True)
class RoomReadingContext:
    """The immutable input to a reflective read (context + hints, not rules).

    Carries the meaning the reflection weighs: the ``text`` of the inbound; the
    ``interlocutor`` as social context (NOT an override); the SHARED author-labelled
    ``recent_thread`` (BOB-058); the ``mood_tone`` descriptor; the structural HINTS
    (``mentions_bob``, ``reply_to_bob``, ``addressivity`` class, ``others_present``,
    ``floor_engaged``) plus the floor-по-говорящему hints (``floor_holder`` — who holds
    the live floor, e.g. ``"bob"``/``"other"``/``"idle"``/``"none"``; ``floor_participant``
    — whether THIS sender belongs to Bob's live exchange, Срез 1.2); and ``interest`` (how
    interesting the topic is to Bob, a primitive passed BY VALUE — no personality import).
    Every field is a signal the reflection interprets — none forces an outcome.
    """

    text: str
    interlocutor: Interlocutor
    recent_thread: str
    mood_tone: str
    addressivity: Addressivity
    mentions_bob: bool
    reply_to_bob: bool
    others_present: bool
    floor_engaged: bool
    floor_holder: str
    floor_participant: bool
    interest: float


@runtime_checkable
class RoomReader(Protocol):
    """The seam: read the room, by meaning, and return the reflective :class:`RoomReading`.

    Injectable so the read is deterministic in tests (a fake returns a scripted
    :class:`RoomReading`) and swappable in tier (a rich Tier-1 realisation lives in
    infrastructure) without touching any consumer.
    """

    async def read(self, ctx: RoomReadingContext) -> RoomReading:
        """Weigh ``ctx`` and return the chosen :class:`RoomReading`."""
        ...
