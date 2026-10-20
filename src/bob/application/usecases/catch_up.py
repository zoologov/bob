# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""CatchUp (BOB-066 Срез 3.2) — one re-entry pass over an away-period backlog.

When Bob comes back to a chat after being away, he does NOT reply to every message that
piled up. This use-case is that «catch up like a person» act as ONE decision: given the
backlog that accumulated behind him — a LARGER-window, non-draining
:meth:`~bob.application.runtime.intake.inbox.ChatInbox.peek_since` snapshot from Срез 2.1,
projected onto the presence domain's value-shaped
:class:`~bob.presence.catchup.BacklogMessage` — it runs ONE
:func:`~bob.presence.catchup.select_catchup` pass under an action ``budget`` and folds in
the :func:`~bob.personality.absence.absence_hint` re-entry tone (the same «haven't seen you
in a while» texture the reply tier already uses).

🔴 **Backpressure with priority.** The ranking is banded (direct-address > reply-to-Bob
thread > ambient) and the budget caps only how many *ambient* asides Bob picks up — a focal
(direct-address) message is NEVER dropped or collapsed (INV-1/INV-10). Only peripheral
ambient beyond the budget is skimmed rather than answered.

Behaviour-changing, so it ships behind a flag that is **OFF by default** (consistent with
the prior slices): disabled, :meth:`CatchUp.plan` returns an empty plan — Bob behaves
exactly as before (no catch-up). The transport-shaped addressivity signals (mention,
reply-to-Bob) are projected HERE, at the application seam that knows Bob's user id, by
:func:`to_backlog_message`; the presence domain stays free of ``MessageReceived``. Like the
Срез 3.1 staleness gate, the live re-entry tick (wiring this into the per-chat worker after
an away period) is DEFERRED to keep the intake worker off the Cohesion-guard — until it is
wired, production behaviour is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.personality.absence import absence_hint
from bob.presence.catchup import BacklogMessage, CatchUpPlan, select_catchup

if TYPE_CHECKING:
    from datetime import datetime

    from bob.kernel.events import MessageReceived


def to_backlog_message(
    message: MessageReceived,
    *,
    bob_user_id: int,
    at: datetime,
    salience: float,
    in_bob_thread: bool = False,
) -> BacklogMessage:
    """Project a runtime ``MessageReceived`` onto the presence domain's ``BacklogMessage``.

    A raw direct address — an @mention of Bob or a reply to one of Bob's messages — is the
    focal band (``addressed_to_bob``). A message that merely continues a thread Bob is in
    (``in_bob_thread``) without addressing him is the reply-thread band; direct address
    wins over the thread flag. ``at`` (the message's arrival time, recorded by the intake
    buffer) and ``salience`` (the ambient «worth chiming in» read) are supplied by the
    caller, since ``MessageReceived`` carries neither.
    """
    addressed = message.mentions_bob or message.reply_to_sender_id == bob_user_id
    return BacklogMessage(
        sender_id=message.sender_id,
        text=message.text,
        addressed_to_bob=addressed,
        reply_to_bob_thread=in_bob_thread and not addressed,
        salience=salience,
        at=at,
    )


@dataclass(frozen=True, slots=True)
class CatchUpOutcome:
    """The result of one catch-up pass: what to act on plus the re-entry tone.

    ``plan`` is the pure :class:`~bob.presence.catchup.CatchUpPlan` (focal-first
    ``to_answer`` + skimmed ``collapsed``); ``absence_tone`` is the optional
    «haven't-seen-you-in-a-while» hint for the compose prompt, or ``None`` when the gap is
    short or catch-up is disabled.
    """

    plan: CatchUpPlan
    absence_tone: str | None

    @classmethod
    def empty(cls) -> CatchUpOutcome:
        """Return the no-op outcome — an empty plan and no tone (catch-up disabled)."""
        return cls(plan=CatchUpPlan(to_answer=(), collapsed=()), absence_tone=None)


class CatchUp:
    """Run ONE re-entry pass over a backlog under a budget (flag OFF by default)."""

    def __init__(self, *, absence_threshold_hours: float, enabled: bool = False) -> None:
        self._enabled = enabled
        self._absence_threshold_hours = absence_threshold_hours

    def plan(
        self,
        *,
        backlog: tuple[BacklogMessage, ...],
        now: datetime,
        last_seen: datetime | None,
        budget: int,
    ) -> CatchUpOutcome:
        """Return the catch-up outcome for ``backlog`` at ``now`` under ``budget``.

        Disabled (the default) → :meth:`CatchUpOutcome.empty` (Bob behaves as before, no
        catch-up). Enabled → one pure :func:`~bob.presence.catchup.select_catchup` pass
        (every focal message answered, ambient capped by the budget, the rest collapsed)
        plus the :func:`~bob.personality.absence.absence_hint` re-entry tone computed from
        ``last_seen`` (``None`` last-seen or a short gap → no tone).
        """
        if not self._enabled:
            return CatchUpOutcome.empty()
        selected = select_catchup(backlog, now=now, budget=budget)
        tone = (
            None
            if last_seen is None
            else absence_hint(
                last_seen, now, threshold_hours=self._absence_threshold_hours
            )
        )
        return CatchUpOutcome(plan=selected, absence_tone=tone)
