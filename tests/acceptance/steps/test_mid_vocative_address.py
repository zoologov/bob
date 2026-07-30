# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the mid-vocative addressivity scenarios (BOB-069.A).

Binds ``mid_vocative_address.feature`` to the floor harness
(:mod:`tests.acceptance.floor_harness`), whose judge chooses REPLY/IGNORE strictly by the
REAL addressivity the pipeline folds into the prompt. So a mid-phrase vocative («Кстати,
Боб, …») is observed to draw a reply through the gateway, while a 3rd-person mention of the
name («Боб молодец» / «расскажу Бобу») draws silence — pinned at the outgoing boundary, not
via the detector's private state.

The scenarios are synchronous (pytest-bdd), so the async run is driven via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.floor_harness import OUTSIDER, PARTICIPANT, Speaker, run_floor_turns

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/mid_vocative_address.feature")


@dataclass(slots=True)
class _AddressContext:
    """The slate the addressivity steps share: temp db root + whether Bob replied."""

    tmp_path: Path
    replied: list[bool] = field(default_factory=list)


@pytest.fixture
def address_context(tmp_path: Path) -> _AddressContext:
    """A fresh, isolated context (temp db + soul) per scenario."""
    return _AddressContext(tmp_path=tmp_path)


@given("Боб запущен и слушает свой топик")
def bob_is_running(address_context: _AddressContext) -> None:
    assert not address_context.replied


def _drive(address_context: _AddressContext, speaker: Speaker, text: str) -> None:
    address_context.replied = asyncio.run(
        run_floor_turns(address_context.tmp_path, [(speaker, text)])
    )


@when(parsers.parse('участник пишет "{text}"'))
def participant_writes(address_context: _AddressContext, text: str) -> None:
    _drive(address_context, PARTICIPANT, text)


@when(parsers.parse('посторонний пишет "{text}"'))
def outsider_writes(address_context: _AddressContext, text: str) -> None:
    _drive(address_context, OUTSIDER, text)


@then("Боб отправляет ответную реплику")
def bob_replied(address_context: _AddressContext) -> None:
    assert address_context.replied[-1], "Боб промолчал на вокатив-обращение в середине фразы"


@then("Боб не отправляет реплику")
def bob_stayed_silent(address_context: _AddressContext) -> None:
    assert not address_context.replied[-1], "Боб ошибочно ответил на имя в 3-м лице"
