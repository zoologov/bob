# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""ProgressAnnouncer — the interim "searching…" reply before a SLOW capability.

Some capabilities are slow (``web_search`` runs ~1-2 min against the streaming
Responses API). Left in silence, the owner cannot tell Bob heard him. Before such
a call the :class:`ToolLoop` asks a :class:`ProgressAnnouncer` to say something —
a short, VARIED live line in Bob's own voice — so minute zero is not dead air.

The announce is **decorative** on two counts:

* it decides *by capability name* whether to speak at all — fast skills get no
  line (the ``Capability`` protocol is untouched; the policy lives here); and
* it **swallows its own errors** (BOB-050 ``_safe_addon`` style): a failed send
  is logged and dropped, never raised — the interim line can never break or
  block the real answer.

:class:`GatewayProgressAnnouncer` is the per-turn, chat-bound implementation:
constructed with the turn's ``chat_id``, the same ``reply`` gateway seam
HandleMessage answers through, an injected seeded RNG (deterministic tests), and
a name→phrases map. It picks one voiced variant via the RNG and sends it — no
robotic "Loading…" (US-4), just Bob glancing at the net.
"""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from random import Random

logger = logging.getLogger(__name__)


class ProgressAnnouncer(Protocol):
    """Announce (or stay silent about) an about-to-run capability, by name."""

    async def announce(self, capability_name: str) -> None: ...


class InterimLineGenerator(Protocol):
    """Generate one LIVE, addressed interim one-liner in Bob's voice (BOB-057 .3).

    The application port for the contextual verify interim: given the ``topic`` Bob
    is about to check and the ``sender_name`` he's talking to, return a short living
    line («Леш, гляну свежие ставки, секунду 🙂»). A Tier-0 LLM realisation lives in
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


# The voiced set for a web search (BOB-055, US-4): ~6-8 short, LIVING variants in
# Bob's own voice — "секунду, гляну в сети…", not a robotic "Loading…". The seeded
# RNG picks one, so across turns the interim line feels human, not templated.
# Russian persona voice (project language); Cyrillic look-alikes are intentional.
WEB_SEARCH_PROGRESS_PHRASES: tuple[str, ...] = (
    "секунду, гляну в сети…",
    "момент, поищу…",
    "щас гляну, что там в интернете…",
    "погоди, пороюсь в сети…",
    "минутку, посмотрю в интернете…",
    "так, сейчас поищу…",
    "дай гляну, что нагуглю…",
    "окей, пойду поищу — момент…",
)

# name → voiced set. Only the slow web search speaks in v1; every other capability
# is absent → the announcer stays silent for it.
DEFAULT_PROGRESS_PHRASES: Mapping[str, Sequence[str]] = MappingProxyType(
    {"web_search": WEB_SEARCH_PROGRESS_PHRASES}
)


class GatewayProgressAnnouncer:
    """Per-turn, chat-bound :class:`ProgressAnnouncer` over the reply gateway."""

    def __init__(
        self,
        *,
        chat_id: int,
        gateway: _ProgressSink,
        rng: Random,
        phrases: Mapping[str, Sequence[str]] = DEFAULT_PROGRESS_PHRASES,
        line_generator: InterimLineGenerator | None = None,
    ) -> None:
        self._chat_id = chat_id
        self._gateway = gateway
        self._rng = rng
        self._phrases = phrases
        # The contextual verify interim (BOB-057 .3): when wired, ``announce_verify``
        # generates a LIVE, addressed one-liner instead of a scripted phrase. Unwired
        # (the default) it falls straight to the seeded BOB-055 set — the seam stays
        # decorative in one place.
        self._line_generator = line_generator

    async def announce(self, capability_name: str) -> None:
        """Send one voiced interim line for a slow capability, or stay silent.

        An unmapped (fast) capability yields nothing. A mapped one picks a varied
        phrase via the seeded RNG and sends it; any send failure is logged and
        dropped — decorative, never propagated (the turn is unaffected).
        """
        options = self._phrases.get(capability_name)
        if not options:
            return
        phrase = self._rng.choice(list(options))
        try:
            await self._gateway.reply(chat_id=self._chat_id, markdown=phrase)
        except Exception:  # decorative: a failed interim line never breaks the turn
            logger.exception(
                "progress announce for %r dropped (decorative)", capability_name
            )

    async def announce_verify(self, *, topic: str, sender_name: str) -> None:
        """Send the LIVE, ADDRESSED interim line before a verify search (BOB-057 US-3b).

        The decorative fallback chain, in ONE place:

        * a wired :class:`InterimLineGenerator` yields a live one-liner naming
          ``topic`` and addressing ``sender_name`` («Леш, гляну свежие ставки,
          секунду 🙂»); on failure/empty/no-generator →
        * a seeded pick from :data:`WEB_SEARCH_PROGRESS_PHRASES` (BOB-055) via the
          same RNG; and if even the send raises →
        * silence — logged and dropped.

        The interim NEVER blocks the search or breaks the turn.
        """
        line = await self._live_verify_line(topic=topic, sender_name=sender_name)
        if not line:
            line = self._rng.choice(list(WEB_SEARCH_PROGRESS_PHRASES))
        try:
            await self._gateway.reply(chat_id=self._chat_id, markdown=line)
        except Exception:  # decorative: a failed interim line never breaks the turn
            logger.exception("verify interim line dropped (decorative)")

    async def _live_verify_line(self, *, topic: str, sender_name: str) -> str:
        """The live Tier-0 interim line, or ``""`` (unwired / failed / empty gen).

        A generator error is caught and degraded to ``""`` (the caller seeds the
        fallback), so a flaky local model never propagates through the interim.
        """
        if self._line_generator is None:
            return ""
        try:
            line = await self._line_generator.generate(
                topic=topic, sender_name=sender_name
            )
        except Exception:  # decorative: a failed live gen falls back to a seeded phrase
            logger.exception("live interim line gen failed (seeded fallback)")
            return ""
        return line.strip()
