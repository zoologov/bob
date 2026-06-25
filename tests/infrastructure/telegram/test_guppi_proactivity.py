# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for GUPPI's proactivity owner-commands (/quiet, /wake) — BOB-010 Ф1.

``/quiet`` mutes Bob's proactivity (an optional ``/quiet 2h`` adds a timed mute
expiry), and ``/wake`` un-mutes it — both owner-only, in the General chat, mirror
the existing ``/authorize`` pattern. These tests exercise the commands directly
against :class:`GuppiHandler` with a fake bot, a fake authorizer, a fake
proactivity store, and a fixed clock (no network, no SQL, deterministic time):

* ``/quiet`` flips ``proactivity_enabled`` to ``False`` and confirms;
* ``/quiet 2h`` also persists a ``mute_until`` two hours from the injected now;
* ``/wake`` flips the flag back to ``True`` and clears any timed mute;
* a non-owner sender, a non-command, or a foreign chat is ignored and silent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from bob.domain.proactivity.social_energy import SocialEnergy
from bob.domain.proactivity.state import ProactivityState
from bob.infrastructure.telegram.guppi import GuppiHandler

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram.types import InputRichMessage

    from bob.infrastructure.telegram.gateway import UpdateLike

_CHAT_ID = -1004372947307
_OWNER_ID = 27468732
_STRANGER_ID = 555
_FOREIGN_CHAT_ID = -100999
_PERSONA = "bob"
_NOW = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _SendCall:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
    sends: list[_SendCall] = field(default_factory=list)

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[UpdateLike]:  # pragma: no cover - GuppiHandler never polls
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> _FakeMessage:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=text, message_thread_id=message_thread_id)
        )
        return _FakeMessage(message_id=0, text=text)

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
    ) -> bool:  # pragma: no cover - GuppiHandler never types
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:  # pragma: no cover - GuppiHandler sends plain only
        return _FakeMessage(message_id=0, text="")

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        # BOB-035: BotLike parity; this fake's tests never post a photo.
        raise NotImplementedError  # pragma: no cover


@dataclass
class _FakeAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(
        self, *, user_id: int | None, chat_id: int
    ) -> bool:  # pragma: no cover - not used here
        raise NotImplementedError

    async def authorize(self, user_id: int) -> None:  # pragma: no cover - not used here
        raise NotImplementedError

    async def deauthorize(self, user_id: int) -> None:  # pragma: no cover - not used here
        raise NotImplementedError


@dataclass
class _FakeStore:
    """In-memory ProactivityStore double recording flag + timed-mute writes."""

    state: ProactivityState = field(
        default_factory=lambda: ProactivityState(
            social_energy=SocialEnergy(0.5),
            last_spoke_at=None,
            last_user_msg_at=None,
            proactivity_enabled=True,
        )
    )
    mute_until: datetime | None = None

    async def load(self, persona_id: str) -> ProactivityState:  # noqa: ARG002
        return self.state

    async def save(self, persona_id: str, state: ProactivityState) -> None:  # noqa: ARG002
        self.state = state

    async def get_mute_until(self, persona_id: str) -> datetime | None:  # noqa: ARG002
        return self.mute_until

    async def set_mute_until(
        self, persona_id: str, until: datetime | None  # noqa: ARG002
    ) -> None:
        self.mute_until = until


@dataclass
class _FixedClock:
    moment: datetime

    def now(self) -> datetime:
        return self.moment


def _build() -> tuple[GuppiHandler, _FakeBot, _FakeStore]:
    bot = _FakeBot()
    store = _FakeStore()
    handler = GuppiHandler(
        bot=bot,
        authorizer=_FakeAuthorizer(),
        general_chat_id=_CHAT_ID,
        proactivity_store=store,
        clock=_FixedClock(_NOW),
        persona_id=_PERSONA,
    )
    return handler, bot, store


# --- /quiet -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_quiet_mutes_and_confirms() -> None:
    handler, bot, store = _build()

    handled = await handler.handle_general_command(
        text="/quiet", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert handled is True
    assert store.state.proactivity_enabled is False
    assert store.mute_until is None
    assert len(bot.sends) == 1
    assert bot.sends[0].message_thread_id is None


@pytest.mark.asyncio
async def test_owner_quiet_timed_sets_mute_until() -> None:
    handler, _, store = _build()

    handled = await handler.handle_general_command(
        text="/quiet 2h", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert handled is True
    assert store.state.proactivity_enabled is False
    assert store.mute_until == _NOW + timedelta(hours=2)


@pytest.mark.asyncio
async def test_owner_quiet_timed_minutes() -> None:
    handler, _, store = _build()

    await handler.handle_general_command(
        text="/quiet 30m", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert store.mute_until == _NOW + timedelta(minutes=30)


@pytest.mark.asyncio
async def test_owner_quiet_bad_duration_replies_usage() -> None:
    handler, bot, store = _build()

    handled = await handler.handle_general_command(
        text="/quiet soon", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert handled is True
    assert store.state.proactivity_enabled is True  # unchanged on bad input
    assert store.mute_until is None
    assert len(bot.sends) == 1


# --- /wake --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_wake_unmutes_and_clears_timed_mute() -> None:
    handler, bot, store = _build()
    store.state = ProactivityState(
        social_energy=SocialEnergy(0.5),
        last_spoke_at=None,
        last_user_msg_at=None,
        proactivity_enabled=False,
    )
    store.mute_until = _NOW + timedelta(hours=2)

    handled = await handler.handle_general_command(
        text="/wake", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert handled is True
    assert store.state.proactivity_enabled is True
    assert store.mute_until is None
    assert len(bot.sends) == 1


# --- Owner-only / silence -----------------------------------------------------


@pytest.mark.asyncio
async def test_non_owner_quiet_is_ignored() -> None:
    handler, bot, store = _build()

    handled = await handler.handle_general_command(
        text="/quiet", user_id=_STRANGER_ID, chat_id=_CHAT_ID
    )

    assert handled is False
    assert store.state.proactivity_enabled is True
    assert bot.sends == []


@pytest.mark.asyncio
async def test_quiet_in_foreign_chat_is_silent() -> None:
    handler, bot, store = _build()

    handled = await handler.handle_general_command(
        text="/quiet", user_id=_OWNER_ID, chat_id=_FOREIGN_CHAT_ID
    )

    assert handled is False
    assert store.state.proactivity_enabled is True
    assert bot.sends == []


@pytest.mark.asyncio
async def test_quiet_without_store_is_unconsumed() -> None:
    """Without a proactivity store wired in, /quiet is not GUPPI's to handle."""
    bot = _FakeBot()
    handler = GuppiHandler(
        bot=bot,
        authorizer=_FakeAuthorizer(),
        general_chat_id=_CHAT_ID,
    )

    handled = await handler.handle_general_command(
        text="/quiet", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert handled is False
    assert bot.sends == []
