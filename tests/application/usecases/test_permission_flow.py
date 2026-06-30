# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for PermissionFlow — detect + notify + owner-only decision (BOB-052 .2).

The flow is the application policy over the .1 domain: on a NON-authorized member's
turn it asks the :class:`PrivilegeJudge` whether the request is privileged; if so it
creates a PENDING :class:`PermissionRequest`, notifies the owner in Bob's voice, tells
the requester «спрошу Вову» and CONSUMES the turn. On the owner's turn (and only the
owner's) with an active pending it records the decision — grant → APPROVED, deny →
DENIED, authorize → APPROVED + a durable hook (the real authorize + execution are .3).

🔴 SECURITY invariants asserted here:

* only the OWNER decides — a non-owner «да» never approves a pending;
* an AUTHORIZED member never enters the flow (the existing path is untouched);
* a non-privileged request never consumes the turn (normal chat unchanged);
* one active pending per requester — a new request supersedes the old.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.usecases.permission_execution import (
    PermissionDecision,
    PermissionExecutor,
)
from bob.application.usecases.permission_flow import (
    PermissionExecutorLike,
    PermissionFlow,
)
from bob.domain.permission.privilege import PrivilegeContext, PrivilegeNeed
from bob.domain.permission.state import PermissionState

if TYPE_CHECKING:
    from collections.abc import Callable

    from bob.domain.permission.entities import PermissionRequest

_OWNER = 1
_GUEST = 7
_OTHER_GUEST = 8
_AT = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


class _FakeJudge:
    """A scripted privilege judge; records the contexts it assessed."""

    def __init__(self, *, need: PrivilegeNeed) -> None:
        self._need = need
        self.seen: list[PrivilegeContext] = []

    async def assess(self, ctx: PrivilegeContext) -> PrivilegeNeed:
        self.seen.append(ctx)
        return self._need


class _FakeStore:
    """In-memory permission-request store (the .1 store's surface)."""

    def __init__(self) -> None:
        self.requests: dict[str, PermissionRequest] = {}

    async def save(self, request: PermissionRequest) -> None:
        self.requests[request.id] = request

    async def active_for(self, requester_id: int) -> tuple[PermissionRequest, ...]:
        return tuple(
            r
            for r in self.requests.values()
            if r.requester_id == requester_id and r.state is PermissionState.PENDING
        )

    async def active(self) -> tuple[PermissionRequest, ...]:
        return tuple(
            r for r in self.requests.values() if r.state is PermissionState.PENDING
        )

    async def set_state(self, request_id: str, state: PermissionState) -> None:
        request = self.requests.get(request_id)
        if request is not None:
            self.requests[request_id] = request.with_state(state)


class _FakeNotifier:
    """Records owner notices + requester acknowledgements the flow sends."""

    def __init__(self) -> None:
        self.owner_notices: list[str] = []
        self.requester_acks: list[str] = []

    async def notify_owner(self, text: str) -> None:
        self.owner_notices.append(text)

    async def tell_requester(self, text: str) -> None:
        self.requester_acks.append(text)


class _FixedClock:
    def now(self) -> datetime:
        return _AT


class _RecordingAuthorize:
    """Durable-authorize hook (.3 wires the real Authorizer); records requesters."""

    def __init__(self) -> None:
        self.authorized: list[int] = []

    async def __call__(self, requester_id: int) -> None:
        self.authorized.append(requester_id)


class _RecordingExecutor:
    """Records the (request, decision) the flow handed to the executor (.3)."""

    def __init__(self) -> None:
        self.executed: list[tuple[PermissionRequest, object]] = []

    async def execute(
        self, request: PermissionRequest, decision: object
    ) -> None:
        self.executed.append((request, decision))


def _flow(
    *,
    need: PrivilegeNeed,
    store: _FakeStore | None = None,
    notifier: _FakeNotifier | None = None,
    on_authorize: _RecordingAuthorize | None = None,
    executor: PermissionExecutorLike | None = None,
) -> tuple[PermissionFlow, _FakeStore, _FakeNotifier]:
    used_store = store if store is not None else _FakeStore()
    used_notifier = notifier if notifier is not None else _FakeNotifier()
    flow = PermissionFlow(
        judge=_FakeJudge(need=need),
        store=used_store,
        notifier=used_notifier,
        clock=_FixedClock(),
        owner_name="Вова",
        id_factory=_ids(),
        capability_hints=("render_diagram",),
        on_authorize=on_authorize,
        executor=executor,
    )
    return flow, used_store, used_notifier


