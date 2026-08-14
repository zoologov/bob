# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Acceptance + guardrail tests for the permission flow (BOB-052 PRD US-1..6).

End-to-end over the WHOLE BOB-052 application stack wired together with deterministic
fakes only (no LLM / Telegram): the real :class:`PermissionFlow` (.2) drives the real
:class:`PermissionExecutor` (.3) over the real :class:`PrivilegedRequestFulfiller` (.3),
with fakes ONLY at the boundaries — judge, store, notifier, clock, requester-channel,
durable authorizer, plain router. This proves the user stories as black-box behaviour
and locks the 🔴 SECURITY invariants:

* **US-1** non-authorized privileged request → owner asked, requester acked, turn
  consumed, NOTHING fulfilled/disclosed (Bob does not silently do it);
* **US-2** owner «да» → the stored request is fulfilled ONCE for the requester + sent;
* **US-3** owner «нет» → gentle decline, nothing run/disclosed;
* **US-4** an authorized (allowlisted) member's same request → the flow is NOT entered
  (judge never consulted, no pending);
* **US-5** owner «авторизуй Нормана» → durable :meth:`Authorizer.authorize` + the current
  request fulfilled, and a subsequent authorized turn takes the no-ask path;
* **🔴 US-6** ONLY the owner decides (a non-owner «да»/`/allow` approves nobody, not even
  themselves); per-request elevation never carries to the requester's NEXT message;
  privileged info is never disclosed without an owner approve; ANY failure → the safe
  default is REFUSE (dropped silently, no GUPPI notice, no raise).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.usecases.privileged_fulfiller import PrivilegedRequestFulfiller
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.social.permission.privilege import PrivilegeContext, PrivilegeNeed
from bob.social.permission.state import PermissionState
from bob.social.usecases.permission_execution import PermissionExecutor
from bob.social.usecases.permission_flow import PermissionFlow

if TYPE_CHECKING:
    from collections.abc import Callable

    from bob.application.router.llm_router import LLMRequest
    from bob.social.permission.entities import PermissionRequest

_OWNER = 1
_NORMAN = 7
_OTHER = 8
_AT = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

_PRIVILEGED = PrivilegeNeed(needs_permission=True, kind="tool", what="показать задачи")
_NOT_PRIVILEGED = PrivilegeNeed(needs_permission=False, kind="", what="")


# --- boundary fakes ------------------------------------------------------------


class _FakeJudge:
    """Scripted privilege judge; records every context it was asked to assess."""

    def __init__(self, *, need: PrivilegeNeed) -> None:
        self._need = need
        self.seen: list[PrivilegeContext] = []

    async def assess(self, ctx: PrivilegeContext) -> PrivilegeNeed:
        self.seen.append(ctx)
        return self._need


class _FakeStore:
    """In-memory permission-request store (the .1 persistence surface)."""

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
    """Records the owner notices + requester acks the flow emits."""

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


class _FakeRouter:
    """Plain-reply router the fulfiller falls back to (no tools wired)."""

    def __init__(self, *, reply: str = "Вот задачи: A, B, C") -> None:
        self._reply = reply
        self.requests: list[LLMRequest] = []

    async def run(self, request: LLMRequest) -> str:
        self.requests.append(request)
        return self._reply


class _FakeChannel:
    """Records (or fails) what Bob sends back to the requester."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        if self._fail:
            msg = "channel boom"
            raise RuntimeError(msg)
        self.sent.append(text)


class _FakeAuthorizer:
    """Durable allowlist grant (the real Authorizer seam); records grants."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.granted: list[int] = []

    async def authorize(self, user_id: int) -> None:
        if self._fail:
            msg = "authorize boom"
            raise RuntimeError(msg)
        self.granted.append(user_id)


def _ids() -> Callable[[], str]:
    counter = {"n": 0}

    def make() -> str:
        counter["n"] += 1
        return f"req-{counter['n']}"

    return make


def _stack(
    *,
    need: PrivilegeNeed = _PRIVILEGED,
    router: _FakeRouter | None = None,
    channel: _FakeChannel | None = None,
    authorizer: _FakeAuthorizer | None = None,
) -> tuple[PermissionFlow, _FakeStore, _FakeNotifier, _FakeRouter, _FakeChannel, _FakeAuthorizer]:
    """Wire the real flow → real executor → real fulfiller, fakes at the edges."""
    store = _FakeStore()
    notifier = _FakeNotifier()
    used_router = router if router is not None else _FakeRouter()
    used_channel = channel if channel is not None else _FakeChannel()
    used_authorizer = authorizer if authorizer is not None else _FakeAuthorizer()
    fulfiller = PrivilegedRequestFulfiller(
        router=used_router,
        registry=CapabilityRegistry(),
        tool_provider=None,
        voice_canon=None,
    )
    executor = PermissionExecutor(
        fulfiller=fulfiller, channel=used_channel, authorizer=used_authorizer
    )
    flow = PermissionFlow(
        judge=_FakeJudge(need=need),
        store=store,
        notifier=notifier,
        clock=_FixedClock(),
        owner_name="Вова",
        id_factory=_ids(),
        executor=executor,
    )
    return flow, store, notifier, used_router, used_channel, used_authorizer


