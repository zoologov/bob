# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Boundary-харнесс сценариев канона GUPPI (BOB-090.D, US-4).

Один прогон полной гейтед-сессии даёт СРАЗУ обе наблюдаемые стороны канона:

* **кто говорил** — две записывающие «телеграм-личности» (:class:`RecordingBot` Боба и
  GUPPI) под НАСТОЯЩИМ транспортным адаптером
  :class:`~bob.coding.adapters.owner_notifier._CodingOwnerNotifier`, так что видно ровно
  то, что увидел бы человек в чате: какая строка каким ботом пришла;
* **что осталось в памяти** — эпизоды читаются прямо из НАСТОЯЩЕЙ SQLite, а оба пишущих
  в память тракта включены в худшем для нас положении (реальная автобиография + рабочий
  журнал с нарочно «дырявым» эхо-дистиллятором). Если бы машинная строка GUPPI могла
  добраться до памяти, этот прогон бы её показал.

🔴 Почему одним прогоном: голос Боба воспроизводится по recall (BOB-022 / 074 / 078), и
вопрос «чей это был голос» осмысленен только вместе с «что от него осело». Разъединённые
проверки допускают мир, где канал разошёлся с памятью.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.application.runtime.events import MessageReceived
from bob.coding.adapters.owner_notifier import _CodingOwnerNotifier
from bob.coding.usecases.coding_assistant import CodingAssistant
from bob.coding.usecases.work_journal_recorder import DistillingWorkJournalRecorder
from bob.memory.adapters.self_action_recorder import MemoryBackedSelfActionRecorder
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.work_journal import WorkEpisode
from tests.acceptance.guppi_channel_harness import (
    BOB_TOPIC_ID as SESSION_TOPIC_ID,
)
from tests.acceptance.guppi_channel_harness import (
    CHAT_ID as SESSION_CHAT_ID,
)
from tests.acceptance.guppi_channel_harness import (
    OWNER_ID,
    _FakeClock,
    _FakeOwner,
    _FakePROpener,
    _FakeRunner,
    _FakeStore,
    _FakeWorktree,
    _ids,
    execute_events,
)
from tests.acceptance.live_app_harness import (
    BOB_TOPIC_ID,
    GROUP_CHAT_ID,
    NORMAN_ID,
    NORMAN_NAME,
    NORMAN_USERNAME,
    RecordingBot,
    SentLine,
    Tier0Provider,
    Tier1Provider,
    build_live_app,
    remember_norman,
    remember_owner,
)

if TYPE_CHECKING:
    from pathlib import Path

    from bob.coding.work_facts import SessionKeyFacts, WorkOutcome

__all__ = [
    "GUPPI_PREFIX",
    "CanonOutcome",
    "PermissionOutcome",
    "run_coding_session",
    "run_permission_ask",
]

# Как машинная строка выглядит в чате: пер-событийный нарратив атрибутирован исполнителю.
GUPPI_PREFIX = "GUPPI: "


class _EchoDistiller:
    """Дистиллятор-эхо: выливает в эпизод ВСЁ, что дошло до снимка фактов сессии.

    Нарочно «дырявый» — так сценарий видит не только то, что пишется сегодня, но и всё,
    что вообще способно доехать до памяти этим трактом.
    """

    async def distill(
        self, task: str, facts: SessionKeyFacts, outcome: WorkOutcome
    ) -> tuple[WorkEpisode, ...]:
        return (WorkEpisode(content=f"я вёл сессию «{task}»: {facts} → {outcome}"),)


@dataclass(slots=True)
class CanonOutcome:
    """Наблюдаемое: какой бот что сказал и что от сессии осталось в памяти."""

    bob: RecordingBot
    guppi: RecordingBot
    episodes: tuple[tuple[str, str], ...] = ()

    @property
    def remembered(self) -> tuple[str, ...]:
        """Содержимое всех эпизодов, осевших за прогон."""
        return tuple(content for _, content in self.episodes)

    def remembers(self, event_type: str) -> bool:
        """Есть ли в памяти хоть один эпизод такого рода (позитивный контроль)."""
        return any(kind == event_type for kind, _ in self.episodes)

    @staticmethod
    def carried(bot: RecordingBot, needle: str) -> bool:
        """Несла ли хоть одна строка этого бота ``needle``."""
        return any(needle in line.text for line in bot.sent)