def _ids() -> Callable[[], str]:
    counter = {"n": 0}

    def make() -> str:
        counter["n"] += 1
        return f"req-{counter['n']}"

    return make


_PRIVILEGED = PrivilegeNeed(needs_permission=True, kind="tool", what="показать задачи")
_NOT_PRIVILEGED = PrivilegeNeed(needs_permission=False, kind="", what="")


# --- detection (maybe_request) -------------------------------------------------


async def test_non_authorized_privileged_request_pends_notifies_and_consumes() -> None:
    flow, store, notifier = _flow(need=_PRIVILEGED)

    consumed = await flow.maybe_request(
        text="покажи задачи проекта",
        requester_id=_GUEST,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )

    assert consumed is True
    pending = await store.active_for(_GUEST)
    assert len(pending) == 1
    request = pending[0]
    assert request.state is PermissionState.PENDING
    assert request.requester_id == _GUEST
    assert request.requester_name == "Норман"
    assert request.request_text == "покажи задачи проекта"
    assert request.kind == "tool"
    assert request.what == "показать задачи"
    assert request.created_at == _AT
    # The owner is notified in Bob's voice, the requester gets the light ack.
    assert len(notifier.owner_notices) == 1
    notice = notifier.owner_notices[0]
    assert "Вова" in notice
    assert "Норман" in notice
    assert "показать задачи" in notice
    assert len(notifier.requester_acks) == 1


async def test_non_privileged_request_is_not_consumed_and_pends_nothing() -> None:
    flow, store, notifier = _flow(need=_NOT_PRIVILEGED)

    consumed = await flow.maybe_request(
        text="привет, как дела?",
        requester_id=_GUEST,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )

    assert consumed is False
    assert await store.active_for(_GUEST) == ()
    assert notifier.owner_notices == []
    assert notifier.requester_acks == []


async def test_authorized_member_never_enters_the_flow() -> None:
    flow, store, notifier = _flow(need=_PRIVILEGED)

    consumed = await flow.maybe_request(
        text="покажи задачи проекта",
        requester_id=_GUEST,
        requester_name="Друг",
        is_owner=False,
        is_authorized=True,
    )

    assert consumed is False
    assert await store.active() == ()
    assert notifier.owner_notices == []


async def test_owner_never_enters_the_request_flow() -> None:
    flow, store, _ = _flow(need=_PRIVILEGED)

    consumed = await flow.maybe_request(
        text="покажи задачи проекта",
        requester_id=_OWNER,
        requester_name="Вова",
        is_owner=True,
        is_authorized=True,
    )

    assert consumed is False
    assert await store.active() == ()


async def test_one_active_pending_per_requester_supersedes_the_old() -> None:
    flow, store, _ = _flow(need=_PRIVILEGED)

    await flow.maybe_request(
        text="покажи задачи",
        requester_id=_GUEST,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )
    await flow.maybe_request(
        text="запусти диаграмму",
        requester_id=_GUEST,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )

    pending = await store.active_for(_GUEST)
    assert len(pending) == 1
    assert pending[0].request_text == "запусти диаграмму"
    # The superseded request is EXPIRED, not lingering as a second pending.
    expired = [
        r for r in store.requests.values() if r.state is PermissionState.EXPIRED
    ]
    assert len(expired) == 1
    assert expired[0].request_text == "покажи задачи"


# --- owner decision (maybe_decide) ---------------------------------------------


async def _pending_for(store: _FakeStore, flow: PermissionFlow) -> PermissionRequest:
    await flow.maybe_request(
        text="покажи задачи",
        requester_id=_GUEST,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )
    return (await store.active_for(_GUEST))[0]


async def test_owner_grant_transitions_pending_to_approved() -> None:
    flow, store, _ = _flow(need=_PRIVILEGED)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(text="да", is_owner=True)

    assert consumed is True
    assert store.requests[request.id].state is PermissionState.APPROVED


