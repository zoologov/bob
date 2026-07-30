# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""MultiBotGateway — one process, two admin bots, one central router (BOB-003).

Bob and GUPPI share a single intake: both are group admins, so a group message
can be delivered to BOTH bots. This module is the multi-bot seam that keeps that
sane and forward-compatible with future replica bots (Bobiverse):

* **:class:`BotRegistry`** — register a bot as ``{identity, bot, scope}``. Adding
  a replica is one more ``register`` call, no rewrite of the composition.
* **One poll over all bots.** :meth:`MultiBotGateway.poll_once` pulls each
  registered bot's updates; a failing or reconnecting bot is isolated so it
  cannot stop the others (bot isolation, leaning on BOB-002 resilience).
* **Cross-bot dedup.** A message both admin bots see is keyed on
  ``(chat_id, message_id)`` and processed **once** — independent of which bot
  delivered it (a different key from the per-bot ``update_id`` dedup the inner
  :class:`TelegramGateway` does).
* **Central router (routes by content, not by the delivering bot).** The same
  group message arrives once per admin bot, and the copies are *not*
  interchangeable: Telegram may deliver the General-scoped GUPPI bot's copy of a
  Bob-topic message **without** ``message_thread_id`` while the Bob bot's copy
  carries it. So the handler is chosen from the message's **content** (chat +
  topic-thread + authorization), independent of which bot delivered it, and the
  cross-bot dedup slot is committed only **after** a copy was actually handled —
  a non-routable copy leaves the slot open for its routable sibling. The **Bob
  path**: ANY message in **Bob's topic** (``chat_id == bob.chat_id`` AND
  ``message_thread_id == bob.topic_id`` — so, by construction, inside the allowed
  chat) publishes one :class:`MessageReceived` onto the bus (Bob's pipeline) and
  Bob's replies are pinned to his topic thread. An *authorized* sender (owner /
  allowlisted) gets Bob's full trusted path; an *unauthorized* one is a **guest**
  (BOB-019): instead of GUPPI's old hard reject they reach Bob's social pipeline,
  and the *restricted* guest mode (no tools, no owner memory, audience-redacted) is
  enforced downstream in :class:`~bob.application.usecases.handle_message.HandleMessage`
  (which re-derives trust from the same Authorizer via sender perception). The
  **GUPPI path** (BEAD-03,
  :class:`~bob.infrastructure.telegram.guppi.GuppiHandler`): an owner command in
  General (``/authorize`` / ``/deauthorize`` / ``/status``) is consumed by GUPPI.
  Everything else — a stranger DM, a foreign chat, a non-owner command — is dropped
  silently (no reveal); chat-scope is unchanged, so only the allowed chat's Bob
  topic earns the guest route.

Transport only: no Higher-Mind / LLM / memory logic. Bots are injected behind the
:class:`~bob.infrastructure.telegram.gateway.BotLike` protocol so tests use fake
aiogram bots — no network. The concrete aiogram wiring lives in ``bob.app``
(BEAD-04).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramNetworkError

from bob.application.reliability import call_with_retry
from bob.infrastructure.telegram.gateway import (
    AuthorizerLike,
    BobMessageFilter,
    BotIdentitySignals,
    BotLike,
    MonotonicClock,
    Sleep,
    TelegramGateway,
    UpdateLike,
    is_reaction_update,
)
from bob.infrastructure.telegram.guppi import GuppiHandler

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from bob.infrastructure.telegram.gateway import MessageLike
    from bob.infrastructure.telegram.guppi import (
        CodingAssistantLike,
        GoalStoreLike,
        ProactivityStoreLike,
        PursuitStoreLike,
        RuleStoreLike,
    )
    from bob.kernel.ports import Clock, EventBus
    from bob.proactivity.usecases.plan_goal import PlanGoal

logger = logging.getLogger(__name__)

# Reply-typing cadence for the inner gateways. Replies flow through reply_gateway,
# which (BOB-009) wraps the slow generation in a ``typing_indicator`` keepalive,
# then commits one rich final — no streaming. Bob cannot stream in a group topic
# (drafts are DM-only, edits are slow + flood-prone), so the inner gateways re-send
# ``sendChatAction("typing")`` about every ``_DEFAULT_TYPING_INTERVAL`` seconds
# (Telegram auto-clears the indicator after a few seconds), driven by the injected
# ``sleep`` so a long generation keeps showing "Bob is typing…".
_DEFAULT_TYPING_INTERVAL = 4.0

