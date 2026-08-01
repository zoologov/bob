# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the disclosure-consent seam — pure prompt + parser (BOB-082 .4).

The consent detector answers ONE question semantically (Tier-0, not keyword matching):
"Is the OWNER, in THIS turn, authorising Bob to voice previously-private content into
THIS (group) chat?" :func:`build_disclosure_consent_user_prompt` folds the context into
the Tier-0 request; :func:`parse_disclosure_consent` maps the reply to a bool. 🔴 The
parser is CONSERVATIVE and biased to NO: only a clear ``consent: yes`` is consent; a
``no``, an ambiguous, or an unparseable reply is NO (never accidentally discloses).
"""

from __future__ import annotations

from bob.social.disclosure_consent import (
    DISCLOSURE_CONSENT_SYSTEM_PROMPT,
    DisclosureConsentContext,
    build_disclosure_consent_user_prompt,
    parse_disclosure_consent,
)


def _ctx(text: str, thread: str = "") -> DisclosureConsentContext:
    return DisclosureConsentContext(request_text=text, recent_thread=thread)


# --- parse_disclosure_consent — the conservative pure verdict ------------------------


def test_clear_yes_is_consent() -> None:
    assert parse_disclosure_consent("consent: yes") is True


def test_clear_no_is_not_consent() -> None:
    assert parse_disclosure_consent("consent: no") is False


def test_russian_da_is_consent() -> None:
    assert parse_disclosure_consent("consent: да") is True


def test_russian_net_is_not_consent() -> None:
    assert parse_disclosure_consent("consent: нет") is False


def test_unparseable_reply_is_not_consent() -> None:
    # 🔴 Bias to NO: garbage never discloses.
    assert parse_disclosure_consent("я не уверен") is False


def test_empty_reply_is_not_consent() -> None:
    assert parse_disclosure_consent("") is False


def test_ambiguous_reply_is_not_consent() -> None:
    # No recognisable yes/no token → conservative NO.
    assert parse_disclosure_consent("consent: maybe") is False


def test_label_is_case_and_whitespace_tolerant() -> None:
    assert parse_disclosure_consent("  CONSENT :  Yes  ") is True


def test_yes_token_with_trailing_punctuation_is_consent() -> None:
    # The token trim strips punctuation (not only whitespace): "yes!" → "yes" → consent.
    assert parse_disclosure_consent("consent: yes!") is True
    assert parse_disclosure_consent("consent: да.") is True


def test_filler_word_before_a_yes_token_still_consents() -> None:
    # The scan skips a non-yes/non-no filler token and keeps looking — a later clear yes
    # still resolves to consent (the no-branch must not short-circuit on the filler).
    assert parse_disclosure_consent("consent: hmm yes") is True
    assert parse_disclosure_consent("consent: ну, да") is True


def test_filler_word_before_a_no_token_is_not_consent() -> None:
    # Symmetrically, a clear no after filler stays a conservative NO.
    assert parse_disclosure_consent("consent: ну, нет") is False


def test_reads_the_labelled_line_among_prose() -> None:
    raw = "Thinking about it...\nconsent: yes\nbecause the owner said so"
    assert parse_disclosure_consent(raw) is True


# --- build_disclosure_consent_user_prompt — folds the context (pure) ----------------


def test_user_prompt_includes_the_request_text() -> None:
    prompt = build_disclosure_consent_user_prompt(_ctx("расскажи ребятам про наш план"))
    assert "расскажи ребятам про наш план" in prompt


def test_user_prompt_includes_recent_thread_when_present() -> None:
    prompt = build_disclosure_consent_user_prompt(
        _ctx("да, можешь", thread="bob: рассказать группе про X?")
    )
    assert "рассказать группе про X" in prompt


def test_user_prompt_is_stable_without_a_thread() -> None:
    prompt = build_disclosure_consent_user_prompt(_ctx("поделись с группой"))
    assert "поделись с группой" in prompt
    assert "(none)" in prompt


def test_system_prompt_frames_the_conservative_owner_group_question() -> None:
    # The prompt must ask for the labelled contract and bias to no on doubt.
    assert "consent:" in DISCLOSURE_CONSENT_SYSTEM_PROMPT
    assert "yes" in DISCLOSURE_CONSENT_SYSTEM_PROMPT
    assert "no" in DISCLOSURE_CONSENT_SYSTEM_PROMPT
