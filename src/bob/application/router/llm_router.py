# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

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

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.domain.ports import LLMMessage, LLMProvider

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


# Task -> preferred tier. Quality-critical, user-facing work goes to Tier 1
# (with redaction); cheap or privacy-sensitive work stays local on Tier 0.
_PREFERRED_TIER: dict[TaskType, int] = {
    TaskType.REPLY_TO_USER: _TIER_API,
    TaskType.GENESIS: _TIER_API,
    TaskType.SENTIMENT: _TIER_LOCAL,
    TaskType.INNER_MONOLOGUE: _TIER_LOCAL,
    TaskType.REFLECT: _TIER_LOCAL,
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
    """

    task_type: TaskType
    messages: Sequence[LLMMessage]
    shareable_context: str | None = None
    private_context: str | None = None
    stream: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


class LLMRouter:
    """Route a task to a tier, redacting private context before Tier 1, with fallback."""

    def __init__(self, *, providers: Mapping[int, LLMProvider]) -> None:
        if _TIER_LOCAL not in providers:
            raise ValueError("LLMRouter requires a Tier 0 (local) provider")
        self._providers = dict(providers)

    async def run(self, request: LLMRequest) -> str:
        """Complete ``request`` on its preferred tier, falling back to Tier 0 on error.

        The payload is built once: a Tier 1-bound request carries only its
        ``shareable_context`` (private context is stripped); a local-only Tier 0
        request carries both. That same built payload is what a Tier 1 -> Tier 0
        fallback sends — the private-context redaction is preserved end to end.
        """
        preferred = _PREFERRED_TIER[request.task_type]
        messages = self._build_messages(request)
        try:
            return await self._complete(preferred, messages)
        except Exception:
            if preferred == _TIER_LOCAL:
                logger.exception("Tier 0 completion failed with no fallback")
                raise
            logger.warning(
                "Tier 1 completion failed for %s; falling back to Tier 0",
                request.task_type.value,
            )
        return await self._complete(_TIER_LOCAL, messages)

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
