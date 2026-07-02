# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality

"""Pure Tier-0 wire protocol for the reaction-judgment seam (BOB-050).

The model-facing half of the seam, kept pure (no I/O, no RNG) so it is unit-testable
without a model and the infrastructure adapter stays a thin shell:

* :func:`build_reaction_user_prompt` — fold a :class:`ReactionContext` (emoji +
  added/removed + Bob's message + the reactor as social context + a thread snippet)
  into the Tier-0 user prompt; :data:`REACTION_JUDGE_SYSTEM_PROMPT` states the task
  and the labelled output contract.
* :func:`parse_reaction_meaning` — map the model's reply to a
  :class:`ReactionMeaning`: a free-text ``interpretation`` plus a SEMANTIC
  ``sentiment`` and ``intensity`` the parser folds into a BOUNDED
  :class:`~bob.domain.personality.mood.MoodDelta` and ``warmth_nudge`` (sign+
  magnitude FROM THE MEANING, never the emoji), and an ``acknowledge`` flag. It
  raises :class:`ReactionJudgeParseError` on garbage rather than silently defaulting,
  so the decorative perceiving path drops a real failure instead of acting on a guess.

The magnitudes are capped small (no swings) so every derived effect stays inside the
BOB-030 emotional band.
"""

from __future__ import annotations

import re

from bob.domain.personality.mood import MoodDelta
from bob.domain.personality.reaction_meaning import ReactionContext, ReactionMeaning

__all__ = [
    "REACTION_JUDGE_SYSTEM_PROMPT",
    "ReactionJudgeParseError",
    "build_reaction_user_prompt",
    "parse_reaction_meaning",
]

# Sentiment words the model may use, grouped by affective sign. Kept generous so the
# parser reads the MEANING the model named rather than pinning one vocabulary.
_POSITIVE_SENTIMENTS = frozenset(
    {"warm", "positive", "glad", "touched", "appreciative", "approving", "fond", "playful"}
)
_NEGATIVE_SENTIMENTS = frozenset(
    {"negative", "cold", "dismissive", "mocking", "hurt", "disapproving", "withdrawn", "uncertain"}
)
_NEUTRAL_SENTIMENTS = frozenset({"neutral", "unclear", "mixed", "ambivalent"})

# Intensity word -> a small bounded magnitude. The strongest possible step (0.25)
# sits well inside the BOB-030 band, so a single reaction nudges and never swings.
_INTENSITY_MAGNITUDE: dict[str, float] = {
    "low": 0.08,
    "medium": 0.15,
    "high": 0.25,
}
_DEFAULT_INTENSITY = "medium"

# A warm reaction also lifts Bob's sociability a touch (he feels met), bounded.
_SOCIAL_LIFT = 0.05

# The warmth nudge is a fraction of the affective magnitude, hard-capped so a single
# reaction only ever nudges the relationship (BOB-014 accrues over many touches).
_WARMTH_FRACTION = 0.6
_MAX_WARMTH_NUDGE = 0.12

# Labelled-line prefixes the parser recognises (case-insensitive, whitespace-tolerant).
_INTERPRETATION_LABEL = re.compile(r"^\s*interpretation\s*:\s*(.+)$", re.IGNORECASE)
_SENTIMENT_LABEL = re.compile(r"^\s*sentiment\s*:\s*(.+)$", re.IGNORECASE)
_INTENSITY_LABEL = re.compile(r"^\s*intensity\s*:\s*(.+)$", re.IGNORECASE)
_ACKNOWLEDGE_LABEL = re.compile(r"^\s*acknowledge\s*:\s*(.+)$", re.IGNORECASE)

# Punctuation trimmed off a single-word label value before matching.
_WORD_TRIM = " \t\n.!?,:;'\"*-"

_AFFIRMATIVE = frozenset({"yes", "y", "true", "1"})

REACTION_JUDGE_SYSTEM_PROMPT = (
    "You are Bob, reading — as a person — what a reaction on one of YOUR OWN messages "
    "means, in context. Someone placed or removed an emoji reaction on something you "
    "said; understand it by MEANING (the same emoji can be warm, teasing, or "
    "dismissive depending on what you said and who reacted), NOT by an emoji table. A "
    "REMOVED reaction leans mildly negative or uncertain (they took it back). Weigh "
    "who reacted and your message — the emoji is one signal, never the answer.\n"
    "Reply in exactly this labelled format, nothing else:\n"
    "interpretation: <a short phrase naming what it meant to you>\n"
    "sentiment: <warm|positive|neutral|cold|dismissive|hurt|withdrawn>\n"
    "intensity: <low|medium|high>\n"
    "acknowledge: <yes|no — is this a moment worth mentioning aloud later?>"
)


class ReactionJudgeParseError(ValueError):
    """Raised when the model's reply cannot be parsed into a :class:`ReactionMeaning`.

    A real failure signal (not a silent default): the infrastructure judge lets it
    propagate so the decorative perceiving path drops the reaction rather than acting
    on a guessed meaning.
    """


