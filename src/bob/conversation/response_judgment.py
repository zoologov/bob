# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Pure Tier-0 wire protocol for the response-judgment seam (BOB-049).

The model-facing half of the seam, kept pure (no I/O, no RNG) so it is unit-
testable without a model and the infrastructure adapter stays a thin shell:

* :func:`build_judgment_user_prompt` — fold a :class:`ResponseContext` (message +
  sender social context + per-person thread + structural hints + mood tone) into
  the Tier-0 user prompt; :data:`RESPONSE_JUDGE_SYSTEM_PROMPT` states the task and
  the labelled output contract.
* :func:`parse_response_choice` — map the model's reply to a
  :class:`ResponseChoice` (robust to whitespace/case; raising
  :class:`ResponseJudgeParseError` on garbage rather than silently defaulting, so
  .3's retry/GUPPI-notice path can catch a real failure).
* :func:`validate_reaction_emoji` — validate an emoji against the Telegram
  free-reaction set (reused from :mod:`~bob.personality.reaction`),
  normalising a trailing variation selector; an out-of-set emoji yields ``None``
  (the parser then substitutes :data:`DEFAULT_WARM_EMOJI` for a REACT turn).
"""

from __future__ import annotations

import re

from bob.conversation.response_choice import (
    ResponseChoice,
    ResponseContext,
    ResponseIntent,
)
from bob.personality.reaction import STANDARD_REACTION_EMOJI

__all__ = [
    "DEFAULT_WARM_EMOJI",
    "RESPONSE_JUDGE_SYSTEM_PROMPT",
    "ResponseJudgeParseError",
    "build_judgment_user_prompt",
    "parse_response_choice",
    "validate_reaction_emoji",
]

# A warm, in-set emoji used when a REACT turn carries no valid emoji (the model
# omitted one or returned one outside the free-reaction set).
DEFAULT_WARM_EMOJI = "🥰"

# Unicode variation selectors a client may append to an emoji (text/emoji presentation,
# U+FE0E / U+FE0F). Telegram's free-reaction set stores the bare codepoint, so we strip
# these before comparing.
_VARIATION_SELECTORS = "︎️"

# Labelled-line prefixes the parser recognises (case-insensitive, whitespace-tolerant).
_INTENT_LABEL = re.compile(r"^\s*intent\s*:\s*(.+)$", re.IGNORECASE)
_EMOJI_LABEL = re.compile(r"^\s*emoji\s*:\s*(.+)$", re.IGNORECASE)
_REASON_LABEL = re.compile(r"^\s*reason\s*:\s*(.+)$", re.IGNORECASE)

# Punctuation trimmed off the model's intent word before matching the enum.
_WORD_TRIM = " \t\n.!?,:;'\"*-"

RESPONSE_JUDGE_SYSTEM_PROMPT = (
    "You are Bob deciding, as a person, how to respond socially to ONE incoming "
    "message in its context. Understand the message by MEANING — the structural "
    "hints (mention, reply, addressivity, others present, conversation floor) are "
    "signals to weigh, NOT rules; they never force an answer, whoever the sender "
    "is. Choose exactly one intent:\n"
    "- reply: answer in words (the message wants or deserves a spoken response);\n"
    "- react: set a single emoji reaction instead of words (you read it and want "
    "to mark presence warmly, but words aren't needed);\n"
    "- ignore: stay silent (you read it; it isn't addressed to you and wants no "
    "response).\n"
    "Reply in exactly this labelled format, nothing else:\n"
    "intent: <reply|react|ignore>\n"
    "emoji: <one emoji, only when intent is react>\n"
    "reason: <a short phrase explaining why>"
)


class ResponseJudgeParseError(ValueError):
    """Raised when the model's reply cannot be parsed into a :class:`ResponseChoice`.

    A real failure signal (not a silent default): the infrastructure judge lets it
    propagate so .3's bounded-retry / GUPPI-notice path handles it — Bob never
    answers from garbage.
    """


def build_judgment_user_prompt(ctx: ResponseContext) -> str:
    """Fold ``ctx`` into the Tier-0 user prompt (pure).

    Includes the incoming message, the sender as social context (kind + name +
    trust), the recent per-person thread, the structural hints (addressivity /
    mention / reply / others-present / floor) and the mood tone — everything the
    judge weighs by meaning.
    """
    sender = ctx.interlocutor
    lines = [
        "Sender (social context, NOT an override):",
        f"  name: {sender.display_name}",
        f"  kind: {sender.kind.value}",
        f"  trust: {sender.trust.value}",
        "",
        "Recent thread with this person:",
        ctx.recent_thread or "  (none)",
        "",
        "Structural hints (signals only):",
        f"  addressivity: {ctx.addressivity.value}",
        f"  mentions_bob: {_yes_no(ctx.mentions_bob)}",
        f"  reply_to_bob: {_yes_no(ctx.reply_to_bob)}",
        f"  others_present: {_yes_no(ctx.others_present)}",
        f"  floor_engaged: {_yes_no(ctx.floor_engaged)}",
        "",
        f"Bob's current mood tone: {ctx.mood_tone}",
        "",
        "Incoming message:",
        ctx.text,
    ]
    return "\n".join(lines)


def _yes_no(value: bool) -> str:
    """Render a boolean hint as a compact yes/no for the prompt."""
    return "yes" if value else "no"


def parse_response_choice(raw: str) -> ResponseChoice:
    """Parse the model's reply into a :class:`ResponseChoice` (robust, no defaulting).

    Accepts the labelled format (``intent:`` / ``emoji:`` / ``reason:``) and, as a
    fallback, a bare reply whose first recognisable token is an intent word.
    Whitespace/case are tolerated. On a REACT turn the emoji is validated against
    the free-reaction set, substituting :data:`DEFAULT_WARM_EMOJI` when it is
    missing or out of set. A reply with no recognisable intent raises
    :class:`ResponseJudgeParseError`.
    """
    intent_text, emoji_text, reason_text = _scan_labels(raw)
    intent = _parse_intent(intent_text if intent_text is not None else raw)
    if intent is None:
        raise ResponseJudgeParseError(f"no recognisable intent in: {raw!r}")
    emoji = _react_emoji(emoji_text, raw) if intent is ResponseIntent.REACT else None
    reason = (reason_text or "").strip()
    return ResponseChoice(intent=intent, emoji=emoji, reason=reason)


def _scan_labels(raw: str) -> tuple[str | None, str | None, str | None]:
    """Extract the intent / emoji / reason label values from ``raw`` (any may be None)."""
    intent_text: str | None = None
    emoji_text: str | None = None
    reason_text: str | None = None
    for line in raw.splitlines():
        if intent_text is None and (m := _INTENT_LABEL.match(line)):
            intent_text = m.group(1)
        elif emoji_text is None and (m := _EMOJI_LABEL.match(line)):
            emoji_text = m.group(1)
        elif reason_text is None and (m := _REASON_LABEL.match(line)):
            reason_text = m.group(1)
    return intent_text, emoji_text, reason_text


def _parse_intent(text: str) -> ResponseIntent | None:
    """Find the first intent keyword in ``text`` (label value or bare reply)."""
    for token in text.split():
        word = token.strip(_WORD_TRIM).casefold()
        for intent in ResponseIntent:
            if word == intent.value:
                return intent
    return None


def _react_emoji(emoji_text: str | None, raw: str) -> str:
    """Resolve the emoji for a REACT turn (validated label, else scanned, else warm default).

    Prefers the validated ``emoji:`` label; if that is missing or out of set, scans
    the whole reply for the first in-set emoji (a bare ``react ❤`` reply); finally
    falls back to :data:`DEFAULT_WARM_EMOJI` so a REACT turn always carries a valid
    emoji.
    """
    return (
        validate_reaction_emoji(emoji_text)
        or _scan_for_emoji(raw)
        or DEFAULT_WARM_EMOJI
    )


def _scan_for_emoji(raw: str) -> str | None:
    """Return the first in-set reaction emoji found among ``raw``'s tokens, else None."""
    for token in raw.split():
        valid = validate_reaction_emoji(token)
        if valid is not None:
            return valid
    return None


def validate_reaction_emoji(raw: str | None) -> str | None:
    """Validate ``raw`` against the Telegram free-reaction set (pure).

    Strips surrounding whitespace and a trailing variation selector, then checks
    membership in :data:`~bob.personality.reaction.STANDARD_REACTION_EMOJI`.
    Returns the normalised in-set emoji, or ``None`` when ``raw`` is empty or out
    of set (the caller decides the fallback).
    """
    if raw is None:
        return None
    normalised = raw.strip().strip(_VARIATION_SELECTORS)
    if normalised and normalised in STANDARD_REACTION_EMOJI:
        return normalised
    return None
