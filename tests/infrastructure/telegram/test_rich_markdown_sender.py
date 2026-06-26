# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты RichMarkdownSender — общий rich/markdown-путь с фолбэком (BOB-041 .1).

Coding-сообщения (план / нарратив / PR) содержат markdown (## заголовки, **жирный**,
``код``) — их надо рендерить через тот же ``send_rich_message``, что и обычные ответы
Боба, а не плоским ``send_message`` (тогда markdown течёт сырым). На ЛЮБОЙ rich-ошибке
— безопасный фолбэк на plain, сообщение не теряется.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from bob.infrastructure.telegram.gateway import RichMarkdownSender

if TYPE_CHECKING:
    from aiogram.types import InputRichMessage


@dataclass
class _FakeMessage:
    message_id: int = 1
    text: str | None = None
    message_thread_id: int | None = None


@dataclass
class _FakeBot:
    rich_raises: bool = False
    rich_markdowns: list[str | None] = field(default_factory=list)
    plain_texts: list[str] = field(default_factory=list)
    next_id: int = 1

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:
        if self.rich_raises:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=""),
                message="rich rejected",
            )
        self.rich_markdowns.append(rich_message.markdown)
        self.next_id += 1
        return _FakeMessage(message_id=self.next_id, text=rich_message.markdown)

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> _FakeMessage:
        self.plain_texts.append(text)
        self.next_id += 1
        return _FakeMessage(message_id=self.next_id, text=text)


@pytest.mark.asyncio
async def test_markdown_goes_through_rich_path() -> None:
    bot = _FakeBot()
    sender = RichMarkdownSender(bot)

    await sender.send(chat_id=42, markdown="## План\n\n**жирный** и `код`")

    assert len(bot.rich_markdowns) == 1
    assert bot.plain_texts == []


@pytest.mark.asyncio
async def test_rich_error_falls_back_to_plain_never_loses_message() -> None:
    bot = _FakeBot(rich_raises=True)
    sender = RichMarkdownSender(bot)

    await sender.send(chat_id=42, markdown="## План")

    assert bot.rich_markdowns == []
    assert bot.plain_texts == ["## План"]


@pytest.mark.asyncio
async def test_blank_markdown_sends_nothing() -> None:
    bot = _FakeBot()
    sender = RichMarkdownSender(bot)

    await sender.send(chat_id=42, markdown="   \n  ")

    assert bot.rich_markdowns == []
    assert bot.plain_texts == []


@pytest.mark.asyncio
async def test_realistic_coding_plan_renders_rich_not_plain() -> None:
    # BRIEF acceptance (markdown): a realistic coding plan — headings, **bold**, a list
    # and a ``code`` span — goes through the rich path as ONE message, never leaking raw
    # markdown via the plain ``send_message``.
    plan = (
        "## План\n\n"
        "Сначала **правка** модуля, потом тесты:\n\n"
        "- Поправить `parser.py`\n"
        "- Запустить `pytest`\n"
    )
    bot = _FakeBot()
    sender = RichMarkdownSender(bot)

    await sender.send(chat_id=42, markdown=plan)

    assert len(bot.rich_markdowns) == 1
    assert bot.plain_texts == []  # nothing leaked as raw plain markdown


@pytest.mark.asyncio
async def test_rich_failure_falls_back_preserving_the_exact_coding_text() -> None:
    # The plain fallback must carry the FULL original text verbatim (split only on the
    # length limit) — a coding plan is never silently lost or truncated on a rich error.
    plan = "## План\n\n- Шаг 1: правки в `app.py`\n- Шаг 2: тесты"
    bot = _FakeBot(rich_raises=True)
    sender = RichMarkdownSender(bot)

    await sender.send(chat_id=42, markdown=plan)

    assert bot.rich_markdowns == []
    assert bot.plain_texts == [plan]
