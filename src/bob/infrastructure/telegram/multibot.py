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
* **Central router** — every deduplicated update is routed with its delivering
  **bot identity**. The **Bob path**: an *authorized* message in **Bob's topic**
  (``chat_id == bob.chat_id`` AND ``message_thread_id == bob.topic_id``)
  publishes one :class:`MessageReceived` onto the bus (Bob's pipeline) and Bob's
  replies are pinned to his topic thread. The **GUPPI path** (BEAD-03,
  :class:`~bob.infrastructure.telegram.guppi.GuppiHandler`): an *unauthorized*
  message in Bob's topic gets GUPPI's visible reject (Bob's pipeline is NOT
  invoked); an owner command in General (``/authorize`` / ``/deauthorize`` /
  ``/status``) is consumed by GUPPI. Everything else — a stranger DM, a foreign
  chat, a non-owner command — is dropped silently (no reveal).

Transport only: no Higher-Mind / LLM / memory logic. Bots are injected behind the
:class:`~bob.infrastructure.telegram.gateway.BotLike` protocol so tests use fake
aiogram bots — no network. The concrete aiogram wiring lives in ``bob.app``
(BEAD-04).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from bob.infrastructure.telegram.gateway import (
    AuthorizerLike,
    BotLike,
    TelegramGateway,
    UpdateLike,
)
from bob.infrastructure.telegram.guppi import GuppiHandler

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from bob.domain.ports import EventBus

logger = logging.getLogger(__name__)

__all__ = [
    "BotIdentity",
    "BotRegistration",
    "BotRegistry",
    "BotScope",
    "MultiBotGateway",
]


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
    """Polls every registered bot, dedups cross-bot, routes by identity + scope."""

    def __init__(
        self,
        *,
        registry: BotRegistry,
        bus: EventBus,
        poll_timeout: int,
        authorizer: AuthorizerLike | None = None,
    ) -> None:
        self._registry = registry
        self._bus = bus
        self._authorizer = authorizer
        self._poll_timeout = poll_timeout
        # One inner TelegramGateway per bot does the per-bot intake/normalisation
        # and reply streaming. Bob's inner gateway pins replies to his topic.
        self._inner: dict[BotIdentity, TelegramGateway] = {}
        for reg in registry.all():
            self._inner[reg.identity] = TelegramGateway(
                bot=reg.bot,
                bus=bus,
                poll_timeout=poll_timeout,
                batch_tokens=_DEFAULT_BATCH_TOKENS,
                throttle_interval=_DEFAULT_THROTTLE_INTERVAL,
                clock=_zero_clock,
                sleep=_noop_sleep,
                reply_thread_id=reg.scope.topic_id,
            )
        # Cross-bot dedup: a group message both admin bots see arrives on two
        # update streams; we process each (chat_id, message_id) exactly once.
        self._seen_messages: set[tuple[int, int]] = set()
        self._offsets: dict[BotIdentity, int] = dict.fromkeys(self._inner, 0)
        # GUPPI's gatekeeper identity (the visible reject + owner commands). Built
        # only when GUPPI is registered AND an authorizer is wired; otherwise the
        # GUPPI hooks fall back to silent drops (backward-compatible).
        self._guppi = self._build_guppi(authorizer)

    def _build_guppi(self, authorizer: AuthorizerLike | None) -> GuppiHandler | None:
        """Construct GUPPI's handler from its registration, if both are present."""
        if authorizer is None or BotIdentity.GUPPI not in self._inner:
            return None
        guppi_reg = self._registry.get(BotIdentity.GUPPI)
        return GuppiHandler(
            bot=guppi_reg.bot,
            authorizer=authorizer,
            general_chat_id=guppi_reg.scope.chat_id,
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
        """Poll one bot, isolating its failures from the rest."""
        identity = registration.identity
        try:
            updates = await registration.bot.get_updates(
                offset=self._offsets[identity], timeout=self._poll_timeout
            )
        except (OSError, RuntimeError, TimeoutError) as exc:
            logger.warning("bot %s poll failed (isolated): %s", identity.value, exc)
            return 0
        published = 0
        for update in updates:
            self._offsets[identity] = max(
                self._offsets[identity], update.update_id + 1
            )
            if await self.route(update, identity):
                published += 1
        return published

    # --- Central router -------------------------------------------------------

    async def route(self, update: UpdateLike, identity: BotIdentity) -> bool:
        """Route one ``(update, bot_identity)`` through the central router.

        The public ``(update, identity)`` seam: cross-bot dedup, then Bob's
        topic-scope + authorization, publishing onto Bob's pipeline when the
        update is his. Dedup + scope are identity-independent (a group message is
        processed once whichever admin bot delivered it); ``identity`` is the
        routing key future replicas and the GUPPI branch dispatch on. Returns
        ``True`` iff a :class:`MessageReceived` was published (the Bob path only).

        Bob's topic + unauthorized → GUPPI's visible reject (no publish). General +
        owner command → GUPPI consumes it (no publish). Everything else (stranger
        DM, foreign chat, non-owner command) is dropped silently — no reveal.
        """
        message = update.message
        chat = update.effective_chat
        if message is None or chat is None or not message.text:
            return False

        key = (chat.id, message.message_id)
        if key in self._seen_messages:
            logger.debug("dropping cross-bot duplicate %s via %s", key, identity.value)
            return False
        self._seen_messages.add(key)

        bob_scope = self._registry.scope_of(BotIdentity.BOB)
        if not bob_scope.matches(
            chat_id=chat.id, message_thread_id=message.message_thread_id
        ):
            # Not Bob's topic (General / other topic / foreign chat): GUPPI may
            # consume an owner command in General; otherwise drop silently.
            await self._maybe_guppi_command(update, chat.id)
            return False

        if not await self._is_authorized(update, chat.id):
            # Unauthorized inside Bob's topic → GUPPI's visible reject; Bob's
            # pipeline is NOT invoked.
            await self._guppi_reject(chat.id, message.message_thread_id)
            return False

        # Authorized, in Bob's topic → publish onto Bob's pipeline (as today).
        return await self._inner[BotIdentity.BOB].intake(update)

    async def _maybe_guppi_command(self, update: UpdateLike, chat_id: int) -> None:
        """Let GUPPI consume an owner command in General (silent otherwise)."""
        if self._guppi is None:
            return
        message = update.message
        text = message.text if message is not None else None
        if text is None:
            return
        user = update.effective_user
        user_id = user.id if user is not None else None
        await self._guppi.handle_general_command(
            text=text, user_id=user_id, chat_id=chat_id
        )

    async def _guppi_reject(self, chat_id: int, thread_id: int | None) -> None:
        """Send GUPPI's visible "unauthorized" reject into Bob's topic thread."""
        if self._guppi is None:
            return
        await self._guppi.reject(chat_id=chat_id, thread_id=thread_id)

    async def _is_authorized(self, update: UpdateLike, chat_id: int) -> bool:
        """Classify the sender via the injected Authorizer (open if unwired)."""
        if self._authorizer is None:
            return True
        user = update.effective_user
        user_id = user.id if user is not None else None
        return await self._authorizer.is_authorized(user_id=user_id, chat_id=chat_id)

    # --- Reply (per identity) -------------------------------------------------

    def reply_streamer(self, identity: BotIdentity) -> _ReplyStreamer:
        """Return the reply seam for ``identity`` (Bob's pins his topic thread)."""
        return _ReplyStreamer(self._inner[identity])


class _ReplyStreamer:
    """Adapts a per-bot :class:`TelegramGateway` to the ``ReplyStreamer`` port.

    Delegates to the inner gateway, which already pins ``message_thread_id`` for
    its bot, so HandleMessage's ``stream_reply(chat_id, tokens)`` stays untouched
    yet Bob's replies land in his topic thread.
    """

    def __init__(self, gateway: TelegramGateway) -> None:
        self._gateway = gateway

    async def stream_reply(
        self, *, chat_id: int, tokens: AsyncIterator[str]
    ) -> int:
        return await self._gateway.stream_reply(chat_id=chat_id, tokens=tokens)


# Reply-streaming knobs for the inner gateways. The multi-bot intake does not
# itself stream drafts during routing; replies flow through reply_streamer, where
# batching/throttle are exercised by the inner gateway's own (tested) path. These
# defaults keep a single committed message per reply without timed throttling.
_DEFAULT_BATCH_TOKENS = 1
_DEFAULT_THROTTLE_INTERVAL = 0.0


def _zero_clock() -> float:
    return 0.0


async def _noop_sleep(_seconds: float) -> None:
    return None
