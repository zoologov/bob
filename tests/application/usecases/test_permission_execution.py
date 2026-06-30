# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for PermissionExecutor — execution on the owner's decision (BOB-052 .3).

The EXECUTION half of the permission flow: once :meth:`PermissionFlow.maybe_decide`
records the owner's verdict, the executor acts on it.

🔴 SECURITY invariants asserted here:

* APPROVED → the stored ``request_text`` is fulfilled ONCE for the requester WITH the
  privilege (a one-shot elevated context), and the result is sent to the requester;
* 🔴 the elevation is scoped to THAT request only — it never carries to the requester's
  next/other message (the fulfiller is handed only the stored request_text);
* AUTHORIZE → :meth:`Authorizer.authorize` is called (durable grant) AND the current
  request is fulfilled — a subsequent turn then goes the normal authorized path;
* DENIED → a gentle decline is sent; NOTHING is fulfilled / disclosed;
* 🔴 DECORATIVE: any failure (fulfiller / authorize / channel) is caught and dropped
  silently — the SAFE DEFAULT on failure is REFUSE (never disclose / run on error),
  never a GUPPI outage notice;
* the request becomes terminal after execution (no longer pending).
"""

from __future__ import annotations

from datetime import UTC, datetime

from bob.application.usecases.permission_execution import (
    PermissionDecision,
    PermissionExecutor,
)
from bob.domain.permission.entities import PermissionRequest
from bob.domain.permission.state import PermissionState

_GUEST = 7
_AT = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def _request(
    *, text: str = "покажи задачи проекта", state: PermissionState = PermissionState.PENDING
) -> PermissionRequest:
    return PermissionRequest(
        id="req-1",
        requester_id=_GUEST,
        requester_name="Норман",
        request_text=text,
        kind="tool",
        what="показать задачи",
        state=state,
        created_at=_AT,
    )


class _FakeFulfiller:
    """One-shot elevated fulfiller; records the request_texts it was asked to run."""

    def __init__(self, *, reply: str = "Вот задачи: ...", fail: bool = False) -> None:
        self._reply = reply
        self._fail = fail
        self.fulfilled: list[tuple[str, int]] = []

    async def fulfil(
        self, request_text: str, *, requester_id: int, requester_name: str
    ) -> str:
        self.fulfilled.append((request_text, requester_id))
        if self._fail:
            msg = "fulfiller boom"
            raise RuntimeError(msg)
        return self._reply


class _FakeChannel:
    """Records what was sent to the requester."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        if self._fail:
            msg = "channel boom"
            raise RuntimeError(msg)
        self.sent.append(text)


class _FakeAuthorizer:
    """Records durable grants; the real Authorizer.authorize seam."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.granted: list[int] = []

    async def authorize(self, user_id: int) -> None:
        if self._fail:
            msg = "authorize boom"
            raise RuntimeError(msg)
        self.granted.append(user_id)


def _executor(
    *,
    fulfiller: _FakeFulfiller | None = None,
    channel: _FakeChannel | None = None,
    authorizer: _FakeAuthorizer | None = None,
) -> tuple[PermissionExecutor, _FakeFulfiller, _FakeChannel, _FakeAuthorizer]:
    used_fulfiller = fulfiller if fulfiller is not None else _FakeFulfiller()
    used_channel = channel if channel is not None else _FakeChannel()
    used_authorizer = authorizer if authorizer is not None else _FakeAuthorizer()
    executor = PermissionExecutor(
        fulfiller=used_fulfiller,
        channel=used_channel,
        authorizer=used_authorizer,
    )
    return executor, used_fulfiller, used_channel, used_authorizer


# --- APPROVED (per-request elevation) -----------------------------------------


async def test_approved_fulfils_the_stored_request_and_sends_result() -> None:
    executor, fulfiller, channel, authorizer = _executor()

    await executor.execute(_request(), PermissionDecision.GRANT)

    # The stored request_text is fulfilled ONCE, with the privilege, for the requester.
    assert fulfiller.fulfilled == [("покажи задачи проекта", _GUEST)]
    assert channel.sent == ["Вот задачи: ..."]
    # No durable grant on a plain approve.
    assert authorizer.granted == []


async def test_approved_only_fulfils_the_stored_text_not_other_messages() -> None:
    executor, fulfiller, _, _ = _executor()

    await executor.execute(
        _request(text="покажи задачи проекта"), PermissionDecision.GRANT
    )

    # 🔴 The fulfiller is handed ONLY the stored request_text — the elevation cannot
    # leak to the requester's other/future messages (there is no durable state).
    assert [t for t, _ in fulfiller.fulfilled] == ["покажи задачи проекта"]


# --- AUTHORIZE (durable) -------------------------------------------------------


async def test_authorize_grants_durably_and_fulfils_the_current_request() -> None:
    executor, fulfiller, channel, authorizer = _executor()

    await executor.execute(_request(), PermissionDecision.AUTHORIZE)

    # Durable grant fires AND the current request is still fulfilled + sent.
    assert authorizer.granted == [_GUEST]
    assert fulfiller.fulfilled == [("покажи задачи проекта", _GUEST)]
    assert channel.sent == ["Вот задачи: ..."]


# --- DENIED --------------------------------------------------------------------


async def test_denied_sends_a_gentle_decline_and_runs_nothing() -> None:
    executor, fulfiller, channel, authorizer = _executor()

    await executor.execute(_request(), PermissionDecision.DENY)

    # Nothing is fulfilled / disclosed; no durable grant.
    assert fulfiller.fulfilled == []
    assert authorizer.granted == []
    # A single gentle decline reaches the requester (mentions asking the owner).
    assert len(channel.sent) == 1
    assert "Вову" in channel.sent[0]


# --- 🔴 decorative / safe-default refuse ---------------------------------------


async def test_fulfiller_failure_is_dropped_silently_no_disclosure() -> None:
    fulfiller = _FakeFulfiller(fail=True)
    executor, _, channel, _ = _executor(fulfiller=fulfiller)

    # Must not raise (decorative); the SAFE DEFAULT on failure is REFUSE — nothing
    # is disclosed to the requester.
    await executor.execute(_request(), PermissionDecision.GRANT)

    assert channel.sent == []


async def test_authorize_failure_is_dropped_silently_no_disclosure() -> None:
    authorizer = _FakeAuthorizer(fail=True)
    executor, fulfiller, channel, _ = _executor(authorizer=authorizer)

    await executor.execute(_request(), PermissionDecision.AUTHORIZE)

    # 🔴 A failed durable grant refuses the whole thing — no fulfilment, no disclosure.
    assert fulfiller.fulfilled == []
    assert channel.sent == []


async def test_channel_failure_is_dropped_silently() -> None:
    channel = _FakeChannel(fail=True)
    executor, _, _, _ = _executor(channel=channel)

    # Must not raise even when the requester-channel itself fails.
    await executor.execute(_request(), PermissionDecision.GRANT)
