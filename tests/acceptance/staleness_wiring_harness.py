# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Staleness врезка WIRING acceptance harness (BOB-066 Срез W.3).

Drives the REAL :meth:`~bob.application.usecases.handle_message.HandleMessage.handle` — the
production reply path — with the staleness reassessor wired over a SCRIPTED judge and a
turn scope whose ``peek_arrivals`` returns what «landed during generation», so the BDD scenarios
witness the *wired* behaviour through the outgoing boundary (a Telegram reply vs a native
reaction):

* when the drafted reply was answered by someone else while Bob composed it, he DROPS it to a
  like instead of firing the stale line;
* 🔴🔴 when a FRESH DIRECT question landed on top, he still speaks — a focal signal is never
  dropped (INV-1);
* with the врезка OFF (no reassessor) the same burst is ignored and Bob replies as before.

(The handler is assembled through the same builder the unit tests use, so the harness exercises
the production врезка end to end rather than re-deriving the wiring.)
"""

from __future__ import annotations

from dataclasses import dataclass

from bob.application.runtime.intake.scope import new_turn_scope
from tests.application.usecases.test_handle_message import (
    _build,
    _message,
    _RecordingReactor,
    _staleness_reassessor,
)

_BOB_USER_ID = 100


@dataclass(frozen=True, slots=True)
class StalenessWiringOutcome:
    """What one wiring turn produced through the boundary."""

    replied: bool
    liked: bool


async def run_staleness_turn(
    *,
    enabled: bool,
    answered_by_other: bool = False,
    topic_closed: bool = False,
    new_direct_question: bool = False,
) -> StalenessWiringOutcome:
    """Drive one reply turn with a burst that landed during generation; observe reply vs like.

    ``enabled`` wires the reassessor (over a judge scripted with the given flags); off leaves it
    unwired (byte-identical). A single arrival is peeked as «landed during generation».
    """
    reactor = _RecordingReactor()
    reassessor = (
        _staleness_reassessor(
            answered_by_other=answered_by_other,
            topic_closed=topic_closed,
            new_direct_question=new_direct_question,
        )
        if enabled
        else None
    )
    handler, bot, _repo, _tier1 = _build(
        reply="кофе лучше всего утром",
        reactor=reactor,
        staleness_reassessor=reassessor,
        bob_user_id_source=lambda: _BOB_USER_ID,
    )
    arrival = _message("а на это уже ответили")
    scope = new_turn_scope(
        base_seed=0,
        chat_id=555,
        message_id=10,
        peek_arrivals=lambda: (arrival,),
    )
    await handler.handle(_message(), scope)
    return StalenessWiringOutcome(replied=bool(bot.sent), liked=bool(reactor.calls))
