# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=domain

"""ExpressionPlan — Bob's per-turn plan for *how* he expresses himself (BOB-018).

Before composing a reply, Bob decides — as character, not config — a plan for the
turn: a *mode* (a full :data:`ExpressionMode.REPLY` vs. a terse
:data:`ExpressionMode.REACT_ONLY` acknowledgement) plus the rare add-on flags
(``leak_inner_life`` / ``callback``) and a soft :class:`FormHint`
(terse/normal/expansive). The decision is a **pure, deterministic heuristic on
mood + the turn's signals + an injected seeded RNG** — like
:func:`~bob.application.router.reply_tier_selector.select_reply_tier`, but it
also draws once per rare flag from the RNG so a fixed seed makes the whole plan
reproducible. No LLM (cheap, testable).

State drives form and mode: a low-energy/withdrawn mood on a short, low-signal
inbound pulls toward terse and raises the chance of a react-only turn, while a
bright, open mood on a substantive inbound allows an expansive full reply. A
substantive inbound (a real question wanting an answer) is **never** downgraded
to react-only. The rare flags stay rare by construction — their fire chance is a
small, configurable :class:`ExpressionFreqs` frequency, so they read as
occasional spontaneity, not a tic.

This is the foundation seam: the ``leak_inner_life`` / ``callback`` flags and the
``REACT_ONLY`` mode are carried on the plan for later beads to ground (grounded
inner-life/callbacks and native reactions); here the plan is computed and its
``form_hint`` shapes the reply.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from random import Random

    from bob.personality.mood import Mood

# Below this much arousal, Bob is low-energy: he leans terse and is likelier to
# react rather than compose a full reply. Above the bright threshold, with an open
# mood, a substantive turn may expand.
_LOW_AROUSAL = -0.25
_BRIGHT_AROUSAL = 0.35

# An inbound at or under this many characters is "short" — a low-signal turn that,
# in a low-energy state, can resolve to a brief reaction rather than a full reply.
_SHORT_INBOUND_CHARS = 8

# A substantive inbound (longer than this, or carrying a question) always earns a
# full reply and can support an expansive form when the mood is bright.
_SUBSTANTIVE_INBOUND_CHARS = 40

# Extra react-only chance granted by a withdrawn, low-energy state on a short
# inbound — small, so most low-energy turns still reply (anti-tic).
_REACT_ONLY_CHANCE = 0.35

# Frequencies are probabilities, bounded to the closed unit interval.
_MIN_FREQ = 0.0
_MAX_FREQ = 1.0

# Small default fire chances for the rare add-ons — occasional spontaneity, never
# a per-message tic. Tunable per persona via config (``expression.freqs.*``).
_DEFAULT_LEAK_FREQ = 0.12
_DEFAULT_CALLBACK_FREQ = 0.1

# How often Bob, à propos, surfaces his CURRENT fascination (BOB-020) — small, so
# it reads as occasional spontaneity, never a per-message tic. No fascination → the
# compose path no-ops regardless. Tunable via ``emotion.fascination.mention_freq``.
_DEFAULT_MENTION_FASCINATION_FREQ = 0.1


class ExpressionMode(Enum):
    """Whether Bob composes a full reply or a terse react-only acknowledgement."""

    REPLY = "reply"
    REACT_ONLY = "react_only"


class FormHint(Enum):
    """A soft length/shape hint for the reply — augments anti-bait, never replaces it."""

    TERSE = "terse"
    NORMAL = "normal"
    EXPANSIVE = "expansive"


class Verbosity(Enum):
    """Финальная развёрнутость хода — сколько Боб напишет (решение, не сигнал).

    Грань выразительного вокабуляра — насколько развёрнуто характер выражается на
    этом ходе. Живёт в :mod:`expression` подле :class:`FormHint`/:class:`ExpressionMode`;
    вычисляющая логика (:func:`~bob.conversation.brevity.decide_verbosity`)
    зависит от этого enum — правильное направление conversation→personality.

    * :data:`TERSE` — одной фразой, без преамбул/списков.
    * :data:`NORMAL` — нейтральная длина.
    * :data:`EXPANSIVE` — можно развернуться.
    """

    TERSE = "terse"
    NORMAL = "normal"
    EXPANSIVE = "expansive"


class EngagementLevel(Enum):
    """How much appetite Bob has to converse THIS turn, strongest to weakest.

    A facet of Bob's expressive vocabulary: HOW engaged the character is on this
    turn. It lives in :mod:`expression` beside :class:`Verbosity`/:class:`FormHint`;
    the deciding logic (:func:`~bob.conversation.engagement.decide_engagement`)
    DEPENDS ON this enum — the personality-inward direction (conversation→personality).

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


