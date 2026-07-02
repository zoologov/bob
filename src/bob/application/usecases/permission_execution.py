# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""PermissionExecutor — execute the owner's decision on a pending request (BOB-052 .3).

The EXECUTION half of the permission flow. Once :meth:`PermissionFlow.maybe_decide`
records the owner's verdict (.2), the executor acts on it — owning HOW the privilege is
fulfilled (the flow owns only WHEN/WHO):

* **GRANT (per-request elevation).** Re-run the stored ``request_text`` through the
  injected :class:`PrivilegedFulfiller` AS IF the requester were authorized — but ONLY
  for THIS one request (a one-shot elevated context). 🔴 The fulfiller is handed only the
  stored ``request_text``: the elevation cannot leak to the requester's other/future
  messages, because no durable state is touched. The result is sent to the requester in
  Bob's voice via the :class:`RequesterChannel`.
* **AUTHORIZE (durable).** Call :meth:`DurableAuthorizer.authorize` (the real allowlist
  grant) so the requester becomes allowlisted and future turns take the normal authorized
  path — then ALSO fulfil the current request (now authorized).
* **DENY.** Send the requester a gentle decline in Bob's voice; NOTHING is fulfilled or
  disclosed.

🔴 DECORATIVE / safe-default refuse. The whole execution is wrapped: any failure
(fulfiller / authorize / channel) is caught and DROPPED silently — the SAFE DEFAULT on
failure is REFUSE (never disclose or run anything when something goes wrong), and NEVER a
GUPPI outage notice (this is flavour, not an essential reply step). Bob's normal replies
are never broken by it.

Everything is injected (fulfiller / channel / authorizer), so execution is deterministic
in tests with fakes.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from bob.domain.permission.entities import PermissionRequest

logger = logging.getLogger(__name__)

__all__ = [
    "DurableAuthorizer",
    "PermissionDecision",
    "PermissionExecutor",
    "PrivilegedFulfiller",
    "RequesterChannel",
]


class PermissionDecision(Enum):
    """The owner's classified verdict the executor acts on (mirrors the flow's verdict)."""

    GRANT = "grant"
    DENY = "deny"
    AUTHORIZE = "authorize"


class PrivilegedFulfiller(Protocol):
    """The one-shot elevated fulfilment seam the executor drives (BOB-052 .3).

    :meth:`fulfil` re-runs ``request_text`` through the capability/tool-loop (or the
    internal-info disclosure) AS IF the requester were authorized — but ONLY for this
    request (a one-shot elevated context the adapter builds per call). 🔴 It is handed
    only the stored ``request_text``, so the elevation cannot carry to the requester's
    other messages. Returns Bob's reply text for the requester.
    """

    async def fulfil(
        self, request_text: str, *, requester_id: int, requester_name: str
    ) -> str: ...


class RequesterChannel(Protocol):
    """Send one line to the requester in Bob's voice (BOB-052 .3).

    The result of an approved fulfilment, or a gentle decline on a denial, is sent to the
    requester (in the chat they wrote in) through this seam. The concrete adapter knows
    the transport (chat_id); the executor only knows :meth:`send`.
    """

    async def send(self, text: str) -> None: ...


class DurableAuthorizer(Protocol):
    """The durable-grant seam an AUTHORIZE decision fires (BOB-052 .3).

    Realised by :class:`~bob.application.authz.Authorizer`: :meth:`authorize` adds the
    requester to the persisted allowlist, so future turns take the normal authorized path
    (no more asking).
    """

    async def authorize(self, user_id: int) -> None: ...


# The gentle decline Bob sends the requester on a denial (Russian persona voice; Cyrillic
# look-alikes intentional — silenced via per-file-ignores). Names asking the owner, never
# discloses what was refused.
_DENY_DECLINE = "Спросил Вову — пока не могу с этим помочь."


class PermissionExecutor:
    """Execute the owner's recorded decision on a pending permission-request."""

    def __init__(
        self,
        *,
        fulfiller: PrivilegedFulfiller,
        channel: RequesterChannel,
        authorizer: DurableAuthorizer,
    ) -> None:
        self._fulfiller = fulfiller
        self._channel = channel
        self._authorizer = authorizer

    async def execute(
        self, request: PermissionRequest, decision: PermissionDecision
    ) -> None:
        """Act on the owner's ``decision`` for ``request``; decorative + safe-default refuse.

        🔴 The whole path is guarded: any failure is logged and DROPPED silently (the safe
        default is REFUSE — nothing is disclosed / run on error), never raised and never a
        GUPPI outage notice. A DENY sends a gentle decline; a GRANT fulfils the stored
        request once with the privilege; an AUTHORIZE durably grants AND then fulfils.
        """
        try:
            await self._execute(request, decision)
        except Exception:
            logger.exception(
                "permission execution failed (refused, dropped): decision=%s request=%s",
                decision.value,
                request.id,
            )

    async def _execute(
        self, request: PermissionRequest, decision: PermissionDecision
    ) -> None:
        """Inner execution (wrapped by :meth:`execute` for the safe-default refuse)."""
        if decision is PermissionDecision.DENY:
            await self._channel.send(_DENY_DECLINE)
            return
        if decision is PermissionDecision.AUTHORIZE:
            # 🔴 Durable grant FIRST — if it fails, the whole thing refuses (raises out to
            # the guard) and nothing is fulfilled or disclosed.
            await self._authorizer.authorize(request.requester_id)
        # GRANT or AUTHORIZE both fulfil the stored request ONCE, with the privilege,
        # for this requester (a one-shot elevated context inside the fulfiller).
        reply = await self._fulfiller.fulfil(
            request.request_text,
            requester_id=request.requester_id,
            requester_name=request.requester_name,
        )
        await self._channel.send(reply)
