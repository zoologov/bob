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
  :func:`~bob.application.router.fallback_policy.should_fall_back` says the failure
  was the *transport* — one attempt on the local fallback. No cascade, no retry loop;
* every switch is a ``WARNING`` naming the cause. Silent degradation is unacceptable:
  the owner must be able to learn that Bob is answering on the emergency model;
* if the fallback fails too, the **primary** error is what propagates (it explains why
  the cloud went away), with the local failure attached as its cause.

The streaming path is a plain delegation to the primary: a streaming failure surfaces
mid-iteration, after tokens may already have reached the reader, so re-running the turn
on another model would duplicate output rather than rescue it. Nothing streams Tier-0
today, and the honest narrow behaviour is better than a broken-by-design retry.

**Health reporting (BOB-116).** The composite reports every attempt to the injected
:class:`~bob.kernel.ports.HealthObserver` — the cloud as ``tier0-primary``, the stand-in as
``tier0-understudy`` — each with its own outcome, classified by
:func:`~bob.application.router.fallback_policy.classify_failure`. Separately, because a dead
cloud key behind a LIVE stand-in must still reach the owner: the caller sees a fine answer,
only this report can tell. The router does not report a call that goes through this
composite (one HTTP call — one record). A failure is recorded before it propagates (the
heartbeat lane gate reads the snapshot right after the tick). The stream path is not
reported: nothing streams Tier 0, and a stream's outcome is only known mid-iteration.

**Capability mirroring (BOB-087.E1b).** A wrapper must not quietly change what the
wrapped tier can do. :class:`~bob.kernel.ports.ToolCallingProvider` is an
*optional* companion of the ``LLMProvider`` port, and the tool seam
(``bob.runtime.wiring.access._as_tool_provider``) probes for it with ``hasattr`` — so a
composite that dropped ``complete_with_tools`` would put the tool loop to sleep without
a single error, and one that invented it would hand the seam a provider that cannot
serve. Hence two variants, chosen by :func:`build_fallback_provider` from what the
primary actually offers: the composite advertises tool-calling exactly when its primary
does. Never less, never more.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypeVar

from bob.application.router.fallback_policy import classify_failure, should_fall_back
from bob.application.router.health_monitor import (
    TIER0_PRIMARY,
    TIER0_UNDERSTUDY,
    NoopHealthObserver,
)
from bob.kernel.ports import ToolCallingProvider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Sequence

    from bob.kernel.ports import (
        HealthObserver,
        LLMMessage,
        LLMProvider,
        ToolCallResult,
        ToolDefinition,
        ToolLoopMessage,
    )

logger = logging.getLogger(__name__)

# What kind of turn degraded — named in the WARNING so the operator can tell a plain
# chat degradation from the sharper one: a small local model is markedly weaker at
# tool-calling than at chat.
_CHAT_TURN = "chat turn"
_TOOL_TURN = "tool-calling turn"

_LocalResult = TypeVar("_LocalResult")


