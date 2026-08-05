# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Собранный запрос разрешения — на НАСТОЯЩЕЙ проводке (BOB-090.E).

🔴 Юнит на фейках доказывает контракт фейка (§0.3 п.4). Здесь тот же путь собирается
реальными деталями: настоящий SQLite (запись запроса + ростер), настоящий парсер
вердикта судьи, настоящий нотификатор поверх бота — и проверяется то, что увидит owner:

* реплика уходит БОТОМ БОБА и в ЕГО топик — запрос разрешения социальный акт, и канон
  (:func:`~bob.coding.speaker.speaker_for`) закрепляет его за Бобом, а не за GUPPI;
* в реплике нет ни английской строки судьи, ни латиницы вообще;
* owner упомянут НАСТОЯЩИМ ``@ником`` из ростера — тот берётся из живой таблицы, а не
  собирается из имени;
* ack просителю уходит в тот же топик (фикс B5 не сломан).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import pytest

from bob.memory.adapters import SqliteMemoryRepo
from bob.runtime.wiring.permission import _build_permission_flow
from bob.social.adapters.first_impression_store import SqliteFirstImpressionStore
from bob.social.first_impression import FirstImpression

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from bob.application.router.llm_router import LLMRequest, LLMRouter
    from bob.capabilities.usecases import CapabilityRegistry
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.social.usecases import Authorizer

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32
_OWNER_ID = 27468732
_NORMAN_ID = 555
_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
_ASK = "расскажи, о чём вы с Вовой говорили вчера"

# Ответ судьи ровно в том виде, в каком его отдаёт Tier-0 по размеченному контракту:
# машинный вердикт + внутренняя пометка. Наружу не должно выйти ни одно из полей.
_VERDICT = "needs_permission: да\nkind: owner_data\nwhat: Requesting private details"


class _FakeRouter:
    """Роутер, отдающий готовый вердикт судьи (сеть не трогается)."""

    def __init__(self, verdict: str) -> None:
        self._verdict = verdict
        self.prompts: list[str] = []

    async def run(self, request: LLMRequest) -> str:
        self.prompts.extend(str(message["content"]) for message in request.messages)
        return self._verdict


class _SentMessage:
    """Одна отправка ботом: куда, в какой тред и что именно."""

    def __init__(self, chat_id: int, thread: int | None, text: str) -> None:
        self.chat_id = chat_id
        self.thread = thread
        self.text = text


class _FakeMessage:
    message_id = 1


class _FakeBot:
    """Бот Боба: записывает всё, что он реально отправил."""

    def __init__(self) -> None:
        self.sent: list[_SentMessage] = []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None, **kwargs: Any
    ) -> _FakeMessage:
        del kwargs
        self.sent.append(_SentMessage(chat_id, message_thread_id, text))
        return _FakeMessage()

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: Any,
        message_thread_id: int | None = None,
        **kwargs: Any,
    ) -> _FakeMessage:
        del kwargs
        # Рич-сообщение несёт текст в ``markdown`` — сравниваем именно его, а не repr.
        markdown = str(getattr(rich_message, "markdown", rich_message))
        self.sent.append(_SentMessage(chat_id, message_thread_id, markdown))
        return _FakeMessage()


class _FixedClock:
    def now(self) -> datetime:
        return _AT


@pytest.fixture
async def repo(tmp_path: Path) -> AsyncIterator[SqliteMemoryRepo]:
    """Настоящая временная база: та же схема, что и в проде (не фейк-стор)."""
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    yield instance
    await instance.close()


async def _remember(repo: SqliteMemoryRepo, *, name: str, username: str | None) -> None:
    await SqliteFirstImpressionStore(repo).save(
        FirstImpression(
            sender_id=abs(hash(name)) % 10_000,
            first_seen_at=_AT,
            note=f"{name} — знакомый.",
            display_name=name,
            username=username,
        )
    )


async def _ask_through_the_wiring(
    repo: SqliteMemoryRepo, *, bot: _FakeBot, owner_username: str | None
) -> None:
    """Прогнать привилегированную просьбу через собранный композицией флоу."""
    await _remember(repo, name="Вова", username=owner_username)
    flow = _build_permission_flow(
        router=cast("LLMRouter", _FakeRouter(_VERDICT)),
        repo=cast("SqliteConnection", repo),
        bot=cast("BotLike", bot),
        chat_id=_CHAT_ID,
        topic_id=_BOB_TOPIC_ID,
        owner_id=_OWNER_ID,
        clock=_FixedClock(),
        authorizer=cast("Authorizer", object()),
        registry=cast("CapabilityRegistry", object()),
        tool_provider=None,
        directory=SqliteFirstImpressionStore(repo),
    )
    consumed = await flow.maybe_request(
        text=_ASK,
        requester_id=_NORMAN_ID,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )
    assert consumed is True


@pytest.mark.asyncio
async def test_the_notice_goes_out_on_bobs_bot_into_his_topic(repo: SqliteMemoryRepo) -> None:
    bot = _FakeBot()

    await _ask_through_the_wiring(repo, bot=bot, owner_username="vzoologov")

    # Оба канала — этим ботом и в топик Боба (нотис owner'у + ack просителю, фикс B5).
    assert len(bot.sent) == 2
    assert [message.chat_id for message in bot.sent] == [_CHAT_ID, _CHAT_ID]
    assert [message.thread for message in bot.sent] == [_BOB_TOPIC_ID, _BOB_TOPIC_ID]
    assert "Секунду, спрошу Вову." in bot.sent[1].text


@pytest.mark.asyncio
async def test_the_owner_reads_bobs_words_not_the_classifier(repo: SqliteMemoryRepo) -> None:
    bot = _FakeBot()

    await _ask_through_the_wiring(repo, bot=bot, owner_username="vzoologov")

    notice = bot.sent[0].text
    assert "Requesting private details" not in notice
    assert "owner_data" not in notice
    assert "Норман" in notice
    assert f"«{_ASK}»" in notice


@pytest.mark.asyncio
async def test_the_owner_is_tagged_with_the_handle_the_roster_actually_knows(
    repo: SqliteMemoryRepo,
) -> None:
    bot = _FakeBot()

    await _ask_through_the_wiring(repo, bot=bot, owner_username="vzoologov")

    assert "@vzoologov" in bot.sent[0].text


@pytest.mark.asyncio
async def test_an_owner_without_a_handle_is_addressed_by_name(repo: SqliteMemoryRepo) -> None:
    # 🔴 Из имени тег не собирается никогда — ни в инструменте отправки, ни здесь.
    bot = _FakeBot()

    await _ask_through_the_wiring(repo, bot=bot, owner_username=None)

    assert "@" not in bot.sent[0].text
    assert bot.sent[0].text.startswith("Вова,")


@pytest.mark.asyncio
async def test_the_stored_request_keeps_the_verdict_for_the_audit(repo: SqliteMemoryRepo) -> None:
    # Вердикт не выброшен — он внутренний: по записи видно, ПОЧЕМУ сработал гейт.
    bot = _FakeBot()

    await _ask_through_the_wiring(repo, bot=bot, owner_username="vzoologov")

    async with repo.connection.execute(
        "SELECT kind, what FROM permission_request WHERE requester_id = ?", (_NORMAN_ID,)
    ) as cursor:
        rows = await cursor.fetchall()
    assert [(str(row[0]), str(row[1])) for row in rows] == [
        ("owner_data", "Requesting private details")
    ]
