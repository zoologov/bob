# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for mood→emoji — the pure reaction-emoji picker (BOB-018).

A react-only turn (:data:`ExpressionMode.REACT_ONLY`) sets a native Telegram
reaction instead of composing a reply; the emoji is chosen deterministically from
Bob's current mood. The picker is pure (no I/O, no RNG) and only ever returns an
emoji from Telegram's *standard* reaction set, so a real ``set_message_reaction``
never trips the "reaction not allowed" / premium-custom-emoji limits.
"""

from __future__ import annotations

from bob.personality.mood import Mood
from bob.personality.reaction import (
    STANDARD_REACTION_EMOJI,
    reaction_emoji_for,
)


def test_picker_is_deterministic_for_a_given_mood() -> None:
    # Same mood in → same emoji out (pure, no RNG): reproducible by construction.
    mood = Mood(valence=0.6, arousal=0.6)
    assert reaction_emoji_for(mood) == reaction_emoji_for(mood)


def test_every_mood_tone_maps_to_a_standard_reaction_emoji() -> None:
    # Whatever the mood, the chosen emoji is always inside Telegram's standard
    # reaction set — never a custom (premium) emoji that the API would reject.
    moods = [
        Mood(valence=0.6, arousal=0.6),  # excited
        Mood(valence=0.6, arousal=0.0),  # cheerful
        Mood(valence=0.6, arousal=-0.6),  # content
        Mood(),  # neutral
        Mood(valence=-0.6, arousal=0.6),  # agitated
        Mood(valence=-0.6, arousal=0.0),  # glum
        Mood(valence=-0.6, arousal=-0.6),  # subdued
    ]
    for mood in moods:
        assert reaction_emoji_for(mood) in STANDARD_REACTION_EMOJI


def test_positive_and_negative_moods_pick_different_emoji() -> None:
    # The mapping is mood-flavoured, not a single constant: a bright mood and a
    # glum one react with different emoji.
    bright = reaction_emoji_for(Mood(valence=0.6, arousal=0.6))
    glum = reaction_emoji_for(Mood(valence=-0.6, arousal=0.0))
    assert bright != glum


def test_a_positive_mood_reacts_warmly() -> None:
    # A cheerful mood reacts with a warm/affirming standard emoji (not a heart-break
    # or thumbs-down) — the reaction reads as Bob being pleased.
    warm = {"👍", "❤", "🔥", "🥰", "👏", "😁", "🎉", "🤩", "😍"}
    assert reaction_emoji_for(Mood(valence=0.6, arousal=0.0)) in warm
