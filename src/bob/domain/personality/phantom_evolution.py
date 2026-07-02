# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality

"""Phantom-preference evolution — the pure kernel that lets Bob's symphonies drift.

Bob's phantom preferences (``SOUL.phantom_prefs`` — кофе, дождь, книги…) are not a
frozen tuple: they come alive and shift *slowly* over time. A new symphony emerges
from a real strong taste or fresh reflection; an old one fades. This module is the
pure membership kernel that decides the next set — the application layer supplies
the grounded ``candidate`` and drives it on a rare cadence.

The discipline mirrors :mod:`bob.domain.personality.taste_evolution` (BOB-013):

* **Grounded, never fabricated** — emergence only ever admits the ``candidate`` the
  caller derived from Bob's REAL inner life (a strong taste topic / recent
  reflection). With no candidate there is no change: Bob never invents a preference.
* **Slow** — a membership change is gated behind a small per-step probability draw
  on the injected, seeded RNG, so most steps leave the set untouched.
* **Bounded** — the set never grows past ``max_count``; when a fresh phantom would
  overflow it, the oldest (front of the tuple) fades to make room (one in, one out).
* **At most one change per step** — never more than a single addition (plus, only on
  overflow, the matching eviction).
* **Idempotent** — a candidate already present is a no-op, so a re-run in the same
  period (the same already-grounded candidate) causes no churn.

Pure and deterministic: no I/O, no LLM, no clock — only the membership tuple, the
:class:`PhantomSignals`, and a seeded RNG in, a new membership tuple out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from random import Random

# Per-step probability that a grounded candidate actually emerges. Small on purpose
# (slow membership drift, like the conservative learning rates of taste_evolution),
# so phantoms shift over many ticks rather than every one. Overridable by the caller
# via ``emotion.phantom.change_rate`` in config.
CHANGE_RATE = 0.2

# A sane default ceiling on how many phantom preferences Bob carries at once.
MAX_PHANTOMS = 5


@dataclass(frozen=True, slots=True)
class PhantomSignals:
    """The grounded inputs to one phantom-evolution step.

    ``candidate`` is a fresh phantom preference the application layer derived from
    Bob's REAL inner life (a strong taste topic or recent reflection), or ``None``
    when no material warrants a change. ``max_count`` bounds how many phantoms Bob
    holds — an emergence over the bound fades the oldest. ``change_rate`` is the
    per-step probability the (grounded) emergence actually fires, keeping the drift
    slow; it defaults to the conservative :data:`CHANGE_RATE`.
    """

    candidate: str | None
    max_count: int = MAX_PHANTOMS
    change_rate: float = CHANGE_RATE


def evolve_phantoms(
    phantoms: tuple[str, ...],
    signals: PhantomSignals,
    *,
    rng: Random,
) -> tuple[str, ...]:
    """Return Bob's next phantom set — a slow, grounded, bounded membership step.

    A grounded ``candidate`` (and only such a candidate) may emerge, gated behind
    the small ``change_rate`` draw on ``rng`` so most steps are no-ops. When the
    candidate is already present, absent, or blank, the set is returned unchanged
    (idempotent, no fabrication). On emergence the candidate is appended; if that
    overflows ``max_count`` the oldest phantom (front) fades, so the set stays
    bounded with at most one in / one out per step.
    """
    candidate = _grounded(signals.candidate)
    if candidate is None or candidate in phantoms:
        return phantoms
    if rng.random() >= signals.change_rate:  # slowness gate: most steps no-op.
        return phantoms
    grown = (*phantoms, candidate)
    if len(grown) <= signals.max_count:
        return grown
    return grown[len(grown) - signals.max_count :]  # fade the oldest, stay bounded.


def _grounded(candidate: str | None) -> str | None:
    """Return a non-blank, stripped candidate, or ``None`` when there is no material."""
    if candidate is None:
        return None
    stripped = candidate.strip()
    return stripped or None