class FallbackLLMProvider:
    """Complete on ``primary``; on a transport failure, once on ``fallback``.

    One responsibility: surviving an outage of the primary endpoint. What counts as
    an outage is not decided here — that verdict is the pure
    :mod:`bob.application.router.fallback_policy` core (shared with the router's own
    Tier1 → Tier0 fallback, bob-41o — one policy for both floors of the tiering).
    """

    def __init__(
        self,
        *,
        primary: LLMProvider,
        fallback: LLMProvider,
        health: HealthObserver | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._health: HealthObserver = health if health is not None else NoopHealthObserver()

    def without_understudy(self) -> LLMProvider:
        """The primary alone — this composite minus its stand-in (BOB-087.E-M1).

        Realises :class:`~bob.kernel.ports.UnderstudyBackedProvider`. The degradation is
        invisible to the caller by design, which is right for a служебный ход and wrong for
        a turn published in BOB'S OWN voice: the router asks for the bare primary there, so
        an outage SURFACES (and is escalated upward) instead of being answered by a weak
        stand-in. Nothing is unwrapped recursively — the composite is one level deep.
        """
        return self._primary

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
            result = await self._primary.complete(messages, stream=False)
        except Exception as error:
            await self._health.record_failure(TIER0_PRIMARY, classify_failure(error))
            if not should_fall_back(error):
                raise
            return await self._degrade_to_local(
                self._fallback.complete(messages, stream=False),
                error=error,
                turn=_CHAT_TURN,
            )
        await self._health.record_success(TIER0_PRIMARY)
        return result

    async def _degrade_to_local(
        self,
        local_attempt: Awaitable[_LocalResult],
        *,
        error: Exception,
        turn: str,
    ) -> _LocalResult:
        """Await the already-prepared local attempt, announcing the degradation.

        A failure of the local model re-raises the ORIGINAL primary error (the more
        informative one) with the local failure attached as its cause.
        """
        logger.warning(
            "Primary LLM failed on the %s (%s: %s); falling back to the local model",
            turn,
            type(error).__name__,
            error,
        )
        try:
            result = await local_attempt
        except Exception as local_error:
            await self._health.record_failure(TIER0_UNDERSTUDY, classify_failure(local_error))
            logger.warning(
                "Local fallback LLM failed too (%s: %s); re-raising the primary failure",
                type(local_error).__name__,
                local_error,
            )
            raise error from local_error
        await self._health.record_success(TIER0_UNDERSTUDY)
        return result


class ToolCallingFallbackLLMProvider(FallbackLLMProvider):
    """The composite for a primary that also drives the tool loop.

    Adds exactly one thing to :class:`FallbackLLMProvider`: ``complete_with_tools``,
    under the SAME :func:`~bob.application.router.fallback_policy.should_fall_back`
    policy as plain chat. Build it via :func:`build_fallback_provider`, which picks this
    variant only when the primary really is a
    :class:`~bob.kernel.ports.ToolCallingProvider`.

    The local understudy is used for a tool turn ONLY if it can make tool calls at all.
    When it cannot, the primary's outage propagates: an answer produced without the
    tools the caller asked for is not a degraded answer, it is a different — and
    silently wrong — one, and the tool loop has no way to tell.
    """

    def __init__(
        self,
        *,
        primary: LLMProvider,
        fallback: LLMProvider,
        health: HealthObserver | None = None,
    ) -> None:
        if not isinstance(primary, ToolCallingProvider):
            raise TypeError(
                "ToolCallingFallbackLLMProvider needs a tool-calling primary; "
                "use build_fallback_provider() to pick the right composite"
            )
        super().__init__(primary=primary, fallback=fallback, health=health)
        self._tool_primary: ToolCallingProvider = primary

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        """Complete a tool turn, degrading to the local model on a transport failure."""
        try:
            result = await self._tool_primary.complete_with_tools(messages, tools=tools)
        except Exception as error:
            await self._health.record_failure(TIER0_PRIMARY, classify_failure(error))
            if not should_fall_back(error):
                raise
            local = self._fallback
            if not isinstance(local, ToolCallingProvider):
                logger.warning(
                    "Primary LLM failed on the %s (%s: %s); the local fallback cannot make "
                    "tool calls, so the failure stands",
                    _TOOL_TURN,
                    type(error).__name__,
                    error,
                )
                raise
            return await self._degrade_to_local(
                local.complete_with_tools(messages, tools=tools),
                error=error,
                turn=_TOOL_TURN,
            )
        await self._health.record_success(TIER0_PRIMARY)
        return result


def build_fallback_provider(
    *,
    primary: LLMProvider,
    fallback: LLMProvider,
    health: HealthObserver | None = None,
) -> FallbackLLMProvider:
    """Compose ``primary`` + ``fallback`` into the variant that mirrors ``primary``.

    The single supported way to build the composite: a tool-calling primary yields a
    :class:`ToolCallingFallbackLLMProvider`, anything else the plain
    :class:`FallbackLLMProvider`. Constructing the classes directly is legitimate but
    puts the capability decision on the caller — and getting it wrong is invisible to
    the ``hasattr``-based tool seam.
    """
    if isinstance(primary, ToolCallingProvider):
        return ToolCallingFallbackLLMProvider(primary=primary, fallback=fallback, health=health)
    return FallbackLLMProvider(primary=primary, fallback=fallback, health=health)
