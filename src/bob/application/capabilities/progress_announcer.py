# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""ProgressAnnouncer — the LIVE interim "searching…" reply before a SLOW capability.

Some capabilities are slow (``web_search`` runs ~1-2 min against the streaming
Responses API). Left in silence, the owner cannot tell Bob heard him. Before such
a call the :class:`ToolLoop` asks a :class:`ProgressAnnouncer` to say something —
a short line in Bob's OWN voice, generated LIVE on the Tier-0
:class:`InterimLineGenerator` (BOB-057) — so minute zero is not dead air.

There are **no hardwired phrases** (BOB-060, US-2): both the tool-loop path
(:meth:`GatewayProgressAnnouncer.announce`) and the verify path
(:meth:`GatewayProgressAnnouncer.announce_verify`) go through ONE live-only engine
(``_announce_live``). On generator failure / empty line / no generator the announcer
stays **silent** — never a scripted phrase.

The announce is **decorative** on two counts:

* it decides *by capability name* whether to speak at all — fast skills get no
  line (the ``Capability`` protocol is untouched; the policy lives here); and
* it **swallows its own errors** (BOB-050 ``_safe_addon`` style): a failed gen or
  send is logged and dropped, never raised — the interim line can never break or
  block the real answer.

:class:`GatewayProgressAnnouncer` is the per-turn, chat-bound implementation:
constructed with the turn's ``chat_id``, the same ``reply`` gateway seam
HandleMessage answers through, the live ``line_generator`` (the source of truth),
and the ``sender_name`` it addresses.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

# A generic topic for a web search whose call arguments carry no ``query`` — the line
# still generates LIVE (never a scripted phrase), just without a specific subject.
# Russian persona voice (project language); Cyrillic look-alikes are intentional.
_GENERIC_SEARCH_TOPIC = "поиск в интернете"


class ProgressAnnouncer(Protocol):
    """Announce (or stay silent about) an about-to-run capability, by name + args."""

    async def announce(
        self, capability_name: str, arguments: Mapping[str, object]
    ) -> None: ...


class InterimLineGenerator(Protocol):
    """Generate one LIVE, addressed interim one-liner in Bob's voice (BOB-057 .3).

    The application port for the contextual interim: given the ``topic`` Bob is about
    to search and the ``sender_name`` he's talking to, return a short living line
    («Леш, гляну свежие ставки, секунду 🙂»). A Tier-0 LLM realisation lives in
    infrastructure; the announcer depends only on this narrow port (DDD clean).
    """

    async def generate(self, *, topic: str, sender_name: str) -> str: ...


class _ProgressSink(Protocol):
    """The gateway seam the announcer needs: send one live line into a chat.

    Structurally satisfied by HandleMessage's ``ReplyGateway`` — the announcer
    depends on this narrow application port, never on the Telegram transport.
    """

    async def reply(
        self, *, chat_id: int, markdown: str, thinking: str | None = None
    ) -> int | None: ...


class GatewayProgressAnnouncer:
    """Per-turn, chat-bound :class:`ProgressAnnouncer` over the reply gateway (live-only)."""

    def __init__(
        self,
        *,
        chat_id: int,
        gateway: _ProgressSink,
        line_generator: InterimLineGenerator | None = None,
        sender_name: str = "",
    ) -> None:
        self._chat_id = chat_id
        self._gateway = gateway
        # The live generator is the SINGLE source of the interim line for both paths
        # (BOB-060, US-2). Unwired → the announcer stays silent (no scripted fallback).
        self._line_generator = line_generator
        self._sender_name = sender_name

    async def announce(
        self, capability_name: str, arguments: Mapping[str, object]
    ) -> None:
        """Send one LIVE interim line for a slow ``web_search``, or stay silent.

        Only ``web_search`` speaks; every other (fast) capability yields nothing. The
        call's ``query`` argument becomes the topic Bob names in his live line (or a
        generic search topic when absent). Fully decorative — see :meth:`_announce_live`.
        """
        if capability_name != "web_search":
            return
        query = arguments.get("query")
        topic = (
            query.strip()
            if isinstance(query, str) and query.strip()
            else _GENERIC_SEARCH_TOPIC
        )
        await self._announce_live(topic=topic)

    async def announce_verify(self, *, topic: str) -> None:
        """Send the LIVE, ADDRESSED interim line before a verify search (BOB-057 US-3b).

        The same live-only engine as the tool-loop path; ``sender_name`` comes from the
        ctor. On gen failure / empty / no generator → silence. Never blocks the search.
        """
        await self._announce_live(topic=topic)

    async def _announce_live(self, *, topic: str) -> None:
        """Generate one live interim line and send it, or stay silent (BOB-060).

        The single decorative engine for both paths:

        * no generator wired → silent;
        * generator raises or returns empty/whitespace → logged and dropped (silent) —
          🔴 never a scripted phrase (US-2);
        * otherwise the live line is sent; a failing send is swallowed too (decorative).

        The interim NEVER blocks the search or breaks the turn.
        """
        if self._line_generator is None:
            return
        try:
            line = (
                await self._line_generator.generate(
                    topic=topic, sender_name=self._sender_name
                )
            ).strip()
        except Exception:  # decorative: a failed live gen falls to silence, not a phrase
            logger.exception("live interim line gen failed (dropped, silent)")
            return
        if not line:
            return
        try:
            await self._gateway.reply(chat_id=self._chat_id, markdown=line)
        except Exception:  # decorative: a failed interim line never breaks the turn
            logger.exception("interim line send dropped (decorative)")
