# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the GUPPI-channel scenarios (BOB-087 Срез A).

Binds ``guppi_channel.feature`` to a REAL :class:`~bob.coding.usecases.coding_assistant.
CodingAssistant` streaming through the REAL owner-notifier adapter over TWO fake bots (Bob's
and GUPPI's). Every assertion reads only the two bots' recorded sends — a real transport
boundary — never private use-case state:

* S-A1 (flag ON) proves the split: the mechanical per-event firehose («GUPPI: …») lands on
  GUPPI's bot while Bob's gate voice («берусь…», «готово, PR…») lands on Bob's bot.
* S-A2 (flag OFF, default) proves no regression: both the firehose AND Bob's voice go through
  Bob's bot, GUPPI's bot stays silent — byte-identical to before BOB-087 (INV-5).
* S-A3 proves the flag only moves the firehose: Bob's gate voice is on Bob's bot in BOTH
  flag positions, never on GUPPI's bot (INV-1).
"""

from __future__ import annotations

import asyncio

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from bob.coding import session_voice
from tests.acceptance.guppi_channel_harness import (
    OWNER_ID,
    PR_URL,
    RecordingBot,
    build_assistant,
)

scenarios("../features/guppi_channel.feature")

# The GUPPI-attributed firehose marker (a per-event ``narrate`` edit line) — the mechanical
# stream. Bob's own gate voice is asserted via the exact ``session_voice`` strings.
_FIREHOSE_MARKER = "GUPPI: правлю"


class _Ctx:
    """The mutable slate a scenario's steps share (two bots + the flag under test)."""

    def __init__(self) -> None:
        self.bob = RecordingBot()
        self.guppi = RecordingBot()
        self.stream_via_guppi = False


@pytest.fixture
def ctx() -> _Ctx:
    return _Ctx()


@given("Боб и GUPPI — два разных бота")
def _two_bots(ctx: _Ctx) -> None:
    assert ctx.bob is not ctx.guppi


@given(parsers.parse("флаг stream_via_guppi в положении {state}"))
def _flag(ctx: _Ctx, state: str) -> None:
    ctx.stream_via_guppi = state.strip() == "ON"


@when("owner проводит полную coder-сессию: план, апрув, PR")
def _run_session(ctx: _Ctx) -> None:
    assistant = build_assistant(
        bob_bot=ctx.bob,
        guppi_bot=ctx.guppi,
        stream_via_guppi=ctx.stream_via_guppi,
    )

    async def _go() -> None:
        await assistant.start("Починить парсер", OWNER_ID)
        outcome = await assistant.approve_plan(OWNER_ID)
        assert outcome.ok is True  # the scripted run opens a PR

    asyncio.run(_go())


@then("механический firehose исполнения несёт бот GUPPI")
def _firehose_on_guppi(ctx: _Ctx) -> None:
    assert ctx.guppi.carried(_FIREHOSE_MARKER)


@then("голос-гейты Боба несёт бот Боба")
def _voice_on_bob(ctx: _Ctx) -> None:
    assert session_voice.accepted() in ctx.bob.sent
    assert session_voice.pr(PR_URL) in ctx.bob.sent


@then("бот Боба не несёт механический firehose")
def _bob_no_firehose(ctx: _Ctx) -> None:
    assert not ctx.bob.carried(_FIREHOSE_MARKER)


@then("бот GUPPI не несёт голос Боба")
def _guppi_no_voice(ctx: _Ctx) -> None:
    assert session_voice.accepted() not in ctx.guppi.sent
    assert not ctx.guppi.carried(PR_URL)


@then("и firehose, и голос Боба несёт бот Боба")
def _all_on_bob(ctx: _Ctx) -> None:
    # OFF path: the single Bob channel carries BOTH the firehose and Bob's gate voice.
    assert ctx.bob.carried(_FIREHOSE_MARKER)
    assert session_voice.accepted() in ctx.bob.sent
    assert session_voice.pr(PR_URL) in ctx.bob.sent


@then("бот GUPPI молчит")
def _guppi_silent(ctx: _Ctx) -> None:
    assert ctx.guppi.sent == []
