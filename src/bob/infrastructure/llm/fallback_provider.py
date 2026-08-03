# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""FallbackLLMProvider — a cloud provider with a local emergency understudy.

Realises :class:`bob.kernel.ports.LLMProvider` by composing two providers, so the
resilience lives in ONE place and neither the :class:`~bob.application.router.LLMRouter`
nor its callers change (BOB-087.E1, BOB-Issues #34): the factory simply hands this
object over as Tier 0 when a fallback is configured.

The policy is deliberately small:

* one attempt on the primary, and — only when
  :func:`~bob.infrastructure.llm.fallback_policy.should_fall_back` says the failure
  was the *transport* — one attempt on the local fallback. No cascade, no retry loop;
* every switch is a ``WARNING`` naming the cause. Silent degradation is unacceptable:
  the owner must be able to learn that Bob is answering on the emergency model;
* if the fallback fails too, the **primary** error is what propagates (it explains why
  the cloud went away), with the local failure attached as its cause.

The streaming path is a plain delegation to the primary: a streaming failure surfaces
mid-iteration, after tokens may already have reached the reader, so re-running the turn
on another model would duplicate output rather than rescue it. Nothing streams Tier-0
today, and the honest narrow behaviour is better than a broken-by-design retry.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.infrastructure.llm.fallback_policy import should_fall_back

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from bob.kernel.ports import LLMMessage, LLMProvider

logger = logging.getLogger(__name__)


class FallbackLLMProvider:
    """Complete on ``primary``; on a transport failure, once on ``fallback``.

    One responsibility: surviving an outage of the primary endpoint. What counts as
    an outage is not decided here — that verdict is the pure
    :mod:`bob.infrastructure.llm.fallback_policy` core.
    """

    def __init__(self, *, primary: LLMProvider, fallback: LLMProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """Complete a chat turn, degrading to the local model on a transport failure."""
        if stream:
            return await self._primary.complete(messages, stream=True)
        try:
            return await self._primary.complete(messages, stream=False)
        except Exception as error:
            if not should_fall_back(error):
                raise
            return await self._complete_locally(messages, error)

    async def _complete_locally(
        self,
        messages: Sequence[LLMMessage],
        error: Exception,
    ) -> str | AsyncIterator[str]:
        """Run the turn on the local model, announcing the degradation.

        A failure of the local model re-raises the ORIGINAL primary error (the more
        informative one) with the local failure attached as its cause.
        """
        logger.warning(
            "Primary LLM failed (%s: %s); falling back to the local model",
            type(error).__name__,
            error,
        )
        try:
            return await self._fallback.complete(messages, stream=False)
        except Exception as local_error:
            logger.warning(
                "Local fallback LLM failed too (%s: %s); re-raising the primary failure",
                type(local_error).__name__,
                local_error,
            )
            raise error from local_error
