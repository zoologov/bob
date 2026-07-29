# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for endorsement perception — кредит доверия по рекомендации owner (BOB-066 2.6).

When the owner vouches for a newcomer ("это мой друг Норман, ему можно доверять"), Bob
should meet that person with a warm start rather than as a blank stranger — a credit of
trust the owner extends on their behalf. :func:`detected_endorsement` is the light, pure
heuristic (в духе :func:`is_directed_hostility`) that fires only when the owner's text
reads as vouching FOR a person; :func:`owner_endorsed_sender` narrows it to *this* sender
by requiring the endorsement to name them, so a warm word about Лёша never warm-starts
Норман.
"""

from __future__ import annotations

from bob.social.endorsement import detected_endorsement, owner_endorsed_sender


def test_plain_message_is_not_an_endorsement() -> None:
    assert detected_endorsement("во сколько встреча?") is False


def test_vouching_phrase_is_an_endorsement() -> None:
    assert detected_endorsement("это мой друг, ему можно доверять") is True


def test_introduction_is_an_endorsement() -> None:
    assert detected_endorsement("познакомься, это Норман, хороший человек") is True


def test_trust_vouch_is_an_endorsement() -> None:
    assert detected_endorsement("он свой, я за него ручаюсь") is True


def test_neutral_mention_of_a_person_is_not_an_endorsement() -> None:
    # Mentioning someone is not vouching for them.
    assert detected_endorsement("Лёша опять опоздал на созвон") is False


def test_empty_text_is_not_an_endorsement() -> None:
    assert detected_endorsement("   ") is False


def test_endorsement_is_case_insensitive() -> None:
    assert detected_endorsement("ЭТО МОЙ ДРУГ, ЕМУ МОЖНО ДОВЕРЯТЬ") is True


def test_owner_endorsed_sender_when_a_vouch_names_them() -> None:
    owner_texts = ["это мой друг Норман, ему можно доверять"]
    assert owner_endorsed_sender(owner_texts, sender_name="Норман") is True


def test_owner_endorsed_sender_is_false_when_the_vouch_names_someone_else() -> None:
    # A warm word about Лёша must not warm-start Норман.
    owner_texts = ["Лёша — отличный человек, ему можно доверять"]
    assert owner_endorsed_sender(owner_texts, sender_name="Норман") is False


def test_owner_endorsed_sender_is_false_without_an_endorsement() -> None:
    owner_texts = ["Норман, ты придёшь на встречу?"]
    assert owner_endorsed_sender(owner_texts, sender_name="Норман") is False


def test_owner_endorsed_sender_is_false_for_an_empty_name() -> None:
    # No name to attribute the credit to → conservative False.
    owner_texts = ["это мой друг, ему можно доверять"]
    assert owner_endorsed_sender(owner_texts, sender_name="") is False


def test_owner_endorsed_sender_matches_first_name_case_insensitively() -> None:
    owner_texts = ["познакомься с Норманом Дайсоном, он свой, ручаюсь за него"]
    assert owner_endorsed_sender(owner_texts, sender_name="норман дайсон") is True


def test_owner_endorsed_sender_is_false_on_empty_history() -> None:
    assert owner_endorsed_sender([], sender_name="Норман") is False


def test_owner_endorsed_sender_uses_the_first_name_of_a_multiword_name() -> None:
    # A three-word name: only the FIRST token ("иван") is matched against the vouch,
    # which names just the first name — so left-splitting (not right-splitting) is
    # load-bearing.
    owner_texts = ["познакомься, это иван, ему можно доверять"]
    assert owner_endorsed_sender(owner_texts, sender_name="иван петрович сидоров") is True
