# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for LlmPrivilegeJudge — the Tier-0 realisation of the seam (BOB-052 .1).

The judge builds a Tier-0 ``LLMRequest`` from the pure prompt builder, runs it on
the local provider, and parses the reply into a ``PrivilegeNeed``. On a parse
failure or a model/router error it RAISES (no silent default) — the caller in .3
drops the add-on decoratively with a safe default (= refuse).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.domain.permission.privilege import (
    PrivilegeContext,
    PrivilegeJudgeParseError,
)
from bob.infrastructure.llm.privilege_judge import LlmPrivilegeJudge

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class _FakeProvider:
    """Tier-0 provider returning a fixed reply and recording the messages."""

    def __init__(self, reply: str, *, raises: bool = False) -> None:
        self._reply = reply
        self._raises = raises
        self.messages: Sequence[Mapping[str, str]] | None = None

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.messages = messages
        if self._raises:
            raise RuntimeError("local model down")
        return self._reply


def _context() -> PrivilegeContext:
    return PrivilegeContext(
        request_text="покажи задачи проекта",
        capability_hints=("show_tasks",),
        recent_thread="Норман: эй\nbob: да",
    )


def _judge(reply: str, *, raises: bool = False) -> tuple[LlmPrivilegeJudge, _FakeProvider]:
    provider = _FakeProvider(reply, raises=raises)
    router = LLMRouter(providers={0: provider})
    return LlmPrivilegeJudge(router=router), provider


async def test_builds_tier0_request_and_parses_reply() -> None:
    judge, provider = _judge(
        "needs_permission: yes\nkind: owner_data\nwhat: показать задачи"
    )

    need = await judge.assess(_context())

    assert need.needs_permission is True
    assert need.kind == "owner_data"
    assert provider.messages is not None
    user_contents = " ".join(m["content"] for m in provider.messages)
    assert "покажи задачи проекта" in user_contents
    assert "show_tasks" in user_contents


async def test_uses_the_local_privilege_judge_task() -> None:
    # PRIVILEGE_JUDGE is pinned Tier-0: a Tier-0-only router proves it never needs
    # a Tier 1 provider.
    judge, _ = _judge("needs_permission: no\nkind: \nwhat: ")
    assert (await judge.assess(_context())).needs_permission is False
    assert TaskType.PRIVILEGE_JUDGE.value == "privilege_judge"


async def test_raises_on_unparseable_reply() -> None:
    judge, _ = _judge("я не знаю")
    with pytest.raises(PrivilegeJudgeParseError):
        await judge.assess(_context())


async def test_raises_on_model_error() -> None:
    judge, _ = _judge("needs_permission: no", raises=True)
    with pytest.raises(RuntimeError):
        await judge.assess(_context())