@dataclass(frozen=True, slots=True)
class ExpressionSignals:
    """The per-turn signals the decider reads beyond mood (pure inputs).

    ``inbound_text`` is the incoming user message (its length/shape is a signal);
    ``idle_seconds`` is the silence before it. Kept minimal and extensible — later
    beads may add signals without changing the decider's call shape.
    """

    inbound_text: str
    idle_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class ExpressionFreqs:
    """Small, configurable fire chances for the rare add-on flags (anti-tic).

    Each is a probability in ``[0, 1]``: ``0`` is a hard off switch (the flag never
    fires) and larger values fire it more often. Defaults are deliberately small so
    the add-ons read as occasional spontaneity, not a tic.
    """

    leak_inner_life: float = _DEFAULT_LEAK_FREQ
    callback: float = _DEFAULT_CALLBACK_FREQ
    mention_fascination: float = _DEFAULT_MENTION_FASCINATION_FREQ

    def __post_init__(self) -> None:
        for name in ("leak_inner_life", "callback", "mention_fascination"):
            value = getattr(self, name)
            if not _MIN_FREQ <= value <= _MAX_FREQ:
                raise ValueError(
                    f"expression frequency '{name}' must be within "
                    f"[{_MIN_FREQ}, {_MAX_FREQ}], got {value}"
                )


@dataclass(frozen=True, slots=True)
class ExpressionPlan:
    """Bob's plan for how he expresses this turn (mode + rare flags + form hint)."""

    mode: ExpressionMode
    leak_inner_life: bool
    callback: bool
    mention_fascination: bool
    form_hint: FormHint


def decide_expression(
    mood: Mood,
    signals: ExpressionSignals,
    *,
    rng: Random,
    freqs: ExpressionFreqs,
) -> ExpressionPlan:
    """Decide the expression plan for this turn — pure, deterministic by seed.

    Mood + the inbound's shape drive the form hint and the react-only chance; an
    injected seeded ``rng`` resolves the react-only draw and the two rare-flag
    draws, so an equal ``(mood, signals, seed, freqs)`` always yields an equal
    plan. A substantive inbound is never downgraded to react-only.

    The draw ORDER is fixed (react mode, then leak, callback, mention-fascination)
    so the plan is stable under a fixed seed regardless of which branch is taken.
    """
    form_hint = _form_hint(mood, signals)
    mode = _mode(mood, signals, rng=rng)
    leak = _draw(rng, freqs.leak_inner_life)
    callback = _draw(rng, freqs.callback)
    mention_fascination = _draw(rng, freqs.mention_fascination)
    return ExpressionPlan(
        mode=mode,
        leak_inner_life=leak,
        callback=callback,
        mention_fascination=mention_fascination,
        form_hint=form_hint,
    )


def _mode(mood: Mood, signals: ExpressionSignals, *, rng: Random) -> ExpressionMode:
    """Pick the turn mode: a brief reaction only on a low-energy, low-signal turn.

    The draw is always taken (even when the state can't reach react-only) so the
    later rare-flag draws keep a stable position in the RNG stream — the decision
    stays deterministic by seed whichever branch runs.
    """
    roll = rng.random()
    if _is_substantive(signals.inbound_text):
        return ExpressionMode.REPLY
    react_leaning = _is_low_energy(mood) and _is_short(signals.inbound_text)
    if react_leaning and roll < _REACT_ONLY_CHANCE:
        return ExpressionMode.REACT_ONLY
    return ExpressionMode.REPLY


def _form_hint(mood: Mood, signals: ExpressionSignals) -> FormHint:
    """Map mood + inbound shape to a soft length hint (state-driven, no RNG)."""
    if _is_low_energy(mood) and _is_short(signals.inbound_text):
        return FormHint.TERSE
    if _is_bright(mood) and _is_substantive(signals.inbound_text):
        return FormHint.EXPANSIVE
    return FormHint.NORMAL


def _draw(rng: Random, frequency: float) -> bool:
    """Fire a rare flag with probability ``frequency`` (a hard off at 0)."""
    if frequency <= _MIN_FREQ:
        return False
    return rng.random() < frequency


def _is_low_energy(mood: Mood) -> bool:
    """A withdrawn, low-arousal state — leans terse and react-only."""
    return mood.arousal < _LOW_AROUSAL


def _is_bright(mood: Mood) -> bool:
    """A high-arousal, open state — can support an expansive reply."""
    return mood.arousal > _BRIGHT_AROUSAL and mood.openness >= 0.0


def _is_short(text: str) -> bool:
    """A short, low-signal inbound (length only — no question, no depth)."""
    return len(text.strip()) <= _SHORT_INBOUND_CHARS


def _is_substantive(text: str) -> bool:
    """A real inbound wanting an answer: long enough, or carrying a question."""
    stripped = text.strip()
    return len(stripped) >= _SUBSTANTIVE_INBOUND_CHARS or "?" in stripped
