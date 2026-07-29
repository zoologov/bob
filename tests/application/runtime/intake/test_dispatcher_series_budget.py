# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Batch top-k budget wiring for :class:`ChatDispatcher` (BOB-066 Срез W.2, Пласт 3).

The pure plan is truth-tabled in ``tests/domain/presence/test_series_salience.py``; here we
assert the dispatcher WIRES it — it stamps each settled-burst message's outcome ceiling on its
:class:`TurnScope`, so a burst collapses to ONE addressed reply + a budget-capped like:

* off (the default) → every message is uncapped (``ENGAGE``), byte-identical to before;
* on → an ambient burst yields REPLY / REACT / SILENT ceilings; 🔴 a focus message is always a
  REPLY ceiling (INV-1 — never dropped by the budget).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.events import MessageReceived
from bob.application.runtime.intake.dispatcher import ChatDispatcher
from bob.conversation.addressivity import ResponseOutcome

if TYPE_CHECKING:
    from bob.application.runtime.intake.scope import TurnScope


def _msg(message_id: int, *, mentions_bob: bool = False) -> MessageReceived:
    return MessageReceived(
        update_id=message_id,
        chat_id=7,
        message_id=message_id,
        text="привет",
        mentions_bob=mentions_bob,
    )


def _focus_on_mention(message: MessageReceived) -> bool:
    return message.mentions_bob


async def _drive(
    *, enabled: bool, messages: list[MessageReceived], max_reactions: int = 1
) -> list[ResponseOutcome]:
    seen: list[ResponseOutcome] = []

    async def handle(_message: MessageReceived, scope: TurnScope) -> None:
        seen.append(scope.series_ceiling)

    dispatcher = ChatDispatcher(
        handle=handle,
        base_seed=1,
        is_focused=_focus_on_mention,
        series_budget_enabled=enabled,
        series_max_reactions=max_reactions,
    )
    for message in messages:
        dispatcher.submit(message)
    await dispatcher.aclose()
    return seen


@pytest.mark.asyncio
async def test_disabled_leaves_every_message_uncapped() -> None:
    ceilings = await _drive(enabled=False, messages=[_msg(1), _msg(2), _msg(3)])

    assert ceilings == [ResponseOutcome.ENGAGE] * 3


@pytest.mark.asyncio
async def test_ambient_burst_collapses_to_one_reply_plus_a_like() -> None:
    ceilings = await _drive(enabled=True, messages=[_msg(1), _msg(2), _msg(3)])

    assert ceilings == [
        ResponseOutcome.ENGAGE,  # one addressed reply
        ResponseOutcome.REACT,  # one budget-capped like
        ResponseOutcome.SILENT,
    ]


@pytest.mark.asyncio
async def test_focus_message_in_a_burst_is_never_capped() -> None:
    # 🔴 INV-1: the direct address keeps a REPLY (ENGAGE) ceiling; the ambient ones collapse.
    ceilings = await _drive(
        enabled=True,
        messages=[_msg(1), _msg(2, mentions_bob=True), _msg(3)],
    )

    assert ceilings == [
        ResponseOutcome.REACT,
        ResponseOutcome.ENGAGE,  # the focus message — always answered
        ResponseOutcome.SILENT,
    ]
