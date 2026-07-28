# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=domain

"""Mood — Bob's affective state as a bounded five-axis vector.

A pure value object (no I/O): valence, arousal, openness, social, and stability,
each in ``[-1, 1]``. Mood is updated by applying a :class:`MoodDelta` (clamped to
bounds) and decays back toward a baseline via :meth:`Mood.drift_toward`. The
:meth:`Mood.tone` method derives a deterministic tone descriptor that the
application layer feeds to the LLM to colour Bob's replies — the same input
always yields the same descriptor, so tone is testable without a model.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

# Each mood axis is bounded to the closed interval [-1, 1].
_MIN_AXIS = -1.0
_MAX_AXIS = 1.0

# Drift rate is a fraction of the gap to baseline, so it lives in [0, 1].
_MIN_RATE = 0.0
_MAX_RATE = 1.0

# Tone thresholds: how strong an axis must be to read as positive/negative
# or high/low arousal rather than neutral.
_VALENCE_THRESHOLD = 0.25
_AROUSAL_THRESHOLD = 0.25

# Tone descriptor keyed by (valence sign, arousal band), each in {-1, 0, +1}.
# Valence sets the emotional sign; arousal sets the intensity word.
_TONE_BY_VALENCE_AROUSAL: dict[tuple[int, int], str] = {
    (1, 1): "excited",
    (1, 0): "cheerful",
    (1, -1): "content",
    (0, 1): "neutral",
    (0, 0): "neutral",
    (0, -1): "neutral",
    (-1, 1): "agitated",
    (-1, 0): "glum",
    (-1, -1): "subdued",
}


def _clamp(value: float) -> float:
    """Saturate ``value`` into the axis bounds rather than overflowing them."""
    return max(_MIN_AXIS, min(_MAX_AXIS, value))


def _band(value: float, threshold: float) -> int:
    """Bucket ``value`` to a sign in ``{-1, 0, +1}`` either side of ``threshold``."""
    if value > threshold:
        return 1
    if value < -threshold:
        return -1
    return 0


@dataclass(frozen=True, slots=True)
class MoodDelta:
    """A signed nudge to apply to each mood axis (defaults to no change)."""

    valence: float = 0.0
    arousal: float = 0.0
    openness: float = 0.0
    social: float = 0.0
    stability: float = 0.0


@dataclass(frozen=True, slots=True)
class Mood:
    """Bob's current affective state as a bounded five-axis vector."""

    valence: float = 0.0
    arousal: float = 0.0
    openness: float = 0.0
    social: float = 0.0
    stability: float = 0.0

    def __post_init__(self) -> None:
        for axis in fields(self):
            value = getattr(self, axis.name)
            if not _MIN_AXIS <= value <= _MAX_AXIS:
                raise ValueError(
                    f"mood axis '{axis.name}' must be within "
                    f"[{_MIN_AXIS}, {_MAX_AXIS}], got {value}"
                )

    def update(self, delta: MoodDelta) -> Mood:
        """Return a new mood with ``delta`` applied per axis, clamped to bounds."""
        return Mood(
            valence=_clamp(self.valence + delta.valence),
            arousal=_clamp(self.arousal + delta.arousal),
            openness=_clamp(self.openness + delta.openness),
            social=_clamp(self.social + delta.social),
            stability=_clamp(self.stability + delta.stability),
        )

    def drift_toward(self, baseline: Mood, *, rate: float) -> Mood:
        """Return a new mood moved a ``rate`` fraction of the gap toward ``baseline``.

        Models emotional homeostasis: between stimuli, mood decays back toward
        Bob's resting baseline. ``rate`` is in ``[0, 1]`` (0 = no drift,
        1 = snap to baseline).
        """
        if not _MIN_RATE <= rate <= _MAX_RATE:
            raise ValueError(f"drift rate must be within [{_MIN_RATE}, {_MAX_RATE}], got {rate}")
        return Mood(
            valence=self._toward(self.valence, baseline.valence, rate),
            arousal=self._toward(self.arousal, baseline.arousal, rate),
            openness=self._toward(self.openness, baseline.openness, rate),
            social=self._toward(self.social, baseline.social, rate),
            stability=self._toward(self.stability, baseline.stability, rate),
        )

    def lift_toward(self, target: Mood, *, rate: float) -> Mood:
        """Return a new mood pulled a ``rate`` fraction of the gap toward ``target``.

        The mechanics mirror :meth:`drift_toward`, but the intent differs: this is
        an *external* lift — a warm incoming message (BOB-033 social contagion)
        displacing accumulated low by tugging mood toward a warmer ``target`` —
        rather than passive homeostatic decay. ``rate`` is in ``[0, 1]`` (0 = no
        lift, 1 = snap to ``target``); results stay clamped to the axis bounds.
        """
        if not _MIN_RATE <= rate <= _MAX_RATE:
            raise ValueError(f"lift rate must be within [{_MIN_RATE}, {_MAX_RATE}], got {rate}")
        return Mood(
            valence=self._toward(self.valence, target.valence, rate),
            arousal=self._toward(self.arousal, target.arousal, rate),
            openness=self._toward(self.openness, target.openness, rate),
            social=self._toward(self.social, target.social, rate),
            stability=self._toward(self.stability, target.stability, rate),
        )

    def tone(self) -> str:
        """Derive a deterministic tone descriptor from valence and arousal.

        Valence sets the emotional sign and arousal the intensity, so the same
        mood always maps to the same word the LLM uses to colour a reply.
        """
        valence_sign = _band(self.valence, _VALENCE_THRESHOLD)
        arousal_band = _band(self.arousal, _AROUSAL_THRESHOLD)
        return _TONE_BY_VALENCE_AROUSAL[(valence_sign, arousal_band)]

    @staticmethod
    def _toward(current: float, target: float, rate: float) -> float:
        return _clamp(current + (target - current) * rate)
