# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the anti-repeat self-dup scenario (BOB-078 C).

Binds ``anti_repeat_self_dup.feature`` to :mod:`tests.acceptance.anti_repeat_harness`,
which drives the REAL graph over a poisoned thread: a vivid prior Bob reply is seeded and
oustered past the narrow anti-repeat window by other replies, then the model tries to copy
it verbatim. The scenario asserts Bob's OBSERVABLE sent reply — it differs from the seeded
one (Bob did not repeat himself), witnessed at the fake-gateway boundary, never via the
guard's private state.

The scenario is synchronous (pytest-bdd), so the async graph runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from tests.acceptance.anti_repeat_harness import POISON_REPLY, run_self_dup_turn

if TYPE_CHECKING:
    from pathlib import Path

    from tests.acceptance.fake_gateway import FakeGateway

scenarios("../features/anti_repeat_self_dup.feature")


@dataclass(slots=True)
class _SelfDupContext:
    """The slate the steps share: temp db root + the driven gateway."""

    tmp_path: Path
    gateway: FakeGateway | None = field(default=None)


@pytest.fixture
def self_dup_context(tmp_path: Path) -> _SelfDupContext:
    return _SelfDupContext(tmp_path=tmp_path)


@given("у Боба в ленте есть яркая прошлая реплика, оттеснённая другими ответами")
def poisoned_thread_is_seeded(self_dup_context: _SelfDupContext) -> None:
    """A clean slate — the poisoned thread is seeded inside the harness turn."""
    assert self_dup_context.gateway is None


@when("модель пытается дословно повторить ту же реплику")
def model_tries_to_repeat_verbatim(self_dup_context: _SelfDupContext) -> None:
    self_dup_context.gateway = asyncio.run(run_self_dup_turn(self_dup_context.tmp_path))


def _sent_reply(self_dup_context: _SelfDupContext) -> str:
    assert self_dup_context.gateway is not None
    assert self_dup_context.gateway.sent, "Боб не отправил ни одной реплики"
    return self_dup_context.gateway.sent[-1][1]


@then("Боб отправляет ответ владельцу")
def bob_sent_a_reply(self_dup_context: _SelfDupContext) -> None:
    assert _sent_reply(self_dup_context).strip(), "Боб отправил пустую реплику"


@then("отправленная реплика не совпадает дословно с прошлой")
def sent_reply_is_not_a_verbatim_dup(self_dup_context: _SelfDupContext) -> None:
    sent = _sent_reply(self_dup_context)
    assert sent.strip() != POISON_REPLY.strip(), (
        "дословный само-дубль недавней реплики ушёл в чат (recall poisoning не пойман)"
    )
