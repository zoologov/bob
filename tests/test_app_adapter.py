# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening for the aiogram transport adapter in the composition root (BOB-003).

``build_application`` wraps each real aiogram ``Bot`` in ``_AiogramBotAdapter`` and
lifts each aiogram ``Update`` (chat/sender nested under ``message``) into the flat
``UpdateLike`` the gateway reads. The end-to-end two-bot tests inject fakes that
*already* speak ``UpdateLike``, so this adapter glue itself was untested. These
tests drive it directly with a fake aiogram-shaped bot (no network): every
``BotLike`` method delegates with the thread id preserved, and ``_to_update_view``
maps both the populated and the empty (no message / no chat / no sender) update.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from aiogram.types import BufferedInputFile, InputRichMessage

from bob.app import _AiogramBotAdapter, _to_update_view

if TYPE_CHECKING:
    from collections.abc import Sequence

_CHAT_ID = -1004372947307
_THREAD_ID = 32


# --- Fake aiogram-shaped objects (no network) ---------------------------------


@dataclass
class _AioChat:
    id: int


@dataclass
class _AioUser:
    id: int
    full_name: str


@dataclass
class _AioMessage:
    message_id: int
    text: str | None
    chat: _AioChat | None = None
    from_user: _AioUser | None = None


@dataclass
class _AioUpdate:
    update_id: int
    message: _AioMessage | None = None
    message_reaction: object | None = None
    message_reaction_count: object | None = None


@dataclass
class _Call:
    name: str
    kwargs: dict[str, object]


