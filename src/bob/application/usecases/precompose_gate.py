# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""PreComposeGate — the cross-domain gates that may CONSUME a turn before compose.

The pre-compose consumption gates in one cohesive collaborator (extracted from
``HandleMessage`` in BOB-062.6b, wave 1, behavior-preserving). BEFORE composing a normal
reply the turn is routed, in order, through:

* :meth:`maybe_route_interactive` — an OWNER DM message driving a live interactive claude
  session (open / steer / stop), owner-only + DM-only (BOB-083 .4);
* :meth:`maybe_route_coding` — an OWNER coding-intent message in Bob's topic is routed
  into the gated CodingAssistant (BOB-041 .2); and
* :meth:`maybe_permission` — the OWNER's verdict on a pending privilege request, or a
  NON-authorized member opening one (BOB-052 .2).

Each returns whether it CONSUMED the turn (so ``HandleMessage`` short-circuits the normal
perceive→decide→act flow). This is a CROSS-DOMAIN coordinator (coding + social), so it
lives in the application layer, OUTSIDE both verticals — it only passes the perceived
authz facts; the owner-only decision + non-authorized-only request gates live inside the
flows. Unwired (the default) both gates are inert and every message takes the normal chat
path exactly as before.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.social.interlocutor import InterlocutorKind, Trust

if TYPE_CHECKING:
    from bob.application.runtime.events import MessageReceived
    from bob.social.interlocutor import Interlocutor

logger = logging.getLogger(__name__)


class NaturalCodingRouter(Protocol):
    """The natural-language coding-intent seam HandleMessage delegates to (BOB-041 .2).

    Realised by
    :class:`~bob.coding.usecases.coding_intent_router.CodingIntentRouter`: given an
    owner message in Bob's topic it decides WHEN to drive the gated coding session
    (plan / approve / stop) and returns whether it CONSUMED the turn (so HandleMessage
    short-circuits the normal compose). Owner-only and gate-bound live in the router +
    the use-case + the domain machine, never here. Unwired (the default) OR ``coder.enabled``
    false → no router is injected, so the natural-language path is inert and every
    message takes the normal chat flow exactly as before.
    """

    async def route(self, *, text: str, sender: int | None, is_owner: bool) -> bool: ...


class InteractiveRouterLike(Protocol):
    """The interactive-terminal intake seam HandleMessage delegates to (BOB-083 .4).

    Realised by
    :class:`~bob.interactive.usecases.intake.InteractiveIntakeRouter`: given an
    owner DM message it may OPEN a live interactive claude session, FEED an owner reply to
    its stdin (steer) or STOP it, returning whether it CONSUMED the turn (so HandleMessage
    short-circuits the normal compose). 🔴 owner-only + DM-only: the seam is passed BOTH
    ``is_owner`` (derived from the perceived interlocutor) and ``is_group`` (the channel
    signal), and re-checks both inside — a guest or a GROUP message is never routed into
    interactive, so the mode can only ever fire in the owner's DM. Unwired (the default /
    ``coder.interactive`` false) → no router is injected, so the seam is inert and every
    message takes the normal chat flow exactly as before.
    """

    async def route(
        self, *, text: str, sender: int | None, is_owner: bool, is_group: bool
    ) -> bool: ...


class PermissionFlowLike(Protocol):
    """The permission-flow seam HandleMessage delegates privilege gating to (BOB-052 .2).

    Realised by :class:`~bob.social.usecases.permission_flow.PermissionFlow`. On a
    turn it owns two decisions, each returning whether it CONSUMED the turn (so
    HandleMessage short-circuits the normal compose): ``maybe_decide`` records the
    OWNER's verdict on an active pending request (grant / deny / authorize), and
    ``maybe_request`` opens a pending request + asks the owner when a NON-authorized
    member asks for something privileged. 🔴 Owner-only decision and the
    non-authorized-only request gate live INSIDE the flow; HandleMessage only passes the
    perceived authz facts. Unwired (the default) the seam is inert and every message
    takes the normal chat flow exactly as before.
    """

    async def maybe_decide(self, *, text: str, is_owner: bool) -> bool: ...

    async def maybe_request(
        self,
        *,
        text: str,
        requester_id: int,
        requester_name: str,
        is_owner: bool,
        is_authorized: bool,
        recent_thread: str = "",
    ) -> bool: ...