async def _pend_norman(
    flow: PermissionFlow, *, text: str = "покажи задачи проекта"
) -> None:
    """Norman (non-authorized) makes a privileged request that pends."""
    await flow.maybe_request(
        text=text,
        requester_id=_NORMAN,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )


# --- US-1: detect → ask the owner ---------------------------------------------


async def test_us1_non_authorized_privileged_request_asks_owner_and_does_not_fulfil() -> None:
    # Arrange
    flow, store, notifier, router, channel, authz = _stack()

    # Act
    consumed = await flow.maybe_request(
        text="покажи задачи проекта",
        requester_id=_NORMAN,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )

    # Assert — pended + owner asked + requester acked + turn consumed
    assert consumed is True
    pending = await store.active_for(_NORMAN)
    assert len(pending) == 1
    assert pending[0].state is PermissionState.PENDING
    assert len(notifier.owner_notices) == 1
    assert "Норман" in notifier.owner_notices[0]
    # 🔴 BOB-090.E: owner слышит слова САМОГО просителя, а не пометку судьи — она
    # остаётся внутренней (именно её английский вариант и утекал в живую реплику).
    assert "«покажи задачи проекта»" in notifier.owner_notices[0]
    assert _PRIVILEGED.what not in notifier.owner_notices[0]
    assert len(notifier.requester_acks) == 1
    # 🔴 Bob did NOT silently fulfil: nothing was run or disclosed to the requester.
    assert router.requests == []
    assert channel.sent == []
    assert authz.granted == []


# --- US-2: approve → fulfil once ----------------------------------------------


async def test_us2_owner_approve_fulfils_the_stored_request_once_and_sends_result() -> None:
    # Arrange
    flow, store, _, router, channel, authz = _stack()
    await _pend_norman(flow, text="покажи задачи проекта")

    # Act
    consumed = await flow.maybe_decide(text="да", is_owner=True)

    # Assert — fulfilled exactly once over the STORED text, result sent, no durable grant
    assert consumed is True
    assert len(router.requests) == 1
    assert "покажи задачи проекта" in router.requests[0].messages[-1]["content"]
    assert channel.sent == ["Вот задачи: A, B, C"]
    assert authz.granted == []
    pending = await store.active_for(_NORMAN)
    assert pending == ()  # no longer pending — terminal APPROVED


# --- US-3: deny → gentle decline ----------------------------------------------


async def test_us3_owner_deny_sends_gentle_decline_and_runs_nothing() -> None:
    # Arrange
    flow, store, _, router, channel, authz = _stack()
    request_id = await _request_id(flow, store)

    # Act
    consumed = await flow.maybe_decide(text="нет", is_owner=True)

    # Assert — soft decline only; nothing fulfilled / disclosed / granted
    assert consumed is True
    assert router.requests == []
    assert authz.granted == []
    assert len(channel.sent) == 1
    assert "Вову" in channel.sent[0]
    assert store.requests[request_id].state is PermissionState.DENIED


# --- US-4: authorized member → no asking --------------------------------------


async def test_us4_authorized_member_never_enters_the_flow() -> None:
    # Arrange
    judge = _FakeJudge(need=_PRIVILEGED)
    store = _FakeStore()
    flow = PermissionFlow(
        judge=judge,
        store=store,
        notifier=_FakeNotifier(),
        clock=_FixedClock(),
        id_factory=_ids(),
    )

    # Act — an allowlisted member asks the SAME privileged thing
    consumed = await flow.maybe_request(
        text="покажи задачи проекта",
        requester_id=_NORMAN,
        requester_name="Друг",
        is_owner=False,
        is_authorized=True,
    )

    # Assert — flow not entered: judge never consulted, no pending created
    assert consumed is False
    assert judge.seen == []
    assert await store.active() == ()


# --- US-5: durable authorize --------------------------------------------------


