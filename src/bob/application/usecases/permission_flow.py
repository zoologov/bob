# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""PermissionFlow — detect a privileged request, ask the owner, record the decision.

Canon (BOB-052): the Bobiverse group is closed and memory is public (BOB-051), but a
PRIVILEGE — running a tool, revealing Bob's inner life, disclosing owner data — is
owner-gated. So when a NON-authorized member asks for something privileged, Bob does
NOT fulfil it: he opens a pending request and asks the owner; the owner alone decides.
This application policy is the .2 flow over the .1 domain — it owns WHEN, never HOW the
privilege is executed (that is .3):

* :meth:`maybe_request` — for a non-owner, non-authorized member's turn, ask the
  injected :class:`~bob.domain.permission.privilege.PrivilegeJudge` whether the message
  is privileged. If so, create + save a PENDING
  :class:`~bob.domain.permission.entities.PermissionRequest`, 🔴 NOTIFY THE OWNER in
  Bob's voice («Вова, <кто> просит <что> — разрешить?»), tell the requester a light
  «спрошу Вову», and CONSUME the turn. A non-privileged need leaves the turn untouched
  (normal chat). One active pending per requester — a new request supersedes the old
  (EXPIRED). 🔴 An OWNER or an AUTHORIZED member never enters this path.
* :meth:`maybe_decide` — 🔴 ONLY when ``is_owner`` and an active pending exists: read
  the owner's reply with the pure NL predicates (:func:`is_grant` / :func:`is_deny` /
  :func:`is_authorize`) or an explicit ``/allow`` / ``/deny`` / ``/authorize`` command
  → move the request to APPROVED / DENIED; an authorize also fires the durable
  ``on_authorize`` hook (the real :class:`~bob.application.authz.Authorizer` grant +
  the execution-on-approve live in .3 — here the hook is an inert seam). A non-owner
  «да» NEVER approves; an ambiguous owner reply is left to chat.

Everything is injected (judge / store / notifier / clock / id-factory), so the flow is
deterministic in tests with fakes. Unwired into ``HandleMessage`` (the default) the
seam is inert and every turn behaves exactly as before.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from bob.application.usecases.permission_execution import PermissionDecision
from bob.domain.permission.entities import PermissionRequest
from bob.domain.permission.intent import is_authorize, is_deny, is_grant
from bob.domain.permission.privilege import PrivilegeContext
from bob.domain.permission.state import PermissionState

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from bob.domain.permission.privilege import PrivilegeJudge
    from bob.domain.ports import Clock

logger = logging.getLogger(__name__)

__all__ = [
    "PermissionExecutorLike",
    "PermissionFlow",
    "PermissionNotifier",
    "PermissionRequestStoreLike",
]

# Owner-only decision commands (BOB-052 .2). Explicit, unambiguous companions to the
# NL predicates: ``/allow`` approves the active pending, ``/deny`` refuses it,
# ``/authorize`` approves AND durably authorises the requester (the .3 hook). They are
# matched on the FIRST whitespace-separated token so ``/authorize 7`` still routes.
_ALLOW_COMMAND = "/allow"
_DENY_COMMAND = "/deny"
_AUTHORIZE_COMMAND = "/authorize"


class PermissionRequestStoreLike(Protocol):
    """The permission-request persistence surface the flow needs (BOB-052 .1/.2).

    Realised by
    :class:`~bob.infrastructure.persistence.permission_request_store.SqlitePermissionRequestStore`.
    ``save`` UPSERTs a request; ``active`` / ``active_for`` list the still-PENDING
    requests oldest-first; ``set_state`` transitions one. A test injects an in-memory
    fake.
    """

    async def save(self, request: PermissionRequest) -> None: ...
    async def active(self) -> tuple[PermissionRequest, ...]: ...
    async def active_for(
        self, requester_id: int
    ) -> tuple[PermissionRequest, ...]: ...
    async def set_state(self, request_id: str, state: PermissionState) -> None: ...


class PermissionNotifier(Protocol):
    """The two-channel notice seam the flow drives (BOB-052 .2).

    ``notify_owner`` posts Bob's «Вова, <кто> просит <что> — разрешить?» into Bob's
    topic (the owner decides there); ``tell_requester`` sends the requester the light
    «спрошу Вову» acknowledgement in the chat they wrote in. The concrete adapter knows
    the transport (chat_id / topic); the flow only knows these two methods.
    """

    async def notify_owner(self, text: str) -> None: ...
    async def tell_requester(self, text: str) -> None: ...


