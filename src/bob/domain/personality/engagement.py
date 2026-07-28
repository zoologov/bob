# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality

"""Engagement — Bob's APPETITE to converse, modelled as a level (BOB-014 .2a).

Conversational appetite is not an on/off switch but a *level* that emerges, per
turn, from four pure signals:

* **mood** — a bright, open mood makes Bob playful and willing to banter "ни о чём";
  a flat, low mood raises his threshold so he won't engage on "какие-попало" topics;
* **topic interest** — a genuinely interesting topic (a strong taste opinion, or the
  thing he is currently fascinated by) pulls him in even on a bad day; an aimless,
  low-interest topic does not;
* **conversational fatigue** — a bounded, decaying reservoir that rises on aimless
  low-interest turns ("наскучило") and recedes over time / on an interesting turn,
  so prolonged pointless chatter winds him down — and crucially recovers, never a
  permanent lock-out;
* **relationship** — closeness lowers the bar: Bob plays along more readily with
  someone he is close to, and a stranger gets a higher threshold.

:func:`decide_engagement` maps these to an :class:`EngagementLevel`
(FULL / PLAYFUL / TERSE / DECLINE) by a pure, deterministic heuristic with one
small seeded RNG draw at the FULL/PLAYFUL boundary, so a fixed seed reproduces the
whole turn. :class:`ConversationalFatigue` is the bounded reservoir; :func:`topic_interest`
derives the [0, 1] interest scalar from a taste verdict/conviction + a fascination
match. No I/O, no clock (elapsed time is passed in) — trivially testable and pure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from random import Random

    from bob.domain.personality.mood import Mood
    from bob.domain.personality.taste import Verdict
    from bob.social.relationship import Relationship

__all__ = [
    "ConversationalFatigue",
    "EngagementLevel",
    "EngagementThresholds",
    "FatigueRates",
    "appetite_of",
    "decide_engagement",
    "engagement_mood_lift",
    "topic_interest",
]

# Interest + fatigue are bounded scalars in the closed unit interval [0, 1].
_MIN_LEVEL = 0.0
_MAX_LEVEL = 1.0


class EngagementLevel(Enum):
    """How much appetite Bob has to converse THIS turn, strongest to weakest.

    * :data:`FULL` — fully engaged: a real, substantive exchange.
    * :data:`PLAYFUL` — engaged AND in the mood to banter / подурачиться / play along.
    * :data:`TERSE` — engaging only minimally; interest is thinning.
    * :data:`DECLINE` — winding the chatter down softly ("что-то заболтались") — never
      a refusal of the person, just no appetite for THIS aimless thread right now.
    """

    FULL = "full"
    PLAYFUL = "playful"
    TERSE = "terse"
    DECLINE = "decline"


# How the discrete appetite LEVEL reads as a [0, 1] scalar (BOB-024). The brevity
# decision (decide_verbosity) takes a numeric ``engagement`` — the appetite of the
# turn as a continuous signal — while the rest of the app reasons in the four-way
# level. This pure mapping bridges the two without a parallel numeric model: FULL is
# maximum appetite (1.0), DECLINE is none (0.0), PLAYFUL is high, TERSE is thin. It
# is strictly decreasing FULL → PLAYFUL → TERSE → DECLINE so a thinning appetite
# always pulls verbosity DOWN, never up.
_APPETITE_OF: dict[EngagementLevel, float] = {
    EngagementLevel.FULL: 1.0,
    EngagementLevel.PLAYFUL: 0.7,
    EngagementLevel.TERSE: 0.3,
    EngagementLevel.DECLINE: 0.0,
}


def appetite_of(level: EngagementLevel) -> float:
    """Return Bob's conversational appetite this turn as a [0, 1] scalar (BOB-024).

    Bridges the four-way :class:`EngagementLevel` to the numeric ``engagement`` that
    :func:`~bob.domain.personality.brevity.decide_verbosity` consumes — FULL is full
    appetite (``1.0``), DECLINE is none (``0.0``), with PLAYFUL/TERSE between. Strictly
    decreasing FULL → DECLINE so a thinning appetite only ever pulls verbosity down.
    Pure and deterministic: same level → same appetite.
    """
    return _APPETITE_OF[level]


# How firmly a strong taste opinion + conviction reads as "interesting". A loved/hated
# topic Bob is convinced about is the most engaging; a mild like/dislike less so. The
# extra lift a current-fascination match adds is on top, capped at the bound.
_VERDICT_INTEREST: dict[str, float] = {
    "love": 0.85,
    "hate": 0.7,
    "like": 0.55,
    "dislike": 0.45,
    "neutral": 0.1,
}

# A live fascination MATCH (the topic is the thing Bob is into right now) is the single
# strongest "interesting" signal — it pulls him in even on a bad day. Added on top of
# the verdict interest and clamped, so a matched topic always clears the interest bar.
_FASCINATION_MATCH_BONUS = 0.6

# How much of the conviction modulates the verdict interest: a held opinion is more
# engaging than a tepid one. Kept small so even a low-conviction strong verdict still
# reads as some interest (Bob can be drawn into a topic he has not fully formed a view on).
_CONVICTION_WEIGHT = 0.3


def _clamp(value: float) -> float:
    """Saturate ``value`` into the bounded [0, 1] interval rather than overflowing."""
    if math.isnan(value):
        return _MIN_LEVEL
    return max(_MIN_LEVEL, min(_MAX_LEVEL, value))


def topic_interest(
    verdict: Verdict, conviction: float, *, fascination_match: bool = False
) -> float:
    """Return how INTERESTING this topic is to Bob, as a [0, 1] scalar (pure).

    Derived from his deterministic taste :class:`~bob.domain.personality.taste.Verdict`
    on the topic (a strong love/hate is more engaging than a mild like/dislike; a
    NEUTRAL/unknown topic is "какие-попало" — low), nudged up by how firmly he holds
    that opinion (``conviction``), and lifted by a live ``fascination_match`` — the topic
    being the very thing he is into right now is the strongest pull and clears the bar
    even when his verdict is mild. Deterministic: same inputs → same interest.
    """
    base = _VERDICT_INTEREST.get(verdict.value, _VERDICT_INTEREST["neutral"])
    conviction_lift = base * _CONVICTION_WEIGHT * _clamp(conviction)
    bonus = _FASCINATION_MATCH_BONUS if fascination_match else 0.0
    return _clamp(base + conviction_lift + bonus)


# Default appetite thresholds. ``interesting`` is the interest at/above which a topic
# reads as genuinely engaging (clears even a low mood); ``high_fatigue`` is the fatigue
# at/above which Bob is bored ("наскучило") and winds chatter down; ``low_mood`` is the
# mood valence at/below which Bob's bar for "какие-попало" topics is raised from the
# start; ``bright_mood`` is the valence at/above which a good mood unlocks playfulness.
_DEFAULT_INTERESTING = 0.5
_DEFAULT_HIGH_FATIGUE = 0.7
_DEFAULT_LOW_MOOD = -0.3
_DEFAULT_BRIGHT_MOOD = 0.3

# How much the relationship shifts Bob's interest bar (warmth + compatibility), both
# ways: closeness LOWERS the bar (he plays along more readily with someone close), a
# cratered/hostile relationship RAISES it (BOB-014 .2b guest-disengage — he winds down
# with a person he has soured on). Small + bounded — the relationship NUDGES the
# threshold, never forcing engagement on a boring topic nor a permanent block.
_RELATIONSHIP_BAR_DISCOUNT = 0.2

# Probability that an otherwise-FULL turn tips into PLAYFUL when the mood is bright —
# playfulness is a possibility a good mood unlocks, not a guarantee on every turn, so a
# fixed seed makes it reproducible without it reading as a tic.
_PLAYFUL_CHANCE = 0.6


@dataclass(frozen=True, slots=True)
class EngagementThresholds:
    """Tunable appetite thresholds (injected from ``engagement.*`` config).

    ``interesting`` — interest at/above which a topic clears even a low mood;
    ``high_fatigue`` — fatigue at/above which Bob winds chatter down ("наскучило");
    ``low_mood`` — valence at/below which the bar for "какие-попало" topics is raised;
    ``bright_mood`` — valence at/above which a good mood unlocks playful banter;
    ``playful_chance`` — probability a bright-mood FULL turn tips into PLAYFUL.
    The defaults keep a normal mood fully engaging on any non-trivial topic.
    """

    interesting: float = _DEFAULT_INTERESTING
    high_fatigue: float = _DEFAULT_HIGH_FATIGUE
    low_mood: float = _DEFAULT_LOW_MOOD
    bright_mood: float = _DEFAULT_BRIGHT_MOOD
    playful_chance: float = _PLAYFUL_CHANCE


def decide_engagement(
    *,
    mood: Mood,
    topic_interest: float,
    fatigue: ConversationalFatigue,
    relationship: Relationship | None = None,
    rng: Random,
    thresholds: EngagementThresholds | None = None,
) -> EngagementLevel:
    """Decide Bob's appetite to converse THIS turn — pure, deterministic by seed.

    The four human scenarios this realises:

    1. **Good mood → can play along.** A bright mood on an at-least-mildly-interesting
       topic yields :data:`~EngagementLevel.FULL`, and a seeded draw tips it to
       :data:`~EngagementLevel.PLAYFUL` (banter / "ни о чём").
    2. **Aimless chatter bores him.** High ``fatigue`` (built up over aimless turns)
       winds him down to :data:`~EngagementLevel.TERSE`, and to
       :data:`~EngagementLevel.DECLINE` once an uninteresting topic compounds it.
    3. **Bad mood → high threshold.** A low mood raises the interest bar, so a
       "какие-попало" (low-interest) topic gets :data:`~EngagementLevel.TERSE`/
       :data:`~EngagementLevel.DECLINE` from the start.
    4. **Interesting topic overrides a bad mood.** Interest at/above the ``interesting``
       bar engages Bob (:data:`~EngagementLevel.FULL`) even in a low mood — and a good
       exchange can lift his mood (see :func:`engagement_mood_lift`).

    Closeness (``relationship`` warmth + compatibility) shifts the interest bar a
    little: a close person lowers it (Bob plays along more readily), a cratered/hostile
    relationship RAISES it (BOB-014 .2b guest-disengage — Bob winds down with a person
    he has soured on, recovering as the relationship does). One RNG draw resolves the
    PLAYFUL boundary; it is ALWAYS taken so the stream position stays stable whatever
    branch runs, keeping the turn reproducible under a fixed seed.
    """
    bands = thresholds if thresholds is not None else EngagementThresholds()
    # The PLAYFUL draw is taken unconditionally up front so a fixed seed yields the
    # same stream position regardless of which branch the heuristic takes.
    playful_roll = rng.random()

    interest = _clamp(topic_interest)
    bar = _clamp(bands.interesting - _relationship_bar_shift(relationship))
    interesting = interest >= bar
    bored = fatigue.level >= bands.high_fatigue
    low_mood = mood.valence <= bands.low_mood
    bright = mood.valence >= bands.bright_mood and mood.openness >= 0.0

    # Fatigue first: prolonged aimless chatter winds Bob down. An interesting topic
    # still earns a terse-but-present reply; a boring one when he is bored is declined.
    if bored:
        return EngagementLevel.TERSE if interesting else EngagementLevel.DECLINE

    # An interesting topic engages him fully — this is what overrides a low mood.
    if interesting:
        if bright and playful_roll < bands.playful_chance:
            return EngagementLevel.PLAYFUL
        return EngagementLevel.FULL

    # Uninteresting ("какие-попало") topic: a low mood raises the bar so he declines it;
    # otherwise he stays present but terse — no appetite, but not a brush-off.
    if low_mood:
        return EngagementLevel.DECLINE
    return EngagementLevel.TERSE


def _relationship_bar_shift(relationship: Relationship | None) -> float:
    """How the relationship shifts Bob's interest bar — signed, pure (BOB-014).

    Positive when CLOSE (positive warmth + compatibility): closeness shaves a small,
    bounded amount OFF the ``interesting`` threshold, so Bob plays along more readily
    with someone he is close to. NEGATIVE when CRATERED (a soured, hostile relationship,
    BOB-014 .2b guest-disengage): a very negative warmth + compatibility RAISES the bar
    instead, so Bob disengages (terse / winds down) from a person he has soured on —
    keyed on THAT person's cratered relationship, and recovers as the relationship does
    (no permanent block). A neutral relationship (or none) shifts nothing. Bounded both
    ways by :data:`_RELATIONSHIP_BAR_DISCOUNT`.
    """
    if relationship is None:
        return 0.0
    closeness = (relationship.warmth + relationship.compatibility) / 2.0
    return _RELATIONSHIP_BAR_DISCOUNT * closeness


# Recovery rate of the fatigue reservoir per second of elapsed time. At ~1/3600 it
# unwinds over roughly an hour of conversation winding down — slow enough that a long
# aimless run actually reads as "наскучило", fast enough that appetite always recovers.
_FATIGUE_DECAY_PER_SECOND = 1.0 / 3600.0

# How much one aimless, low-interest turn adds to fatigue — small, so a single dull
# message never bores Bob; it accrues only over a sustained pointless run.
_AIMLESS_RISE = 0.15

# How much an interesting turn EASES fatigue on top of time decay — a good exchange
# is restorative, so a genuinely engaging topic actively pulls Bob back from boredom.
_INTEREST_EASE = 0.25


@dataclass(frozen=True, slots=True)
class FatigueRates:
    """Tunable fatigue dynamics (injected from ``engagement.fatigue.*`` config).

    ``decay_per_second`` — how fast fatigue unwinds with elapsed time (guarantees
    recovery, so the owner is never permanently locked out); ``aimless_rise`` — how much
    one aimless low-interest turn adds; ``interest_ease`` — how much an interesting turn
    eases it on top of decay. Defaults make a single dull turn harmless and a sustained
    aimless run boring, while any quiet/interesting stretch restores appetite.
    """

    decay_per_second: float = _FATIGUE_DECAY_PER_SECOND
    aimless_rise: float = _AIMLESS_RISE
    interest_ease: float = _INTEREST_EASE


@dataclass(frozen=True, slots=True)
class ConversationalFatigue:
    """Bob's bounded [0, 1] reservoir of conversational fatigue ("наскучило").

    Rises on aimless, low-interest turns and recedes with elapsed time and on
    interesting turns. Bounded to [0, 1] and ALWAYS decaying with time, so prolonged
    pointless chatter winds Bob down but appetite is guaranteed to recover — the owner
    is never permanently locked out. Pure: elapsed time is passed in (the clock lives
    in the application layer), so it is fully deterministic and unit-testable.
    """

    level: float = _MIN_LEVEL

    def __post_init__(self) -> None:
        if not _MIN_LEVEL <= self.level <= _MAX_LEVEL:
            raise ValueError(
                f"conversational fatigue must be within "
                f"[{_MIN_LEVEL}, {_MAX_LEVEL}], got {self.level}"
            )

    def decayed(
        self, *, elapsed_seconds: float, rates: FatigueRates | None = None
    ) -> ConversationalFatigue:
        """Return the reservoir relaxed by ``elapsed_seconds`` of time (toward 0).

        Decay is linear in elapsed time and saturates at the floor; a longer gap never
        leaves MORE fatigue than a shorter one. This is the recovery guarantee — given
        enough quiet, fatigue returns to zero whatever it was, so appetite always comes
        back and the owner cannot be permanently locked out.
        """
        if elapsed_seconds < 0.0:
            raise ValueError(f"elapsed seconds must be non-negative, got {elapsed_seconds}")
        cfg = rates if rates is not None else FatigueRates()
        return ConversationalFatigue(
            _clamp(self.level - elapsed_seconds * cfg.decay_per_second)
        )

    def after_turn(
        self, *, interesting: bool, rates: FatigueRates | None = None
    ) -> ConversationalFatigue:
        """Return the reservoir after one turn: an aimless turn tires, interest eases.

        An uninteresting ("какие-попало") turn adds a small ``aimless_rise`` — fatigue
        accrues only over a sustained dull run, never from one message. An interesting
        turn instead EASES fatigue (a good exchange is restorative). Bounded to [0, 1].
        Apply :meth:`decayed` for the elapsed-time component separately.
        """
        cfg = rates if rates is not None else FatigueRates()
        if interesting:
            return ConversationalFatigue(_clamp(self.level - cfg.interest_ease))
        return ConversationalFatigue(_clamp(self.level + cfg.aimless_rise))


# How much a genuinely interesting, well-going exchange lifts Bob's mood valence — a
# small bounded nudge (a good chat brightens him a little), applied by the application
# as a MoodDelta. Kept small so it accrues over a real exchange, never jolts.
_DEFAULT_ENGAGEMENT_MOOD_LIFT = 0.1


def engagement_mood_lift(
    level: EngagementLevel, *, interesting: bool, lift: float = _DEFAULT_ENGAGEMENT_MOOD_LIFT
) -> float:
    """Return the small mood-valence lift a good, interesting exchange earns (pure).

    Scenario 4's feedback loop: an interesting topic Bob actually engaged with
    (:data:`~EngagementLevel.FULL`/:data:`~EngagementLevel.PLAYFUL`) brightens him a
    little — a small bounded valence ``lift`` the application folds into the mood. A
    terse/declined turn, or an uninteresting topic, earns nothing (``0.0``), so only a
    genuinely good exchange feeds back. Deterministic: same inputs → same lift.
    """
    engaged = level in (EngagementLevel.FULL, EngagementLevel.PLAYFUL)
    return lift if engaged and interesting else 0.0
