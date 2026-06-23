# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for mood→taste modulation (BOB-020 element 3).

A pure, deterministic modulator: Bob's *current mood* temporarily colours how he
reads a taste verdict — a flat, low mood makes him stricter/more conservative and
less eager to experiment; a bright, open mood softens his verdict and makes him
more curious. The contract is the guardrail set from the RFC: the shift is **at
most one step**, the modulation is **temporary** (it never mutates the taste axes —
this is not self-evolution / BOB-013), it is **bounded**, and it is
**deterministic** (equal mood + verdict + value always yield an equal result).
"""

from __future__ import annotations

from bob.domain.personality.mood import Mood
from bob.domain.personality.mood_taste import experiment_bias, modulate
from bob.domain.personality.taste import Verdict

# A clearly bright/open mood and a clearly flat/low mood for the band tests.
_BRIGHT = Mood(valence=0.7, arousal=0.4, openness=0.6)
_LOW = Mood(valence=-0.7, arousal=-0.4, openness=-0.5)
_NEUTRAL = Mood()

# Verdict order from softest-positive to harshest-negative, used to measure the
# "at most one step" guardrail independently of the implementation.
_SCALE = (
    Verdict.LOVE,
    Verdict.LIKE,
    Verdict.NEUTRAL,
    Verdict.DISLIKE,
    Verdict.HATE,
)


def _step_distance(a: Verdict, b: Verdict) -> int:
    return abs(_SCALE.index(a) - _SCALE.index(b))


def test_neutral_mood_is_identity() -> None:
    # A neutral mood neither dampens nor brightens: the stored verdict passes
    # through unchanged for every verdict.
    for verdict in _SCALE:
        assert modulate(verdict, 0.5, _NEUTRAL) is verdict


def test_low_mood_dampens_a_positive_verdict_one_step_stricter() -> None:
    # Flat mood → a positive liking reads more conservatively (LIKE → NEUTRAL),
    # by exactly one step toward the strict end.
    assert modulate(Verdict.LIKE, 0.5, _LOW) is Verdict.NEUTRAL
    assert modulate(Verdict.LOVE, 0.9, _LOW) is Verdict.LIKE


def test_low_mood_hardens_a_negative_verdict_one_step_stricter() -> None:
    # Flat mood → a dislike reads harsher (DISLIKE → HATE), still one step.
    assert modulate(Verdict.DISLIKE, -0.5, _LOW) is Verdict.HATE


def test_bright_mood_softens_a_negative_verdict_one_step() -> None:
    # Bright/open mood → a dislike reads softer/more curious (DISLIKE → NEUTRAL).
    assert modulate(Verdict.DISLIKE, -0.5, _BRIGHT) is Verdict.NEUTRAL
    assert modulate(Verdict.HATE, -0.9, _BRIGHT) is Verdict.DISLIKE


def test_bright_mood_warms_a_positive_verdict_one_step() -> None:
    # Bright/open mood → a liking reads warmer/more curious (LIKE → LOVE).
    assert modulate(Verdict.LIKE, 0.5, _BRIGHT) is Verdict.LOVE


def test_neutral_verdict_skews_by_value_sign_under_mood() -> None:
    # At NEUTRAL the value sign picks the direction of the skew. Low mood pushes a
    # mildly-positive topic to caution, a mildly-negative one to dislike.
    assert modulate(Verdict.NEUTRAL, 0.3, _LOW) is Verdict.DISLIKE
    # Bright mood warms a mildly-positive neutral to a like.
    assert modulate(Verdict.NEUTRAL, 0.3, _BRIGHT) is Verdict.LIKE


def test_neutral_verdict_on_an_unknown_topic_stays_neutral() -> None:
    # Genuine indifference (no opinion, value ≈ 0) is never turned into a dislike by
    # a flat mood — mood colours opinions, it does not invent them.
    assert modulate(Verdict.NEUTRAL, 0.0, _LOW) is Verdict.NEUTRAL
    assert modulate(Verdict.NEUTRAL, 0.0, _BRIGHT) is Verdict.NEUTRAL


def test_shift_is_at_most_one_step_for_every_combination() -> None:
    # Guardrail: across all verdicts, values and the three mood bands, the verdict
    # never moves more than a single step on the scale.
    for verdict in _SCALE:
        for value in (-0.9, -0.3, 0.0, 0.3, 0.9):
            for mood in (_LOW, _NEUTRAL, _BRIGHT):
                result = modulate(verdict, value, mood)
                assert _step_distance(verdict, result) <= 1


def test_modulate_is_deterministic() -> None:
    # Equal inputs → equal output, every time (no hidden state, no RNG).
    first = modulate(Verdict.LIKE, 0.5, _LOW)
    second = modulate(Verdict.LIKE, 0.5, _LOW)
    assert first is second


def test_modulate_returns_a_verdict_and_never_falls_off_the_scale() -> None:
    # Bounded: the result is always a valid Verdict (the ends saturate, they do not
    # overflow past LOVE/HATE).
    assert modulate(Verdict.LOVE, 0.9, _BRIGHT) is Verdict.LOVE  # already brightest
    assert modulate(Verdict.HATE, -0.9, _LOW) is Verdict.HATE  # already harshest
    for verdict in _SCALE:
        assert isinstance(modulate(verdict, 0.0, _LOW), Verdict)


def test_experiment_bias_low_for_flat_mood_high_for_bright() -> None:
    # Readiness to experiment tracks mood: a bright/open mood is more willing than
    # a flat/low one, and a neutral mood sits between.
    assert experiment_bias(_LOW) < experiment_bias(_NEUTRAL) < experiment_bias(_BRIGHT)


def test_experiment_bias_is_bounded_unit_interval() -> None:
    # Bounded to [0, 1] for every mood (incl. the saturating extremes).
    for mood in (_LOW, _NEUTRAL, _BRIGHT, Mood(valence=1.0, openness=1.0),
                 Mood(valence=-1.0, openness=-1.0)):
        bias = experiment_bias(mood)
        assert 0.0 <= bias <= 1.0


def test_experiment_bias_is_deterministic() -> None:
    assert experiment_bias(_BRIGHT) == experiment_bias(_BRIGHT)
