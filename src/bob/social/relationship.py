# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Relationship — Bob's per-person relationship quality, accrued over turns (BOB-014).

A pure value object: how Bob stands with one person, on four axes each bounded to
``[-1, 1]`` and starting at ``0`` (neutral, a person he has not formed a read on):

* **trust** — how much Bob relies on this person's word and intent;
* **respect** — how much he rates their judgement;
* **warmth** — how fond he feels toward them (the axis that colours his tone most);
* **compatibility** — how well they get along (drives willingness to compromise).

:func:`apply_interaction` is the single, deterministic step that updates a
relationship from ONE turn's signals — the negotiation :class:`Stance` Bob took,
his :class:`Mood`, and a ``sentiment`` scalar — with small bounded deltas (a
yielding CONCEDE/AGREE warms differently from holding ground with
PROPOSE_ALTERNATIVE; positive sentiment/mood lifts warmth + trust, negative lowers
them). A gentle **drift toward neutral 0** is applied first, so a relationship left
without upkeep relaxes back toward neutral and never runs away to a pinned extreme.
Every axis is clamped to ``[-1, 1]`` on every step. No I/O, no clock — trivially
testable and reusable by the application's influence/update path and the store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.domain.personality.negotiation import Stance

if TYPE_CHECKING:
    from bob.domain.personality.mood import Mood

__all__ = [
    "Relationship",
    "RelationshipDeltas",
    "apply_interaction",
    "compromise_bias",
]

# Each relationship axis is bounded to the closed interval [-1, 1].
_MIN_AXIS = -1.0
_MAX_AXIS = 1.0

# Default small per-interaction step sizes (Q1: ≈0.05) — one turn nudges, never
# jolts, so a relationship is *accrued* over many turns, not set in one.
_DEFAULT_WARMTH_STEP = 0.05
_DEFAULT_TRUST_STEP = 0.05
_DEFAULT_RESPECT_STEP = 0.05
_DEFAULT_COMPAT_STEP = 0.05

# Fraction of the gap to neutral 0 each interaction relaxes — a gentle homeostasis
# (mirrors Mood.drift_toward) that keeps the relationship from pinning at an extreme.
_DEFAULT_DRIFT_RATE = 0.05

# How much more a yielding stance warms than holding ground does. CONCEDE (Bob gives
# the person their way) and AGREE warm at the full step; PROPOSE_ALTERNATIVE (Bob
# holds his own view) warms less — disagreement is cooler, though never hostile here.
_STANCE_WARMTH_FACTOR: dict[Stance, float] = {
    Stance.CONCEDE: 1.0,
    Stance.AGREE: 0.6,
    Stance.PROPOSE_ALTERNATIVE: 0.2,
}

# A small intrinsic warmth a yielding stance carries on its own, independent of the
# turn's affect — accommodating someone is warming in itself, even on a flat turn,
# while holding a counter-view is faintly cooling. A fraction of the warmth step.
_STANCE_INTRINSIC_WARMTH: dict[Stance, float] = {
    Stance.CONCEDE: 0.4,
    Stance.AGREE: 0.2,
    Stance.PROPOSE_ALTERNATIVE: -0.1,
}

# Holding a reasoned alternative earns Bob's read of the person as worth engaging,
# so PROPOSE_ALTERNATIVE lifts respect more than simply yielding does.
_STANCE_RESPECT_FACTOR: dict[Stance, float] = {
    Stance.CONCEDE: 0.4,
    Stance.AGREE: 0.4,
    Stance.PROPOSE_ALTERNATIVE: 1.0,
}


def _clamp(value: float) -> float:
    """Saturate ``value`` into the axis bounds rather than overflowing them."""
    return max(_MIN_AXIS, min(_MAX_AXIS, value))


@dataclass(frozen=True, slots=True)
class RelationshipDeltas:
    """Tunable per-interaction step sizes + drift rate (injected from config).

    Each ``*_step`` is the base move applied to an axis on a single interaction;
    ``drift_rate`` is the fraction of the gap to neutral 0 relaxed each step. The
    defaults are small (≈0.05) so a relationship is accrued over many turns.
    """

    warmth_step: float = _DEFAULT_WARMTH_STEP
    trust_step: float = _DEFAULT_TRUST_STEP
    respect_step: float = _DEFAULT_RESPECT_STEP
    compatibility_step: float = _DEFAULT_COMPAT_STEP
    drift_rate: float = _DEFAULT_DRIFT_RATE


@dataclass(frozen=True, slots=True)
class Relationship:
    """Bob's quality of relationship with one person, on four bounded axes."""

    sender_id: int
    trust: float = 0.0
    respect: float = 0.0
    warmth: float = 0.0
    compatibility: float = 0.0

    def __post_init__(self) -> None:
        for name in ("trust", "respect", "warmth", "compatibility"):
            value = getattr(self, name)
            if not _MIN_AXIS <= value <= _MAX_AXIS:
                raise ValueError(
                    f"relationship axis '{name}' must be within "
                    f"[{_MIN_AXIS}, {_MAX_AXIS}], got {value}"
                )


