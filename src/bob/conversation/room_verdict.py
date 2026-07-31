# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Reflective verdict core — map a :class:`RoomReading` to an outcome (BOB-066 Срез 2.2).

🔴 The load-bearing invariant of the whole reflective seam: *the LLM VERBALISES the read
(situation, mood, intent, salience, wants_web); THIS pure core DECIDES the verdict.* No
I/O, no RNG — a deterministic mapping the tests pin exactly (and mutation-test hard),
exactly as :func:`~bob.conversation.addressivity.decide_response` decides on the
legacy path. It reads ONLY the reading — every signal the reflection weighed is already
folded into it, so the core needs no extra addressivity state (which would be an
application type and a layer cycle).

Policy:

* ``salience`` below :data:`SALIENCE_THRESHOLD` → :data:`~VerdictKind.IGNORE` (ambient
  low-salience → silence), whatever the intent — Bob doesn't barge into a room he doesn't
  matter to this turn.
* Otherwise the intent decides: REACT → :data:`~VerdictKind.REACT` (+emoji); IGNORE /
  SELF_CHECK → :data:`~VerdictKind.IGNORE` (silence — SELF_CHECK is inward, no outward
  act); REPLY / INITIATE → :data:`~VerdictKind.REPLY` (INITIATE collapses to a barge-in
  reply in a reactive turn). ``wants_web`` rides a REPLY verdict as
  :attr:`~ReflectiveVerdict.force_web` (C11 — forces the EXISTING verify pass), and
  ``addressee_id`` rides it for the floor pass / reply-to.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from bob.conversation.room_reading import ReflectiveIntent, RoomReading

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "SALIENCE_THRESHOLD",
    "ReflectiveVerdict",
    "VerdictKind",
    "decide_batch",
    "decide_from_reading",
]

# The salience floor below which a periphery read stays silent. A read AT the threshold
# still engages (``<`` is strict) — the threshold is the «стоит ли влезть» bar, tuned
# conservative so Bob reads the room quietly far more often than he barges in.
SALIENCE_THRESHOLD = 0.35


class VerdictKind(StrEnum):
    """The outcome the reflective core commits to for this periphery turn.

    * :data:`REPLY` — compose+send (join the ambient thread / barge-in).
    * :data:`REACT` — set a meaning-chosen emoji reaction instead of words.
    * :data:`IGNORE` — stay silent (read it, nothing worth a word this turn).
    """

    REPLY = "reply"
    REACT = "react"
    IGNORE = "ignore"


@dataclass(frozen=True, slots=True)
class ReflectiveVerdict:
    """The immutable outcome of one reflective verdict (BOB-066 Срез 2.2).

    ``emoji`` is set only on a :data:`~VerdictKind.REACT` verdict; ``force_web`` is set
    only on a :data:`~VerdictKind.REPLY` verdict (forces the existing verify pass, C11);
    ``addressee_id`` is who a REPLY addresses (for the floor pass / reply-to), or ``None``.
    """

    kind: VerdictKind
    emoji: str | None
    force_web: bool
    addressee_id: int | None


# The silent verdict is a value (no per-instance state) — one shared object for every
# IGNORE outcome keeps the core allocation-free on the common periphery path.
_IGNORE = ReflectiveVerdict(
    kind=VerdictKind.IGNORE, emoji=None, force_web=False, addressee_id=None
)


def decide_from_reading(reading: RoomReading) -> ReflectiveVerdict:
    """Map a :class:`RoomReading` to a :class:`ReflectiveVerdict` — pure, deterministic.

    See the module docstring for the policy. The salience floor is checked FIRST, so an
    ambient read Bob doesn't matter to (low salience) stays silent no matter how the LLM
    labelled the intent.
    """
    if reading.salience < SALIENCE_THRESHOLD:
        return _IGNORE
    if reading.intent is ReflectiveIntent.REACT:
        return ReflectiveVerdict(
            kind=VerdictKind.REACT,
            emoji=reading.emoji,
            force_web=False,
            addressee_id=None,
        )
    if reading.intent in (ReflectiveIntent.IGNORE, ReflectiveIntent.SELF_CHECK):
        return _IGNORE
    # REPLY or INITIATE (a reactive INITIATE collapses to a barge-in reply).
    return ReflectiveVerdict(
        kind=VerdictKind.REPLY,
        emoji=None,
        force_web=reading.wants_web,
        addressee_id=reading.addressee_id,
    )


def decide_batch(readings: Sequence[RoomReading]) -> list[ReflectiveVerdict]:
    """Project each per-message reading of an ambient batch to its verdict (pure).

    The holistic stream-read (BOB-072) already made the SEMANTIC choice — for every message
    of the batch it verbalised a :class:`RoomReading` (reply / react / ignore, salience,
    emoji, addressee, wants_web). This core lifts :func:`decide_from_reading` over the whole
    batch, applying the SAME deterministic policy (salience floor first, then intent map) to
    each reading in arrival order — semantics live in the read, POLICY is this pure
    projection. An empty batch yields an empty plan. No I/O, no RNG (the mutation-tested
    core, mirroring the single-message path one-for-one).
    """
    return [decide_from_reading(reading) for reading in readings]
