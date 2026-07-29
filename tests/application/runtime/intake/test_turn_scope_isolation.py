# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Turn-scope isolation under concurrency (BOB-066 Срез 2.1) — 🔴 INV-4 at the seam.

The pure ``TurnScope`` reproducibility is covered in ``test_scope.py``; this module proves
the harder property: when turns run as concurrent workers and finish in a SCRAMBLED order, a
turn's seeded draws still depend only on its ``(base_seed, chat_id, message_id)`` coordinates
and never leak between messages of a chat or between chats. So a turn's rng is reproducible
independent of dispatch/completion timing, and turn-local state (rng draws, and — by the same
per-turn ``TurnScope`` — verify-note / "already searched" flags carried on it) cannot bleed
across turns.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.events import MessageReceived
from bob.application.runtime.intake.dispatcher import ChatDispatcher
from bob.application.runtime.intake.scope import new_turn_scope

if TYPE_CHECKING:
    from bob.application.runtime.intake.scope import TurnScope

_BASE_SEED = 7


def _msg(chat_id: int, message_id: int) -> MessageReceived:
    return MessageReceived(
        update_id=message_id, chat_id=chat_id, message_id=message_id, text="привет"
    )


def _never_focused(_message: MessageReceived) -> bool:
    return False


def _expected_draws(chat_id: int, message_id: int, *, n: int = 4) -> list[float]:
    """The draw stream the coordinate-derived seed must produce — the timing-free oracle."""
    scope = new_turn_scope(base_seed=_BASE_SEED, chat_id=chat_id, message_id=message_id)
    return [scope.rng.random() for _ in range(n)]


@pytest.mark.asyncio
async def test_turn_draws_are_reproducible_despite_scrambled_completion_order() -> None:
    # Arrange: chat 1 is forced to FINISH AFTER chat 2, so completion order (2, 1) is the
    # reverse of submit order (1, 2). The seed must not care.
    draws: dict[int, list[float]] = {}
    chat_two_done = asyncio.Event()

    async def handle(message: MessageReceived, scope: TurnScope) -> None:
        if message.chat_id == 1:
            await chat_two_done.wait()  # chat 1 completes last
        draws[message.chat_id] = [scope.rng.random() for _ in range(4)]
        if message.chat_id == 2:
            chat_two_done.set()

    dispatcher = ChatDispatcher(handle=handle, base_seed=_BASE_SEED, is_focused=_never_focused)

    # Act: same message_id in two different chats (so only chat_id distinguishes the seed).
    dispatcher.submit(_msg(1, 5))
    dispatcher.submit(_msg(2, 5))
    await dispatcher.aclose()

    # Assert: 🔴 INV-4 — each stream matches its coordinate-derived oracle, timing aside.
    assert draws[1] == _expected_draws(1, 5)
    assert draws[2] == _expected_draws(2, 5)
    # And the two chats did NOT share an rng despite the identical message_id.
    assert draws[1] != draws[2]


@pytest.mark.asyncio
async def test_heavy_draw_in_one_turn_does_not_disturb_the_next_turns_stream() -> None:
    # Arrange: turn 1 of a chat consumes its rng heavily; turn 2 must still get its own
    # pristine, coordinate-seeded stream (no shared/leaking rng within a chat).
    streams: dict[int, list[float]] = {}

    async def handle(message: MessageReceived, scope: TurnScope) -> None:
        if message.message_id == 1:
            for _ in range(1000):
                scope.rng.random()
        streams[message.message_id] = [scope.rng.random() for _ in range(4)]

    dispatcher = ChatDispatcher(handle=handle, base_seed=_BASE_SEED, is_focused=_never_focused)

    # Act: two sequential turns of one chat.
    dispatcher.submit(_msg(7, 1))
    dispatcher.submit(_msg(7, 2))
    await dispatcher.aclose()

    # Assert: turn 2's stream equals its independent oracle — turn 1's draws left no residue.
    assert streams[2] == _expected_draws(7, 2)


@pytest.mark.asyncio
async def test_every_message_of_a_burst_gets_a_distinct_isolated_scope() -> None:
    # Arrange: a whole burst in one chat, handled sequentially; each turn's scope must be
    # distinct and coordinate-seeded (no scope reuse across a batch).
    seen: list[tuple[int, int, float]] = []

    async def handle(message: MessageReceived, scope: TurnScope) -> None:
        seen.append((scope.chat_id, scope.message_id, scope.rng.random()))

    dispatcher = ChatDispatcher(handle=handle, base_seed=_BASE_SEED, is_focused=_never_focused)

    # Act.
    for message_id in (1, 2, 3, 4):
        dispatcher.submit(_msg(7, message_id))
    await dispatcher.aclose()

    # Assert: coordinates line up with arrival, and the four first-draws are all different.
    assert [(chat_id, message_id) for chat_id, message_id, _ in seen] == [
        (7, 1),
        (7, 2),
        (7, 3),
        (7, 4),
    ]
    first_draws = [draw for _, _, draw in seen]
    assert len(set(first_draws)) == 4
