# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=domain

"""Mood→Taste modulation — Bob's mood temporarily colours a verdict (no I/O, no LLM).

A pure, deterministic modulator (BOB-020 element 3): Bob's *current mood*
temporarily shifts how he reads a stored taste verdict, **without ever mutating the
taste axes** — this is mood colouring an opinion, NOT self-evolution (BOB-013).

* :func:`modulate` shifts a :class:`~bob.personality.taste.Verdict` by **at
  most one step** along the love→like→neutral→dislike→hate scale: a flat, low mood
  reads stricter/more conservative (positives dampen, negatives harden); a bright,
  open mood reads softer/more curious (negatives soften, positives warm). The ends
  saturate — the result is always a valid verdict.
* :func:`experiment_bias` derives Bob's readiness to try something new from mood,
  bounded to ``[0, 1]``: low when he is flat, higher when he is bright and open.

Both are temporary: callers fold the *effective* verdict + the experiment hint into
the reply prompt, leaving the persisted axes untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.personality.taste import Verdict

if TYPE_CHECKING:
    from bob.personality.mood import Mood

# The verdict scale, brightest (LOVE) to harshest (HATE). A "strict" mood moves a
# verdict one index toward HATE; a "bright" mood one index toward LOVE.
_SCALE: tuple[Verdict, ...] = (
    Verdict.LOVE,
    Verdict.LIKE,
    Verdict.NEUTRAL,
    Verdict.DISLIKE,
    Verdict.HATE,
)
_NEUTRAL_INDEX = _SCALE.index(Verdict.NEUTRAL)

# How flat/bright a mood must read before it colours the verdict at all. Below the
# strict floor → stricter; above the bright ceiling → softer; in between → unchanged.
# A small dead-band keeps an ordinary mood a clean identity (no jitter).
_STRICT_FLOOR = -0.35
_BRIGHT_CEILING = 0.35

# Mood disposition is the average of valence and openness: how Bob feels AND how
# open he is to the topic both bear on whether he reads it generously or strictly.
_DISPOSITION_AXES = 2.0

# Experiment bias maps the same disposition from [-1, 1] onto [0, 1].
_BIAS_MIN = 0.0
_BIAS_MAX = 1.0

# At a NEUTRAL verdict the skew leans by the value sign — but only when there is a
# real (if sub-opinion) lean to amplify. A topic Bob has no opinion on (value ≈ 0,
# e.g. an unknown topic) stays NEUTRAL whatever his mood, so a flat day never
# invents a dislike out of indifference.
_NEUTRAL_LEAN_THRESHOLD = 0.05


def modulate(verdict: Verdict, value: float, mood: Mood) -> Verdict:
    """Return the *effective* verdict after mood colours it — at most one step.

    Bob's mood temporarily shifts the stored ``verdict``: a flat, low mood reads it
    stricter (a positive liking dampens, a dislike hardens), a bright/open mood
    reads it softer/more curious (a dislike eases, a liking warms). ``value`` is the
    signed axis liking; at a NEUTRAL verdict it picks which side the skew leans. The
    shift is bounded to a single step and the ends saturate, so the result is always
    a valid :class:`Verdict`. **Temporary and pure**: the taste axes are never
    mutated, and equal inputs always yield an equal verdict.
    """
    direction = _disposition_direction(mood)
    if direction == 0:
        return verdict
    target = _shifted_index(verdict, value, direction)
    return _SCALE[target]


def experiment_bias(mood: Mood) -> float:
    """Return Bob's mood-driven readiness to experiment, bounded to ``[0, 1]``.

    A flat, low mood yields a low bias (Bob plays it safe); a bright, open mood a
    high one (he is more curious). Derived from the same valence/openness
    disposition as :func:`modulate`, mapped from ``[-1, 1]`` onto ``[0, 1]``. Pure
    and deterministic — equal moods yield equal bias.
    """
    disposition = _disposition(mood)
    bias = (disposition + 1.0) / 2.0
    return max(_BIAS_MIN, min(_BIAS_MAX, bias))


def _disposition(mood: Mood) -> float:
    """Bob's generosity-of-reading: the mean of valence and openness, in [-1, 1]."""
    return (mood.valence + mood.openness) / _DISPOSITION_AXES


def _disposition_direction(mood: Mood) -> int:
    """+1 = stricter (low mood), -1 = softer (bright mood), 0 = unchanged."""
    disposition = _disposition(mood)
    if disposition <= _STRICT_FLOOR:
        return 1
    if disposition >= _BRIGHT_CEILING:
        return -1
    return 0


def _shifted_index(verdict: Verdict, value: float, direction: int) -> int:
    """The clamped scale index of the verdict after a one-step ``direction`` shift.

    Away from NEUTRAL the shift is a plain one-step move along the scale. AT NEUTRAL
    the move follows the ``value`` sign so the skew leans toward the side Bob already
    tilts: a stricter mood cools a positive-leaning topic to dislike (and warms a
    negative one only as far as caution), a brighter mood warms it toward liking.
    """
    index = _SCALE.index(verdict)
    if index == _NEUTRAL_INDEX:
        if abs(value) < _NEUTRAL_LEAN_THRESHOLD:
            return index  # genuine indifference — mood does not invent an opinion
        lean = 1 if value > 0 else -1
        # direction +1 (strict) pushes toward the value's harsh side; -1 (bright)
        # toward its generous side.
        step = lean * (1 if direction > 0 else -1)
        index += step
    else:
        index += direction
    return max(0, min(len(_SCALE) - 1, index))
