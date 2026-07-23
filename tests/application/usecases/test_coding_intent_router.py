# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for CodingIntentRouter — NL routing into the gated session (BOB-041 .2).

The router decides WHEN to call the gated CodingAssistant from a natural-language
owner message in Bob's topic; it can NEVER bypass a gate (it only ever calls
``start`` / ``approve_plan`` / ``stop``, each owner-checked + gated in the use-case
and domain). The security invariants asserted here:

* owner-only — a non-owner message never touches the assistant;
* no active session → a coding-intent message PLANS (``start``), chat does nothing;
* an active PLAN_READY session → an approval calls ``approve_plan``, a stop ``stop``,
  an ambiguous message does NOTHING (never an accidental approve);
* a misclassified chat at worst PLANS — there is no NL path to EXECUTING except an
  explicit approval from PLAN_READY.
"""

from __future__ import annotations

from bob.coding.state import CodingSessionState
from bob.coding.usecases.coding_intent_router import CodingIntentRouter

_OWNER = 99
_GUEST = 7


class _FakeCoder:
    """Records every gated call; ``state`` drives the active-session query."""

    def __init__(self, *, state: CodingSessionState | None = None) -> None:
        self._state = state
        self.started: list[tuple[str, int | None]] = []
        self.approved: list[int | None] = []
        self.stopped: list[int | None] = []

    async def active_state(self) -> CodingSessionState | None:
        return self._state

    async def start(self, task: str, sender: int | None) -> object:
        self.started.append((task, sender))
        return None

    async def approve_plan(self, sender: int | None) -> object:
        self.approved.append(sender)
        return None

    async def stop(self, sender: int | None) -> object:
        self.stopped.append(sender)
        return None


class _FakeClassifier:
    """A deterministic coding/chat classifier (records the texts it saw)."""

    def __init__(self, *, coding: bool) -> None:
        self._coding = coding
        self.seen: list[str] = []

    async def is_coding_request(self, text: str) -> bool:
        self.seen.append(text)
        return self._coding


def _router(coder: _FakeCoder, *, coding: bool) -> CodingIntentRouter:
    return CodingIntentRouter(coder=coder, classifier=_FakeClassifier(coding=coding))


# --- intent → start --------------------------------------------------------------


async def test_owner_dev_task_starts_a_gated_session() -> None:
    coder = _FakeCoder(state=None)
    router = _router(coder, coding=True)

    consumed = await router.route(text="создай файл X", sender=_OWNER, is_owner=True)

    assert consumed is True
    assert coder.started == [("создай файл X", _OWNER)]
    assert coder.approved == []
    assert coder.stopped == []


async def test_owner_chat_does_not_start_a_session() -> None:
    coder = _FakeCoder(state=None)
    router = _router(coder, coding=False)

    consumed = await router.route(text="как настроение?", sender=_OWNER, is_owner=True)

    assert consumed is False
    assert coder.started == []


# --- owner-only (authz) ----------------------------------------------------------


async def test_guest_dev_task_never_touches_the_assistant() -> None:
    coder = _FakeCoder(state=None)
    router = _router(coder, coding=True)

    consumed = await router.route(text="создай файл X", sender=_GUEST, is_owner=False)

    assert consumed is False
    assert coder.started == []
    assert coder.approved == []
    assert coder.stopped == []


# --- natural approve / stop on an active PLAN_READY session -----------------------


async def test_owner_approval_on_plan_ready_approves() -> None:
    coder = _FakeCoder(state=CodingSessionState.PLAN_READY)
    router = _router(coder, coding=False)

    consumed = await router.route(text="давай", sender=_OWNER, is_owner=True)

    assert consumed is True
    assert coder.approved == [_OWNER]
    assert coder.started == []  # no new session — the pending plan is approved


async def test_owner_stop_on_plan_ready_stops() -> None:
    coder = _FakeCoder(state=CodingSessionState.PLAN_READY)
    router = _router(coder, coding=False)

    consumed = await router.route(text="стоп", sender=_OWNER, is_owner=True)

    assert consumed is True
    assert coder.stopped == [_OWNER]


async def test_ambiguous_message_on_plan_ready_is_treated_as_chat() -> None:
    # Conservative: an ambiguous reply while a plan waits must NOT approve — it falls
    # through to normal chat (not consumed), so Bob never accidentally executes.
    coder = _FakeCoder(state=CodingSessionState.PLAN_READY)
    router = _router(coder, coding=True)

    consumed = await router.route(
        text="а что там по тестам?", sender=_OWNER, is_owner=True
    )

    assert consumed is False
    assert coder.approved == []
    assert coder.started == []
    assert coder.stopped == []


async def test_stop_works_while_a_session_is_executing() -> None:
    # The kill-switch is valid from any live state; an approval is NOT (only PLAN_READY).
    coder = _FakeCoder(state=CodingSessionState.EXECUTING)
    router = _router(coder, coding=False)

    assert await router.route(text="стоп", sender=_OWNER, is_owner=True) is True
    assert coder.stopped == [_OWNER]


async def test_approval_while_executing_does_not_approve() -> None:
    # No NL path to EXECUTING via approve except from PLAN_READY: an "approval" word
    # while already executing approves nothing (the plan gate is structural).
    coder = _FakeCoder(state=CodingSessionState.EXECUTING)
    router = _router(coder, coding=True)

    consumed = await router.route(text="давай", sender=_OWNER, is_owner=True)

    assert consumed is False
    assert coder.approved == []
    assert coder.started == []


async def test_classifier_not_consulted_while_a_session_is_active() -> None:
    # With a live session the router handles approve/stop only; it never tries to start
    # a second session, so the classifier is not even consulted on a non-command word.
    coder = _FakeCoder(state=CodingSessionState.PLAN_READY)
    classifier = _FakeClassifier(coding=True)
    router = CodingIntentRouter(coder=coder, classifier=classifier)

    await router.route(text="расскажи про космос", sender=_OWNER, is_owner=True)

    assert classifier.seen == []
    assert coder.started == []
