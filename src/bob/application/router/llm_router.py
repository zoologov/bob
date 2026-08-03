# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=router

"""LLMRouter — task classification, privacy redaction, and tier fallback.

GUPPI's policy layer over the provider-agnostic :class:`LLMProvider` ports
(Tier 0 local / Tier 1 API). For each request it:

1. **Classifies** the task type to a preferred tier — replying to the user
   defaults to **Tier 1** (Qwen) for quality (CONTEXT Q2); cheap or sensitive
   work (sentiment, inner monologue) stays on **Tier 0** locally.
2. **Selectively redacts** before any Tier 1 call (Variant 2, VISION §7.1).
   Each request splits its context in two: ``shareable_context``
   (conversation/memory/mood/identity/taste — material that shapes Bob's reply
   and returns to that same user) MAY accompany a Tier 1 call, while
   ``private_context`` (genuinely-internal scratch) is Tier-0-only and is
   stripped before any Tier 1 call. Redaction is a property of the *request*,
   applied whenever the destination is Tier 1, including on a Tier 1 -> Tier 0
   fallback (the redacted payload is what was built, so the fallback sees it too).
3. **Falls back** Tier 1 -> Tier 0 if the preferred tier errors or is
   unavailable, so a flaky Qwen API never blocks a reply.

This module is pure application policy: it holds no transport/HTTP knowledge —
that lives behind the injected :class:`LLMProvider` adapters.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.kernel.ports import LLMMessage, LLMProvider

logger = logging.getLogger(__name__)

_TIER_LOCAL = 0
_TIER_API = 1


class TaskType(Enum):
    """Kinds of LLM work, each mapped to a preferred tier by the router."""

    REPLY_TO_USER = "reply_to_user"
    GENESIS = "genesis"
    SENTIMENT = "sentiment"
    INNER_MONOLOGUE = "inner_monologue"
    REFLECT = "reflect"
    EXTRACT_FACTS = "extract_facts"
    PLAN_GOAL = "plan_goal"
    DETECT_PATTERNS = "detect_patterns"
    CODING_INTENT = "coding_intent"
    RESPONSE_JUDGE = "response_judge"
    REACTION_JUDGE = "reaction_judge"
    PRIVILEGE_JUDGE = "privilege_judge"
    VOLATILITY_JUDGE = "volatility_judge"
    INTERIM_LINE = "interim_line"
    ROOM_READ = "room_read"
    STALENESS_JUDGE = "staleness_judge"
    DISCLOSURE_CONSENT = "disclosure_consent"
    WORK_JOURNAL = "work_journal"
    WORK_TALK = "work_talk"


# Task -> preferred tier. Quality-critical, user-facing work goes to Tier 1
# (with redaction); cheap or privacy-sensitive work stays local on Tier 0.
_PREFERRED_TIER: dict[TaskType, int] = {
    TaskType.REPLY_TO_USER: _TIER_API,
    TaskType.GENESIS: _TIER_API,
    TaskType.SENTIMENT: _TIER_LOCAL,
    TaskType.INNER_MONOLOGUE: _TIER_LOCAL,
    TaskType.REFLECT: _TIER_LOCAL,
    TaskType.EXTRACT_FACTS: _TIER_LOCAL,
    # Goal decomposition (BOB-015) is reasoning-heavy: Tier 1 by default for a
    # sensible plan (the config can pin the tier per persona via tier_override).
    TaskType.PLAN_GOAL: _TIER_API,
    # Pattern detection (BOB-028) is reasoning over self-signals: Tier 1 by default
    # for a human-readable rule (config can pin the tier via detector_tier override).
    TaskType.DETECT_PATTERNS: _TIER_API,
    # Coding-intent classification (BOB-041 .2) is a cheap one-word coding/chat call
    # that also keeps dev-intent local (privacy) — Tier 0.
    TaskType.CODING_INTENT: _TIER_LOCAL,
    # Response judgment (BOB-049) is a cheap per-inbound reply/react/ignore decision
    # run on every message — Tier 0 for cost, like the other classifiers.
    TaskType.RESPONSE_JUDGE: _TIER_LOCAL,
    # Reaction judgment (BOB-050) reads what a reaction on Bob's OWN message means —
    # a cheap, privacy-adjacent local read, like the other personality classifiers.
    TaskType.REACTION_JUDGE: _TIER_LOCAL,
    # Privilege judgment (BOB-052) decides whether a not-yet-authorised person's
    # request needs owner permission — a cheap, privacy-sensitive local read, like
    # the other classifiers.
    TaskType.PRIVILEGE_JUDGE: _TIER_LOCAL,
    # Volatility judgment (BOB-057) decides, before Bob answers, whether the answer
    # hinges on a fresh volatile fact — a cheap per-inbound classifier, Tier 0.
    TaskType.VOLATILITY_JUDGE: _TIER_LOCAL,
    # Interim line (BOB-057 .3) is a cheap one-liner in Bob's voice before the verify
    # search — a fast, latency-tolerant local gen (the search wait dwarfs it), Tier 0.
    TaskType.INTERIM_LINE: _TIER_LOCAL,
    # Reflective «read the room» (BOB-066 Срез 2.2) is the rich semantic pass on a
    # PERIPHERY turn — situation / room-mood / intent / salience / wants_web. It is the
    # heart of Bob's living group presence, so it runs on Tier 1 for real understanding
    # («не жалеть LLM», PRINCIPLE-1 liveness > economy) — unlike the cheap Tier-0 judge.
    TaskType.ROOM_READ: _TIER_API,
    # Staleness judgment (BOB-066 Срез W.3) reads how the room shifted under a drafted reply
    # while Bob was composing — a cheap per-turn classifier over a short burst, Tier 0.
    TaskType.STALENESS_JUDGE: _TIER_LOCAL,
    # Disclosure-consent judgment (BOB-082 .4) reads whether the OWNER authorised voicing
    # previously-private content into the group — privacy-sensitive, so it stays local (Tier 0).
    TaskType.DISCLOSURE_CONSENT: _TIER_LOCAL,
    # Work-journal distillation (BOB-087.B1) sweeps a coding session's key facts into a few
    # first-person operator episodes — privacy-sensitive (owner's repo work) + a background
    # side-channel, so it stays local (Tier 0), like the other cheap classifiers.
    TaskType.WORK_JOURNAL: _TIER_LOCAL,
    # Work-talk classification (BOB-087.C2) is a cheap one-word work/chat call deciding
    # whether a turn is ABOUT Bob's dev work (so his work memories lift to full recall) —
    # privacy-sensitive (dev context) + per-inbound, so it stays local (Tier 0).
    TaskType.WORK_TALK: _TIER_LOCAL,
}


@dataclass(frozen=True)
class LLMRequest:
    """A unit of LLM work: the prompt plus its two-tier context split.

    Context is split by destination policy (Variant 2, selective redaction):

    - ``shareable_context`` — conversation/memory/mood/identity/taste material
      that shapes Bob's reply and returns to that same user. It MAY accompany a
      Tier 1 (remote API) call.
    - ``private_context`` — genuinely-internal material that is Tier-0-only and
      MUST be redacted before any Tier 1 call. May be empty in P0.1, but the seam
      is kept so internal-only context never silently leaks.

    ``tier_override`` lets a caller pick the destination tier for *this* request,
    overriding the task's default (BOB-006 hybrid reply tiering: a casual reply
    runs on the fast Tier 0 model, a complex one on the quality Tier 1 model).
    Redaction is unaffected — it follows the *task* policy, not the chosen tier,
    so a reply overridden down to Tier 0 still never bundles ``private_context``.
    """

    task_type: TaskType
    messages: Sequence[LLMMessage]
    shareable_context: str | None = None
    private_context: str | None = None
    stream: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)
    tier_override: int | None = None


class LLMRouter:
    """Route a task to a tier, redacting private context before Tier 1, with fallback."""

    def __init__(
        self,
        *,
        providers: Mapping[int, LLMProvider],
        tier1_max_concurrency: int | None = None,
    ) -> None:
        if _TIER_LOCAL not in providers:
            raise ValueError("LLMRouter requires a Tier 0 (local) provider")
        self._providers = dict(providers)
        # 🔴 Tier-1 rate-cap (BOB-072): a ceiling on CONCURRENT Tier-1 (Qwen API) completions —
        # invisible insurance against 429/degradation when bursts across chats (incl. batch
        # ROOM_READ) hit Tier 1 at once. It only SERIALIZES calls; it never touches the routing
        # decision or the payload. ``None``/``<= 0`` (the default) → no gate → byte-identical.
        self._tier1_gate = (
            asyncio.Semaphore(tier1_max_concurrency)
            if tier1_max_concurrency is not None and tier1_max_concurrency > 0
            else None
        )

    async def run(self, request: LLMRequest) -> str:
        """Complete ``request`` on its preferred tier, falling back to Tier 0 on error.

        The payload is built once: a Tier 1-bound request carries only its
        ``shareable_context`` (private context is stripped); a local-only Tier 0
        request carries both. That same built payload is what a Tier 1 -> Tier 0
        fallback sends — the private-context redaction is preserved end to end.

        A Tier-1 attempt is throttled by the optional concurrency gate (BOB-072); the
        Tier-0 fallback runs OUTSIDE the gate so a failing Tier-1 call never holds a
        Tier-1 slot while its local fallback completes.
        """
        preferred = self._destination_tier(request)
        messages = self._build_messages(request)
        try:
            return await self._complete_gated(preferred, messages)
        except Exception:
            if preferred == _TIER_LOCAL:
                logger.exception("Tier 0 completion failed with no fallback")
                raise
            logger.warning(
                "Tier 1 completion failed for %s; falling back to Tier 0",
                request.task_type.value,
            )
        return await self._complete(_TIER_LOCAL, messages)

    async def _complete_gated(self, tier: int, messages: Sequence[LLMMessage]) -> str:
        """Complete on ``tier``, holding the Tier-1 concurrency gate when it applies.

        Only a Tier-1 attempt with a configured gate is throttled; every other call (Tier 0,
        or Tier 1 with no cap) runs ungated — byte-identical to the pre-cap path.
        """
        if tier != _TIER_API or self._tier1_gate is None:
            return await self._complete(tier, messages)
        async with self._tier1_gate:
            return await self._complete(tier, messages)

    def _destination_tier(self, request: LLMRequest) -> int:
        """The tier to attempt first: the caller's override if wired, else the task default.

        An override naming an unknown tier is ignored (falls through to the task
        default) so a mis-set override can never route to a missing provider.
        """
        override = request.tier_override
        if override is not None and override in self._providers:
            return override
        return _PREFERRED_TIER[request.task_type]

    @staticmethod
    def _build_messages(request: LLMRequest) -> list[LLMMessage]:
        """Build the payload with selective redaction by destination tier.

        A local-only (Tier 0) request gets BOTH ``shareable_context`` and
        ``private_context``; a Tier 1-bound request gets ONLY
        ``shareable_context`` — ``private_context`` is never attached, so
        genuinely-internal material cannot reach Tier 1 (nor a Tier 1 -> Tier 0
        fallback, since the payload is built once).
        """
        stays_local = _PREFERRED_TIER[request.task_type] == _TIER_LOCAL
        parts = [request.shareable_context]
        if stays_local:
            parts.append(request.private_context)
        context = "\n".join(part for part in parts if part)
        messages: list[LLMMessage] = list(request.messages)
        if context:
            context_message: LLMMessage = {"role": "system", "content": context}
            return [context_message, *messages]
        return messages

    async def _complete(self, tier: int, messages: Sequence[LLMMessage]) -> str:
        provider = self._providers[tier]
        result = await provider.complete(messages, stream=False)
        if not isinstance(result, str):
            raise TypeError("non-stream completion must return str")
        return result