class PermissionExecutorLike(Protocol):
    """The execution seam the flow drives once the owner's decision is recorded (.3).

    Realised by
    :class:`~bob.application.usecases.permission_execution.PermissionExecutor`. After
    :meth:`PermissionFlow.maybe_decide` records APPROVED / DENIED, it hands the request
    and the classified :class:`PermissionDecision` to :meth:`execute`, which fulfils a
    GRANT with a one-shot elevation, durably grants + fulfils an AUTHORIZE, or sends a
    gentle decline on a DENY — all decorative (safe-default refuse). Unwired (the .2
    default) the flow keeps the legacy inert ``on_authorize`` hook instead.
    """

    async def execute(
        self, request: PermissionRequest, decision: PermissionDecision
    ) -> None: ...


# Owner notice + requester ack templates (Russian persona voice; Cyrillic look-alikes
# intentional — silenced via per-file-ignores). The owner notice names WHO asks WHAT so
# the owner can decide with «да»/«нет»/«авторизуй» or /allow //deny //authorize.
def _owner_notice(*, owner_name: str, requester_name: str, what: str) -> str:
    return f"{owner_name}, {requester_name} просит {what} — разрешить?"


_REQUESTER_ACK = "Секунду, спрошу Вову."


class PermissionFlow:
    """Detect a privileged non-member request, ask the owner, record the decision."""

    def __init__(
        self,
        *,
        judge: PrivilegeJudge,
        store: PermissionRequestStoreLike,
        notifier: PermissionNotifier,
        clock: Clock,
        owner_name: str = "Вова",
        id_factory: Callable[[], str] | None = None,
        capability_hints: Sequence[str] = (),
        on_authorize: Callable[[int], Awaitable[None]] | None = None,
        executor: PermissionExecutorLike | None = None,
    ) -> None:
        self._judge = judge
        self._store = store
        self._notifier = notifier
        self._clock = clock
        self._owner_name = owner_name
        self._id_factory = id_factory if id_factory is not None else _uuid_id
        self._capability_hints = tuple(capability_hints)
        # Durable-authorise hook (BOB-052 .2 seam): an «авторизуй» / ``/authorize``
        # decision approves the pending AND should durably authorise the requester via the
        # real Authorizer. With NO executor wired (.2) it is the durable seam — unwired it
        # is an inert no-op (the state still moves to APPROVED). When an executor IS wired
        # (.3) the executor owns the durable grant, so this hook is NOT also fired (no
        # double-authorize).
        self._on_authorize = on_authorize
        # Execution seam (BOB-052 .3): once the owner's decision is recorded, the request
        # + the classified :class:`PermissionDecision` are handed to the executor, which
        # fulfils a GRANT (one-shot elevation), durably grants + fulfils an AUTHORIZE, or
        # sends a gentle decline on a DENY — decorative (safe-default refuse). Unwired (the
        # .2 default) the legacy ``on_authorize`` hook fires instead and no execution runs.
        self._executor = executor

    async def maybe_request(
        self,
        *,
        text: str,
        requester_id: int,
        requester_name: str,
        is_owner: bool,
        is_authorized: bool,
        recent_thread: str = "",
    ) -> bool:
        """Maybe open a pending permission-request for a non-member; return consumed.

        🔴 Only a NON-owner, NON-authorized member ever reaches the judge — an owner or
        an authorized member returns ``False`` immediately (the existing path is
        untouched). A privileged need pends + notifies the owner + acks the requester +
        consumes the turn; a non-privileged need returns ``False`` so the normal chat
        flow handles the message exactly as before.
        """
        if is_owner or is_authorized:
            return False
        need = await self._judge.assess(
            PrivilegeContext(
                request_text=text,
                capability_hints=self._capability_hints,
                recent_thread=recent_thread,
            )
        )
        if not need.needs_permission:
            return False
        await self._supersede_active(requester_id)
        request = PermissionRequest(
            id=self._id_factory(),
            requester_id=requester_id,
            requester_name=requester_name,
            request_text=text,
            kind=need.kind,
            what=need.what,
            state=PermissionState.PENDING,
            created_at=self._clock.now(),
        )
        await self._store.save(request)
        await self._notifier.notify_owner(
            _owner_notice(
                owner_name=self._owner_name,
                requester_name=requester_name,
                what=need.what,
            )
        )
        await self._notifier.tell_requester(_REQUESTER_ACK)
        return True

    async def maybe_decide(self, *, text: str, is_owner: bool) -> bool:
        """Maybe record the OWNER's decision on the active pending; return consumed.

        🔴 ONLY the owner decides: a non-owner reply (even a bare «да») returns
        ``False`` and never moves a request. With no active pending, ``False``. The
        owner's intent is read from an explicit ``/allow`` / ``/deny`` / ``/authorize``
        command first, then the pure NL predicates — grant → APPROVED, deny → DENIED,
        authorize → APPROVED + the durable hook. An ambiguous owner reply is left to the
        chat path (``False``), never an accidental grant.
        """
        if not is_owner:
            return False
        pending = await self._oldest_pending()
        if pending is None:
            return False
        decision = _classify_decision(text)
        if decision is None:
            return False
        if decision is _Decision.DENY:
            await self._store.set_state(pending.id, PermissionState.DENIED)
            await self._run_execution(pending, decision)
            return True
        # GRANT or AUTHORIZE both approve; AUTHORIZE also durably authorises (the
        # executor on the .3 path, else the legacy hook on the .2 path).
        await self._store.set_state(pending.id, PermissionState.APPROVED)
        if self._executor is None and decision is _Decision.AUTHORIZE:
            await self._authorize(pending.requester_id)
        await self._run_execution(pending, decision)
        return True

    async def _run_execution(
        self, request: PermissionRequest, decision: _Decision
    ) -> None:
        """Hand the recorded decision to the executor, when one is wired (BOB-052 .3).

        The executor owns HOW: it fulfils a GRANT with a one-shot elevation, durably
        grants + fulfils an AUTHORIZE, or sends a gentle decline on a DENY — all
        decorative (safe-default refuse inside the executor). Unwired (the .2 default)
        nothing runs here and the legacy ``on_authorize`` hook already handled the durable
        grant above.
        """
        if self._executor is None:
            return
        await self._executor.execute(request, _DECISION_TO_EXECUTION[decision])

    async def _supersede_active(self, requester_id: int) -> None:
        """Expire any still-PENDING request of ``requester_id`` (one active per person)."""
        for request in await self._store.active_for(requester_id):
            await self._store.set_state(request.id, PermissionState.EXPIRED)

    async def _oldest_pending(self) -> PermissionRequest | None:
        """The oldest still-PENDING request across requesters, or ``None`` when none."""
        active = await self._store.active()
        return active[0] if active else None

    async def _authorize(self, requester_id: int) -> None:
        """Fire the durable-authorise hook, best-effort (BOB-052 .3 seam).

        Unwired (.2) this is a no-op — the request is already APPROVED. A wired hook's
        failure is logged and swallowed so a flaky durable grant can never break the
        already-recorded decision (the .3 fault-tolerance contract).
        """
        if self._on_authorize is None:
            return
        try:
            await self._on_authorize(requester_id)
        except Exception:
            logger.exception("durable authorize hook failed (ignored)")


