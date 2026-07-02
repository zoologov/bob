# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory

"""Immutable memory entities — episodic events and semantic facts.

Pure domain value objects with no I/O. The persistence adapter translates these
to and from SQLite rows; the domain never sees a database. Timestamps are
timezone-aware (sourced from the injected :class:`~bob.domain.ports.Clock`), and
confidence is a ``[0, 1]`` probability — both invariants are enforced at
construction so an invalid record can never exist in memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

# Confidence is a probability in the closed unit interval.
_MIN_CONFIDENCE = 0.0
_MAX_CONFIDENCE = 1.0


def _require_aware(ts: datetime) -> None:
    """Reject naive datetimes — all memory timestamps must be timezone-aware."""
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError("memory timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EpisodicEvent:
    """One thing that happened on the timeline (a message, a tick, an action).

    Episodic memory is the append-only log of lived experience; ``mood_snapshot``
    captures Bob's mood at the moment, and ``tags`` are free-form labels for
    later recall. ``sender_id`` attributes the turn to the interlocutor it is with
    (BOB-045 per-person memory) — ``None`` for a turn with no sender (a tick, a
    digest, a legacy row). ``bob_message_id`` is the Telegram message_id of Bob's
    own outgoing reply for this turn (BOB-050), so a later reaction can be linked
    back to what Bob said; ``None`` when Bob sent no message.
    """

    ts: datetime
    event_type: str
    content: str
    mood_snapshot: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    sender_id: int | None = None
    bob_message_id: int | None = None

    def __post_init__(self) -> None:
        _require_aware(self.ts)


@dataclass(frozen=True, slots=True)
class SemanticFact:
    """A distilled, durable fact Bob believes (a preference, a relationship cue).

    Unlike an episode (a timestamped event), a fact is knowledge with a
    ``confidence`` in ``[0, 1]`` and a ``category`` for grouping.
    """

    ts: datetime
    category: str
    content: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        _require_aware(self.ts)
        if not _MIN_CONFIDENCE <= self.confidence <= _MAX_CONFIDENCE:
            raise ValueError(
                f"confidence must be within [{_MIN_CONFIDENCE}, {_MAX_CONFIDENCE}], "
                f"got {self.confidence}"
            )