async def test_owner_deny_transitions_pending_to_denied() -> None:
    flow, store, _ = _flow(need=_PRIVILEGED)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(text="нет", is_owner=True)

    assert consumed is True
    assert store.requests[request.id].state is PermissionState.DENIED


async def test_owner_authorize_approves_and_fires_durable_hook() -> None:
    on_authorize = _RecordingAuthorize()
    flow, store, _ = _flow(need=_PRIVILEGED, on_authorize=on_authorize)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(text="авторизуй его", is_owner=True)

    assert consumed is True
    assert store.requests[request.id].state is PermissionState.APPROVED
    assert on_authorize.authorized == [_GUEST]


async def test_non_owner_da_does_not_approve() -> None:
    flow, store, _ = _flow(need=_PRIVILEGED)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(text="да", is_owner=False)

    assert consumed is False
    assert store.requests[request.id].state is PermissionState.PENDING


async def test_owner_decision_with_no_pending_is_not_consumed() -> None:
    flow, _, _ = _flow(need=_PRIVILEGED)

    consumed = await flow.maybe_decide(text="да", is_owner=True)

    assert consumed is False


async def test_owner_ambiguous_reply_does_not_consume_or_transition() -> None:
    flow, store, _ = _flow(need=_PRIVILEGED)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(
        text="кстати, что там по погоде", is_owner=True
    )

    assert consumed is False
    assert store.requests[request.id].state is PermissionState.PENDING


# --- owner commands ------------------------------------------------------------


async def test_allow_command_is_owner_only_and_approves() -> None:
    flow, store, _ = _flow(need=_PRIVILEGED)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(text="/allow", is_owner=True)

    assert consumed is True
    assert store.requests[request.id].state is PermissionState.APPROVED


async def test_deny_command_is_owner_only_and_denies() -> None:
    flow, store, _ = _flow(need=_PRIVILEGED)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(text="/deny", is_owner=True)

    assert consumed is True
    assert store.requests[request.id].state is PermissionState.DENIED


async def test_authorize_command_approves_and_fires_durable_hook() -> None:
    on_authorize = _RecordingAuthorize()
    flow, store, _ = _flow(need=_PRIVILEGED, on_authorize=on_authorize)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(text="/authorize", is_owner=True)

    assert consumed is True
    assert store.requests[request.id].state is PermissionState.APPROVED
    assert on_authorize.authorized == [_GUEST]


async def test_allow_command_from_non_owner_does_not_approve() -> None:
    flow, store, _ = _flow(need=_PRIVILEGED)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(text="/allow", is_owner=False)

    assert consumed is False
    assert store.requests[request.id].state is PermissionState.PENDING


async def test_decision_targets_the_oldest_pending_across_requesters() -> None:
    flow, store, _ = _flow(need=_PRIVILEGED)
    await flow.maybe_request(
        text="покажи задачи",
        requester_id=_GUEST,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )
    await flow.maybe_request(
        text="запусти диаграмму",
        requester_id=_OTHER_GUEST,
        requester_name="Гость",
        is_owner=False,
        is_authorized=False,
    )

    consumed = await flow.maybe_decide(text="да", is_owner=True)

    assert consumed is True
    norman = (await store.active_for(_GUEST))
    assert norman == ()  # the oldest pending (Норман) was approved
    other = await store.active_for(_OTHER_GUEST)
    assert len(other) == 1  # the newer one stays pending


# --- execution wiring (BOB-052 .3) ---------------------------------------------


async def test_grant_hands_the_approved_request_to_the_executor() -> None:
    executor = _RecordingExecutor()
    flow, store, _ = _flow(need=_PRIVILEGED, executor=executor)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(text="да", is_owner=True)

    assert consumed is True
    # The request was recorded APPROVED and then executed as a GRANT.
    assert store.requests[request.id].state is PermissionState.APPROVED
    assert len(executor.executed) == 1
    executed_request, decision = executor.executed[0]
    assert executed_request.id == request.id
    assert executed_request.request_text == "покажи задачи"
    assert decision is PermissionDecision.GRANT


