# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Disposition — Bob's stable affective temperament as a pure value object.

A frozen, two-trait vector — ``optimism`` and ``resilience``, each in ``[0, 1]`` —
from which Bob's canon-optimism *emerges* rather than being scripted. It carries
no I/O: it only exposes pure derivations the emotional-regulation mechanisms read.

- :meth:`reappraisal_probability` — how readily Bob reframes a dark thought
  (rises with optimism); the reappraisal step (BOB-033 .2) gates on it.
- :meth:`positive_lift_scale` / :meth:`negative_dip_scale` — the *asymmetric*
  magnitudes of social contagion (BOB-033 .3): a warm message lifts Bob more than
  a cold one drags him down (``positive_lift_scale() > negative_dip_scale()`` for
  every disposition), the structural anti-depressant. The lift grows with
  optimism; the dip shrinks with resilience.
- :meth:`social_lift_rate` — the (proportional, never-maxed) fraction toward the
  baseline a warm message tugs Bob's mood (BOB-033 .3 social co-regulation), so a
  warm exchange displaces accumulated low rather than only adding a delta.

All derivations are deterministic — same traits, same result — so they are
testable without a model and stay clamped to sane ranges.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

# Both traits live in the closed unit interval.
_MIN_TRAIT = 0.0
_MAX_TRAIT = 1.0

# Canon-Bob's temperament: a strong optimist who recovers well.
_CANON_OPTIMISM = 0.8
_CANON_RESILIENCE = 0.7

# Reappraisal probability rises linearly with optimism within a guarded band:
# even a pessimist sometimes reframes, even an optimist sometimes lets a thought
# stay honestly sad (no certainty either way → never mechanistic).
_REAPPRAISAL_FLOOR = 0.2
_REAPPRAISAL_SPAN = 0.7

# Social-contagion magnitudes. The lift band sits strictly above the dip band so
# the asymmetry holds for every disposition: max possible dip < min possible lift.
_LIFT_BASE = 0.4
_LIFT_OPTIMISM_GAIN = 0.4  # lift in [0.4, 0.8], growing with optimism
_DIP_BASE = 0.3
_DIP_RESILIENCE_DAMP = 0.5  # dip in [0.15, 0.3], shrinking with resilience

# Low-displacement pull (BOB-033 .3). On a warm exchange Bob is tugged a fraction
# of the gap back toward his baseline (Mood.lift_toward) — proportional, never a
# mechanical snap (kept strictly inside the open interval (0, 1)). Grows with
# optimism so a sunnier Bob recharges out of a dip faster.
_LIFT_RATE_BASE = 0.1
_LIFT_RATE_OPTIMISM_GAIN = 0.3  # rate in [0.1, 0.4], growing with optimism


@dataclass(frozen=True, slots=True)
class Disposition:
    """Bob's stable temperament: ``optimism`` and ``resilience`` in ``[0, 1]``."""

    optimism: float
    resilience: float

    def __post_init__(self) -> None:
        for trait in fields(self):
            value = getattr(self, trait.name)
            if not _MIN_TRAIT <= value <= _MAX_TRAIT:
                raise ValueError(
                    f"disposition trait '{trait.name}' must be within "
                    f"[{_MIN_TRAIT}, {_MAX_TRAIT}], got {value}"
                )

    @staticmethod
    def canonical() -> Disposition:
        """Return canon-Bob's default temperament (a strong, resilient optimist)."""
        return DEFAULT_DISPOSITION

    def reappraisal_probability(self) -> float:
        """Return the probability Bob reframes a negative thought, in ``[0, 1]``.

        Linear in optimism within a guarded band so reappraisal is never certain
        and never impossible — the probabilistic, human (not scripted) shape.
        """
        return _REAPPRAISAL_FLOOR + _REAPPRAISAL_SPAN * self.optimism

    def positive_lift_scale(self) -> float:
        """Return the magnitude a warm message lifts mood toward the baseline.

        Grows with optimism and always exceeds :meth:`negative_dip_scale` — warmth
        moves Bob more than negativity, the structural anti-depressant.
        """
        return _LIFT_BASE + _LIFT_OPTIMISM_GAIN * self.optimism

    def negative_dip_scale(self) -> float:
        """Return the (smaller) magnitude a cold message drags mood down.

        Shrinks with resilience — a sturdier Bob is moved less by the same blow —
        and stays strictly below :meth:`positive_lift_scale`.
        """
        return _DIP_BASE * (_MAX_TRAIT - _DIP_RESILIENCE_DAMP * self.resilience)

    def social_lift_rate(self) -> float:
        """Return the fraction toward baseline a warm message pulls mood, in ``(0, 1)``.

        The "displace the low" tug (BOB-033 .3 social co-regulation): a warm exchange
        does not just add a valence delta — it charges Bob back up out of a dip by
        pulling his mood a *fraction* of the gap toward his disposition baseline (fed
        to :meth:`~bob.domain.personality.mood.Mood.lift_toward`). It is proportional,
        never a mechanical snap (strictly below ``1``), and grows with optimism so a
        sunnier Bob recovers faster.
        """
        return _LIFT_RATE_BASE + _LIFT_RATE_OPTIMISM_GAIN * self.optimism


# Canon-Bob's seed temperament, used as the load-time fallback (existing installs
# without a ``disposition.json`` keep Bob a canon optimist).
DEFAULT_DISPOSITION = Disposition(optimism=_CANON_OPTIMISM, resilience=_CANON_RESILIENCE)
