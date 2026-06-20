# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""GuppiHandler — the GUPPI gatekeeper/admin identity (BOB-003 BEAD-03).

GUPPI is the second admin bot in the process: the gatekeeper in General and the
visible "you're not allowed" voice in Bob's topic. This module owns *only* GUPPI's
behaviours; the multi-bot router (:mod:`bob.infrastructure.telegram.multibot`)
dispatches its two BEAD-02 drop-hooks here:

* :meth:`GuppiHandler.reject` — an unauthorized user wrote in Bob's topic, so
  GUPPI sends the visible :data:`GUPPI_REJECT_TEXT` back into **that same chat +
  thread**. Bob's pipeline is never invoked. (The router only reaches this hook
  for the allowed group's Bob topic, so a stranger DM never triggers a reject.)
* :meth:`GuppiHandler.handle_general_command` — an owner-only command in General:
  ``/authorize <id>`` / ``/deauthorize <id>`` mutate the allowlist through the
  shared :class:`~bob.application.authz.Authorizer` (no duplicated authz),
  ``/status`` answers a short whoami line, and — when a proactivity store is wired
  in — ``/quiet`` (optionally ``/quiet 2h`` for a timed mute) / ``/wake`` toggle
  Bob's per-persona proactivity flag (and its timed-mute expiry). A command from
  anyone but the owner, a non-command message, or any chat other than the General
  chat is **ignored and silent** — no reveal outside the group.

Transport only: GUPPI replies are sent through GUPPI's own injected bot (never
Bob's). The bot is behind the :class:`~bob.infrastructure.telegram.gateway.BotLike`
protocol so tests use a fake bot — no network.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from bob.domain.ports import Clock
    from bob.domain.proactivity.state import ProactivityState
    from bob.infrastructure.telegram.gateway import AuthorizerLike, BotLike

__all__ = [
    "GUPPI_REJECT_TEXT",
    "GuppiHandler",
]

# The single visible reject shown to an unauthorized user inside Bob's topic.
GUPPI_REJECT_TEXT = "⛔ Пользователь не авторизован"

# Owner-only privileged commands GUPPI consumes in General.
_AUTHORIZE_COMMAND = "/authorize"
_DEAUTHORIZE_COMMAND = "/deauthorize"
_STATUS_COMMAND = "/status"
_QUIET_COMMAND = "/quiet"
_WAKE_COMMAND = "/wake"

_USAGE_AUTHORIZE = "Использование: /authorize <user_id>"
_USAGE_DEAUTHORIZE = "Использование: /deauthorize <user_id>"
_USAGE_QUIET = "Использование: /quiet [длительность], напр. /quiet 2h или /quiet 30m"
_STATUS_TEXT = "GUPPI на связи — привратник Боба. Команды: /authorize, /deauthorize, /status."
_QUIET_TEXT = "Боб притих — проактивность выключена."
_QUIET_TIMED_TEXT = "Боб притих до {until} — проактивность выключена."
_WAKE_TEXT = "Боб снова на связи — проактивность включена."

# Suffix → unit multiplier (to seconds) for the optional timed-mute duration.
_DURATION_UNITS = {"h": 3600, "m": 60, "s": 1}


class _ProactivityStoreLike(Protocol):
    """The proactivity-store surface the owner /quiet, /wake commands need."""

    async def load(self, persona_id: str) -> ProactivityState: ...
    async def save(self, persona_id: str, state: ProactivityState) -> None: ...
    async def set_mute_until(self, persona_id: str, until: datetime | None) -> None: ...