# Startup identity resolution (BOB-059): a momentary network flap while asking Bob's
# bot ``get_me`` must not crash startup. The call is retried a few times with a short
# backoff (through an INJECTED sleep so tests are deterministic) before it degrades
# gracefully — enough to ride out a blip without stalling the process on a real outage.
_DEFAULT_IDENTITY_RETRY_ATTEMPTS = 3
_DEFAULT_IDENTITY_RETRY_BACKOFF_SECONDS = 1.0

# Poison-cap for the poll loop (BOB-070). An update whose ``route()`` keeps
# raising is re-attempted at most this many times (Telegram redelivers every
# update ≥ the offset, so a non-advanced offset means a redelivery) and is then
# skipped LOUDLY so a single wedged update cannot stall intake forever.
_MAX_ROUTE_ATTEMPTS = 3


def _zero_clock() -> float:
    return 0.0


async def _noop_sleep(_seconds: float) -> None:
    # A "no real wait" sleep for intake-only / deterministic wiring. It still
    # ``await``s a real suspension point so it can NEVER starve the event loop:
    # the reply path's typing keepalive runs a ``while True`` loop driven by this
    # sleep, and a sleep that returns without yielding would spin it at 100% CPU.
    await asyncio.sleep(0)


# Real timing seams for the live inner gateways (the deterministic stubs above are
# kept for tests/intake-only wiring that must not actually wait).
_LIVE_CLOCK: MonotonicClock = time.monotonic
_LIVE_SLEEP: Sleep = asyncio.sleep

__all__ = [
    "BotIdentity",
    "BotRegistration",
    "BotRegistry",
    "BotScope",
    "MultiBotGateway",
]


class _RouteOutcome(Enum):
    """What the central router did with one message copy (drives cross-bot dedup).

    ``PUBLISHED`` / ``HANDLED`` mean a real handler ran (Bob's pipeline, GUPPI's
    reject, or a GUPPI command) → the ``(chat_id, message_id)`` slot is committed.
    ``UNROUTABLE`` means this copy matched no handler (e.g. a thread-less duplicate
    of a Bob-topic message) → the slot stays open so a routable sibling copy can
    still be handled.
    """

    PUBLISHED = "published"
    HANDLED = "handled"
    UNROUTABLE = "unroutable"


class BotIdentity(Enum):
    """Which persona a registered bot is — the routing key.

    ``BOB`` is the persona living in his topic; ``GUPPI`` is the gatekeeper/admin
    in General. New replicas (Bender, Bill, …) get their own member later.
    """

    BOB = "bob"
    GUPPI = "guppi"


@dataclass(frozen=True, slots=True)
class BotScope:
    """Where a bot is active: a chat, optionally pinned to one topic thread.

    ``topic_id`` set (Bob) means the bot owns exactly that thread; ``None``
    (GUPPI) means the General / un-threaded scope of the chat.
    """

    chat_id: int
    topic_id: int | None

    def matches(self, *, chat_id: int, message_thread_id: int | None) -> bool:
        """Whether an update in ``chat_id``/``message_thread_id`` is in scope."""
        return chat_id == self.chat_id and message_thread_id == self.topic_id


@dataclass(frozen=True, slots=True)
class BotRegistration:
    """A registered bot: its identity, the bot adapter, and its active scope."""

    identity: BotIdentity
    bot: BotLike
    scope: BotScope


class BotRegistry:
    """The set of bots this process polls, keyed by identity (registration order)."""

    def __init__(self) -> None:
        self._registrations: dict[BotIdentity, BotRegistration] = {}

    def register(
        self, *, identity: BotIdentity, bot: BotLike, scope: BotScope
    ) -> None:
        """Register ``bot`` under ``identity`` with its ``scope``.

        Re-registering an identity replaces it (idempotent wiring). Adding a
        future replica is exactly one more call here.
        """
        self._registrations[identity] = BotRegistration(
            identity=identity, bot=bot, scope=scope
        )

    def get(self, identity: BotIdentity) -> BotRegistration:
        """Return the registration for ``identity`` (raises if absent)."""
        return self._registrations[identity]

    def all(self) -> tuple[BotRegistration, ...]:
        """Every registration, in registration order."""
        return tuple(self._registrations.values())

    def scope_of(self, identity: BotIdentity) -> BotScope:
        """The scope a bot is registered with."""
        return self._registrations[identity].scope


