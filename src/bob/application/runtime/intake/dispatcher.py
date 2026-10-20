# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""ChatDispatcher (BOB-066 Срез 2.1) — the intake seam: fast submit, per-chat workers.

The bus subscriber for an inbound message becomes :meth:`submit` — normalise → buffer →
return — so the Telegram poller never blocks on Bob's generation again. Behind it, one
worker task per ``chat_id`` drains that chat's :class:`ChatInbox` and runs the real
handler sequentially:

* 🔴 INV-5 (order/serialization): a single worker owns a chat's inbox, so that chat's
  messages are handled strictly in arrival order (floor / mood / relationship advance in
  order). Parallelism is only ACROSS chats (distinct workers) — no global lock, so a
  worker can only ever wait on its own inbox and can never deadlock another.
* 🔴 INV-4 (turn-local isolation): each message is handled under a fresh
  :class:`~bob.application.runtime.intake.scope.TurnScope`, so its seeded draws never leak
  into the next message.

Graceful :meth:`aclose` closes every inbox and awaits the workers, so a drained shutdown
delivers the buffered replies (the acceptance/e2e harness relies on this).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from bob.application.runtime.catch_up_reentry import CatchUpSelection
from bob.application.runtime.intake.inbox import ChatInbox
from bob.application.runtime.intake.room_stream_reader import SILENT_IGNORE_READING
from bob.application.runtime.intake.scope import new_turn_scope
from bob.conversation.addressivity import ResponseOutcome
from bob.presence.series_salience import SeriesAction, plan_series_actions
from bob.presence.staleness import QueuedAmbient, coalesce_stale

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from bob.application.runtime.catch_up_reentry import CatchUpReentry
    from bob.application.runtime.intake.room_stream_reader import AmbientBatchReader
    from bob.application.runtime.intake.scope import TurnScope
    from bob.conversation.room_reading import RoomReading
    from bob.kernel.events import MessageReceived

    type _Handle = Callable[[MessageReceived, TurnScope], Awaitable[None]]
    type _Sleep = Callable[[float], Awaitable[None]]
    type _Focused = Callable[[MessageReceived], bool]
    type _PeekArrivals = Callable[[], tuple[MessageReceived, ...]]

logger = logging.getLogger(__name__)

# The default per-series reaction budget: one gentle like per settled burst — a bot that likes
# every message in a run reads as scripted. Tunable via ``presence.series_budget.max_reactions``.
_DEFAULT_MAX_REACTIONS = 1

# Map the pure batch-plan verdict to the outcome ceiling the handler caps the ambient turn by.
_CEILING_FOR_ACTION: dict[SeriesAction, ResponseOutcome] = {
    SeriesAction.REPLY: ResponseOutcome.ENGAGE,
    SeriesAction.REACT: ResponseOutcome.REACT,
    SeriesAction.SILENT: ResponseOutcome.SILENT,
}


