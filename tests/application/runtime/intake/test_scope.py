# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for :class:`TurnScope` — the isolated per-turn context (BOB-066 Срез 2.1)."""

from __future__ import annotations

from bob.application.runtime.intake.scope import TurnScope, new_turn_scope


def test_scope_carries_the_turn_coordinates() -> None:
    scope = new_turn_scope(base_seed=99, chat_id=42, message_id=7)
    assert isinstance(scope, TurnScope)
    assert (scope.chat_id, scope.message_id) == (42, 7)


def test_same_turn_reproduces_the_same_draw_stream() -> None:
    # 🔴 INV-4: a turn's rng is reproducible regardless of dispatch timing.
    first = new_turn_scope(base_seed=99, chat_id=42, message_id=7)
    second = new_turn_scope(base_seed=99, chat_id=42, message_id=7)
    assert [first.rng.random() for _ in range(5)] == [second.rng.random() for _ in range(5)]


def test_two_messages_of_one_chat_draw_independently() -> None:
    # 🔴 INV-4: turn-local draws never leak between messages of the same chat.
    first = new_turn_scope(base_seed=99, chat_id=42, message_id=7)
    second = new_turn_scope(base_seed=99, chat_id=42, message_id=8)
    assert first.rng.random() != second.rng.random()
