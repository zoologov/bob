# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the GUPPI identity (BOB-003 BEAD-03).

GUPPI is the gatekeeper/admin. This module covers the behaviours the BEAD-02
drop-hooks become, exercised directly against :class:`GuppiHandler` with a fake
bot + a fake authorizer (no network, no SQL):

* **reject** — an unauthorized user in Bob's topic gets the visible
  "⛔ Пользователь не авторизован" sent by GUPPI into the same chat + thread;
* **owner commands** — ``/authorize <id>`` / ``/deauthorize <id>`` mutate the
  allowlist (owner only), ``/status`` answers a short whoami line;
* **non-owner** — a command from anyone but the owner is ignored (no send, no
  grant);
* **silence** — a stranger DM / disallowed chat produces no send (no reveal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.telegram.guppi import (
    GUPPI_REJECT_TEXT,
    GUPPI_SULK_ANNOUNCE_TEXT,
    GuppiHandler,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram.types import InputRichMessage

    from bob.infrastructure.telegram.gateway import UpdateLike

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32
_OWNER_ID = 27468732
_STRANGER_ID = 555
_FOREIGN_CHAT_ID = -100999


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
    """Records GUPPI's outgoing sends; no network."""

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
    """Owner + allowlist stub recording grants/revocations."""

    granted: list[int] = field(default_factory=list)
    revoked: list[int] = field(default_factory=list)

    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(
        self, *, user_id: int | None, chat_id: int
    ) -> bool:  # pragma: no cover - not used by GuppiHandler
        raise NotImplementedError

    async def authorize(self, user_id: int) -> None:
        self.granted.append(user_id)

    async def deauthorize(self, user_id: int) -> None:
        self.revoked.append(user_id)


def _build() -> tuple[GuppiHandler, _FakeBot, _FakeAuthorizer]:
    bot = _FakeBot()
    authorizer = _FakeAuthorizer()
    handler = GuppiHandler(
        bot=bot,
        authorizer=authorizer,
        general_chat_id=_CHAT_ID,
    )
    return handler, bot, authorizer


# --- Reject (unauthorized in Bob's topic) -------------------------------------


@pytest.mark.asyncio
async def test_reject_sends_into_same_chat_and_thread() -> None:
    handler, bot, _ = _build()

    await handler.reject(chat_id=_CHAT_ID, thread_id=_BOB_TOPIC_ID)

    assert len(bot.sends) == 1
    call = bot.sends[0]
    assert call.chat_id == _CHAT_ID
    assert call.text == GUPPI_REJECT_TEXT
    assert call.message_thread_id == _BOB_TOPIC_ID


# --- Sulk announce (BOB-014 .2b) ----------------------------------------------


@pytest.mark.asyncio
async def test_announce_sulk_posts_the_systemic_line_into_general() -> None:
    handler, bot, _ = _build()

    await handler.announce_sulk()

    # The внеличностный systemic voice (GUPPI, not Bob) posts the обида line into
    # General (un-threaded) where the owner sees GUPPI's system messages.
    assert len(bot.sends) == 1
    call = bot.sends[0]
    assert call.chat_id == _CHAT_ID
    assert call.text == GUPPI_SULK_ANNOUNCE_TEXT
    assert call.message_thread_id is None


# --- Owner commands -----------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_authorize_grants_and_confirms() -> None:
    handler, bot, authorizer = _build()

    handled = await handler.handle_general_command(
        text="/authorize 12345", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert handled is True
    assert authorizer.granted == [12345]
    assert len(bot.sends) == 1
    assert bot.sends[0].message_thread_id is None


@pytest.mark.asyncio
async def test_owner_deauthorize_revokes() -> None:
    handler, _, authorizer = _build()

    handled = await handler.handle_general_command(
        text="/deauthorize 12345", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert handled is True
    assert authorizer.revoked == [12345]


@pytest.mark.asyncio
async def test_owner_authorize_bad_argument_replies_usage() -> None:
    handler, bot, authorizer = _build()

    handled = await handler.handle_general_command(
        text="/authorize nope", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert handled is True
    assert authorizer.granted == []
    assert len(bot.sends) == 1
    assert "user_id" in bot.sends[0].text


@pytest.mark.asyncio
async def test_status_replies_whoami_line() -> None:
    handler, bot, _ = _build()

    handled = await handler.handle_general_command(
        text="/status", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert handled is True
    assert len(bot.sends) == 1
    assert "GUPPI" in bot.sends[0].text


# --- Non-owner / non-command --------------------------------------------------


@pytest.mark.asyncio
async def test_non_owner_command_is_ignored() -> None:
    handler, bot, authorizer = _build()

    handled = await handler.handle_general_command(
        text="/authorize 12345", user_id=_STRANGER_ID, chat_id=_CHAT_ID
    )

    assert handled is False
    assert authorizer.granted == []
    assert bot.sends == []


@pytest.mark.asyncio
async def test_owner_non_command_is_ignored() -> None:
    handler, bot, _ = _build()

    handled = await handler.handle_general_command(
        text="just chatting", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert handled is False
    assert bot.sends == []


# --- Silence (stranger DM / disallowed chat) ----------------------------------


@pytest.mark.asyncio
async def test_owner_command_in_foreign_chat_is_silent() -> None:
    """Even the owner's command outside the General chat is ignored (no reveal)."""
    handler, bot, authorizer = _build()

    handled = await handler.handle_general_command(
        text="/authorize 12345", user_id=_OWNER_ID, chat_id=_FOREIGN_CHAT_ID
    )

    assert handled is False
    assert authorizer.granted == []
    assert bot.sends == []
