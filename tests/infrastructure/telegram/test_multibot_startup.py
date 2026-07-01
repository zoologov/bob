# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Startup resilience of the multi-bot gateway (BOB-059).

``MultiBotGateway.resolve_bot_identities`` asks Bob's bot ``get_me`` once at
startup to learn his ``user_id``/``@username``. A momentary network flap must NOT
crash startup (which would leave Bob *and* GUPPI mute until a manual restart):

* a transient blip is absorbed by a bounded retry (``call_with_retry``, BOB-049)
  driven by an INJECTED sleep, so the identity still resolves;
* a persistent network failure — the aiogram ``TelegramNetworkError`` the earlier
  ``except`` did not catch — degrades gracefully (warn + return), so startup
  CONTINUES and polling starts;
* a non-network bug (a programming error) is NOT swallowed — it still surfaces;
* ``get_me`` missing / Bob not registered is a no-op, as before.

All fakes are in-process (no network); the backoff sleep is injected so the tests
are deterministic (no wall-clock wait).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetMe

from bob.application.runtime.event_bus import AsyncEventBus
from bob.infrastructure.telegram.multibot import (
    BotIdentity,
    BotRegistry,
    BotScope,
    MultiBotGateway,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32
_BOB_USER_ID = 555001
_BOB_USERNAME = "bob_bot"


@dataclass
class _FakeUser:
    id: int
    username: str


@dataclass
class _SleepSpy:
    """Records the backoff delays instead of actually sleeping."""

    delays: list[float] = field(default_factory=list)

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@dataclass
class _IdentityBot:
    """A minimal bot whose ``get_me`` plays a scripted sequence of outcomes.

    Each entry is either a :class:`_FakeUser` (return it) or an ``Exception``
    instance (raise it). The last entry repeats once exhausted, so "fail on every
    attempt" needs just one exception.
    """

    outcomes: list[object]
    get_me_calls: int = 0

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[object]:
        return []

    async def get_me(self) -> _FakeUser:
        self.get_me_calls += 1
        outcome = self.outcomes[0] if len(self.outcomes) == 1 else self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, _FakeUser)
        return outcome


@dataclass
class _PlainBot:
    """A bot WITHOUT ``get_me`` (the pre-BOB-023 / GUPPI shape)."""

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[object]:
        return []


def _build(
    bob_bot: object,
    *,
    sleep: _SleepSpy,
    attempts: int = 3,
    register_bob: bool = True,
) -> MultiBotGateway:
    registry = BotRegistry()
    if register_bob:
        registry.register(
            identity=BotIdentity.BOB,
            bot=bob_bot,  # type: ignore[arg-type]
            scope=BotScope(chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID),
        )
    registry.register(
        identity=BotIdentity.GUPPI,
        bot=_PlainBot(),  # type: ignore[arg-type]
        scope=BotScope(chat_id=_CHAT_ID, topic_id=None),
    )
    return MultiBotGateway(
        registry=registry,
        bus=AsyncEventBus(),
        poll_timeout=10,
        identity_retry_attempts=attempts,
        identity_retry_backoff_seconds=0.25,
        identity_retry_sleep=sleep,
    )


@pytest.mark.asyncio
async def test_persistent_network_error_does_not_crash_startup() -> None:
    """The core fix: TelegramNetworkError on every attempt → warn+return, not raise."""
    bot = _IdentityBot(outcomes=[TelegramNetworkError(method=GetMe(), message="down")])
    sleep = _SleepSpy()
    gateway = _build(bot, sleep=sleep, attempts=3)

    # Must NOT raise — startup continues.
    await gateway.resolve_bot_identities()

    assert bot.get_me_calls == 3  # all attempts were spent
    assert sleep.delays == [0.25, 0.25]  # one backoff between each pair of tries
    assert gateway.bob_user_id() is None  # identity stays unresolved (graceful degrade)


@pytest.mark.asyncio
async def test_transient_blip_is_retried_then_resolves() -> None:
    """A blip then success → the retry resolves Bob's identity."""
    bot = _IdentityBot(
        outcomes=[
            TelegramNetworkError(method=GetMe(), message="blip"),
            _FakeUser(id=_BOB_USER_ID, username=_BOB_USERNAME),
        ]
    )
    sleep = _SleepSpy()
    gateway = _build(bot, sleep=sleep, attempts=3)

    await gateway.resolve_bot_identities()

    assert bot.get_me_calls == 2  # failed once, succeeded on the retry
    assert sleep.delays == [0.25]  # exactly one backoff before the retry
    assert gateway.bob_user_id() == _BOB_USER_ID


@pytest.mark.asyncio
async def test_success_on_first_try_sets_identity_without_sleeping() -> None:
    """Success path is unchanged: identity set, no backoff sleep."""
    bot = _IdentityBot(outcomes=[_FakeUser(id=_BOB_USER_ID, username=_BOB_USERNAME)])
    sleep = _SleepSpy()
    gateway = _build(bot, sleep=sleep, attempts=3)

    await gateway.resolve_bot_identities()

    assert bot.get_me_calls == 1
    assert sleep.delays == []
    assert gateway.bob_user_id() == _BOB_USER_ID


@pytest.mark.asyncio
async def test_non_network_exception_is_not_swallowed() -> None:
    """A programming error (ValueError) must still surface — not silently degrade."""
    bot = _IdentityBot(outcomes=[ValueError("bug")])
    sleep = _SleepSpy()
    gateway = _build(bot, sleep=sleep, attempts=3)

    with pytest.raises(ValueError, match="bug"):
        await gateway.resolve_bot_identities()

    assert gateway.bob_user_id() is None


@pytest.mark.asyncio
async def test_get_me_missing_is_a_noop() -> None:
    """A bot without ``get_me`` leaves the identity unresolved, no crash (as before)."""
    sleep = _SleepSpy()
    gateway = _build(_PlainBot(), sleep=sleep)

    await gateway.resolve_bot_identities()

    assert sleep.delays == []
    assert gateway.bob_user_id() is None


@pytest.mark.asyncio
async def test_bob_not_registered_is_a_noop() -> None:
    """No Bob bot registered → resolve is a no-op (GUPPI-only wiring)."""
    sleep = _SleepSpy()
    gateway = _build(_PlainBot(), sleep=sleep, register_bob=False)

    await gateway.resolve_bot_identities()

    assert sleep.delays == []
    assert gateway.bob_user_id() is None
