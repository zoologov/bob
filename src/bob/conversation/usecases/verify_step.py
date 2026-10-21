# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=application

"""VerifyStep — the pre-answer epistemic verify for a turn (BOB-057 .2).

The turn's «один поиск, не петля» verify concern in one cohesive collaborator (extracted
from ``HandleMessage`` in BOB-062.6b, wave 1, behavior-preserving). BEFORE generation a
conservative Tier-0 :class:`~bob.conversation.volatility_judgment.VolatilityJudge` decides
whether the answer hinges on a FRESH volatile fact; on ``needs_check`` Bob makes ONE
DIRECT :class:`~bob.conversation.ports.VerifySearch` ``.search`` (NOT via the capability
registry / tool-loop → NOT the BOB-052 per-sender gate — an internal public-verify exposing
only PUBLIC web info) and folds the finding into the reply-generation context. The search
port is the NARROW consumer-side one (BOB-113 E): the step reads only ``answer``, so it
imports nothing from the capability vertical; that vertical's web-search adapter
satisfies the port structurally and is wired in unchanged.

🔴 The whole step is DECORATIVE: a judge failure degrades to «no check» (normal answer),
a search failure/timeout/empty to an honest hedge — the turn is never blocked or broken.
🔴 :meth:`note` returns the note as a PER-TURN LOCAL (``""`` = «judged, no note»); it is
NEVER cached on this collaborator (a shared singleton would leak the note / «already
searched» state across turns and users). The per-turn interim announcer is CONSTRUCTED
locally from the turn's ``chat_id`` via the injected factory, never held as an attribute.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

from bob.conversation.thread import _render_thread
from bob.conversation.volatility_judgment import VolatilityContext, VolatilityVerdict

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from bob.conversation.ports import VerifySearch
    from bob.conversation.volatility_judgment import VolatilityJudge
    from bob.kernel.interlocutor import Interlocutor

logger = logging.getLogger(__name__)

# The web finding is trimmed before it enters the generation context (it only needs to
# ground the answer, not dump the whole search payload into the prompt).
_VERIFY_ANSWER_MAX_CHARS = 800

# A FORCED verify (BOB-066 Срез 2.2, C11): a reflective read set ``wants_web`` — Bob
# already decided to go look, so the volatility judge is skipped and the turn's own text
# is the search query/topic. The short topic keeps the interim line readable.
_FORCED_TOPIC_MAX_CHARS = 60

# The GROUNDED note (US-1/US-4 + BOB-060 .2 register-nudge): the fresh finding + an
# explicit steer to present it IN BOB'S OWN VOICE, reacting to it — NOT as a generic
# agent report («выполнен поиск, найдено N…»). The tone adapts through generation,
# unprogrammed; the note only nudges the register, never the search mechanism.
_VERIFY_GROUNDED_NOTE = (
    "СВЕЖАЯ ПРОВЕРКА (веб): {answer}. Ты сходил и глянул это в сети — отреагируй "
    "по-своему, как БОБ, со своим отношением и тоном, если картина изменилась; "  # noqa: RUF001
    "НЕ отчётом («выполнен поиск, найдено…»), не сухой сводкой."  # noqa: RUF001
)

# The HEDGE note (US-6 + BOB-060 .2): on a failed/timed-out/empty verify Bob makes an
# HONEST epistemic caveat — 🔴 never a confident STALE number dressed as fact, never a
# fabrication (BOB-053 invariant). The register-nudge steers a LIVE, in-voice caveat
# (not a robotic «поиск не удался»), without weakening the anti-confabulation intent.
_VERIFY_HEDGE_NOTE = (
    "Свериться со свежими данными по {topic} не вышло — скажи это честно и живо, "  # noqa: RUF001
    "своими словами (не сухим «поиск не удался»); не выдавай устаревшие цифры за "
    "точные и ничего не выдумывай."
)


class VerifyInterimAnnouncer(Protocol):
    """The per-turn seam that speaks the live interim line before the verify search."""

    async def announce_verify(self, *, topic: str) -> None: ...


# Build the per-turn, chat-bound interim announcer from the turn's ``chat_id`` and the
# perceived ``sender_name``. Injected so the conversation vertical never imports the
# concrete announcer (it lives in the capability vertical; the factory is composed in the
# application layer).
type InterimAnnouncerFactory = Callable[..., VerifyInterimAnnouncer]


class VerifyStep:
    """Run the turn's pre-answer epistemic verify, returning a turn-local note (BOB-057)."""

    def __init__(
        self,
        *,
        verify_judge: VolatilityJudge | None,
        verify_provider: VerifySearch | None,
        verify_timeout_seconds: float,
        announcer_factory: InterimAnnouncerFactory,
    ) -> None:
        self._verify_judge = verify_judge
        self._verify_provider = verify_provider
        self._verify_timeout_seconds = verify_timeout_seconds
        self._announcer_factory = announcer_factory

    async def note(
        self,
        text: str,
        history: Sequence[Mapping[str, object]],
        *,
        interlocutor: Interlocutor | None = None,
        chat_id: int | None = None,
        forced: bool = False,
    ) -> str:
        """The pre-answer epistemic-verify note for this turn, or ``""`` (BOB-057 .2).

        The whole step is DECORATIVE and DIRECT:

        * Unwired (no provider — ``verify.enabled`` off) → ``""`` immediately, zero
          judge/search calls, zero added latency (US-2 «не зануда» by default).
        * A CONSERVATIVE Tier-0 :class:`VolatilityJudge` decides whether the answer hinges
          on a FRESH volatile fact. A judge failure is caught and treated as «no check»
          (``""``) — the turn is never blocked by a flaky judge.
        * On ``needs_check`` Bob runs ONE search via :meth:`_search_note`.

        🔴 BOB-066 Срез 2.2 (C11): ``forced=True`` — a reflective read set ``wants_web``, so
        Bob ALREADY decided to go look. The volatility judge is SKIPPED (no second opinion)
        and the turn's own text drives ONE search on the SAME direct path — reusing the
        existing verify/web seam rather than building a new one. A missing provider still
        short-circuits to ``""`` (no web capability wired).

        🔴 The search is DIRECT (``provider.search``), NOT ``registry.dispatch`` /
        the tool-loop — so it is NOT the BOB-052 per-sender privilege gate. This is an
        internal public-verify (nobody asked for a tool; only PUBLIC web info is exposed,
        never owner/private data), so it works for owner and guest alike without weakening
        BOB-051/052 on user-facing tool requests.
        """
        provider = self._verify_provider
        if provider is None:
            return ""
        verdict = await self._verdict(text, history, forced=forced)
        if verdict is None or not verdict.needs_check:
            return ""
        # BOB-057 .3 (US-3b): before the search, Bob sends a LIVE, ADDRESSED interim line
        # naming WHAT he checks and WHO he's talking to («Леш, гляну свежие ставки,
        # секунду 🙂»). Decorative (live gen → silence) and does
        # NOT block the search below.
        await self._send_interim(verdict, interlocutor, chat_id)
        return await self._search_note(provider, verdict)

    async def _verdict(
        self,
        text: str,
        history: Sequence[Mapping[str, object]],
        *,
        forced: bool,
    ) -> VolatilityVerdict | None:
        """The volatility verdict for this turn — forced (skip the judge) or judged.

        ``forced`` (BOB-066 C11 — a reflective ``wants_web``): Bob already chose to look, so
        build an affirmative verdict straight from the turn text (query = text; a short
        topic for the interim line) with NO judge call. Otherwise a CONSERVATIVE Tier-0
        :class:`VolatilityJudge` decides; an unwired or flaky judge degrades to ``None``
        («no check») — the turn is never blocked.
        """
        if forced:
            topic = text.strip()[:_FORCED_TOPIC_MAX_CHARS]
            return VolatilityVerdict(needs_check=True, query=text, topic=topic)
        judge = self._verify_judge
        if judge is None:
            return None
        try:
            return await judge.assess(
                VolatilityContext(text=text, recent_thread=_render_thread(history))
            )
        except Exception:
            # Decorative: a judge failure degrades to «no check» (normal answer), never
            # blocks or breaks the turn.
            logger.exception("volatility judge failed (verify skipped)")
            return None

    async def _send_interim(
        self,
        verdict: VolatilityVerdict,
        interlocutor: Interlocutor | None,
        chat_id: int | None,
    ) -> None:
        """Send the live addressed interim line for the verify search (BOB-057 US-3b).

        Reuses the per-turn announcer in its BOB-060 live-only mode so the decorative
        chain (live Tier-0 gen → silence) lives in one place. No ``chat_id`` (an
        unaddressed path) → no interim. The sender's perceived ``display_name`` addresses
        the line; an unknown sender → topic-only. 🔴 The announcer is constructed LOCALLY
        from this turn's ``chat_id``, never held on the collaborator (per-turn locality).
        """
        if chat_id is None:
            return
        sender_name = interlocutor.display_name if interlocutor is not None else ""
        announcer = self._announcer_factory(chat_id=chat_id, sender_name=sender_name)
        await announcer.announce_verify(topic=verdict.topic)

    async def _search_note(
        self, provider: VerifySearch, verdict: VolatilityVerdict
    ) -> str:
        """Run ONE direct, short-timeout web_search and return the grounded/hedge note.

        On success with a non-empty answer → a GROUNDED note (the trimmed finding + a nudge
        to react in Bob's own voice/tone). On failure / timeout / empty → an HONEST hedge
        note (US-6: never a confident stale number as fact, never a fabrication). The
        provider call is bounded by ``verify.timeout_seconds`` so a slow search cannot
        stall the turn (US-3 «не 5 минут»).
        """
        try:
            # ``asyncio.wait_for`` raises ``TimeoutError`` past the deadline; a slow/failing
            # provider raises its own error — both are caught below as one honest hedge.
            result = await asyncio.wait_for(
                provider.search(verdict.query), timeout=self._verify_timeout_seconds
            )
        except Exception:
            logger.exception("verify web_search failed (hedge)")
            return _VERIFY_HEDGE_NOTE.format(topic=verdict.topic)
        answer = result.answer.strip()[:_VERIFY_ANSWER_MAX_CHARS]
        if not answer:
            return _VERIFY_HEDGE_NOTE.format(topic=verdict.topic)
        return _VERIFY_GROUNDED_NOTE.format(answer=answer)
