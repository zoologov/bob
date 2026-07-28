# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the persona language directive (BOB-012).

Self-generated text (proactive compose, the Tier-0 gate, the inner monologue and
the reflection ticks) has no user message to mirror, so without an explicit
language constraint the model drifts to English. ``language_directive`` produces
the short, imperative directive that pins Bob to his configured language; these
tests pin the contract (Russian by default, a known directive per language, a
safe fallback for an unknown code) on the pure helper.
"""

from __future__ import annotations

from bob.personality.language import DEFAULT_LANGUAGE, language_directive


def test_default_language_is_russian() -> None:
    # The persona speaks Russian unless a replica overrides it.
    assert DEFAULT_LANGUAGE == "ru"


def test_russian_directive_is_in_russian() -> None:
    directive = language_directive("ru")
    # The directive must itself be Russian so the model reads it natively.
    assert "по-русски" in directive.casefold()


def test_english_directive_is_in_english() -> None:
    directive = language_directive("en")
    assert "english" in directive.casefold()


def test_unknown_language_falls_back_to_a_generic_directive_naming_the_code() -> None:
    # An unconfigured replica language still gets a directive that names the code,
    # so the model is constrained rather than left to default to English.
    directive = language_directive("fr")
    assert directive.strip() != ""
    assert "fr" in directive.casefold()
