# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the persona voice directives (BOB-016).

Two persona/voice concerns pinned here as pure helpers, mirroring
``language.py``: the *anti-bait* directive + few-shot that breaks Qwen's RLHF
"end on an engagement-bait question + ☕ signature" tic, and the *GUPPI canon*
that fixes GUPPI's gender (male, "он") and seeds Bob's wry running relationship
with his non-sentient executor. The contract is structural — presence of the
voice guidance, the substance-ending exemplars, and the male-gendered GUPPI
flavor — never a brittle full-string match (the prose is free to evolve).
"""

from __future__ import annotations

from bob.domain.personality.voice import (
    anti_bait_directive,
    guppi_canon,
    variable_form_directive,
)


def test_anti_bait_directive_is_natural_voice_not_a_rule_list() -> None:
    directive = anti_bait_directive()
    folded = directive.casefold()
    # It guides HOW Bob ends a thought (no fishing for continuation) as voice,
    # and it never reads like a numbered/bulleted rule list Bob could recite.
    assert "вопрос" in folded  # talks about when (not) to ask a question
    assert "•" not in directive
    assert "- " not in directive


def test_anti_bait_directive_addresses_the_emoji_signature_tic() -> None:
    # The ☕ "sign every message" reflex is named so the model drops it.
    folded = anti_bait_directive().casefold()
    assert "эмодзи" in folded or "emoji" in folded


def test_anti_bait_directive_carries_substance_ending_exemplars() -> None:
    # The few-shot is what actually breaks the tic: at least one short exemplar
    # Bob line that ENDS ON SUBSTANCE — no trailing question, no ☕ signature.
    directive = anti_bait_directive()
    assert "☕" not in directive  # the exemplars must not model the signature
    # An exemplar line exists and does not end on a question mark.
    exemplars = _exemplar_lines(directive)
    assert exemplars, "no few-shot exemplar lines found"
    assert all(not line.rstrip().endswith("?") for line in exemplars)


def test_guppi_canon_establishes_male_gender() -> None:
    # GUPPI is "он": Bob must refer to him in the masculine, never "она"/"её".
    canon = guppi_canon()
    tokens = {t.strip(".,:;«»()—-") for t in canon.casefold().split()}
    assert "он" in tokens  # the masculine pronoun is present as its own word
    # No feminine agreement for GUPPI leaks into the canon.
    assert "она" not in tokens
    assert "её" not in tokens


def test_guppi_canon_names_him_as_bobs_non_sentient_executor() -> None:
    # The relationship flavor: GUPPI is Bob's literal, non-sentient executor
    # subsystem — the seed for the running gags.
    folded = guppi_canon().casefold()
    assert "guppi" in folded
    assert "исполн" in folded  # executes / executor
    assert "разум" in folded  # (non-)sentient


def test_guppi_canon_seeds_running_relationship_flavor() -> None:
    # Bob's wry relationship is seeded (literal-to-a-fault, glad he isn't
    # sentient — "fewer philosophical arguments") so it can surface naturally.
    folded = guppi_canon().casefold()
    assert "буквальн" in folded or "дословн" in folded
    assert "кофе" in folded  # the "philosophical arguments over coffee" gag seed


def test_variable_form_directive_is_natural_voice_not_a_rule_list() -> None:
    # The variable-form directive (BOB-018) is written as voice — Bob's form and
    # length vary by mood, not one fixed frame — never a recitable rule list.
    directive = variable_form_directive()
    folded = directive.casefold()
    assert "форма" in folded  # speaks about the shape/form of his replies
    assert "•" not in directive
    assert "- " not in directive


def test_variable_form_directive_names_the_one_frame_tic() -> None:
    # It names the failure it counters: every reply in one shape/length (a rut),
    # so sometimes short, sometimes expansive.
    folded = variable_form_directive().casefold()
    assert "коротк" in folded  # sometimes terse
    assert "развёрнут" in folded or "развернут" in folded  # sometimes expansive


def test_variable_form_directive_carries_a_few_shot() -> None:
    # A short few-shot (between « ») shows the varied form, mirroring anti-bait.
    exemplars = _exemplar_lines(variable_form_directive())
    assert exemplars, "no few-shot exemplar lines found"


def _exemplar_lines(directive: str) -> list[str]:
    """The quoted few-shot exemplar lines inside the directive (between « »)."""
    lines: list[str] = []
    rest = directive
    while "«" in rest and "»" in rest:
        start = rest.index("«") + 1
        end = rest.index("»", start)
        lines.append(rest[start:end])
        rest = rest[end + 1 :]
    return lines
