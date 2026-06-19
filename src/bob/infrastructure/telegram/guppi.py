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
  shared :class:`~bob.application.authz.Authorizer` (no duplicated authz), and
  ``/status`` answers a short whoami line. A command from anyone but the owner, a
  non-command message, or any chat other than the General chat is **ignored and
  silent** — no reveal outside the group.

Transport only: GUPPI replies are sent through GUPPI's own injected bot (never
Bob's). The bot is behind the :class:`~bob.infrastructure.telegram.gateway.BotLike`
protocol so tests use a fake bot — no network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
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

_USAGE_AUTHORIZE = "Использование: /authorize <user_id>"
_USAGE_DEAUTHORIZE = "Использование: /deauthorize <user_id>"
_STATUS_TEXT = "GUPPI на связи — привратник Боба. Команды: /authorize, /deauthorize, /status."


class GuppiHandler:
    """GUPPI's gatekeeper behaviours: the visible reject + owner commands."""

    def __init__(
        self,
        *,
        bot: BotLike,
        authorizer: AuthorizerLike,
        general_chat_id: int,
    ) -> None:
        self._bot = bot
        self._authorizer = authorizer
        self._general_chat_id = general_chat_id

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
