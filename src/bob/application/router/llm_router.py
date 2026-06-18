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
2. **Redacts** before any Tier 1 call — raw personal/memory context is stripped
   from the payload so it never leaves the machine (VISION §7.1 privacy rule).
   Redaction is a property of the *request*, applied whenever the destination is
   Tier 1, including on a Tier 1 -> Tier 0 fallback (the redacted payload is what
   was built, so it is what the fallback sees too).
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
    """A unit of LLM work: the prompt plus optional private context.

    ``personal_context`` carries personality/memory material that is safe for the
    local Tier 0 but MUST be redacted before any Tier 1 (remote API) call.
    """

    task_type: TaskType
    messages: Sequence[LLMMessage]
    personal_context: str | None = None
    stream: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


class LLMRouter:
    """Route a task to a tier, redacting personal context before Tier 1, with fallback."""

    def __init__(self, *, providers: Mapping[int, LLMProvider]) -> None:
        if _TIER_LOCAL not in providers:
            raise ValueError("LLMRouter requires a Tier 0 (local) provider")
        self._providers = dict(providers)

    async def run(self, request: LLMRequest) -> str:
        """Complete ``request`` on its preferred tier, falling back to Tier 0 on error.

        The payload is built once: personal context is attached only when the
        request is allowed to stay local (its preferred tier is Tier 0). A
        request bound for Tier 1 is redacted, and that same redacted payload is
        what a Tier 1 -> Tier 0 fallback sends — privacy is preserved end to end.
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
        """Build the payload; attach personal context only for local-only requests.

        A request whose preferred tier is the remote API is redacted here by
        simply never attaching ``personal_context`` — so raw personal/memory
        material cannot reach Tier 1 (nor a redacted-then-fallback Tier 0 call).
        """
        messages: list[LLMMessage] = list(request.messages)
        stays_local = _PREFERRED_TIER[request.task_type] == _TIER_LOCAL
        if request.personal_context and stays_local:
            context_message: LLMMessage = {
                "role": "system",
                "content": request.personal_context,
            }
            return [context_message, *messages]
        return messages

    async def _complete(self, tier: int, messages: Sequence[LLMMessage]) -> str:
        provider = self._providers[tier]
        result = await provider.complete(messages, stream=False)
        if not isinstance(result, str):
            raise TypeError("non-stream completion must return str")
        return result
