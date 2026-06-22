# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the composition root (bob.app) — graph wiring on fakes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.app import SystemClock, build_application
from bob.application.runtime import AgentRuntime, AsyncEventBus, RuntimeState
from bob.application.usecases.handle_message import HandleMessage
from bob.application.usecases.heartbeat import (
    InnerMonologueTick,
    MoodDriftTick,
    ReflectTick,
)
from bob.infrastructure.persistence import SoulStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.domain.ports import LLMProvider
    from bob.infrastructure.telegram.gateway import UpdateLike


class _Provider:
    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        return "ok"


class _Msg:
    message_id = 1
    text: str | None = None
    message_thread_id: int | None = None


class _Bot:
    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> _Msg:
        return _Msg()

    async def set_message_reaction(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        message_id: int,  # noqa: ARG002
        reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        # BOB-018: react-only seam; fakes accept the BotLike reaction call.
        return True

    async def send_chat_action(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        action: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        rich_message: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _Msg:
        return _Msg()


def _config(tmp_path: Path) -> dict[str, object]:
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 1},
        "telegram": {
            "poll_timeout": 1,
            "bob": {"token": "bob-tok", "topic_id": 0},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _providers() -> dict[int, LLMProvider]:
    return {0: _Provider(), 1: _Provider()}


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
    return build_application(
        config=_config(tmp_path),
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )


def test_build_application_returns_wired_runtime_and_bus(tmp_path: Path) -> None:
    # Act
    app = _app(tmp_path)

    # Assert: composition root produced the GUPPI runtime + event bus.
    assert isinstance(app.runtime, AgentRuntime)
    assert isinstance(app.event_bus, AsyncEventBus)
    assert app.runtime.state is RuntimeState.STOPPED


def test_build_application_wires_handler_and_ticks(tmp_path: Path) -> None:
    # Act
    app = _app(tmp_path)

    # Assert: the message handler and all three heartbeat ticks were composed.
    assert isinstance(app.handle_message, HandleMessage)
    assert isinstance(app.inner_monologue_tick, InnerMonologueTick)
    assert isinstance(app.mood_drift_tick, MoodDriftTick)
    assert isinstance(app.reflect_tick, ReflectTick)


def test_system_clock_returns_timezone_aware_now() -> None:
    # Act
    now = SystemClock().now()

    # Assert
    assert now.tzinfo is not None


@pytest.mark.asyncio
async def test_application_runtime_starts_and_stops(tmp_path: Path) -> None:
    # Arrange: pre-seed a SOUL so startup's Genesis is a no-op.
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    app = _app(tmp_path)
    await app.startup()

    # Act
    await app.runtime.start()
    running = app.runtime.is_running
    await app.shutdown()

    # Assert
    assert running is True
    assert app.runtime.state is RuntimeState.STOPPED


@pytest.mark.parametrize(
    ("missing", "identity"),
    [("bob", "bob"), ("guppi", "guppi")],
)
def test_build_application_without_injected_bot_requires_token(
    tmp_path: Path, missing: str, identity: str
) -> None:
    # Arrange: no injected bot for one identity AND its token blanked → the real
    # aiogram-bot path is taken and must reject the empty token (secrets are env
    # only; a missing token is a config error, never a silent network attempt).
    config = _config(tmp_path)
    telegram = config["telegram"]
    assert isinstance(telegram, dict)
    bot_section = telegram[missing]
    assert isinstance(bot_section, dict)
    bot_section["token"] = ""
    # Inject only the OTHER bot so the failure is isolated to `missing`.
    bob_bot = None if missing == "bob" else _Bot()
    guppi_bot = None if missing == "guppi" else _Bot()

    # Act / Assert
    with pytest.raises(KeyError, match=f"telegram.{identity}.token"):
        build_application(
            config=config,
            providers=_providers(),
            bob_bot=bob_bot,
            guppi_bot=guppi_bot,
        )