class MultiBotGateway:
    """Polls every registered bot, dedups cross-bot, routes by message content."""

    def __init__(
        self,
        *,
        registry: BotRegistry,
        bus: EventBus,
        poll_timeout: int,
        authorizer: AuthorizerLike | None = None,
        proactivity_store: ProactivityStoreLike | None = None,
        proactivity_clock: Clock | None = None,
        goal_store: GoalStoreLike | None = None,
        plan_goal: PlanGoal | None = None,
        pursuit_store: PursuitStoreLike | None = None,
        rule_store: RuleStoreLike | None = None,
        coding_assistant: CodingAssistantLike | None = None,
        reply_typing_interval: float = _DEFAULT_TYPING_INTERVAL,
        reply_clock: MonotonicClock = _LIVE_CLOCK,
        reply_sleep: Sleep = _LIVE_SLEEP,
        bob_reaction_filter: BobMessageFilter | None = None,
        identity_retry_attempts: int = _DEFAULT_IDENTITY_RETRY_ATTEMPTS,
        identity_retry_backoff_seconds: float = (
            _DEFAULT_IDENTITY_RETRY_BACKOFF_SECONDS
        ),
        identity_retry_sleep: Sleep = _LIVE_SLEEP,
    ) -> None:
        self._registry = registry
        self._bus = bus
        self._authorizer = authorizer
        # BOB-059: the get_me startup-retry seam. Defaults ride out a transient
        # Telegram blip with a real ``asyncio.sleep`` backoff; tests inject a fake
        # sleep + small attempts for deterministic, wait-free assertions.
        self._identity_retry_attempts = identity_retry_attempts
        self._identity_retry_backoff_seconds = identity_retry_backoff_seconds
        self._identity_retry_sleep = identity_retry_sleep
        self._proactivity_store = proactivity_store
        self._proactivity_clock = proactivity_clock
        self._goal_store = goal_store
        self._plan_goal = plan_goal
        self._pursuit_store = pursuit_store
        self._rule_store = rule_store
        self._coding_assistant = coding_assistant
        self._poll_timeout = poll_timeout
        # One inner TelegramGateway per bot does the per-bot intake/normalisation
        # and reply. Bob's inner gateway pins replies — and the "typing…" indicator
        # — to his topic.
        #
        # The reply clock/sleep/typing-interval default to the live values (a real
        # monotonic clock + ``asyncio.sleep`` + a ~4s typing cadence) so a long
        # generation keeps showing "Bob is typing…" (BOB-008); tests inject
        # deterministic stubs to avoid real waiting.
        #
        # Only Bob's inner gateway gets the reaction filter (BOB-050): reactions are
        # perceived for HIS messages, so GUPPI's gateway has none and drops them.
        self._inner: dict[BotIdentity, TelegramGateway] = {}
        for reg in registry.all():
            self._inner[reg.identity] = TelegramGateway(
                bot=reg.bot,
                bus=bus,
                poll_timeout=poll_timeout,
                typing_interval=reply_typing_interval,
                clock=reply_clock,
                sleep=reply_sleep,
                reply_thread_id=reg.scope.topic_id,
                bob_reaction_filter=(
                    bob_reaction_filter
                    if reg.identity is BotIdentity.BOB
                    else None
                ),
            )
        # Cross-bot dedup: a group message both admin bots see arrives on two
        # update streams; we process each (chat_id, message_id) exactly once.
        self._seen_messages: set[tuple[int, int]] = set()
        self._offsets: dict[BotIdentity, int] = dict.fromkeys(self._inner, 0)
        # Poison-cap (BOB-070): per-bot, per-``update_id`` count of consecutive
        # ``route()`` failures. It grows on a failed route, and is cleared on a
        # success OR after the update is skipped past the cap — so it holds only
        # the currently-wedged update (normally empty), never unbounded memory.
        self._route_failures: dict[BotIdentity, dict[int, int]] = {
            identity: {} for identity in self._inner
        }
        # GUPPI's gatekeeper identity (the visible reject + owner commands). Built
        # only when GUPPI is registered AND an authorizer is wired; otherwise the
        # GUPPI hooks fall back to silent drops (backward-compatible).
        self._guppi = self._build_guppi(authorizer)

    @property
    def registry(self) -> BotRegistry:
        """The bot registry this gateway polls (read-only view for composition)."""
        return self._registry

    @property
    def guppi(self) -> GuppiHandler | None:
        """GUPPI's handler (or ``None`` if GUPPI is not registered) — for composition.

        Exposed so the composition root can hand GUPPI to the обида seam as the
        one-shot :class:`~bob.social.usecases.sulk_sources.SulkAnnouncer`
        (GUPPI posts "Боб обижен …" on a fresh sulk entry, BOB-014 .2b). Read-only.
        """
        return self._guppi

    def _build_guppi(self, authorizer: AuthorizerLike | None) -> GuppiHandler | None:
        """Construct GUPPI's handler from its registration, if both are present.

        When a proactivity store (and clock) are wired in, GUPPI also owns the
        owner ``/quiet`` / ``/wake`` commands that toggle Bob's persisted
        proactivity flag; with a goal store + plan use-case + pursuit store wired,
        it additionally owns the BOB-015 goal commands (``/goals``,
        ``/goal approve|plan|plan-approve|pause|resume|cancel``, ``/goals stop|go``).
        Each unwired group of commands falls through to a silent drop
        (backward-compatible).
        """
        if authorizer is None or BotIdentity.GUPPI not in self._inner:
            return None
        guppi_reg = self._registry.get(BotIdentity.GUPPI)
        return GuppiHandler(
            bot=guppi_reg.bot,
            authorizer=authorizer,
            general_chat_id=guppi_reg.scope.chat_id,
            proactivity_store=self._proactivity_store,
            clock=self._proactivity_clock,
            goal_store=self._goal_store,
            plan_goal=self._plan_goal,
            pursuit_store=self._pursuit_store,
            rule_store=self._rule_store,
            coding_assistant=self._coding_assistant,
            coding_configured=True,
        )

    # --- Startup --------------------------------------------------------------

    async def resolve_bot_identities(self) -> None:
        """Resolve Bob's own bot identity via ``get_me`` and thread it in (BOB-023).

        Called once at startup (the synchronous constructor cannot ``await``):
        asks Bob's bot who it is (id + ``@username``) and wires that into Bob's
        inner gateway so the addressivity scan can tell an @mention of Bob from a
        mention of someone else. Best-effort — a ``get_me`` failure is logged and
        leaves mentions unresolved (``mentions_bob`` stays ``False``) rather than
        blocking startup; reply-to addressivity is unaffected.

        A momentary network flap must not crash the whole process (BOB-059): the
        call is retried a few times with a short injected backoff, so a transient
        blip is ridden out and the identity still resolves. On a PERSISTENT failure
        — including the ``TelegramNetworkError`` aiogram raises on a dropped
        connection (which the pre-BOB-059 ``except`` did not catch, so startup died)
        — it degrades gracefully: warn + return, and startup CONTINUES (polling is
        resilient, so Bob still listens and the identity re-resolves later). A
        NON-network error (a programming bug) is deliberately NOT swallowed — it
        propagates so the fault surfaces.
        """
        if BotIdentity.BOB not in self._inner:
            return
        bob_bot = self._registry.get(BotIdentity.BOB).bot
        get_me = getattr(bob_bot, "get_me", None)
        if get_me is None:
            return
        try:
            me = await call_with_retry(
                get_me,
                attempts=self._identity_retry_attempts,
                backoff_seconds=self._identity_retry_backoff_seconds,
                sleep=self._identity_retry_sleep,
            )
        except (OSError, RuntimeError, TimeoutError, TelegramNetworkError) as exc:
            logger.warning("could not resolve Bob's bot identity (get_me): %s", exc)
            return
        self._inner[BotIdentity.BOB].set_bob_identity(
            BotIdentitySignals(user_id=me.id, username=me.username)
        )

    # --- Intake (all bots) ----------------------------------------------------

    async def poll_once(self) -> int:
        """Poll every bot once (isolated), route the updates, return publish count.

        Each bot is polled independently: one bot raising (a flaky connection /
        reconnect) is logged and skipped, never stopping the others. Returns how
        many :class:`MessageReceived` were published this poll.
        """
        published = 0
        for reg in self._registry.all():
            published += await self._poll_bot(reg)
        return published

    async def _poll_bot(self, registration: BotRegistration) -> int:
        """Poll one bot, isolating its failures from the rest.

        Приём не теряет сообщения на транзиентных обрывах Telegram (BOB-070):

        * **offset — ПОСЛЕ обработки (INV-a).** Сдвигаем ``self._offsets[identity]``
          за апдейт только когда ``route()`` вернулся без исключения. Если
          ``route()`` бросил — offset не двигаем, и Telegram переприсылает апдейт
          (at-least-once) на следующем тике.
        * **батч встаёт на первом сбое (INV-e).** offset монотонный, а Telegram
          переприсылает ВСЁ, что ≥ offset. Значит после сбоя апдейта N нельзя
          обрабатывать N+1 (иначе offset уехал бы за N и N потерян навсегда) —
          прерываем батч на N. Порядок и at-least-once сохранены: остаток придёт
          следующим тиком уже с N во главе.
        * **poison-cap (INV-b).** Апдейт, стабильно падающий в ``route()``, не
          зацикливает приём: считаем неудачи per-``update_id``; после
          ``_MAX_ROUTE_ATTEMPTS`` попыток ГРОМКО логируем и ПРОПУСКАЕМ его
          (сдвигаем offset за него, сбрасываем счётчик). Успех тоже сбрасывает
          счётчик — транзиент не «докапливается» до cap.
        * **изоляция сети (INV-c/d).** ``get_updates`` может бросить
          ``TelegramNetworkError`` (обёртка ``ServerDisconnectedError`` на
          рутинном обрыве long-poll) наравне с OSError/RuntimeError/TimeoutError —
          ловим, логируем, ``return 0``; offset не тронут, тик и таск живы,
          другие боты не задеты.
        """
        identity = registration.identity
        try:
            updates = await registration.bot.get_updates(
                offset=self._offsets[identity], timeout=self._poll_timeout
            )
        except (OSError, RuntimeError, TimeoutError, TelegramNetworkError) as exc:
            logger.warning("bot %s poll failed (isolated): %s", identity.value, exc)
            return 0
        published = 0
        failures = self._route_failures[identity]
        for update in updates:
            try:
                routed = await self.route(update, identity)
            except Exception as exc:
                # INV-d: ловим broadly — любой транзиент из route() не должен
                # ронять poll-таск (CancelledError — BaseException, не задет).
                attempts = failures[update.update_id] = (
                    failures.get(update.update_id, 0) + 1
                )
                if attempts > _MAX_ROUTE_ATTEMPTS:
                    # poison: стабильно падает → ГРОМКО логируем и ПРОПУСКАЕМ,
                    # сдвигая offset за него, чтобы не зациклить приём.
                    logger.error(
                        "bot %s update %d poisoned (route failed %d×) — skipping "
                        "to avoid a poll loop: %s",
                        identity.value, update.update_id, attempts, exc,
                    )
                    del failures[update.update_id]
                    self._offsets[identity] = max(
                        self._offsets[identity], update.update_id + 1
                    )
                    continue
                # Транзиент: offset НЕ двигаем → Telegram переприсылает; батч
                # останавливаем здесь, чтобы не увести offset за непринятый апдейт.
                logger.warning(
                    "bot %s update %d route failed (attempt %d, will redeliver): %s",
                    identity.value, update.update_id, attempts, exc,
                )
                break
            # Durably принят: сбрасываем poison-счётчик и двигаем offset за него.
            failures.pop(update.update_id, None)
            self._offsets[identity] = max(
                self._offsets[identity], update.update_id + 1
            )
            if routed:
                published += 1
        return published

    # --- Central router -------------------------------------------------------

    async def route(self, update: UpdateLike, identity: BotIdentity) -> bool:
        """Route one ``(update, bot_identity)`` through the central router.

        The public ``(update, identity)`` seam. Both admin bots are group admins,
        so the same group message arrives once per bot — and the copies are *not*
        interchangeable: Telegram may deliver the General-scoped GUPPI bot's copy
        of a Bob-topic message **without** ``message_thread_id`` while the Bob
        bot's copy carries it. So the routing decision is made from the message's
        **content** (chat + topic-thread + authorization), never from which bot
        delivered it; the cross-bot dedup keyed on ``(chat_id, message_id)`` only
        commits **after** a copy has actually been handled, so a non-routable copy
        (a thread-less duplicate that matches neither Bob's topic nor a General
        command) does not swallow the slot a later, routable copy needs.

        Returns ``True`` iff a :class:`MessageReceived` was published (the Bob
        path only). Bob's topic + unauthorized → GUPPI's visible reject (no
        publish). General + owner command → GUPPI consumes it (no publish).
        Everything else (stranger DM, foreign chat, non-owner command, a
        non-routable duplicate) is dropped silently — no reveal.

        A reaction update (BOB-050) is routed to Bob's inner gateway (only via Bob's
        own bot copy, to avoid a double from GUPPI) where it is filtered to Bob's
        messages and published as a :class:`BobMessageReaction`; it never counts as a
        published :class:`MessageReceived`.
        """
        if is_reaction_update(update):
            await self._route_reaction(update, identity)
            return False

        message = update.message
        chat = update.effective_chat
        if message is None or chat is None or not message.text:
            return False

        key = (chat.id, message.message_id)
        if key in self._seen_messages:
            logger.debug("dropping cross-bot duplicate %s via %s", key, identity.value)
            return False

        outcome = await self._route_by_content(update, chat.id, message)
        # Only a copy that actually reached a handler commits the dedup slot. A
        # non-routable copy (e.g. GUPPI's thread-less copy of a Bob-topic message)
        # leaves the slot open so the Bob-topic copy can still be routed.
        if outcome is not _RouteOutcome.UNROUTABLE:
            self._seen_messages.add(key)
        return outcome is _RouteOutcome.PUBLISHED

    async def _route_by_content(
        self, update: UpdateLike, chat_id: int, message: MessageLike
    ) -> _RouteOutcome:
        """Classify the message by its content (not the delivering bot) and act.

        * Bob's topic (authorized OR a guest) → publish onto Bob's pipeline.
        * General owner command → GUPPI consumes it.
        * anything else → unroutable (caller leaves the dedup slot open).

        A message inside Bob's topic is by construction inside the **allowed chat**
        (Bob's scope chat is the allowed chat), so reaching this branch already
        means the sender passed chat-scope. An *authorized* sender (owner /
        allowlisted) takes Bob's full trusted path; an *unauthorized* one is a
        **guest** (BOB-019 bob-apv.2) — instead of GUPPI's old hard reject they are
        published onto Bob's pipeline so Bob can meet them socially, and the
        *restricted* guest mode (no tools, no owner memory, audience-redacted) is
        enforced downstream in :class:`HandleMessage` (which re-derives trust from
        the same Authorizer via sender perception). Outside Bob's topic nothing
        changes: a foreign chat / DM never matches Bob's scope and is dropped here.
        """
        bob_scope = self._registry.scope_of(BotIdentity.BOB)
        if bob_scope.matches(
            chat_id=chat_id, message_thread_id=message.message_thread_id
        ):
            # In Bob's topic (so in the allowed chat): publish onto Bob's pipeline,
            # whether the sender is authorized (trusted path) or a guest (restricted
            # path) — the trusted/guest split is HandleMessage's concern, not the
            # router's. The visible hard reject is gone for Bob-topic messages.
            if await self._inner[BotIdentity.BOB].intake(update):
                return _RouteOutcome.PUBLISHED
            return _RouteOutcome.HANDLED
        # Not Bob's topic: GUPPI may consume an owner command in General.
        if await self._maybe_guppi_command(update, chat_id):
            return _RouteOutcome.HANDLED
        return _RouteOutcome.UNROUTABLE

    async def _route_reaction(
        self, update: UpdateLike, identity: BotIdentity
    ) -> None:
        """Dispatch a reaction update to Bob's inner gateway (BOB-050).

        Only Bob's OWN bot copy is dispatched — both admin bots may see the same
        reaction, so routing just Bob's copy avoids a duplicate event (and the inner
        gateway dedups by ``update_id`` on top). With no Bob gateway registered the
        reaction is dropped.
        """
        if identity is not BotIdentity.BOB:
            return
        inner = self._inner.get(BotIdentity.BOB)
        if inner is None:
            return
        await inner.intake_reaction(update)

    async def _maybe_guppi_command(self, update: UpdateLike, chat_id: int) -> bool:
        """Let GUPPI consume an owner command in General; return whether it did."""
        if self._guppi is None:
            return False
        message = update.message
        text = message.text if message is not None else None
        if text is None:
            return False
        user = update.effective_user
        user_id = user.id if user is not None else None
        return await self._guppi.handle_general_command(
            text=text, user_id=user_id, chat_id=chat_id
        )

    # --- Reply (per identity) -------------------------------------------------

    def reply_gateway(self, identity: BotIdentity) -> _ReplyGateway:
        """Return the reply seam for ``identity`` (Bob's pins his topic thread)."""
        return _ReplyGateway(self._inner[identity])

    def bob_user_id(self) -> int | None:
        """Bob's own bot ``user_id``, or ``None`` until resolved at startup (BOB-023).

        The addressivity policy reads this lazily through the use-case's id seam so a
        reply that targets Bob is told from one targeting someone else. It is resolved
        asynchronously by :meth:`resolve_bot_identities` (``get_me``) AFTER the
        synchronous composition root wired the use-case, so it is ``None`` until then
        (and when Bob's gateway is absent) — a graceful degrade (reply-to-Bob cannot
        fire; @mention still does).
        """
        gateway = self._inner.get(BotIdentity.BOB)
        return gateway.bob_user_id() if gateway is not None else None

    def reactor(self, identity: BotIdentity) -> _ReactorGateway:
        """Return the react-only seam for ``identity`` (BOB-018).

        Wraps the per-bot inner gateway so a react-only turn sets a native
        reaction (pinned to the bot's thread) instead of composing a reply; the
        inner gateway makes the reaction best-effort (fallback to a brief ack).
        """
        return _ReactorGateway(self._inner[identity])