async def test_us5_owner_authorize_grants_durably_fulfils_and_next_turn_is_authorized() -> None:
    # Arrange
    flow, store, _, router, channel, authz = _stack()
    await _pend_norman(flow, text="покажи задачи проекта")

    # Act — owner authorises Norman durably
    consumed = await flow.maybe_decide(text="авторизуй Нормана", is_owner=True)

    # Assert — durable grant fired AND the current request was fulfilled + sent
    assert consumed is True
    assert authz.granted == [_NORMAN]
    assert len(router.requests) == 1
    assert channel.sent == ["Вот задачи: A, B, C"]

    # And a subsequent turn from the now-authorized Norman takes the no-ask path.
    consumed_next = await flow.maybe_request(
        text="покажи задачи снова",
        requester_id=_NORMAN,
        requester_name="Норман",
        is_owner=False,
        is_authorized=True,  # now allowlisted by the durable grant above
    )
    assert consumed_next is False
    assert await store.active_for(_NORMAN) == ()


# --- 🔴 US-6: security invariants ---------------------------------------------


async def test_us6_non_owner_da_approves_nobody() -> None:
    # 🔴 ONLY the owner decides — a non-owner «да» never approves a pending (not even
    # the requester approving their own request).
    flow, store, _, router, channel, _ = _stack()
    request_id = await _request_id(flow, store)

    consumed = await flow.maybe_decide(text="да", is_owner=False)

    assert consumed is False
    assert store.requests[request_id].state is PermissionState.PENDING
    assert router.requests == []
    assert channel.sent == []


async def test_us6_non_owner_allow_command_approves_nobody() -> None:
    # 🔴 The explicit /allow command is owner-only too.
    flow, store, _, router, channel, _ = _stack()
    request_id = await _request_id(flow, store)

    consumed = await flow.maybe_decide(text="/allow", is_owner=False)

    assert consumed is False
    assert store.requests[request_id].state is PermissionState.PENDING
    assert router.requests == []
    assert channel.sent == []


async def test_us6_per_request_elevation_does_not_carry_to_the_next_message() -> None:
    # 🔴 After a GRANT fulfils message A, a DIFFERENT privileged message B from the same
    # requester is STILL gated — the elevation never became durable.
    flow, store, _, router, _, authz = _stack()
    await _pend_norman(flow, text="покажи задачи")
    await flow.maybe_decide(text="да", is_owner=True)
    assert len(router.requests) == 1  # A fulfilled once

    consumed_b = await flow.maybe_request(
        text="запусти диаграмму",
        requester_id=_NORMAN,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )

    assert consumed_b is True  # B re-pends, asks the owner again
    assert len(router.requests) == 1  # B was NOT fulfilled without an approve
    assert authz.granted == []  # never durably authorised
    pending_b = await store.active_for(_NORMAN)
    assert len(pending_b) == 1
    assert pending_b[0].request_text == "запусти диаграмму"


async def test_us6_pending_request_discloses_nothing_before_an_approve() -> None:
    # 🔴 Privileged info is never disclosed to a non-authorized member WITHOUT an owner
    # approve: a still-pending request fulfils / sends nothing.
    flow, _, _, router, channel, authz = _stack()
    await _pend_norman(flow)

    assert router.requests == []
    assert channel.sent == []
    assert authz.granted == []


async def test_us6_ambiguous_owner_reply_never_accidentally_approves() -> None:
    # 🔴 An ambiguous owner reply is left to chat — never an accidental grant/disclosure.
    flow, store, _, router, channel, _ = _stack()
    request_id = await _request_id(flow, store)

    consumed = await flow.maybe_decide(text="кстати, что по погоде", is_owner=True)

    assert consumed is False
    assert store.requests[request_id].state is PermissionState.PENDING
    assert router.requests == []
    assert channel.sent == []


async def test_us6_fulfiller_failure_refuses_silently_and_discloses_nothing() -> None:
    # 🔴 Safe default on failure = REFUSE: a fulfiller/router blow-up is dropped silently
    # (no raise, no disclosure) — the decision is still recorded, the chat is unaffected.
    class _BoomRouter:
        async def run(self, request: object) -> str:
            del request
            msg = "router boom"
            raise RuntimeError(msg)

    store = _FakeStore()
    channel = _FakeChannel()
    fulfiller = PrivilegedRequestFulfiller(
        router=_BoomRouter(),
        registry=CapabilityRegistry(),
        tool_provider=None,
        voice_canon=None,
    )
    executor = PermissionExecutor(
        fulfiller=fulfiller, channel=channel, authorizer=_FakeAuthorizer()
    )
    flow = PermissionFlow(
        judge=_FakeJudge(need=_PRIVILEGED),
        store=store,
        notifier=_FakeNotifier(),
        clock=_FixedClock(),
        id_factory=_ids(),
        executor=executor,
    )
    await _pend_norman(flow)

    consumed = await flow.maybe_decide(text="да", is_owner=True)

    assert consumed is True  # the decision was still recorded (does not raise)
    assert channel.sent == []  # 🔴 nothing disclosed on failure