def _drift(value: float, *, rate: float) -> float:
    """Relax ``value`` a ``rate`` fraction of the way toward neutral 0."""
    return value + (0.0 - value) * rate


def apply_interaction(
    rel: Relationship,
    *,
    stance: Stance,
    mood: Mood,
    sentiment: float,
    deltas: RelationshipDeltas | None = None,
) -> Relationship:
    """Return ``rel`` updated from one turn's (stance, mood, sentiment) — pure.

    Each axis first **drifts** a small fraction toward neutral 0 (homeostasis, so a
    relationship without upkeep relaxes back and never pins at an extreme), then a
    small bounded **interaction delta** is added and the result is clamped to
    ``[-1, 1]``:

    * **warmth** rises with positive ``sentiment`` and a positive ``mood`` valence,
      falls with negative ones, and is scaled by the ``stance`` — a yielding
      CONCEDE/AGREE warms more than holding ground with PROPOSE_ALTERNATIVE;
    * **trust** tracks the same affective signal (sentiment + valence), a touch
      gentler — trust accrues more slowly than warmth;
    * **respect** rises when Bob engages a reasoned alternative (a held stance earns
      more than yielding), tempered by the affective sign;
    * **compatibility** rises on a positive, low-friction turn (positive sentiment
      while yielding) and dips on a negative one.

    Deterministic: same inputs → same output. The same input always yields the same
    Relationship, so the influence/update path and the store stay test-without-LLM.
    """
    cfg = deltas if deltas is not None else RelationshipDeltas()
    # Affective sign of the turn: sentiment + the perceived mood valence, kept in
    # [-1, 1] so it scales a single small step rather than compounding it.
    affect = _clamp((sentiment + mood.valence) / 2.0)
    warmth_factor = _STANCE_WARMTH_FACTOR[stance]
    respect_factor = _STANCE_RESPECT_FACTOR[stance]

    warmth = (
        _drift(rel.warmth, rate=cfg.drift_rate)
        + cfg.warmth_step * warmth_factor * affect
        + cfg.warmth_step * _STANCE_INTRINSIC_WARMTH[stance]
    )
    # Trust accrues from the same affect, a touch gentler than warmth.
    trust = _drift(rel.trust, rate=cfg.drift_rate) + (cfg.trust_step * affect * 0.8)
    # Respect leans on engaging a reasoned stance, signed by the affect of the turn.
    respect = _drift(rel.respect, rate=cfg.drift_rate) + (
        cfg.respect_step * respect_factor * _respect_sign(affect)
    )
    # Compatibility rises on a positive, low-friction turn (yielding + warm).
    compatibility = _drift(rel.compatibility, rate=cfg.drift_rate) + (
        cfg.compatibility_step * warmth_factor * affect
    )

    return Relationship(
        sender_id=rel.sender_id,
        trust=_clamp(trust),
        respect=_clamp(respect),
        warmth=_clamp(warmth),
        compatibility=_clamp(compatibility),
    )


# How strongly a fully-close relationship (warmth = compatibility = 1) lowers Bob's
# effective conviction toward compromise. Small and bounded: the relationship NUDGES
# the negotiation threshold, it never overrides Bob's values (a strongly-held view
# still holds). A negative relationship yields a zero bias here — coldness does not
# make Bob *more* stubborn; it simply removes the warm discount (the cool side is
# carried by the relationship TONE, and relational hostility is the sulk, .2).
_MAX_COMPROMISE_BIAS = 0.2


def compromise_bias(rel: Relationship | None) -> float:
    """Return how much closeness lowers Bob's effective conviction (0..bound).

    A close relationship (high ``warmth`` + ``compatibility``) makes Bob MORE willing
    to meet the person halfway, so the application subtracts this bias from the
    conviction it feeds :class:`~bob.domain.personality.negotiation.Negotiation` — a
    close person tips a borderline stance from holding ground toward agreeing. The
    bias is small and bounded (it nudges, never overrides a strong conviction), zero
    for a neutral or negative relationship (coldness does not make Bob more stubborn;
    its reserve is carried by the tone), and zero when there is no relationship on
    record. Pure and deterministic.
    """
    if rel is None:
        return 0.0
    closeness = (rel.warmth + rel.compatibility) / 2.0
    if closeness <= 0.0:
        return 0.0
    return _MAX_COMPROMISE_BIAS * closeness


# A neutral (zero-affect) turn still earns a touch of respect for engaging at all,
# so respect leans positive unless the turn was genuinely negative.
def _respect_sign(affect: float) -> float:
    """Map the turn's affect to a respect direction in ``[-1, 1]`` (neutral → +)."""
    if affect < 0.0:
        return affect
    return max(affect, 0.5)