async def test_deny_hands_the_request_to_the_executor_as_deny() -> None:
    executor = _RecordingExecutor()
    flow, store, _ = _flow(need=_PRIVILEGED, executor=executor)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(text="нет", is_owner=True)

    assert consumed is True
    assert store.requests[request.id].state is PermissionState.DENIED
    assert len(executor.executed) == 1
    _, decision = executor.executed[0]
    assert decision is PermissionDecision.DENY


async def test_authorize_hands_the_request_to_the_executor_as_authorize() -> None:
    executor = _RecordingExecutor()
    flow, store, _ = _flow(need=_PRIVILEGED, executor=executor)
    request = await _pending_for(store, flow)

    consumed = await flow.maybe_decide(text="авторизуй его", is_owner=True)

    assert consumed is True
    assert store.requests[request.id].state is PermissionState.APPROVED
    assert len(executor.executed) == 1
    _, decision = executor.executed[0]
    # The executor owns the durable grant on AUTHORIZE.
    assert decision is PermissionDecision.AUTHORIZE


async def test_executor_takes_precedence_over_the_inert_on_authorize_hook() -> None:
    # When an executor is wired (.3), it owns the durable grant; the legacy .2
    # on_authorize hook is NOT also fired (no double-authorize).
    on_authorize = _RecordingAuthorize()
    executor = _RecordingExecutor()
    flow, store, _ = _flow(
        need=_PRIVILEGED, on_authorize=on_authorize, executor=executor
    )
    await _pending_for(store, flow)

    await flow.maybe_decide(text="авторизуй его", is_owner=True)

    assert on_authorize.authorized == []
    assert len(executor.executed) == 1


async def test_no_executor_keeps_the_legacy_on_authorize_hook() -> None:
    # Backward-compatible (.2): with no executor wired, the legacy durable hook still
    # fires on authorize, so existing constructions behave exactly as before.
    on_authorize = _RecordingAuthorize()
    flow, store, _ = _flow(need=_PRIVILEGED, on_authorize=on_authorize)
    await _pending_for(store, flow)

    await flow.maybe_decide(text="авторизуй его", is_owner=True)

    assert on_authorize.authorized == [_GUEST]


async def test_grant_elevation_does_not_carry_to_the_requesters_next_message() -> None:
    # 🔴 After a GRANT fulfils request A for the requester, a fresh privileged message B
    # from the SAME requester is STILL gated — it re-pends and asks the owner again. The
    # per-request elevation never became a durable allowance.
    class _Fulfiller:
        def __init__(self) -> None:
            self.fulfilled: list[str] = []

        async def fulfil(
            self, request_text: str, *, requester_id: int, requester_name: str
        ) -> str:
            del requester_id, requester_name
            self.fulfilled.append(request_text)
            return "ok"

    class _Channel:
        async def send(self, text: str) -> None:
            del text

    class _Authz:
        def __init__(self) -> None:
            self.granted: list[int] = []

        async def authorize(self, user_id: int) -> None:
            self.granted.append(user_id)

    fulfiller = _Fulfiller()
    authz = _Authz()
    executor = PermissionExecutor(
        fulfiller=fulfiller, channel=_Channel(), authorizer=authz
    )
    store = _FakeStore()
    flow, _, _ = _flow(need=_PRIVILEGED, store=store, executor=executor)

    # Request A → pends; owner grants → A is fulfilled (elevated, once).
    await flow.maybe_request(
        text="покажи задачи",
        requester_id=_GUEST,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )
    await flow.maybe_decide(text="да", is_owner=True)
    assert fulfiller.fulfilled == ["покажи задачи"]

    # A DIFFERENT privileged message B from the same requester is STILL gated: it pends
    # and asks the owner again (NOT auto-fulfilled). No durable grant ever happened.
    consumed_b = await flow.maybe_request(
        text="запусти диаграмму",
        requester_id=_GUEST,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )
    assert consumed_b is True  # pended again, not fulfilled outright
    assert fulfiller.fulfilled == ["покажи задачи"]  # B not fulfilled without approval
    assert authz.granted == []  # never durably authorised
    pending_b = await store.active_for(_GUEST)
    assert len(pending_b) == 1
    assert pending_b[0].request_text == "запусти диаграмму"
