# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the whole-stack wiring INTEGRATION scenarios (BOB-066 Срез W.5).

Binds ``wiring_integration.feature`` to the all-flags-ON full-graph harness
(:mod:`tests.acceptance.wiring_integration_harness`). The scenarios pin the cross-cutting
contract through the outgoing boundary with EVERY presence flag wired at once: a direct address
always replies (INV-1) even under an exhausted share-of-voice ceiling or an active sulk (INV-6),
the same on-stack still stays silent on ambient chatter it hogged the room over, and with all
flags OFF the same direct turn replies byte-identical.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.wiring_integration_harness import (
    IGNORE_READING,
    REPLY_READING,
    run_wiring_turn,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tests.acceptance.fake_gateway import FakeGateway

scenarios("../features/wiring_integration.feature")


@dataclass(slots=True)
class _WiringState:
    """The slate a wiring-integration scenario's steps share.

    ``flags_on`` — whether the whole presence stack is wired; ``hog_airtime`` — whether Bob has
    hogged the recent airtime (arming the ceiling); ``sulk`` — whether Bob is обижен at the
    sender; ``reading`` — the scripted reflective verdict; ``gateway`` — the boundary populated
    once the turn is driven.
    """

    tmp_path: Path
    flags_on: bool = True
    hog_airtime: bool = False
    sulk: bool = False
    reading: str = IGNORE_READING
    gateway: FakeGateway | None = None


@given("весь пласт присутствия включён", target_fixture="wiring_state")
def all_flags_on(tmp_path: Path) -> _WiringState:
    return _WiringState(tmp_path=tmp_path, flags_on=True)


@given("весь пласт присутствия ВЫКЛючен", target_fixture="wiring_state")
def all_flags_off(tmp_path: Path) -> _WiringState:
    return _WiringState(tmp_path=tmp_path, flags_on=False)


@given(
    "весь пласт присутствия включён, а Боб наговорил почти весь недавний эфир",
    target_fixture="wiring_state",
)
def all_flags_on_and_hogged(tmp_path: Path) -> _WiringState:
    # A REPLY reading so a silence can only be the ceiling, never the reflective verdict.
    return _WiringState(
        tmp_path=tmp_path, flags_on=True, hog_airtime=True, reading=REPLY_READING
    )


@given(
    "весь пласт присутствия включён, а Боб обижен на собеседника",
    target_fixture="wiring_state",
)
def all_flags_on_and_sulking(tmp_path: Path) -> _WiringState:
    return _WiringState(tmp_path=tmp_path, flags_on=True, sulk=True)


def _drive(state: _WiringState, *, text: str, mentions_bob: bool) -> None:
    state.gateway = asyncio.run(
        run_wiring_turn(
            state.tmp_path,
            text=text,
            mentions_bob=mentions_bob,
            flags_on=state.flags_on,
            reading=state.reading,
            hog_airtime=state.hog_airtime,
            sulk=state.sulk,
        )
    )


@when(parsers.parse('участник напрямую упоминает Боба: "{text}"'))
def participant_mentions_bob(wiring_state: _WiringState, text: str) -> None:
    _drive(wiring_state, text=text, mentions_bob=True)


@when(parsers.parse('участник обращается по имени: "{text}"'))
def participant_name_addresses_bob(wiring_state: _WiringState, text: str) -> None:
    # No @mention — the «Боб, …» vocative in the text is what classifies as a direct address.
    _drive(wiring_state, text=text, mentions_bob=False)


@when(parsers.parse('участник роняет реплику в воздух: "{text}"'))
def participant_speaks_to_the_air(wiring_state: _WiringState, text: str) -> None:
    _drive(wiring_state, text=text, mentions_bob=False)


@then("Боб отправляет ответную реплику")
def bob_replies(wiring_state: _WiringState) -> None:
    assert wiring_state.gateway is not None
    assert wiring_state.gateway.replied, "Боб промолчал (ожидался ответ)"


@then("Боб не отправляет реплику")
def bob_stays_silent(wiring_state: _WiringState) -> None:
    assert wiring_state.gateway is not None
    assert not wiring_state.gateway.replied, "Боб влез в эфир (ожидалась тишина)"