@dataclass
class _FakeAiogramBot:
    """Records the kwargs each aiogram method was called with; no network."""

    updates: Sequence[_AioUpdate] = field(default_factory=tuple)
    calls: list[_Call] = field(default_factory=list)

    async def get_updates(
        self,
        *,
        offset: int,
        timeout: int,
        allowed_updates: Sequence[str] | None = None,
    ) -> Sequence[_AioUpdate]:
        self.calls.append(
            _Call(
                "get_updates",
                {
                    "offset": offset,
                    "timeout": timeout,
                    "allowed_updates": allowed_updates,
                },
            )
        )
        return self.updates

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> str:
        self.calls.append(
            _Call(
                "send_message",
                {"chat_id": chat_id, "text": text, "message_thread_id": message_thread_id},
            )
        )
        return "sent"

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
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:
        self.calls.append(
            _Call(
                "send_chat_action",
                {
                    "chat_id": chat_id,
                    "action": action,
                    "message_thread_id": message_thread_id,
                },
            )
        )
        return True

    async def send_rich_message(
        self, *, chat_id: int, rich_message: object, message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> str:
        self.calls.append(
            _Call(
                "send_rich_message",
                {
                    "chat_id": chat_id,
                    "rich_message": rich_message,
                    "message_thread_id": message_thread_id,
                },
            )
        )
        return "rich-sent"

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> str:
        self.calls.append(
            _Call(
                "send_photo",
                {
                    "chat_id": chat_id,
                    "photo": photo,
                    "caption": caption,
                    "message_thread_id": message_thread_id,
                },
            )
        )
        return "photo-sent"


    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> str:
        self.calls.append(
            _Call(
                "send_document",
                {
                    "chat_id": chat_id,
                    "document": document,
                    "caption": caption,
                    "message_thread_id": message_thread_id,
                },
            )
        )
        return "document-sent"


# --- get_updates + _to_update_view --------------------------------------------


@pytest.mark.asyncio
async def test_get_updates_lifts_nested_chat_and_sender() -> None:
    # Arrange: an aiogram update with chat + sender nested under message.
    raw = _AioUpdate(
        update_id=7,
        message=_AioMessage(
            message_id=1,
            text="hi",
            chat=_AioChat(id=_CHAT_ID),
            from_user=_AioUser(id=42, full_name="Ada"),
        ),
    )
    bot = _FakeAiogramBot(updates=(raw,))
    adapter = _AiogramBotAdapter(bot)

    # Act
    views = await adapter.get_updates(offset=3, timeout=10)

    # Assert: offset/timeout forwarded; nested chat/sender lifted flat.
    assert bot.calls[0].kwargs["offset"] == 3
    assert bot.calls[0].kwargs["timeout"] == 10
    assert len(views) == 1
    view = views[0]
    assert view.update_id == 7
    assert view.effective_chat is not None
    assert view.effective_chat.id == _CHAT_ID
    assert view.effective_user is not None
    assert view.effective_user.id == 42
    assert view.effective_user.full_name == "Ada"


@pytest.mark.asyncio
async def test_get_updates_requests_reaction_update_types() -> None:
    # BOB-050: Telegram only delivers reaction updates when asked, so the adapter
    # must pass an explicit allowed_updates that includes both reaction types.
    bot = _FakeAiogramBot(updates=())
    adapter = _AiogramBotAdapter(bot)

    await adapter.get_updates(offset=0, timeout=5)

    allowed = bot.calls[0].kwargs["allowed_updates"]
    assert isinstance(allowed, list)
    assert "message" in allowed
    assert "message_reaction" in allowed
    assert "message_reaction_count" in allowed


def test_to_update_view_passes_through_reaction_payloads() -> None:
    # BOB-050: a reaction update has no message; its raw reaction payloads are
    # carried through unchanged for the gateway's reaction route to read.
    reaction = object()
    count = object()
    raw = _AioUpdate(
        update_id=11, message=None, message_reaction=reaction, message_reaction_count=count
    )

    view = _to_update_view(raw)

    assert view.message is None
    assert view.message_reaction is reaction
    assert view.message_reaction_count is count


def test_to_update_view_handles_empty_update() -> None:
    # Arrange/Act: an update with no message (e.g. an edited/non-message update).
    view = _to_update_view(_AioUpdate(update_id=9, message=None))

    # Assert: flat views are None, no crash.
    assert view.update_id == 9
    assert view.message is None
    assert view.effective_chat is None
    assert view.effective_user is None


def test_to_update_view_handles_message_without_chat_or_sender() -> None:
    # Arrange: a message present but chat/from_user absent.
    message = _AioMessage(message_id=2, text="x", chat=None, from_user=None)
    raw = _AioUpdate(update_id=10, message=message)

    # Act
    view = _to_update_view(raw)

    # Assert: the underlying message is carried through; flat views are None.
    carried: object = view.message
    assert carried is message
    assert view.effective_chat is None
    assert view.effective_user is None


# --- send delegations (thread id preserved) -----------------------------------


@pytest.mark.asyncio
async def test_send_message_delegates_with_thread_id() -> None:
    bot = _FakeAiogramBot()
    adapter = _AiogramBotAdapter(bot)

    await adapter.send_message(chat_id=_CHAT_ID, text="yo", message_thread_id=_THREAD_ID)

    assert bot.calls[0].name == "send_message"
    assert bot.calls[0].kwargs == {
        "chat_id": _CHAT_ID,
        "text": "yo",
        "message_thread_id": _THREAD_ID,
    }


@pytest.mark.asyncio
async def test_send_chat_action_delegates() -> None:
    bot = _FakeAiogramBot()
    adapter = _AiogramBotAdapter(bot)

    ok = await adapter.send_chat_action(
        chat_id=_CHAT_ID, action="typing", message_thread_id=_THREAD_ID
    )

    assert ok is True
    assert bot.calls[0].name == "send_chat_action"
    assert bot.calls[0].kwargs["action"] == "typing"
    assert bot.calls[0].kwargs["message_thread_id"] == _THREAD_ID


@pytest.mark.asyncio
async def test_send_rich_message_delegates_with_thread_id() -> None:
    bot = _FakeAiogramBot()
    adapter = _AiogramBotAdapter(bot)
    rich = InputRichMessage(markdown="**hi**")

    await adapter.send_rich_message(
        chat_id=_CHAT_ID, rich_message=rich, message_thread_id=_THREAD_ID
    )

    assert bot.calls[0].name == "send_rich_message"
    assert bot.calls[0].kwargs["rich_message"] is rich
    assert bot.calls[0].kwargs["message_thread_id"] == _THREAD_ID


@pytest.mark.asyncio
async def test_send_photo_delegates_with_thread_id() -> None:
    # BOB-035: the adapter forwards the rendered diagram photo + thread id to aiogram.
    bot = _FakeAiogramBot()
    adapter = _AiogramBotAdapter(bot)
    photo = BufferedInputFile(b"PNGBYTES", filename="diagram.png")

    await adapter.send_photo(
        chat_id=_CHAT_ID, photo=photo, caption="вот", message_thread_id=_THREAD_ID
    )

    assert bot.calls[0].name == "send_photo"
    assert bot.calls[0].kwargs["photo"] is photo
    assert bot.calls[0].kwargs["caption"] == "вот"
    assert bot.calls[0].kwargs["message_thread_id"] == _THREAD_ID


@pytest.mark.asyncio
async def test_send_document_delegates_with_thread_id() -> None:
    # BOB-037: the adapter forwards the uncompressed diagram document + thread id.
    bot = _FakeAiogramBot()
    adapter = _AiogramBotAdapter(bot)
    document = BufferedInputFile(b"PNGBYTES", filename="diagram.png")

    await adapter.send_document(
        chat_id=_CHAT_ID,
        document=document,
        caption="вот",
        message_thread_id=_THREAD_ID,
    )

    assert bot.calls[0].name == "send_document"
    assert bot.calls[0].kwargs["document"] is document
    assert bot.calls[0].kwargs["caption"] == "вот"
    assert bot.calls[0].kwargs["message_thread_id"] == _THREAD_ID


