# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure intake decision core (BOB-066 Срез 2.1 — intake-развязка).

The debounce timing and the per-turn rng-seed derivation are the deterministic
decision logic behind the async :class:`ChatInbox` / :class:`TurnScope`. They are
pure (no asyncio / no I/O), so they are exhaustively truth-tabled here and carry the
per-slice mutation gate — the async orchestration on top is proven separately through
the dispatcher tests.
"""

from __future__ import annotations

import pytest

from bob.application.runtime.intake.decisions import (
    batch_grew,
    derive_turn_seed,
    should_debounce,
)


@pytest.mark.parametrize(
    ("closing", "has_focus", "expected"),
    [
        (False, False, True),  # normal ambient burst → wait the quiet window
        (False, True, False),  # 🔴 INV-1/10: a focused message never waits
        (True, False, False),  # graceful drain → flush immediately
        (True, True, False),  # closing OR focus → no wait
    ],
)
def test_should_debounce_truth_table(
    *, closing: bool, has_focus: bool, expected: bool
) -> None:
    assert should_debounce(closing=closing, has_focus=has_focus) is expected


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (0, 1, True),  # a message arrived during the window → keep waiting
        (2, 3, True),
        (1, 1, False),  # quiet window elapsed with no new arrival → flush
        (3, 3, False),
    ],
)
def test_batch_grew(*, before: int, after: int, expected: bool) -> None:
    assert batch_grew(before=before, after=after) is expected


def test_derive_turn_seed_is_deterministic() -> None:
    seed_a = derive_turn_seed(base_seed=99, chat_id=42, message_id=7)
    seed_b = derive_turn_seed(base_seed=99, chat_id=42, message_id=7)
    assert seed_a == seed_b


def test_derive_turn_seed_isolates_messages_of_one_chat() -> None:
    # 🔴 INV-4: two messages of the SAME chat draw from independent seeds.
    first = derive_turn_seed(base_seed=99, chat_id=42, message_id=7)
    second = derive_turn_seed(base_seed=99, chat_id=42, message_id=8)
    assert first != second


def test_derive_turn_seed_isolates_chats() -> None:
    # Parallelism across chat_ids → distinct seeds for the same message coordinate.
    left = derive_turn_seed(base_seed=99, chat_id=1, message_id=7)
    right = derive_turn_seed(base_seed=99, chat_id=2, message_id=7)
    assert left != right


def test_derive_turn_seed_varies_with_base() -> None:
    low = derive_turn_seed(base_seed=1, chat_id=42, message_id=7)
    high = derive_turn_seed(base_seed=2, chat_id=42, message_id=7)
    assert low != high
