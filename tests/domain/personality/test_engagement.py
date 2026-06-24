# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for Engagement — Bob's appetite to converse, as a level (BOB-014 .2a).

A pure model: :func:`decide_engagement` maps mood x topic-interest x fatigue x
relationship to an :class:`EngagementLevel`, realising the four human scenarios
(good mood → playful; aimless chatter bores; bad mood → high threshold; an
interesting topic overrides a bad mood). :class:`ConversationalFatigue` is the
bounded, decaying reservoir; :func:`topic_interest` derives the interest scalar;
:func:`engagement_mood_lift` is the good-exchange → mood-up feedback.
"""

from __future__ import annotations

from random import Random

import pytest

from bob.domain.personality.engagement import (
    ConversationalFatigue,
    EngagementLevel,
    EngagementThresholds,
    FatigueRates,
    appetite_of,
    decide_engagement,
    engagement_mood_lift,
    topic_interest,
)
from bob.domain.personality.mood import Mood
from bob.domain.personality.relationship import Relationship
from bob.domain.personality.taste import Verdict

_GOOD_MOOD = Mood(valence=0.6, arousal=0.4, openness=0.4)
_BAD_MOOD = Mood(valence=-0.6, arousal=-0.1)
_NEUTRAL_MOOD = Mood()

_FRESH = ConversationalFatigue(0.0)
_TIRED = ConversationalFatigue(0.9)

# Interest scalars either side of the default ``interesting`` bar (0.5).
_INTERESTING = 0.8
_AIMLESS = 0.1


def _rng(seed: int = 0) -> Random:
    return Random(seed)


# --- topic_interest ---------------------------------------------------------


def test_topic_interest_strong_opinion_is_high() -> None:
    interest = topic_interest(Verdict.LOVE, conviction=0.9)

    assert interest >= EngagementThresholds().interesting


def test_topic_interest_neutral_unknown_is_low() -> None:
    interest = topic_interest(Verdict.NEUTRAL, conviction=0.0)

    assert interest < EngagementThresholds().interesting


def test_fascination_match_clears_the_bar_even_for_a_mild_verdict() -> None:
    # A live fascination match is the strongest pull — it makes "какие-попало" interesting.
    interest = topic_interest(Verdict.NEUTRAL, conviction=0.0, fascination_match=True)

    assert interest >= EngagementThresholds().interesting


def test_topic_interest_is_bounded() -> None:
    interest = topic_interest(Verdict.LOVE, conviction=1.0, fascination_match=True)

    assert 0.0 <= interest <= 1.0


# --- Scenario 1: good mood → can play along / banter ------------------------


def test_good_mood_interesting_topic_is_playful_under_seed() -> None:
    # With a bright mood + interesting topic, SOME seed tips to PLAYFUL (banter).
    levels = {
        decide_engagement(
            mood=_GOOD_MOOD,
            topic_interest=_INTERESTING,
            fatigue=_FRESH,
            rng=_rng(seed),
        )
        for seed in range(20)
    }

    assert EngagementLevel.PLAYFUL in levels
    assert levels <= {EngagementLevel.PLAYFUL, EngagementLevel.FULL}


def test_neutral_mood_interesting_topic_engages_but_never_playful() -> None:
    # Playfulness needs a BRIGHT mood; a flat mood engages fully but does not banter.
    levels = {
        decide_engagement(
            mood=_NEUTRAL_MOOD,
            topic_interest=_INTERESTING,
            fatigue=_FRESH,
            rng=_rng(seed),
        )
        for seed in range(20)
    }

    assert levels == {EngagementLevel.FULL}


# --- Scenario 2: aimless chatter bores him → winds down ---------------------


def test_high_fatigue_uninteresting_topic_declines() -> None:
    level = decide_engagement(
        mood=_NEUTRAL_MOOD,
        topic_interest=_AIMLESS,
        fatigue=_TIRED,
        rng=_rng(),
    )

    assert level is EngagementLevel.DECLINE


def test_high_fatigue_interesting_topic_still_only_terse() -> None:
    # Bored, but the topic is interesting — he stays present but terse, not playful.
    level = decide_engagement(
        mood=_GOOD_MOOD,
        topic_interest=_INTERESTING,
        fatigue=_TIRED,
        rng=_rng(),
    )

    assert level is EngagementLevel.TERSE


# --- Scenario 3: bad mood → high threshold for "какие-попало" topics --------


def test_bad_mood_aimless_topic_declines_from_the_start() -> None:
    level = decide_engagement(
        mood=_BAD_MOOD,
        topic_interest=_AIMLESS,
        fatigue=_FRESH,
        rng=_rng(),
    )

    assert level is EngagementLevel.DECLINE


def test_neutral_mood_aimless_topic_is_merely_terse_not_declined() -> None:
    # A normal mood does not refuse an aimless topic — it just answers tersely.
    level = decide_engagement(
        mood=_NEUTRAL_MOOD,
        topic_interest=_AIMLESS,
        fatigue=_FRESH,
        rng=_rng(),
    )

    assert level is EngagementLevel.TERSE


# --- Scenario 4: an interesting topic overrides a bad mood ------------------


def test_interesting_topic_overrides_bad_mood() -> None:
    level = decide_engagement(
        mood=_BAD_MOOD,
        topic_interest=_INTERESTING,
        fatigue=_FRESH,
        rng=_rng(),
    )

    assert level is EngagementLevel.FULL


# --- relationship lowers the bar -------------------------------------------


def test_close_relationship_lowers_the_interest_bar() -> None:
    # A borderline-interesting topic that a stranger gets TERSE on engages a close friend.
    borderline = EngagementThresholds().interesting - 0.1
    close = Relationship(sender_id=1, warmth=0.9, compatibility=0.9)

    stranger_level = decide_engagement(
        mood=_NEUTRAL_MOOD, topic_interest=borderline, fatigue=_FRESH, rng=_rng()
    )
    close_level = decide_engagement(
        mood=_NEUTRAL_MOOD,
        topic_interest=borderline,
        fatigue=_FRESH,
        relationship=close,
        rng=_rng(),
    )

    assert stranger_level is EngagementLevel.TERSE
    assert close_level is EngagementLevel.FULL


def test_cratered_relationship_raises_the_bar_guest_disengage() -> None:
    # BOB-014 .2b guest-disengage: a badgering guest drives their relationship down →
    # Bob disengages from THAT person. A cratered (very negative) relationship RAISES
    # the interest bar, so a borderline topic a stranger would stay present on gets
    # declined/terse from a person Bob has soured on — keyed on the cratered relationship.
    borderline = EngagementThresholds().interesting + 0.05
    cratered = Relationship(sender_id=1, warmth=-0.9, compatibility=-0.9)

    stranger_level = decide_engagement(
        mood=_NEUTRAL_MOOD, topic_interest=borderline, fatigue=_FRESH, rng=_rng()
    )
    cratered_level = decide_engagement(
        mood=_NEUTRAL_MOOD,
        topic_interest=borderline,
        fatigue=_FRESH,
        relationship=cratered,
        rng=_rng(),
    )

    # The stranger stays engaged; the soured person is disengaged from (the bar rose).
    assert stranger_level in (EngagementLevel.FULL, EngagementLevel.PLAYFUL)
    assert cratered_level in (EngagementLevel.TERSE, EngagementLevel.DECLINE)


# --- determinism ------------------------------------------------------------


def test_deterministic_under_a_fixed_seed() -> None:
    first = decide_engagement(
        rng=_rng(42), mood=_GOOD_MOOD, topic_interest=_INTERESTING, fatigue=_FRESH
    )
    second = decide_engagement(
        rng=_rng(42), mood=_GOOD_MOOD, topic_interest=_INTERESTING, fatigue=_FRESH
    )

    assert first is second


# --- ConversationalFatigue --------------------------------------------------


def test_fatigue_rises_on_aimless_turns() -> None:
    fatigue = _FRESH
    for _ in range(5):
        fatigue = fatigue.after_turn(interesting=False)

    assert fatigue.level > _FRESH.level


def test_one_aimless_turn_does_not_bore_him() -> None:
    # A single dull message must not flip Bob to bored — fatigue accrues over a run.
    fatigue = _FRESH.after_turn(interesting=False)

    assert fatigue.level < EngagementThresholds().high_fatigue


def test_fatigue_decays_over_time_and_never_permanently_locks() -> None:
    # Whatever the fatigue, enough quiet returns it to zero — appetite always recovers.
    recovered = _TIRED.decayed(elapsed_seconds=3600.0 * 10)

    assert recovered.level == 0.0


def test_interesting_turn_eases_fatigue() -> None:
    eased = _TIRED.after_turn(interesting=True)

    assert eased.level < _TIRED.level


def test_fatigue_is_bounded() -> None:
    risen = _TIRED.after_turn(interesting=False).after_turn(interesting=False)
    eased = _FRESH.after_turn(interesting=True)

    assert 0.0 <= risen.level <= 1.0
    assert eased.level == 0.0


def test_fatigue_rejects_out_of_bounds() -> None:
    with pytest.raises(ValueError, match="conversational fatigue"):
        ConversationalFatigue(1.5)


def test_decay_rejects_negative_elapsed() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _FRESH.decayed(elapsed_seconds=-1.0)


def test_decay_is_monotonic_in_elapsed_time() -> None:
    short = _TIRED.decayed(elapsed_seconds=60.0)
    long = _TIRED.decayed(elapsed_seconds=600.0)

    assert long.level <= short.level


def test_fatigue_rates_are_tunable() -> None:
    fast = FatigueRates(decay_per_second=1.0)
    recovered = ConversationalFatigue(0.5).decayed(elapsed_seconds=1.0, rates=fast)

    assert recovered.level == 0.0


# --- feedback: a good interesting exchange lifts mood ------------------------


def test_good_interesting_exchange_lifts_mood() -> None:
    lift = engagement_mood_lift(EngagementLevel.FULL, interesting=True)

    assert lift > 0.0


def test_playful_interesting_exchange_lifts_mood() -> None:
    lift = engagement_mood_lift(EngagementLevel.PLAYFUL, interesting=True)

    assert lift > 0.0


def test_terse_or_uninteresting_turn_does_not_lift_mood() -> None:
    assert engagement_mood_lift(EngagementLevel.TERSE, interesting=True) == 0.0
    assert engagement_mood_lift(EngagementLevel.FULL, interesting=False) == 0.0
    assert engagement_mood_lift(EngagementLevel.DECLINE, interesting=True) == 0.0


# --- appetite_of: EngagementLevel → [0, 1] аппетит (BOB-024) ------------------


def test_appetite_of_is_monotonic_full_to_decline() -> None:
    # Аппетит как float для decide_verbosity (BOB-024): убывает от FULL к DECLINE.
    full = appetite_of(EngagementLevel.FULL)
    playful = appetite_of(EngagementLevel.PLAYFUL)
    terse = appetite_of(EngagementLevel.TERSE)
    decline = appetite_of(EngagementLevel.DECLINE)
    assert full == 1.0
    assert decline == 0.0
    assert full >= playful > terse > decline


def test_appetite_of_is_bounded_unit_interval() -> None:
    for level in EngagementLevel:
        assert 0.0 <= appetite_of(level) <= 1.0
