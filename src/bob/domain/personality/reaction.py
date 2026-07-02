# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality

"""Mood→emoji — the pure picker for Bob's native react-only reaction (BOB-018).

On a :data:`~bob.domain.personality.expression.ExpressionMode.REACT_ONLY` turn Bob
sets a native Telegram reaction *instead of* composing a reply (cheap, no LLM). The
emoji is chosen here, deterministically from Bob's current mood — like
:meth:`~bob.domain.personality.mood.Mood.tone`, the same mood always yields the
same emoji, so the choice is testable without a model and reads as character (a
pleased Bob reacts warmly, a glum Bob with a flat acknowledgement) rather than a
random sticker.

The picker is **pure** (no I/O, no RNG) and returns only emoji drawn from
Telegram's **standard reaction set** — custom emoji are a premium feature and out
of scope (RFC Q2), and the standard set is what ``set_message_reaction`` accepts
without a "reaction not allowed" error. The map keys on the deterministic tone
descriptor so a new tone word automatically resolves through the neutral default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.domain.personality.mood import Mood

# A small, safe subset of Telegram's standard reaction set (the emoji a non-premium
# ``set_message_reaction`` accepts). Reactions are restricted to this set so a real
# call never trips the API's allowed-reactions / premium-custom-emoji limits.
STANDARD_REACTION_EMOJI: frozenset[str] = frozenset(
    {"👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "😢", "🎉", "🙏", "😐"}
)

# The neutral fallback emoji — a calm acknowledgement for a flat/unknown tone.
_NEUTRAL_EMOJI = "👍"

# Tone descriptor → standard reaction emoji. Keyed on the deterministic
# :meth:`Mood.tone` word (valence sign by arousal band), so each affective state
# reacts in character: warm when pleased, muted when down. Any tone absent here
# (or a future descriptor) resolves through :data:`_NEUTRAL_EMOJI`.
_EMOJI_BY_TONE: dict[str, str] = {
    "excited": "🔥",
    "cheerful": "😁",
    "content": "🥰",
    "neutral": "👍",
    "agitated": "🤔",
    "glum": "😢",
    "subdued": "🙏",
}


def reaction_emoji_for(mood: Mood) -> str:
    """Pick the standard-reaction emoji for ``mood`` — pure and deterministic.

    Maps the mood's deterministic tone descriptor to an apt emoji from
    :data:`STANDARD_REACTION_EMOJI`; an unmapped tone falls back to the neutral
    acknowledgement. The result is always inside the standard set.
    """
    return _EMOJI_BY_TONE.get(mood.tone(), _NEUTRAL_EMOJI)
