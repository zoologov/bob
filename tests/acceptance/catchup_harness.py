# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Backlog catch-up harness (BOB-066 Срез 3.2) — drives the one-pass re-entry contract.

The catch-up pass ships inert behind the deferred live re-entry врезка (like the Срез 3.1
staleness gate), so its observable behaviour is exercised here through its application
collaborator (:class:`~bob.application.usecases.catch_up.CatchUp`) over the pure
:func:`~bob.presence.catchup.select_catchup` core. The acceptance steps read as living
documentation of «Bob catches up like a person»: one pass answers the direct question, does
not reply to every ambient aside, and — the load-bearing INV-1/INV-10 guarantee — never
drops a direct address, no matter how tight the budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bob.application.usecases.catch_up import CatchUp, to_backlog_message
from bob.kernel.events import MessageReceived

if TYPE_CHECKING:
    from bob.presence.catchup import BacklogMessage

_NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)
_BOB_USER_ID = 100


@dataclass(slots=True)
class BacklogBuilder:
    """Accumulates the away-period backlog as projected domain messages."""

    _next_update_id: int = 1
    messages: list[BacklogMessage] = field(default_factory=list)

    def add_direct_question(self, text: str) -> None:
        """Add a message that @mentions Bob — a focal, must-answer message."""
        self._add(text=text, mentions_bob=True, salience=0.5, age_hours=1.0)

    def add_ambient(self, text: str, *, age_hours: float, salience: float = 0.3) -> None:
        """Add a plain ambient message — peripheral chatter that may collapse."""
        self._add(text=text, mentions_bob=False, salience=salience, age_hours=age_hours)

    def _add(
        self, *, text: str, mentions_bob: bool, salience: float, age_hours: float
    ) -> None:
        event = MessageReceived(
            update_id=self._next_update_id,
            chat_id=1,
            message_id=self._next_update_id,
            text=text,
            sender_id=7,
            mentions_bob=mentions_bob,
        )
        self._next_update_id += 1
        self.messages.append(
            to_backlog_message(
                event,
                bob_user_id=_BOB_USER_ID,
                at=_NOW - timedelta(hours=age_hours),
                salience=salience,
            )
        )


def run_catchup(backlog: tuple[BacklogMessage, ...], *, budget: int) -> list[str]:
    """Run one enabled catch-up pass; return the texts Bob answers (focal-first order)."""
    catch_up = CatchUp(enabled=True, absence_threshold_hours=6.0)
    outcome = catch_up.plan(backlog=backlog, now=_NOW, last_seen=None, budget=budget)
    return [msg.text for msg in outcome.plan.to_answer]


def run_catchup_collapsed(
    backlog: tuple[BacklogMessage, ...], *, budget: int
) -> list[str]:
    """Run one enabled catch-up pass; return the texts Bob lets pass (skimmed, not answered)."""
    catch_up = CatchUp(enabled=True, absence_threshold_hours=6.0)
    outcome = catch_up.plan(backlog=backlog, now=_NOW, last_seen=None, budget=budget)
    return [msg.text for msg in outcome.plan.collapsed]
