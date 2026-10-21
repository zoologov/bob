# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""ReportingLLMProvider — a provider that reports every call's outcome to the health monitor.

One responsibility: put the outcome of each call to the wrapped provider on the record, under
one ``provider_id``, for whoever is calling (BOB-116 F1, review M1). The router reports the
tiers it calls, but it is not the only caller: the owner's turn goes through
:class:`~bob.capabilities.usecases.tool_loop.ToolLoop`, which calls Tier 1 directly. Before
this wrapper a 401/403/5xx there reached nobody — no owner signal, and ``/status`` said
«tier1 — ок». The factory now hands Tier 1 over wrapped, so the router and the tool loop see
the same reporting provider, and the router leaves a
:class:`~bob.kernel.ports.SelfReportingProvider` to report itself: one HTTP call — one record.

The rules are the understudy wrapper's
(:mod:`bob.infrastructure.llm.fallback_provider`), which reports ``tier0-primary`` and
``tier0-understudy`` itself:

* the failure class is :func:`~bob.application.router.fallback_policy.classify_failure`, the
  same verdict the router and the understudy use;
* a failure is recorded BEFORE it propagates — the heartbeat lane gate reads the snapshot
  right after the tick (BOB-116 D5); the error itself goes on untouched;
* a stream is delegated, not reported: its outcome is only known mid-iteration, and nothing
  streams a tier today.

**Capability mirroring (BOB-087.E1b).** The tool seam
(``bob.runtime.wiring.access._as_tool_provider``) probes for ``complete_with_tools`` with
``hasattr``, so a wrapper that dropped it would put the tool loop to sleep without an error.
Hence two variants, chosen by :func:`build_reporting_provider` from what the wrapped provider
offers: the wrapper advertises tool-calling exactly when the wrapped provider does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from bob.application.router.fallback_policy import classify_failure
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

_Result = TypeVar("_Result")


class ReportingLLMProvider:
    """Delegate to ``inner``; report each completed call's outcome as ``provider_id``.

    Realises :class:`~bob.kernel.ports.LLMProvider` and
    :class:`~bob.kernel.ports.SelfReportingProvider`. Not an
    :class:`~bob.kernel.ports.UnderstudyBackedProvider`: there is no stand-in behind it, so
    the voice policy has nothing to take out.
    """

    def __init__(
        self, *, inner: LLMProvider, health: HealthObserver, provider_id: str
    ) -> None:
        self._inner = inner
        self._health = health
        self._provider_id = provider_id

    @property
    def reported_id(self) -> str:
        """The ``provider_id`` every outcome of this provider is reported under."""
        return self._provider_id

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """Complete a chat turn on the wrapped provider; a non-stream outcome is reported."""
        if stream:
            return await self._inner.complete(messages, stream=True)
        return await self._reported(self._inner.complete(messages, stream=False))

    async def _reported(self, call: Awaitable[_Result]) -> _Result:
        """Await ``call``; record its outcome — a failure before it propagates."""
        try:
            result = await call
        except Exception as error:
            await self._health.record_failure(self._provider_id, classify_failure(error))
            raise
        await self._health.record_success(self._provider_id)
        return result


class ToolCallingReportingLLMProvider(ReportingLLMProvider):
    """The reporting wrapper for a provider that also drives the tool loop.

    Adds exactly ``complete_with_tools``, reported like a chat turn. Build it via
    :func:`build_reporting_provider`, which picks this variant only when the wrapped provider
    really is a :class:`~bob.kernel.ports.ToolCallingProvider`.
    """

    def __init__(
        self, *, inner: LLMProvider, health: HealthObserver, provider_id: str
    ) -> None:
        if not isinstance(inner, ToolCallingProvider):
            raise TypeError(
                "ToolCallingReportingLLMProvider needs a tool-calling provider; "
                "use build_reporting_provider() to pick the right wrapper"
            )
        super().__init__(inner=inner, health=health, provider_id=provider_id)
        self._tool_inner: ToolCallingProvider = inner

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        """Complete a tool turn on the wrapped provider and report its outcome."""
        return await self._reported(self._tool_inner.complete_with_tools(messages, tools=tools))


def build_reporting_provider(
    *, inner: LLMProvider, health: HealthObserver, provider_id: str
) -> ReportingLLMProvider:
    """Wrap ``inner`` in the reporting variant that mirrors its tool-calling capability."""
    if isinstance(inner, ToolCallingProvider):
        return ToolCallingReportingLLMProvider(
            inner=inner, health=health, provider_id=provider_id
        )
    return ReportingLLMProvider(inner=inner, health=health, provider_id=provider_id)
