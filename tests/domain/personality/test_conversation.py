# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the user-repeat detection predicate (BOB-022).

A pure, conservative predicate: does the OWNER's current message exactly repeat
(after normalisation) something they already said in the recent window? It is
deliberately EXACT-after-normalise (strip / casefold / collapse internal
whitespace), never fuzzy, so it can never false-fire on a merely-similar turn.
"""

from __future__ import annotations

from bob.domain.personality.conversation import is_user_repeat


def test_exact_repeat_of_a_recent_user_turn_is_a_repeat() -> None:
    assert is_user_repeat("как ты?", ["привет", "как ты?"]) is True


def test_a_different_message_is_not_a_repeat() -> None:
    assert is_user_repeat("чем занят?", ["привет", "как ты?"]) is False


def test_case_variation_is_still_a_repeat() -> None:
    assert is_user_repeat("КАК ТЫ?", ["как ты?"]) is True  # noqa: RUF001


def test_surrounding_and_internal_whitespace_is_normalised() -> None:
    assert is_user_repeat("  как   ты?  ", ["как ты?"]) is True


def test_empty_current_text_is_never_a_repeat() -> None:
    assert is_user_repeat("", ["", "  "]) is False


def test_no_prior_user_turns_is_not_a_repeat() -> None:
    assert is_user_repeat("как ты?", []) is False


def test_matches_any_prior_user_turn_in_the_window_not_just_the_last() -> None:
    assert is_user_repeat("первый", ["первый", "второй", "третий"]) is True
