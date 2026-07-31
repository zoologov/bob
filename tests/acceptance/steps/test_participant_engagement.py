# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the participant-engagement acceptance scenarios (BOB-078 B).

Binds ``participant_engagement.feature`` to the guest-engage harness
(:mod:`tests.acceptance.guest_engage_harness`), reused because both pin the SAME boundary:
whether Bob sends a reply. The two scenarios witness the «ты»-directed balance:

* a direct second-person praise to Bob («Ты классный!») now classifies ``directed_to_bob`` →
  Bob replies (before the fix: AMBIENT → reflective IGNORE → silence to the participant);
* a second-person address to a THIRD party by name («Паша, ты …») stays AMBIENT — on the
  multi-party reflective periphery Bob leaves the cross-talk alone (не баржить на всё).

Observed only at the outgoing boundary (a sent / not-sent reply), never the detector's state.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
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

scenarios("../features/participant_engagement.feature")


@dataclass(slots=True)
class _EngagementContext:
    """The slate the steps share: temp db root + the observed gateway."""

    tmp_path: Path
    gateway: FakeGateway | None = None


@pytest.fixture
def engagement_context(tmp_path: Path) -> _EngagementContext:
    """A fresh, isolated context (temp db + soul) per scenario."""
    return _EngagementContext(tmp_path=tmp_path)


@given("Боб запущен и слушает свой топик")
def bob_listening(engagement_context: _EngagementContext) -> None:
    assert engagement_context.gateway is None


@given("Боб запущен с включённой рефлексией в живой группе")
def bob_reflective_in_group(engagement_context: _EngagementContext) -> None:
    assert engagement_context.gateway is None


@when(parsers.parse('участник пишет Бобу "{text}"'))
def participant_addresses_bob(engagement_context: _EngagementContext, text: str) -> None:
    engagement_context.gateway = asyncio.run(
        run_guest_direct_dot_turn(engagement_context.tmp_path, text=text)
    )


@when(parsers.parse('участник роняет в общий фон реплику другому "{text}"'))
def participant_addresses_a_third(
    engagement_context: _EngagementContext, text: str
) -> None:
    gateway, _memory = asyncio.run(
        run_guest_ambient_unanswered_turn(engagement_context.tmp_path, text=text)
    )
    engagement_context.gateway = gateway


@then("Боб отправляет ответную реплику участнику")
def bob_replied(engagement_context: _EngagementContext) -> None:
    assert engagement_context.gateway is not None
    assert engagement_context.gateway.replied, (
        "Боб промолчал на прямое «ты» участника (комплимент проигнорирован)"
    )


@then("Боб не отправляет реплику участнику")
def bob_stayed_silent(engagement_context: _EngagementContext) -> None:
    assert engagement_context.gateway is not None
    assert not engagement_context.gateway.replied, (
        "Боб влез в чужой кросс-ток («ты» было адресовано третьему)"
    )
