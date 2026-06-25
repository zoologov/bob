# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты GUPPI ``/code`` owner-команд — BOB-039 .3.

Owner-only, в General-чате, по образцу /goals:
* ``/code <задача>`` → CodingAssistant.start(task, owner_id);
* ``/code approve|stop|status`` → approve_plan / stop / status;
* не-owner / чужой чат — игнор и тишина (authz-инвариант, ассистент не вызван);
* coder.enabled=false (ассистент не подключён, но секция есть) → внятный «выключено»;
* секции нет вовсе → команда не потреблена (False).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.telegram.guppi import GuppiHandler

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram.types import InputRichMessage

    from bob.infrastructure.telegram.gateway import UpdateLike

_CHAT_ID = -1004372947307
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
    sends: list[_SendCall] = field(default_factory=list)

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[UpdateLike]:  # pragma: no cover
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> _FakeMessage:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=text, message_thread_id=message_thread_id)
        )
        return _FakeMessage(message_id=0, text=text)

    async def set_message_reaction(
        self, *, chat_id: int, message_id: int, reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover
        return True

    async def send_chat_action(
        self, *, chat_id: int, action: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover
        return True

    async def send_rich_message(
        self, *, chat_id: int, rich_message: InputRichMessage,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:  # pragma: no cover
        return _FakeMessage(message_id=0, text="")

    async def send_photo(
        self, *, chat_id: int, photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:  # pragma: no cover
        raise NotImplementedError

    async def send_document(
        self, *, chat_id: int, document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:  # pragma: no cover
        raise NotImplementedError


@dataclass
class _FakeAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(
        self, *, user_id: int | None, chat_id: int
    ) -> bool:  # pragma: no cover
        raise NotImplementedError

    async def authorize(self, user_id: int) -> None:
        raise NotImplementedError  # pragma: no cover

    async def deauthorize(self, user_id: int) -> None:
        raise NotImplementedError  # pragma: no cover


@dataclass
class _FakeCodingAssistant:
    starts: list[tuple[str, int | None]] = field(default_factory=list)
    approves: list[int | None] = field(default_factory=list)
    stops: list[int | None] = field(default_factory=list)
    statuses: list[int | None] = field(default_factory=list)

    async def start(self, task: str, sender: int | None) -> object:
        self.starts.append((task, sender))
        return object()

    async def approve_plan(self, sender: int | None) -> object:
        self.approves.append(sender)
        return object()

    async def stop(self, sender: int | None) -> object:
        self.stops.append(sender)
        return object()

    async def status(self, sender: int | None) -> object:
        self.statuses.append(sender)
        return object()


def _build(
    *,
    assistant: _FakeCodingAssistant | None = None,
    coding_configured: bool = False,
) -> tuple[GuppiHandler, _FakeBot, _FakeCodingAssistant | None]:
    bot = _FakeBot()
    handler = GuppiHandler(
        bot=bot,
        authorizer=_FakeAuthorizer(),
        general_chat_id=_CHAT_ID,
        coding_assistant=assistant,
        coding_configured=coding_configured,
    )
    return handler, bot, assistant


@pytest.mark.asyncio
async def test_owner_code_task_starts_session() -> None:
    assistant = _FakeCodingAssistant()
    handler, _bot, _ = _build(assistant=assistant)

    consumed = await handler.handle_general_command(
        text="/code добавить ручку health", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert consumed is True
    assert assistant.starts == [("добавить ручку health", _OWNER_ID)]


@pytest.mark.asyncio
async def test_owner_code_subcommands_route_to_assistant() -> None:
    assistant = _FakeCodingAssistant()
    handler, _bot, _ = _build(assistant=assistant)

    for text, bucket in (
        ("/code approve", assistant.approves),
        ("/code stop", assistant.stops),
        ("/code status", assistant.statuses),
    ):
        consumed = await handler.handle_general_command(
            text=text, user_id=_OWNER_ID, chat_id=_CHAT_ID
        )
        assert consumed is True
        assert bucket == [_OWNER_ID]
    # 'approve' did not leak into start (it is a sub-command, not a task).
    assert assistant.starts == []


@pytest.mark.asyncio
async def test_non_owner_code_is_ignored_and_silent() -> None:
    assistant = _FakeCodingAssistant()
    handler, bot, _ = _build(assistant=assistant)

    consumed = await handler.handle_general_command(
        text="/code сделай что-нибудь", user_id=_STRANGER_ID, chat_id=_CHAT_ID
    )

    assert consumed is False
    assert assistant.starts == []
    assert bot.sends == []


@pytest.mark.asyncio
async def test_code_in_foreign_chat_is_ignored() -> None:
    assistant = _FakeCodingAssistant()
    handler, bot, _ = _build(assistant=assistant)

    consumed = await handler.handle_general_command(
        text="/code задача", user_id=_OWNER_ID, chat_id=_FOREIGN_CHAT_ID
    )

    assert consumed is False
    assert assistant.starts == []
    assert bot.sends == []


@pytest.mark.asyncio
async def test_code_disabled_replies_inert_when_configured_but_off() -> None:
    handler, bot, _ = _build(assistant=None, coding_configured=True)

    consumed = await handler.handle_general_command(
        text="/code задача", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert consumed is True
    assert len(bot.sends) == 1
    assert "выключен" in bot.sends[0].text


@pytest.mark.asyncio
async def test_code_not_consumed_when_feature_absent() -> None:
    handler, bot, _ = _build(assistant=None, coding_configured=False)

    consumed = await handler.handle_general_command(
        text="/code задача", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert consumed is False
    assert bot.sends == []
