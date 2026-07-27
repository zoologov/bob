# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""PrivilegedRequestFulfiller — run ONE request with the privilege (BOB-052 .3).

The concrete :class:`~bob.application.usecases.permission_execution.PrivilegedFulfiller`:
once the owner has APPROVED (or AUTHORIZEd) a pending request, this re-runs the stored
``request_text`` AS IF the requester were authorized — but ONLY for THIS request (a
one-shot elevated context built fresh per call):

* when a tool-calling provider AND a non-empty capability registry are wired, the request
  goes through the same capability tool-loop an authorized turn uses (GUPPI may run a
  tool for it);
* otherwise it goes through the plain router (the internal-info disclosure / a normal
  reply).

🔴 The elevation is scoped to the ONE ``request_text`` handed in: this object holds NO
durable state and is invoked once per approved request, so the privilege can never carry
to the requester's other/future messages. The durable path is the explicit AUTHORIZE,
which is the :class:`~bob.application.authz.Authorizer` grant — a different seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.capabilities.usecases.tool_loop import ToolLoop

if TYPE_CHECKING:
    from bob.capabilities.usecases.registry import CapabilityRegistry
    from bob.domain.ports import LLMMessage, ToolCallingProvider


class _Router(Protocol):
    """The minimal router surface the fulfiller needs (the plain-reply path)."""

    async def run(self, request: LLMRequest) -> str: ...

# The elevated system prompt framing the one-shot fulfilment (English instruction; the
# reply itself is in Bob's Russian voice via the persona the router/provider already
# carries). It states plainly that the owner approved THIS request, so Bob fulfils it
# for the requester — bounded to this single request.
_FULFIL_SYSTEM_PROMPT = (
    "You are Bob. Your owner has just APPROVED this single request from {requester}, so "
    "you may fulfil it for them now — use a capability if one helps. This approval is for "
    "THIS request only. Answer them directly, in character."
)

# The manifest preface when the elevated fulfilment drives the capability tool-loop.
_CAPABILITY_PREFACE = "Capabilities GUPPI runs for you; call one when it helps fulfil this:"


class PrivilegedRequestFulfiller:
    """Run one approved request with the privilege (tool-loop or plain router)."""

    def __init__(
        self,
        *,
        router: _Router,
        registry: CapabilityRegistry,
        tool_provider: ToolCallingProvider | None,
    ) -> None:
        self._router = router
        self._registry = registry
        self._tool_provider = tool_provider

    async def fulfil(
        self, request_text: str, *, requester_id: int, requester_name: str
    ) -> str:
        """Fulfil ``request_text`` for the requester with the privilege (one-shot).

        Drives the capability tool-loop when a provider + a non-empty registry are wired
        (an authorized turn's path), else the plain router. 🔴 Only ``request_text`` is
        ever sent to the model, so the elevation cannot leak to the requester's other
        messages.
        """
        del requester_id  # the elevation is bound to the text, not a durable identity
        system_prompt = _FULFIL_SYSTEM_PROMPT.format(requester=requester_name)
        provider = self._tool_provider
        if provider is not None and not self._registry.is_empty:
            return await self._fulfil_with_tools(provider, system_prompt, request_text)
        return await self._router.run(
            LLMRequest(
                task_type=TaskType.REPLY_TO_USER,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": request_text},
                ],
            )
        )

    async def _fulfil_with_tools(
        self, provider: ToolCallingProvider, system_prompt: str, request_text: str
    ) -> str:
        """Drive the capability tool-loop for the elevated one-shot fulfilment."""
        manifest = "\n".join([_CAPABILITY_PREFACE, self._registry.describe()])
        messages: list[LLMMessage] = [
            {"role": "system", "content": f"{system_prompt}\n{manifest}"},
            {"role": "user", "content": request_text},
        ]
        loop = ToolLoop(provider=provider, registry=self._registry)
        return await loop.run(messages)