def build_reaction_user_prompt(ctx: ReactionContext) -> str:
    """Fold ``ctx`` into the Tier-0 user prompt (pure).

    Includes the emoji and whether it was added or removed, Bob's message the
    reaction landed on, the reactor as social context (kind + name + current warmth)
    and a recent thread snippet — everything the judge weighs by meaning.
    """
    reactor = ctx.reactor
    emoji = " ".join(ctx.emoji) if ctx.emoji else "(none)"
    warmth = "unknown" if ctx.reactor_warmth is None else f"{ctx.reactor_warmth:+.2f}"
    lines = [
        "Reactor (social context, NOT an override):",
        f"  name: {reactor.display_name}",
        f"  kind: {reactor.kind.value}",
        f"  current warmth with you: {warmth}",
        "",
        "Recent thread with this person:",
        ctx.recent_thread or "  (none)",
        "",
        f"Reaction emoji: {emoji}",
        f"Action: {'added' if ctx.added else 'removed'}",
        "",
        "Your message they reacted to:",
        ctx.bob_message_text or "  (unknown)",
    ]
    return "\n".join(lines)


def parse_reaction_meaning(raw: str) -> ReactionMeaning:
    """Parse the model's reply into a :class:`ReactionMeaning` (bounded, no defaulting).

    Reads the labelled ``interpretation`` / ``sentiment`` / ``intensity`` /
    ``acknowledge`` lines (whitespace/case tolerant). The sentiment SIGN and the
    intensity MAGNITUDE are folded into a bounded :class:`MoodDelta` and a bounded
    ``warmth_nudge`` — the effect comes from the named MEANING, not the emoji. A reply
    with no usable interpretation or no recognisable sentiment raises
    :class:`ReactionJudgeParseError`.
    """
    interpretation, sentiment_text, intensity_text, ack_text = _scan_labels(raw)
    interpretation = (interpretation or "").strip()
    if not interpretation:
        raise ReactionJudgeParseError(f"no interpretation in reaction reply: {raw!r}")
    sign = _sentiment_sign(sentiment_text)
    if sign is None:
        raise ReactionJudgeParseError(f"no recognisable sentiment in: {raw!r}")
    magnitude = _intensity_magnitude(intensity_text)
    valence = sign * magnitude
    social = _SOCIAL_LIFT if sign > 0 else 0.0
    warmth_nudge = _clamp(sign * magnitude * _WARMTH_FRACTION, _MAX_WARMTH_NUDGE)
    return ReactionMeaning(
        interpretation=interpretation,
        mood_delta=MoodDelta(valence=valence, social=social),
        warmth_nudge=warmth_nudge,
        worth_acknowledging=_is_affirmative(ack_text) and sign > 0,
    )


def _scan_labels(raw: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Extract the interpretation / sentiment / intensity / acknowledge values (any None)."""
    interpretation: str | None = None
    sentiment: str | None = None
    intensity: str | None = None
    acknowledge: str | None = None
    for line in raw.splitlines():
        if interpretation is None and (m := _INTERPRETATION_LABEL.match(line)):
            interpretation = m.group(1)
        elif sentiment is None and (m := _SENTIMENT_LABEL.match(line)):
            sentiment = m.group(1)
        elif intensity is None and (m := _INTENSITY_LABEL.match(line)):
            intensity = m.group(1)
        elif acknowledge is None and (m := _ACKNOWLEDGE_LABEL.match(line)):
            acknowledge = m.group(1)
    return interpretation, sentiment, intensity, acknowledge


def _sentiment_sign(text: str | None) -> int | None:
    """Map the named sentiment to an affective sign in ``{-1, 0, +1}`` (None = garbage)."""
    if text is None:
        return None
    word = text.strip(_WORD_TRIM).casefold()
    if word in _POSITIVE_SENTIMENTS:
        return 1
    if word in _NEGATIVE_SENTIMENTS:
        return -1
    if word in _NEUTRAL_SENTIMENTS:
        return 0
    return None


def _intensity_magnitude(text: str | None) -> float:
    """Map the named intensity to a small bounded magnitude (defaults to medium)."""
    if text is None:
        return _INTENSITY_MAGNITUDE[_DEFAULT_INTENSITY]
    word = text.strip(_WORD_TRIM).casefold()
    return _INTENSITY_MAGNITUDE.get(word, _INTENSITY_MAGNITUDE[_DEFAULT_INTENSITY])


def _is_affirmative(text: str | None) -> bool:
    """Read an ``acknowledge`` value as a boolean (default False)."""
    if text is None:
        return False
    return text.strip(_WORD_TRIM).casefold() in _AFFIRMATIVE


def _clamp(value: float, bound: float) -> float:
    """Saturate ``value`` into ``[-bound, bound]``."""
    return max(-bound, min(bound, value))