class GuppiHandler:
    """GUPPI's gatekeeper behaviours: the visible reject + owner commands."""

    def __init__(
        self,
        *,
        bot: BotLike,
        authorizer: AuthorizerLike,
        general_chat_id: int,
        proactivity_store: _ProactivityStoreLike | None = None,
        clock: Clock | None = None,
        persona_id: str = "bob",
    ) -> None:
        self._bot = bot
        self._authorizer = authorizer
        self._general_chat_id = general_chat_id
        self._proactivity_store = proactivity_store
        self._clock = clock
        self._persona_id = persona_id

    async def reject(self, *, chat_id: int, thread_id: int | None) -> None:
        """Send the visible "unauthorized" reject into ``chat_id``/``thread_id``.

        The router only calls this for an unauthorized message inside the allowed
        group's Bob topic, so the reject is always scoped to the group (never a
        DM). Bob's pipeline is not invoked — GUPPI just speaks.
        """
        await self._bot.send_message(
            chat_id=chat_id,
            text=GUPPI_REJECT_TEXT,
            message_thread_id=thread_id,
        )

    async def handle_general_command(
        self, *, text: str, user_id: int | None, chat_id: int
    ) -> bool:
        """Handle an owner command in General; return whether it was consumed.

        Returns ``True`` only when GUPPI handled the message (a known owner command
        from the owner in the General chat). For a non-owner sender, a non-command
        message, or any chat other than General the call is silent and returns
        ``False`` — no reveal, no grant.
        """
        if chat_id != self._general_chat_id or not self._authorizer.is_owner(user_id):
            return False
        command, _, argument = text.strip().partition(" ")
        return await self._dispatch_authz(chat_id, command, argument) or (
            await self._dispatch_proactivity(chat_id, command, argument)
        )

    async def _dispatch_authz(self, chat_id: int, command: str, argument: str) -> bool:
        """Handle the allowlist owner commands; ``False`` if ``command`` is none of them."""
        if command == _AUTHORIZE_COMMAND:
            await self._grant(chat_id, argument, grant=True)
            return True
        if command == _DEAUTHORIZE_COMMAND:
            await self._grant(chat_id, argument, grant=False)
            return True
        if command == _STATUS_COMMAND:
            await self._reply(chat_id, _STATUS_TEXT)
            return True
        return False

    async def _dispatch_proactivity(self, chat_id: int, command: str, argument: str) -> bool:
        """Handle the /quiet, /wake owner commands when a proactivity store is wired."""
        if self._proactivity_store is None:
            return False
        if command == _QUIET_COMMAND:
            await self._quiet(chat_id, argument)
            return True
        if command == _WAKE_COMMAND:
            await self._wake(chat_id)
            return True
        return False

    async def _quiet(self, chat_id: int, argument: str) -> None:
        """Mute proactivity; an optional duration (``2h``/``30m``) adds an expiry."""
        store = self._require_store()
        until = self._parse_until(argument)
        if argument.strip() and until is None:
            await self._reply(chat_id, _USAGE_QUIET)
            return
        await self._set_enabled(store, enabled=False)
        await store.set_mute_until(self._persona_id, until)
        if until is None:
            await self._reply(chat_id, _QUIET_TEXT)
        else:
            await self._reply(chat_id, _QUIET_TIMED_TEXT.format(until=until.isoformat()))

    async def _wake(self, chat_id: int) -> None:
        """Un-mute proactivity and clear any timed-mute expiry."""
        store = self._require_store()
        await self._set_enabled(store, enabled=True)
        await store.set_mute_until(self._persona_id, None)
        await self._reply(chat_id, _WAKE_TEXT)

    async def _set_enabled(self, store: _ProactivityStoreLike, *, enabled: bool) -> None:
        """Toggle the persisted ``proactivity_enabled`` flag (state-preserving)."""
        state = await store.load(self._persona_id)
        await store.save(self._persona_id, replace(state, proactivity_enabled=enabled))

    def _require_store(self) -> _ProactivityStoreLike:
        """Return the wired proactivity store (the command guard ensures it exists)."""
        if self._proactivity_store is None:  # pragma: no cover - guarded by caller
            raise RuntimeError("proactivity store not configured")
        return self._proactivity_store

    def _parse_until(self, argument: str) -> datetime | None:
        """Resolve an optional duration argument into an absolute expiry instant.

        Returns ``None`` for an empty argument (an indefinite mute) or an
        unparseable one; the caller distinguishes the two by re-checking the text.
        """
        seconds = _parse_duration_seconds(argument)
        if seconds is None or self._clock is None:
            return None
        return self._clock.now() + timedelta(seconds=seconds)

    async def _grant(self, chat_id: int, argument: str, *, grant: bool) -> None:
        """Apply an authorize/deauthorize grant and confirm to the owner."""
        target = _parse_user_id(argument)
        if target is None:
            await self._reply(
                chat_id, _USAGE_AUTHORIZE if grant else _USAGE_DEAUTHORIZE
            )
            return
        if grant:
            await self._authorizer.authorize(target)
            await self._reply(chat_id, f"Пользователь {target} авторизован.")
        else:
            await self._authorizer.deauthorize(target)
            await self._reply(chat_id, f"Пользователь {target} деавторизован.")

    async def _reply(self, chat_id: int, text: str) -> None:
        """Send a GUPPI reply into General (un-threaded)."""
        await self._bot.send_message(chat_id=chat_id, text=text, message_thread_id=None)


def _parse_user_id(argument: str) -> int | None:
    """Parse the ``<user_id>`` argument of an owner command; ``None`` if invalid."""
    cleaned = argument.strip()
    if not cleaned.lstrip("-").isdigit():
        return None
    return int(cleaned)


def _parse_duration_seconds(argument: str) -> int | None:
    """Parse a ``/quiet`` duration (``2h`` / ``30m`` / ``45s``) into seconds.

    Returns ``None`` for an empty argument (no timed mute) or any value that is
    not a positive integer followed by a known unit suffix.
    """
    cleaned = argument.strip().lower()
    if not cleaned:
        return None
    unit = cleaned[-1]
    multiplier = _DURATION_UNITS.get(unit)
    amount = cleaned[:-1]
    if multiplier is None or not amount.isdigit():
        return None
    value = int(amount)
    return None if value <= 0 else value * multiplier
