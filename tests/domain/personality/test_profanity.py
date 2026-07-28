# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for profanity perception — directed hostility vs casual мат (BOB-014 .2b).

Bob is CALM about casual/emphatic profanity (мат "with him", not "at him") — it must
NOT crater the relationship or trigger обида. He REGISTERS directed insults/hostility
("at him"). The signal keys on DIRECTED hostility, not on vocabulary — a light, pure
heuristic over the text, deterministic and unit-testable.
"""

from __future__ import annotations

from bob.personality.profanity import is_directed_hostility


def test_plain_message_is_not_hostile() -> None:
    assert is_directed_hostility("привет, как дела?") is False


def test_casual_emphatic_profanity_is_not_hostile() -> None:
    # Casual мат "with him" — emphasis, not an attack. Must stay calm.
    assert is_directed_hostility("блин, ну это просто охренеть как круто!") is False
    assert is_directed_hostility("да хрен с ним, забей") is False


def test_directed_insult_is_hostile() -> None:
    # An insult aimed AT Bob ("ты ..."): registered as directed hostility.
    assert is_directed_hostility("ты тупой идиот") is True
    assert is_directed_hostility("заткнись, дебил") is True


def test_directed_profanity_at_him_is_hostile() -> None:
    # Profanity aimed at the second person ("ты"/"иди ...") reads as "at him".
    assert is_directed_hostility("да пошёл ты на хрен") is True


def test_empty_text_is_not_hostile() -> None:
    assert is_directed_hostility("") is False
    assert is_directed_hostility("   ") is False


def test_is_case_insensitive() -> None:
    assert is_directed_hostility("ТЫ ТУПОЙ ИДИОТ") is True