class _Decision(Enum):
    """The owner's classified decision on a pending request."""

    GRANT = "grant"
    DENY = "deny"
    AUTHORIZE = "authorize"


# Map the flow's internal decision to the executor's verdict (BOB-052 .3). Kept as a
# pure mapping so the flow's NL/command classification (.2) stays the single source of
# WHICH decision was made, and the executor stays the single source of HOW it runs.
_DECISION_TO_EXECUTION: dict[_Decision, PermissionDecision] = {
    _Decision.GRANT: PermissionDecision.GRANT,
    _Decision.DENY: PermissionDecision.DENY,
    _Decision.AUTHORIZE: PermissionDecision.AUTHORIZE,
}


# Explicit owner-command → decision mapping (deny before allow is moot for an exact
# command, but keeping the dict makes the precedence-free command surface obvious).
_COMMAND_DECISIONS: dict[str, _Decision] = {
    _DENY_COMMAND: _Decision.DENY,
    _ALLOW_COMMAND: _Decision.GRANT,
    _AUTHORIZE_COMMAND: _Decision.AUTHORIZE,
}


def _classify_decision(text: str) -> _Decision | None:
    """Map the owner's reply to a :class:`_Decision`, or ``None`` when ambiguous.

    An explicit ``/allow`` / ``/deny`` / ``/authorize`` command wins first. Otherwise
    the pure NL predicates decide: authorize before grant (a durable «авторизуй» is a
    stronger grant), then deny (the safe default, which vetoes a grant inside
    :func:`is_grant`), then grant. Anything the predicates do not recognise is ``None``
    (left to chat — never an accidental approve).
    """
    command, _, _ = text.strip().partition(" ")
    if command in _COMMAND_DECISIONS:
        return _COMMAND_DECISIONS[command]
    return _classify_nl_decision(text)


def _classify_nl_decision(text: str) -> _Decision | None:
    """Classify a free-text owner reply via the pure NL predicates (no commands)."""
    if is_authorize(text):
        return _Decision.AUTHORIZE
    if is_deny(text):
        return _Decision.DENY
    if is_grant(text):
        return _Decision.GRANT
    return None


def _uuid_id() -> str:
    """Generate a fresh request id (the default id factory)."""
    return uuid4().hex