class _ReplyGateway:
    """Adapts a per-bot :class:`TelegramGateway` to the ``ReplyGateway`` port (BOB-009).

    Delegates to the inner gateway, which already pins ``message_thread_id`` for its
    bot, so HandleMessage's ``typing_indicator`` keepalive and the one rich ``reply``
    both land in Bob's topic thread.
    """

    def __init__(self, gateway: TelegramGateway) -> None:
        self._gateway = gateway

    def typing_indicator(
        self, *, chat_id: int
    ) -> AbstractAsyncContextManager[None]:
        return self._gateway.typing_indicator(chat_id=chat_id)

    async def reply(
        self,
        *,
        chat_id: int,
        markdown: str,
        thinking: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> int | None:
        return await self._gateway.reply(
            chat_id=chat_id,
            markdown=markdown,
            thinking=thinking,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_photo(
        self, *, chat_id: int, photo: bytes, caption: str | None = None
    ) -> None:
        # BOB-035: post a rendered diagram PNG into Bob's topic thread (the inner
        # gateway pins ``message_thread_id``), so render_diagram's image lands in chat.
        await self._gateway.send_photo(chat_id=chat_id, photo=photo, caption=caption)

    async def send_document(
        self, *, chat_id: int, document: bytes, caption: str | None = None
    ) -> None:
        # BOB-037: post a rendered diagram as an UNCOMPRESSED file into Bob's topic
        # thread (no Telegram recompression — full-resolution, tap → real pixels).
        await self._gateway.send_document(
            chat_id=chat_id, document=document, caption=caption
        )


class _ReactorGateway:
    """Adapts a per-bot :class:`TelegramGateway` to the ``MessageReactor`` port (BOB-018).

    Delegates to the inner gateway, which sets a native ``set_message_reaction``
    pinned to the bot's thread (best-effort, with a brief textual-ack fallback), so
    HandleMessage's react-only turn lands Bob's reaction in his topic thread.
    """

    def __init__(self, gateway: TelegramGateway) -> None:
        self._gateway = gateway

    async def react(self, *, chat_id: int, message_id: int, emoji: str) -> None:
        await self._gateway.react(chat_id=chat_id, message_id=message_id, emoji=emoji)