class ChatDispatcher:
    """Route inbound messages to per-``chat_id`` workers that serialize each chat."""

    def __init__(
        self,
        *,
        handle: _Handle,
        base_seed: int,
        is_focused: _Focused,
        quiet_window: float = 0.0,
        sleep: _Sleep = asyncio.sleep,
        series_budget_enabled: bool = False,
        series_max_reactions: int = _DEFAULT_MAX_REACTIONS,
        staleness_enabled: bool = False,
        catch_up_reentry: CatchUpReentry | None = None,
        ambient_batch: AmbientBatchReader | None = None,
        stale_coalesce_enabled: bool = False,
    ) -> None:
        self._handle = handle
        self._base_seed = base_seed
        self._is_focused = is_focused
        self._quiet_window = quiet_window
        self._sleep = sleep
        # 🔴 BOB-066 Срез W.3 (staleness врезка): when enabled, the worker binds each turn's
        # non-draining ``peek_arrivals`` onto its scope so ``HandleMessage`` can reread what
        # landed during generation before sending. Off (the default) → never bound →
        # ``scope.peek_arrivals`` stays None → the reply path is byte-identical.
        self._staleness_enabled = staleness_enabled
        # 🔴 BOB-066 Срез W.3 (catch-up re-entry): when wired, a drained batch that follows an
        # away period is run as ONE catch-up pass (focal + budget ambient answered, the rest
        # skimmed) instead of replaying each message. None (the default) → every batch is a
        # passthrough → byte-identical.
        self._catch_up_reentry = catch_up_reentry
        # 🔴 BOB-066 Срез W.2 (batch top-k): when enabled, a settled burst is planned so it
        # collapses to ONE addressed reply + a budget-capped like (never N replies). Off (the
        # default) → every message keeps the ENGAGE ceiling → byte-identical to before.
        self._series_budget_enabled = series_budget_enabled
        self._series_max_reactions = series_max_reactions
        # 🔴 BOB-072 (holistic stream-read): when wired (``presence.stream_read``), a settled
        # burst is SPLIT — focal (direct address) handled deterministically as now (INV-1), the
        # WHOLE ambient part read at ONCE and each message applied by its per-message reading.
        # None (the default) → the current per-message top-k path → byte-identical.
        self._ambient_batch = ambient_batch
        # 🔴 BOB-072 (queue-level stale-coalesce): when wired (with the stream-read flag), a
        # settled ambient burst is trimmed BEFORE the read — a message the SAME identified sender
        # reformulated in the very next slot is dropped from the read (still persisted, INV-S2) so
        # Bob stays in the present (INV-S3). Off (the default) → every ambient message is read →
        # byte-identical to the plain stream-read path.
        self._stale_coalesce_enabled = stale_coalesce_enabled
        self._inboxes: dict[int, ChatInbox] = {}
        self._workers: dict[int, asyncio.Task[None]] = {}
        self._closing = False
        self._pending = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def submit(self, message: MessageReceived) -> None:
        """Buffer ``message`` for its chat and ensure a worker is draining it (non-blocking).

        The fast bus subscriber: it returns at once so the poller is never blocked on Bob's
        generation. A message that arrives after :meth:`aclose` is dropped (shutting down).
        """
        if self._closing:
            return
        self._pending += 1
        self._idle.clear()
        inbox = self._inbox_for(message.chat_id)
        inbox.offer(message)
        self._ensure_worker(message.chat_id, inbox)

    async def wait_for_idle(self) -> None:
        """Block until every submitted message has been handled (no in-flight turn).

        A synchronisation seam for callers that need the turn(s) completed — the tests drive
        one message and await this before asserting the reply. Production never calls it: the
        whole point of the seam is that submit returns without waiting.
        """
        await self._idle.wait()

    def _inbox_for(self, chat_id: int) -> ChatInbox:
        inbox = self._inboxes.get(chat_id)
        if inbox is None:
            inbox = ChatInbox(
                quiet_window=self._quiet_window,
                is_focused=self._is_focused,
                sleep=self._sleep,
            )
            self._inboxes[chat_id] = inbox
        return inbox

    def _ensure_worker(self, chat_id: int, inbox: ChatInbox) -> None:
        task = self._workers.get(chat_id)
        if task is None or task.done():
            self._workers[chat_id] = asyncio.create_task(self._worker(chat_id, inbox))

    async def _worker(self, chat_id: int, inbox: ChatInbox) -> None:
        """Drain one chat's inbox, handling each drained batch sequentially under its own scope."""
        while True:
            batch = await inbox.drain_batch()
            # An empty batch only ever comes back once the inbox is closing (a live inbox
            # blocks the drain until a message arrives), so it is the worker's exit signal.
            if not batch:
                return
            await self._handle_batch(chat_id, batch, inbox)

    async def _handle_batch(
        self, chat_id: int, batch: Sequence[MessageReceived], inbox: ChatInbox
    ) -> None:
        """Handle one drained batch: a catch-up re-entry pass, or the normal per-burst top-k.

        🔴 BOB-066 Срез W.3 (catch-up re-entry): after an away period the batch is run as ONE
        catch-up pass — every focal + budget-ambient message is answered uncapped, the peripheral
        ambient it collapsed is skimmed (settled without a reply). 🔴 Срез W.2 (batch top-k): a
        NORMAL burst is planned so several inbound collapse to ONE addressed reply + a
        budget-capped like (a focus message is always a reply — INV-1). Both off → every message
        keeps the ENGAGE ceiling (byte-identical).
        """
        selection = self._reentry_selection(chat_id, batch)
        for _ in selection.skipped:
            # A skimmed backlog message is accounted for (its submit counted it) but never replied
            # to — settle it so ``wait_for_idle`` still resolves.
            self._settle()
        if selection.is_reentry:
            for message in selection.to_handle:
                await self._handle_one(
                    chat_id, message, ResponseOutcome.ENGAGE, inbox=inbox
                )
            return
        if self._ambient_batch is not None:
            await self._handle_stream_read(chat_id, selection.to_handle, inbox)
            return
        ceilings = self._plan_ceilings(selection.to_handle)
        for message, ceiling in zip(selection.to_handle, ceilings, strict=True):
            await self._handle_one(chat_id, message, ceiling, inbox=inbox)

    async def _handle_stream_read(
        self, chat_id: int, batch: Sequence[MessageReceived], inbox: ChatInbox
    ) -> None:
        """Split a settled burst into focal + ambient and apply the holistic read (BOB-072).

        🔴 INV-1: focal (a direct address — ``is_focused``) is answered deterministically as
        now, ABOVE and OUTSIDE the batch read (no batch reading stamped → the gate's focal
        short-circuit fires). The WHOLE ambient part goes through ONE holistic «read the stream»
        (:class:`~bob.application.runtime.intake.room_stream_reader.AmbientBatchReader`), and each
        ambient message is handled with its per-message reading riding the scope — so the gate
        persists + floor-advances EVERY ambient message including a silent IGNORE (INV-S2). The
        read never raises (a failure degrades to a safe all-IGNORE plan of the right length).

        🔴 Queue-level stale-coalesce (BOB-072): when enabled, a message the stream already
        overtook (the same identified sender reformulated in the next slot) is dropped from the
        read and stamped a silent IGNORE — still persisted (INV-S2), just never replied to
        (INV-S3). Off → every ambient message is read (byte-identical).
        """
        assert self._ambient_batch is not None  # guarded by the caller
        focal = [message for message in batch if self._is_focused(message)]
        ambient = [message for message in batch if not self._is_focused(message)]
        for message in focal:
            await self._handle_one(chat_id, message, ResponseOutcome.ENGAGE, inbox=inbox)
        if not ambient:
            return
        keep_mask = self._coalesce_mask(ambient)
        kept = [message for message, keep in zip(ambient, keep_mask, strict=True) if keep]
        fresh = iter(await self._ambient_batch.read(kept))
        for message, keep in zip(ambient, keep_mask, strict=True):
            reading = next(fresh) if keep else SILENT_IGNORE_READING
            await self._handle_one(
                chat_id,
                message,
                ResponseOutcome.ENGAGE,
                inbox=inbox,
                ambient_reading=reading,
            )

    def _coalesce_mask(
        self, ambient: Sequence[MessageReceived]
    ) -> tuple[bool, ...]:
        """Per ambient message, whether to KEEP it for the read (superseded → dropped).

        Off (the default) → every message is kept (``True``) so the read sees the whole burst
        (byte-identical). On → the pure :func:`~bob.presence.staleness.coalesce_stale` drops a
        line the same identified sender reformulated in the next slot (INV-S3); focal never
        enters here (split off above), and a dropped message is still persisted (INV-S2).
        """
        if not self._stale_coalesce_enabled:
            return tuple(True for _ in ambient)
        queued = [QueuedAmbient(sender_id=message.sender_id) for message in ambient]
        return coalesce_stale(queued)

    def _reentry_selection(
        self, chat_id: int, batch: Sequence[MessageReceived]
    ) -> CatchUpSelection:
        """Return the catch-up selection for ``batch`` (passthrough when catch-up is unwired)."""
        if self._catch_up_reentry is None:
            return CatchUpSelection.passthrough(batch)
        return self._catch_up_reentry.select(chat_id, batch)

    def _plan_ceilings(
        self, batch: Sequence[MessageReceived]
    ) -> tuple[ResponseOutcome, ...]:
        """Assign each batched message its outcome ceiling from the pure series-salience plan.

        Off (the default) → every message is uncapped (``ENGAGE``), so the worker is
        byte-identical to before the budget. On → the pure
        :func:`~bob.presence.series_salience.plan_series_actions` decides one reply + a
        budget-capped like over the burst's FOCUS flags (a focus message is never dropped).
        """
        if not self._series_budget_enabled:
            return tuple(ResponseOutcome.ENGAGE for _ in batch)
        plan = plan_series_actions(
            [self._is_focused(message) for message in batch],
            max_reactions=self._series_max_reactions,
        )
        return tuple(_CEILING_FOR_ACTION[action] for action in plan)

    def _peek_arrivals_for(
        self, message: MessageReceived, inbox: ChatInbox | None
    ) -> _PeekArrivals | None:
        """Bind this turn's non-draining ``peek_arrivals`` for the staleness врезка (W.3).

        Off (the default) or without an inbox (a directly-driven ``_handle_one``) → ``None`` so
        ``scope.peek_arrivals`` stays unset and the reply path is byte-identical. On → a closure
        that peeks what landed behind THIS message (``update_id``) at reassess time — non-draining,
        so the normal drain keeps feeding.
        """
        if not self._staleness_enabled or inbox is None:
            return None
        update_id = message.update_id
        return lambda: inbox.peek_since(update_id)

    async def _handle_one(
        self,
        chat_id: int,
        message: MessageReceived,
        ceiling: ResponseOutcome = ResponseOutcome.ENGAGE,
        *,
        inbox: ChatInbox | None = None,
        ambient_reading: RoomReading | None = None,
    ) -> None:
        """Run the real handler for one message under a fresh turn scope, isolating faults.

        The batch top-k ``ceiling`` (BOB-066 Срез W.2) rides on the :class:`TurnScope` so the
        handler seam signature is untouched; ``ENGAGE`` (the default) is no cap. When the
        staleness врезка is enabled (BOB-066 Срез W.3), the turn's non-draining
        ``peek_arrivals`` — bound to this message's ``update_id`` — also rides on the scope so
        the handler can reread what landed during generation before sending. The holistic
        stream-read's per-message ``ambient_reading`` (BOB-072) likewise rides the scope so the
        gate applies the pre-computed verdict; ``None`` (a focal message / the flag off) means
        the normal per-message path.
        """
        scope = new_turn_scope(
            base_seed=self._base_seed,
            chat_id=message.chat_id,
            message_id=message.message_id,
            series_ceiling=ceiling,
            peek_arrivals=self._peek_arrivals_for(message, inbox),
            ambient_reading=ambient_reading,
        )
        try:
            await self._handle(message, scope)
        except Exception:
            logger.exception("intake worker failed handling a message for chat %s", chat_id)
        finally:
            self._settle()

    def _settle(self) -> None:
        """Mark one submitted message as accounted for; wake ``wait_for_idle`` when none remain.

        Called once per drained message — whether it was handled (a reply/react turn) or skimmed
        by the catch-up pass (BOB-066 Срез W.3) — so the pending counter always reaches zero.
        """
        self._pending -= 1
        if self._pending == 0:
            self._idle.set()

    async def aclose(self) -> None:
        """Gracefully drain: stop accepting, flush every inbox, await the workers."""
        self._closing = True
        for inbox in self._inboxes.values():
            inbox.close()
        workers = list(self._workers.values())
        self._workers.clear()
        for task in workers:
            with contextlib.suppress(asyncio.CancelledError):
                await task
