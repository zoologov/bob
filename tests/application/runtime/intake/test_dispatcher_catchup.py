# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Catch-up re-entry wiring for :class:`ChatDispatcher` (BOB-066 Срез W.3, Пласт 3).

The pure pass is truth-tabled in ``tests/domain/presence/test_catchup.py`` and the collaborator
in ``test_catch_up_reentry.py``; here we assert the WORKER wires it — after an away period a
drained batch is run as ONE catch-up pass (focal + budget ambient handled, the rest skimmed)
instead of replaying each message. 🔴 The skimmed messages are still settled, so
``wait_for_idle`` resolves (no leaked pending). Off → every message is handled as before.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.catch_up_reentry import CatchUpReentry
from bob.application.runtime.events import MessageReceived
from bob.application.runtime.intake.dispatcher import ChatDispatcher

if TYPE_CHECKING:
    from bob.application.runtime.intake.scope import TurnScope

_T0 = datetime(2026, 7, 29, 9, 0, 0, tzinfo=UTC)


class _AdvancingClock:
    def __init__(self, *instants: datetime) -> None:
        self._instants = list(instants)

    def now(self) -> datetime:
        return self._instants.pop(0)


def _msg(message_id: int, *, mentions_bob: bool = False) -> MessageReceived:
    return MessageReceived(
        update_id=message_id,
        chat_id=7,
        message_id=message_id,
        text="привет",
        sender_id=1,
        mentions_bob=mentions_bob,
    )


def _focus_on_mention(message: MessageReceived) -> bool:
    return message.mentions_bob


async def test_reentry_batch_runs_one_catch_up_pass_and_settles_skimmed() -> None:
    handled: list[int] = []

    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        handled.append(message.message_id)

    reentry = CatchUpReentry(
        clock=_AdvancingClock(_T0, _T0 + timedelta(hours=5)),
        bob_user_id_source=lambda: 500,
        absence_threshold_hours=4.0,
        budget=1,
        enabled=True,
    )
    dispatcher = ChatDispatcher(
        handle=handle,
        base_seed=1,
        is_focused=_focus_on_mention,
        catch_up_reentry=reentry,
    )

    # Batch 1 at T0 establishes last-seen (a normal passthrough).
    dispatcher.submit(_msg(1))
    await dispatcher.wait_for_idle()

    # Batch 2 lands after a 5h gap → catch-up: the direct address is answered, the ambient
    # asides beyond budget 1 are skimmed. wait_for_idle MUST resolve (skimmed are settled).
    dispatcher.submit(_msg(2))
    dispatcher.submit(_msg(3, mentions_bob=True))
    dispatcher.submit(_msg(4))
    await dispatcher.wait_for_idle()
    await dispatcher.aclose()

    assert 1 in handled, "the first passthrough batch was handled"
    assert 3 in handled, "the direct address is always answered on re-entry (INV-1)"
    assert 2 not in handled, "an ambient aside beyond budget is skimmed, not replayed"
    assert 4 not in handled, "an ambient aside beyond budget is skimmed, not replayed"


async def test_disabled_dispatcher_replays_every_message() -> None:
    handled: list[int] = []

    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        handled.append(message.message_id)

    # No catch-up collaborator → every batch is a passthrough (byte-identical).
    dispatcher = ChatDispatcher(
        handle=handle, base_seed=1, is_focused=_focus_on_mention
    )
    for message in (_msg(1), _msg(2), _msg(3)):
        dispatcher.submit(message)
    await dispatcher.aclose()

    assert sorted(handled) == [1, 2, 3]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
