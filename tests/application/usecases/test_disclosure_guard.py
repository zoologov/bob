# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for DisclosureGuard — the warm VOICE of a guest owner_data refusal (BOB-066 W.4).

The application bridge that reuses the permission-flow's
:class:`~bob.social.permission.privilege.PrivilegeJudge` to decide whether a GUEST turn is an
``owner_data`` disclosure request, and — if so — folds the warm
:func:`~bob.personality.voice.tactful_withhold_directive` into compose (the privilege gate
itself is unchanged). These tests pin the gating + the decorative safe-default: a non-guest
is never judged, a non-owner_data need adds no line, and a flaky judge yields ``""``.
"""

from __future__ import annotations

from bob.application.usecases.disclosure_guard import DisclosureGuard
from bob.personality.voice import tactful_withhold_directive
from bob.social.permission.privilege import PrivilegeContext, PrivilegeNeed


class _FakeJudge:
    """Scripted PrivilegeJudge: returns a fixed need and captures the assessed context."""

    def __init__(self, need: PrivilegeNeed) -> None:
        self._need = need
        self.contexts: list[PrivilegeContext] = []

    async def assess(self, ctx: PrivilegeContext) -> PrivilegeNeed:
        self.contexts.append(ctx)
        return self._need


class _RaisingJudge:
    """A judge that always fails — the guard must swallow it (safe-default refuse)."""

    async def assess(self, ctx: PrivilegeContext) -> PrivilegeNeed:  # noqa: ARG002
        raise RuntimeError("boom")


_OWNER_DATA = PrivilegeNeed(needs_permission=True, kind="owner_data", what="адрес владельца")
_TOOL = PrivilegeNeed(needs_permission=True, kind="tool", what="запустить поиск")
_NOT_PRIVILEGED = PrivilegeNeed(needs_permission=False, kind="", what="")


async def test_guest_owner_data_request_gets_the_tactful_withhold_line() -> None:
    guard = DisclosureGuard(judge=_FakeJudge(_OWNER_DATA))

    directive = await guard.withhold_directive(
        text="какой адрес у Вовы?", is_guest=True
    )

    assert directive == tactful_withhold_directive()


async def test_a_non_owner_data_privileged_request_adds_no_line() -> None:
    # A tool request is the permission flow's concern, not the tactful withhold voice.
    guard = DisclosureGuard(judge=_FakeJudge(_TOOL))
    assert await guard.withhold_directive(text="запусти поиск", is_guest=True) == ""


async def test_a_non_privileged_guest_turn_adds_no_line() -> None:
    guard = DisclosureGuard(judge=_FakeJudge(_NOT_PRIVILEGED))
    assert await guard.withhold_directive(text="как дела?", is_guest=True) == ""


async def test_a_non_guest_turn_is_never_judged() -> None:
    judge = _FakeJudge(_OWNER_DATA)
    guard = DisclosureGuard(judge=judge)

    directive = await guard.withhold_directive(
        text="какой адрес у Вовы?", is_guest=False
    )

    assert directive == ""
    assert judge.contexts == []  # the judge is not even consulted off a guest turn


async def test_a_flaky_judge_is_swallowed_and_refuses_by_default() -> None:
    guard = DisclosureGuard(judge=_RaisingJudge())
    assert await guard.withhold_directive(text="адрес владельца?", is_guest=True) == ""


async def test_capability_hints_and_thread_reach_the_judge() -> None:
    judge = _FakeJudge(_OWNER_DATA)
    guard = DisclosureGuard(judge=judge, capability_hints=("web_search",))

    await guard.withhold_directive(
        text="покажи заметки Вовы", is_guest=True, recent_thread="Норман: привет"
    )

    assert judge.contexts[0].capability_hints == ("web_search",)
    assert judge.contexts[0].recent_thread == "Норман: привет"
