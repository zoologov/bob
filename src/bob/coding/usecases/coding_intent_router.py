# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=application

"""CodingIntentRouter — natural-language entry into the gated session (BOB-041 .2).

Canon (T3.B): the owner talks to Bob naturally in Bob's topic ("Боб, создай файл X",
"поправь баг в Z"), and Bob runs the gated coding session via GUPPI. This coordinator
decides WHEN to call the gated :class:`~bob.coding.usecases.coding_assistant.CodingAssistant`
from one owner message — and ONLY that. It is a thin policy over two seams:

* a cheap Tier-0 classifier (coding vs chat) for a FRESH dev-work request, and
* the pure :func:`~bob.coding.intent.is_approval` /
  :func:`~bob.coding.intent.is_stop` predicates for natural approve/stop while
  a session is live.

🔴 SAFETY — this router can NEVER bypass a gate. It only ever calls ``start`` (which
merely PLANS, no edits — the unbypassable gate), ``approve_plan`` (valid ONLY from
``PLAN_READY`` in the domain machine) or ``stop`` (the kill-switch); the use-case
re-checks the owner on each call (defense-in-depth) and the domain forbids
``EXECUTING`` except via ``PLAN_READY → approve_plan``. So the worst a misclassified
chat message can do is make a PLAN proposal (no edits). Owner-only is enforced HERE
too: a non-owner message never reaches the assistant. Everything is injected, so the
routing is deterministic in tests (no real LLM, no real session).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from bob.coding.intent import is_approval, is_stop
from bob.coding.state import CodingSessionState

if TYPE_CHECKING:
    from bob.coding.state import CodingSessionState as _State

__all__ = ["CodingIntentClassifierLike", "CodingIntentRouter", "GatedCoder"]


class GatedCoder(Protocol):
    """The narrow gated-coding surface the router drives (BOB-041 .2).

    A structural subset of
    :class:`~bob.coding.usecases.coding_assistant.CodingAssistant`: ``active_state``
    is the side-effect-free query of the in-flight session's state, while ``start`` /
    ``approve_plan`` / ``stop`` are the gated owner mutators (each re-checks the owner
    and is bounded by the plan gate). The router never reaches past these four methods.
    """

    async def active_state(self) -> CodingSessionState | None: ...
    async def start(self, task: str, sender: int | None) -> object: ...
    async def approve_plan(self, sender: int | None) -> object: ...
    async def stop(self, sender: int | None) -> object: ...


class CodingIntentClassifierLike(Protocol):
    """The coding/chat classifier seam (a fresh dev-work request vs ordinary chat)."""

    async def is_coding_request(self, text: str) -> bool: ...


class CodingIntentRouter:
    """Route one natural-language owner message into the gated coding session."""

    def __init__(
        self,
        *,
        coder: GatedCoder,
        classifier: CodingIntentClassifierLike,
        nl_autostart: bool = False,
    ) -> None:
        self._coder = coder
        self._classifier = classifier
        # 🔴 SAFETY (BOB-076): auto-starting a session from a FRESH natural-language
        # message is gated behind this flag, default OFF. The cheap Tier-0 classifier
        # mis-labels a casual owner reply as a coding request → a runaway coder launch
        # from ordinary chat. OFF → a fresh message is left to the chat path (no
        # classifier call, no ``start``); the coder starts ONLY via an explicit /code.
        # The kill-switch (stop) and plan-approve stay ON regardless — they act on an
        # ALREADY-live session the owner started deliberately, so they are safe.
        self._nl_autostart = nl_autostart

    async def route(self, *, text: str, sender: int | None, is_owner: bool) -> bool:
        """Maybe route ``text`` into the gated session; return whether it was consumed.

        Owner-only: a non-owner message is never routed (returns ``False`` so the normal
        chat path handles it). With a live session the router only drives natural
        approve/stop; with no session a coding-intent message PLANS via ``start``.
        Returns ``False`` (treat as chat) on any ambiguity — never an accidental gate.
        """
        if not is_owner:
            return False
        state = await self._coder.active_state()
        if state is not None:
            return await self._route_active(state, text, sender)
        return await self._route_fresh(text, sender)

    async def _route_active(
        self, state: _State, text: str, sender: int | None
    ) -> bool:
        """Drive an in-flight session: a stop kill-switch, or a PLAN_READY approval.

        A stop phrase stops from any live state (the kill-switch). An approval phrase
        approves ONLY from ``PLAN_READY`` (the plan gate) — never from ``EXECUTING`` or
        any other state, so NL cannot reach execution except the explicit approve of a
        waiting plan. Anything ambiguous is left to the chat path (``False``).
        """
        if is_stop(text):
            await self._coder.stop(sender)
            return True
        if state is CodingSessionState.PLAN_READY and is_approval(text):
            await self._coder.approve_plan(sender)
            return True
        return False

    async def _route_fresh(self, text: str, sender: int | None) -> bool:
        """No live session: a classified dev-work request PLANS; chat is left alone.

        🔴 SAFETY (BOB-076): auto-start is gated behind ``nl_autostart`` (default OFF).
        When OFF the router does NOT even consult the classifier — a fresh message can
        never launch a session from chat; it is left to the normal chat path (``False``),
        and the coder starts only via an explicit ``/code`` command. When ON, a
        classified dev-work request PLANS via ``start`` as before (still just a plan —
        the unbypassable gate stops there until an explicit approve).
        """
        if not self._nl_autostart:
            return False
        if await self._classifier.is_coding_request(text):
            await self._coder.start(text, sender)
            return True
        return False