async def test_us6_authorize_failure_refuses_silently_and_fulfils_nothing() -> None:
    # 🔴 A failed durable grant refuses the whole thing — no fulfilment, no disclosure.
    authz = _FakeAuthorizer(fail=True)
    flow, _, _, router, channel, _ = _stack(authorizer=authz)
    await _pend_norman(flow)

    consumed = await flow.maybe_decide(text="авторизуй Нормана", is_owner=True)

    assert consumed is True
    assert router.requests == []  # not fulfilled
    assert channel.sent == []  # not disclosed


async def test_us6_channel_failure_is_dropped_silently() -> None:
    # 🔴 Even a failing requester-channel must not raise out of execution.
    channel = _FakeChannel(fail=True)
    flow, _, _, _, _, _ = _stack(channel=channel)
    await _pend_norman(flow)

    consumed = await flow.maybe_decide(text="да", is_owner=True)

    assert consumed is True  # decorative: the chat path is never broken


async def test_us6_non_privileged_request_leaves_the_turn_to_normal_chat() -> None:
    # A non-privileged request from a non-authorized member is NOT consumed — normal chat
    # handles it unchanged (the gate is for privileges only).
    flow, store, notifier, router, channel, _ = _stack(need=_NOT_PRIVILEGED)

    consumed = await flow.maybe_request(
        text="привет, как дела?",
        requester_id=_NORMAN,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )

    assert consumed is False
    assert await store.active() == ()
    assert notifier.owner_notices == []
    assert router.requests == []
    assert channel.sent == []


# --- guardrails: the durable-hook seam + default id factory (.2 paths) ---------


async def test_authorize_without_executor_or_hook_still_approves_and_does_not_raise() -> None:
    # The inert .2 seam: with NO executor AND no on_authorize hook wired, an «авторизуй»
    # still records APPROVED and never raises (the durable hook is a no-op).
    store = _FakeStore()
    flow = PermissionFlow(
        judge=_FakeJudge(need=_PRIVILEGED),
        store=store,
        notifier=_FakeNotifier(),
        clock=_FixedClock(),
        id_factory=_ids(),
    )
    request_id = await _request_id(flow, store)

    consumed = await flow.maybe_decide(text="авторизуй Нормана", is_owner=True)

    assert consumed is True
    assert store.requests[request_id].state is PermissionState.APPROVED


async def test_durable_authorize_hook_failure_is_swallowed_decision_stands() -> None:
    # 🔴 A flaky durable-authorize hook (the legacy .2 seam) can never break the
    # already-recorded decision: its failure is logged and swallowed, state stays APPROVED.
    async def _boom(requester_id: int) -> None:
        del requester_id
        msg = "hook boom"
        raise RuntimeError(msg)

    store = _FakeStore()
    flow = PermissionFlow(
        judge=_FakeJudge(need=_PRIVILEGED),
        store=store,
        notifier=_FakeNotifier(),
        clock=_FixedClock(),
        id_factory=_ids(),
        on_authorize=_boom,
    )
    request_id = await _request_id(flow, store)

    consumed = await flow.maybe_decide(text="авторизуй Нормана", is_owner=True)

    assert consumed is True
    assert store.requests[request_id].state is PermissionState.APPROVED


async def test_default_id_factory_produces_unique_non_empty_ids() -> None:
    # With no id_factory injected, the flow's default uuid factory assigns each pending
    # request a fresh, non-empty id.
    store = _FakeStore()
    flow = PermissionFlow(
        judge=_FakeJudge(need=_PRIVILEGED),
        store=store,
        notifier=_FakeNotifier(),
        clock=_FixedClock(),
    )
    await _pend_norman(flow, text="покажи задачи")
    await flow.maybe_request(
        text="запусти диаграмму",
        requester_id=_OTHER,
        requester_name="Гость",
        is_owner=False,
        is_authorized=False,
    )

    ids = {r.id for r in store.requests.values()}
    assert len(ids) == 2  # unique
    assert all(rid for rid in ids)  # non-empty


async def _request_id(flow: PermissionFlow, store: _FakeStore) -> str:
    """Pend a Norman request and return its id (helper for decision tests)."""
    await _pend_norman(flow)
    return (await store.active_for(_NORMAN))[0].id
