# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the guest-engage acceptance scenarios (BOB-071).

Binds ``guest_engage.feature`` to the guest-engage harness
(:mod:`tests.acceptance.guest_engage_harness`). The two scenarios pin, at the boundaries a
user would witness:

* **Seam A** — a guest's dot-vocative («Привет, Боб.») draws a reply through the gateway
  (the judge folds the REAL ``directed_to_bob`` addressivity into the prompt);
* **Seam B** — an ambient guest turn Bob deliberately leaves unanswered on the reflective
  periphery is still stored in ``episodic_log`` (the thread is not torn).

The scenarios are synchronous (pytest-bdd), so the async runs are driven via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.guest_engage_harness import (
    run_guest_ambient_unanswered_turn,
    run_guest_direct_dot_turn,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tests.acceptance.fake_gateway import FakeGateway

scenarios("../features/guest_engage.feature")


@dataclass(slots=True)
class _GuestContext:
    """The slate the guest steps share: temp db root + observed reply / stored thread."""

    tmp_path: Path
    gateway: FakeGateway | None = None
    memory: list[str] = field(default_factory=list)


@pytest.fixture
def guest_context(tmp_path: Path) -> _GuestContext:
    """A fresh, isolated context (temp db + soul) per guest scenario."""
    return _GuestContext(tmp_path=tmp_path)


@given("Боб запущен и слушает свой топик")
def bob_listening(guest_context: _GuestContext) -> None:
    assert guest_context.gateway is None


@given("Боб запущен с включённой рефлексией в живой группе")
def bob_reflective_in_group(guest_context: _GuestContext) -> None:
    assert guest_context.gateway is None


@when(parsers.parse('гость пишет "{text}"'))
def guest_addresses_bob(guest_context: _GuestContext, text: str) -> None:
    guest_context.gateway = asyncio.run(
        run_guest_direct_dot_turn(guest_context.tmp_path, text=text)
    )


@when(parsers.parse('гость роняет реплику в общий фон "{text}"'))
def guest_speaks_to_the_air(guest_context: _GuestContext, text: str) -> None:
    gateway, memory = asyncio.run(
        run_guest_ambient_unanswered_turn(guest_context.tmp_path, text=text)
    )
    guest_context.gateway = gateway
    guest_context.memory = memory


@then("Боб отправляет ответную реплику гостю")
def bob_replied_to_guest(guest_context: _GuestContext) -> None:
    assert guest_context.gateway is not None
    assert guest_context.gateway.replied, "Боб промолчал на прямое обращение гостя с точкой"


@then("Боб не отправляет реплику")
def bob_stayed_silent(guest_context: _GuestContext) -> None:
    assert guest_context.gateway is not None
    assert not guest_context.gateway.replied, "Боб влез в тихий общий фон"


@then("реплика гостя сохранена в памяти разговора")
def guest_turn_is_remembered(guest_context: _GuestContext) -> None:
    thread = "\n".join(guest_context.memory)
    assert "дождь за окном" in thread, (
        "реплика участника, оставленная без ответа, не попала в episodic_log — тред рвётся"
    )