async def run_coding_session(
    tmp_path: Path, *, stream_via_guppi: bool
) -> CanonOutcome:
    """Провести полную сессию (план → апрув → PR) и вернуть наблюдаемое.

    ``stream_via_guppi`` — тот же единственный тумблер, что и в композиционном корне: ON →
    у GUPPI ОТДЕЛЬНЫЙ канал (свой бот), OFF → канала нет и всё уходит ботом Боба, как до
    среза (нулевой регресс).
    """
    bob_bot, guppi_bot = RecordingBot("bob"), RecordingBot("guppi")
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    clock = _FakeClock()
    assistant = CodingAssistant(
        runner=_FakeRunner(
            events={
                "plan": [
                    {"type": "result", "subtype": "success", "result": "Итоговый план"}
                ],
                "acceptEdits": execute_events(),
            }
        ),
        worktree=_FakeWorktree(),
        store=_FakeStore(),
        pr_opener=_FakePROpener(),
        notifier=_notifier(bob_bot),
        stream_notifier=_notifier(guppi_bot) if stream_via_guppi else None,
        owner=_FakeOwner(),
        clock=clock,
        id_factory=_ids(),
        # Оба пишущих в память тракта — НАСТОЯЩИЕ и включены (худший случай).
        recorder=MemoryBackedSelfActionRecorder(repo, clock=clock),
        work_journal=DistillingWorkJournalRecorder(
            distiller=_EchoDistiller(), store=repo, clock=clock
        ),
    )
    try:
        await assistant.start("Починить парсер", OWNER_ID)
        await assistant.approve_plan(OWNER_ID)
    finally:
        await repo.close()
    return CanonOutcome(
        bob=bob_bot, guppi=guppi_bot, episodes=_episodes(tmp_path / "bob.db")
    )


@dataclass(slots=True)
class PermissionOutcome:
    """Наблюдаемое у просьбы о разрешении: кто, каким ботом и в какой топик сказал."""

    bob: RecordingBot
    guppi: RecordingBot
    judge_verdict: str = ""

    @property
    def to_owner(self) -> SentLine | None:
        """Первая реплика Боба — та самая просьба к owner'у (или ``None``)."""
        return self.bob.sent[0] if self.bob.sent else None

    @property
    def to_requester(self) -> SentLine | None:
        """Вторая реплика Боба — лёгкий ack просителю (или ``None``)."""
        return self.bob.sent[1] if len(self.bob.sent) > 1 else None


async def run_permission_ask(
    tmp_path: Path,
    *,
    request: str,
    kind: str = "owner_data",
    judge_what: str = "Requesting details of private conversations with another user",
    owner_username: str | None = None,
) -> PermissionOutcome:
    """Прогнать привилегированную просьбу ЧУЖОГО человека через живой корень.

    Норман здесь не авторизован — ровно тот случай, ради которого гейт и заведён. Судья
    привилегий (Tier-0) возвращает свой ВНУТРЕННИЙ вердикт, в том числе английскую
    служебную фразу ``judge_what``: сценарий проверяет, что наружу она не произносится.
    ``owner_username`` — ник owner'а в живом ростере (``None`` = ника нет).
    """
    bob_bot, guppi_bot = RecordingBot("bob"), RecordingBot("guppi")
    tier0 = Tier0Provider(privilege={"kind": kind, "what": judge_what})
    app = build_live_app(
        tmp_path,
        tier0=tier0,
        tier1=Tier1Provider(reply="Ага."),
        bob_bot=bob_bot,
        guppi_bot=guppi_bot,
    )
    await app.startup()
    try:
        await remember_norman(app, username=NORMAN_USERNAME)
        if owner_username is not None:
            await remember_owner(app, username=owner_username)
        await app.event_bus.publish(
            MessageReceived(
                update_id=1,
                chat_id=GROUP_CHAT_ID,
                message_id=41,
                text=request,
                sender_id=NORMAN_ID,
                sender_name=NORMAN_NAME,
                sender_username=NORMAN_USERNAME,
                is_group=True,
                topic_id=BOB_TOPIC_ID,
            )
        )
    finally:
        await app.shutdown()
    return PermissionOutcome(bob=bob_bot, guppi=guppi_bot, judge_verdict=judge_what)


def _notifier(bot: RecordingBot) -> _CodingOwnerNotifier:
    """Настоящий транспортный адаптер над записывающим ботом этой личности."""
    return _CodingOwnerNotifier(
        bot=bot, chat_id=SESSION_CHAT_ID, topic_id=SESSION_TOPIC_ID
    )


def _episodes(db: Path) -> tuple[tuple[str, str], ...]:
    """Прочитать ``(event_type, content)`` всех эпизодов из настоящей базы."""
    connection = sqlite3.connect(db)
    try:
        rows = connection.execute(
            "SELECT event_type, content FROM episodic_log ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    return tuple((str(kind), str(content)) for kind, content in rows)