class PreComposeGate:
    """Route a turn through the coding-intent + permission gates before compose."""

    def __init__(
        self,
        *,
        coding_router: NaturalCodingRouter | None,
        permission_flow: PermissionFlowLike | None,
        interactive_router: InteractiveRouterLike | None = None,
    ) -> None:
        self._coding_router = coding_router
        self._permission_flow = permission_flow
        self._interactive_router = interactive_router

    async def maybe_route_interactive(
        self, event: MessageReceived, interlocutor: Interlocutor | None
    ) -> bool:
        """Route an owner DM message into the live interactive session (BOB-083 .4).

        Returns whether the interactive intake CONSUMED the turn (so the caller
        short-circuits the normal compose). Inert when no router is wired (the default /
        ``coder.interactive`` false). 🔴 owner-only + DM-only: ``is_owner`` is derived from
        the perceived interlocutor (only an
        :class:`~bob.social.interlocutor.InterlocutorKind.OWNER` sender is owner here) and
        ``is_group`` is threaded from the channel signal — the router re-checks both, so a
        guest or a GROUP message is never routed into interactive and the mode fires ONLY
        in the owner's DM. Resilient like the coding gate: any router fault is logged and
        treated as "not consumed" so a live intake fault never crashes intake.
        """
        if self._interactive_router is None:
            return False
        is_owner = (
            interlocutor is not None and interlocutor.kind is InterlocutorKind.OWNER
        )
        try:
            return await self._interactive_router.route(
                text=event.text,
                sender=event.sender_id,
                is_owner=is_owner,
                is_group=event.is_group,
            )
        except Exception:
            # 🔴 Резилентность приёма: интейк-роутер дёргается на каждом сообщении
            # (manager.active() и подобное). Любая ошибка не должна крашить приём — иначе
            # intake-воркер роняет сообщение и Боб глохнет. Логируем и трактуем как «режим
            # не активен» → ход продолжается обычным chat-путём.
            logger.exception(
                "interactive-router упал на приёме — продолжаю chat-путём (не интерактив)"
            )
            return False

    async def maybe_route_coding(
        self, event: MessageReceived, interlocutor: Interlocutor | None
    ) -> bool:
        """Route an owner coding-intent message into the gated session (BOB-041 .2).

        Returns whether the natural-language coding path CONSUMED the turn (so the
        caller short-circuits the normal compose). Inert when no router is wired (the
        default / ``coder.enabled`` false). Owner is derived from the perceived
        interlocutor — only an :class:`~bob.social.interlocutor.InterlocutorKind.OWNER`
        sender is ever owner here, so with no perception seam (or a guest/known sender)
        the message is never routed (``is_owner`` false) and the router itself re-checks;
        the gated use-case re-checks the owner again (defense-in-depth).
        """
        if self._coding_router is None:
            return False
        is_owner = (
            interlocutor is not None and interlocutor.kind is InterlocutorKind.OWNER
        )
        try:
            return await self._coding_router.route(
                text=event.text, sender=event.sender_id, is_owner=is_owner
            )
        except Exception:
            # 🔴 Резилентность приёма (BOB-078 D): coding-router дёргается на каждом
            # сообщении (session_store.active() и подобное). Любая ошибка роутера
            # (напр. битая строка в coding_session) не должна крашить приём — иначе
            # intake-воркер роняет сообщение и Боб глохнет. Логируем и трактуем как
            # «нет активной сессии / не coding» → ход продолжается обычным chat-путём.
            logger.exception(
                "coding-router упал на приёме — продолжаю chat-путём (сообщение не coding)"
            )
            return False

    async def maybe_permission(
        self, event: MessageReceived, interlocutor: Interlocutor | None
    ) -> bool:
        """Route the turn through the permission flow; return whether it consumed it.

        Inert when no flow is wired (the default). The authz facts are derived from the
        perceived interlocutor: OWNER → owner; a TRUSTED non-owner (KNOWN) → authorized;
        a GUEST → non-authorized. 🔴 On the OWNER's turn the flow may record a decision
        on an active pending; on a NON-authorized member's turn it may open a privileged
        request and ask the owner. The flow itself enforces owner-only decision and the
        non-authorized-only request gate — an AUTHORIZED member is never gated. With no
        perceived interlocutor (no perception seam) the message is treated as
        non-owner/non-authorized only for the request path, and the owner-decision path
        cannot fire — so an unidentified turn is never auto-approved.
        """
        if self._permission_flow is None:
            return False
        is_owner = (
            interlocutor is not None and interlocutor.kind is InterlocutorKind.OWNER
        )
        is_authorized = interlocutor is not None and interlocutor.trust is Trust.TRUSTED
        if is_owner and await self._permission_flow.maybe_decide(
            text=event.text, is_owner=True
        ):
            return True
        if event.sender_id is None:
            return False
        return await self._permission_flow.maybe_request(
            text=event.text,
            requester_id=event.sender_id,
            requester_name=event.sender_name or "",
            is_owner=is_owner,
            is_authorized=is_authorized,
        )
