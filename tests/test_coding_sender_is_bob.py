# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тест: coding-сессия говорит голосом Боб-бота, не GUPPI (BOB-046 .1).

Живой прогон T3.B (обратная связь владельца): coding-сообщения падали в топик Боба, но
от лица бота GUPPI. По канону отвечает Боб (GUPPI — молчаливый исполнитель под капотом),
поэтому отправителем должен быть бот Боба. Меняется только отправитель: топик Боба
(``message_thread_id == telegram.bob.topic_id``, BOB-042), rich/markdown-путь (BOB-041 .1)
и GUPPI-атрибуция нарратива (``GUPPI: ...``) сохранены.

Проверка на уровне композиции: собираем приложение, где Боб и GUPPI — два разных
фейк-бота, при включённом ``coder`` и убеждаемся, что нотифайер coding-сессии шлёт через
бот Боба в топик Боба, тогда как бот GUPPI молчит. Плюс guard: пер-событийный нарратив
сохраняет GUPPI-атрибуцию (текст не трогаем).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.app import build_application
from bob.coding.narrate import narrate

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from aiogram.types import InputRichMessage

    from bob.app import Application
    from bob.domain.ports import LLMProvider
    from bob.infrastructure.telegram.gateway import UpdateLike

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 77
_OWNER_ID = 27468732


class _Provider:
    """Fake LLMProvider returning a fixed reply (stands in for a tier)."""

    def __init__(self, *, reply: str) -> None:
        self.reply = reply

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        return self.reply


@dataclass
class _FakeMessage:
    message_id: int = 0
    text: str | None = None
    message_thread_id: int | None = None


@dataclass
class _RichSend:
    chat_id: int
    markdown: str | None
    message_thread_id: int | None


@dataclass
class _PlainSend:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
    """Fake aiogram bot recording which sends it received (Bob vs GUPPI identity)."""

    rich_sends: list[_RichSend] = field(default_factory=list)
    plain_sends: list[_PlainSend] = field(default_factory=list)

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[UpdateLike]:  # pragma: no cover - no polling in this test
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> _FakeMessage:
        self.plain_sends.append(_PlainSend(chat_id, text, message_thread_id))
        return _FakeMessage(text=text, message_thread_id=message_thread_id)

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        self.rich_sends.append(
            _RichSend(chat_id, rich_message.markdown, message_thread_id)
        )
        return _FakeMessage(text=rich_message.markdown)

    async def set_message_reaction(
        self, *, chat_id: int, message_id: int, reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover - BotLike parity
        return True

    async def send_chat_action(
        self, *, chat_id: int, action: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover - BotLike parity
        return True

    async def send_photo(
        self, *, chat_id: int, photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:  # pragma: no cover - BotLike parity
        raise NotImplementedError

    async def send_document(
        self, *, chat_id: int, document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:  # pragma: no cover - BotLike parity
        raise NotImplementedError


def _config(tmp_path: Path) -> dict[str, object]:
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 0},
        "llm": {
            "tier0_base_url": "http://localhost:8080/v1",
            "tier0_model": "tier0",
            "tier1_base_url": "https://api.example/v1",
            "tier1_model": "tier1",
            "tier1_api_key": "sk-test",
        },
        "telegram": {
            "poll_timeout": 1,
            "chat_id": _CHAT_ID,
            "owner_id": _OWNER_ID,
            "allowed_chat_ids": [_CHAT_ID],
            "bob": {"token": "bob-tok", "topic_id": _BOB_TOPIC_ID},
            "guppi": {"token": "guppi-tok"},
        },
        # The gated coding capability is ON so the assistant (and its owner-notifier)
        # is actually wired; the runner/PR adapters are built but never invoked here.
        "coder": {"enabled": True},
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _providers() -> dict[int, LLMProvider]:
    return {0: _Provider(reply="positive"), 1: _Provider(reply="ok")}


def _build(tmp_path: Path, *, bob_bot: _FakeBot, guppi_bot: _FakeBot) -> Application:
    return build_application(
        config=_config(tmp_path),
        providers=_providers(),
        bob_bot=bob_bot,
        guppi_bot=guppi_bot,
    )


@pytest.mark.asyncio
async def test_coding_session_message_is_sent_from_bobs_bot(tmp_path: Path) -> None:
    # BOB-046 .1: the coding owner-notifier speaks through BOB'S bot, not GUPPI's.
    bob_bot = _FakeBot()
    guppi_bot = _FakeBot()
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot)
    await app.memory_repo.initialize()  # the coding-session store needs its tables
    try:
        assert app.coding_assistant is not None  # coder enabled → assistant wired

        # `status` (owner) sends one owner line through the notifier without touching the
        # runner — a clean way to observe WHICH bot the coding notifier speaks through.
        await app.coding_assistant.status(sender=_OWNER_ID)
    finally:
        await app.memory_repo.close()

    # Bob's bot carried the coding-session message into Bob's topic (rich/markdown path).
    assert len(bob_bot.rich_sends) == 1
    assert bob_bot.rich_sends[0].chat_id == _CHAT_ID
    assert bob_bot.rich_sends[0].message_thread_id == _BOB_TOPIC_ID
    # GUPPI's bot stayed silent — it is the under-the-hood executor, not the speaker.
    assert guppi_bot.rich_sends == []
    assert guppi_bot.plain_sends == []


def test_per_event_narrative_stays_guppi_attributed() -> None:
    # The SENDER changed (Bob speaks), but the per-event narrative TEXT is canon and
    # untouched: GUPPI executes, so a tool event still renders «GUPPI: …».
    line = narrate(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Edit", "input": {"file_path": "x.py"}}
                ]
            },
        }
    )
    assert line is not None
    assert line.startswith("GUPPI:")
