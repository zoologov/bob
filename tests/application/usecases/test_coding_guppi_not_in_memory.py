# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 Реплики GUPPI не попадают в память как голос Боба (BOB-090.D2).

Голос Боба воспроизводится по recall: что осело в эпизодах, то он потом мимикрирует
(BOB-022 / 074 / 078). Значит, механические строки GUPPI («GUPPI: правлю `parser.py`»)
обязаны остаться ТРАНСПОРТОМ — их место в чате, а не в памяти. Иначе сухой машинный
тон вернётся в живую речь Боба через несколько ходов, и канон разъедет сам себя.

Тест гоняет ПОЛНУЮ гейтед-сессию с включённым каналом GUPPI и с обоими пишущими в
память трактами В ХУДШЕМ для нас положении (оба ON, а в живом конфиге они за флагами):

* автобиография — РЕАЛЬНЫЙ :class:`MemoryBackedSelfActionRecorder`;
* рабочий журнал — РЕАЛЬНЫЙ :class:`DistillingWorkJournalRecorder` с дистиллятором,
  который ЭХОМ выливает в эпизод всё, что ему передали (если бы строка GUPPI дошла до
  снимка фактов, она бы осела в памяти — и тест бы это увидел);

и читает эпизоды из НАСТОЯЩЕЙ SQLite-базы напрямую (не через фейк-стор — урок §0.3 п.4:
тест на фейке доказывает контракт фейка). Позитивный контроль обязателен: память в этом
прогоне ПИСАЛАСЬ (поступки Боба от первого лица на месте), так что «ничего не нашли» —
не пустой ассерт.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.coding.state import is_terminal
from bob.coding.usecases.coding_assistant import CodingAssistant
from bob.coding.usecases.work_journal_recorder import DistillingWorkJournalRecorder
from bob.memory.adapters.self_action_recorder import MemoryBackedSelfActionRecorder
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.work_journal import WorkEpisode

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping
    from pathlib import Path

    from bob.coding.entities import CodingSession
    from bob.coding.work_facts import SessionKeyFacts, WorkOutcome

_OWNER_ID = 27468732
_NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


@dataclass
class _FakeRunner:
    events: dict[str, list[Mapping[str, object]]] = field(default_factory=dict)

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        for event in self.events.get(mode, []):
            yield event


@dataclass
class _FakeWorktree:
    async def create(self, branch: str) -> str:
        return f"/wt/{branch.split('/', 1)[1]}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        return True

    async def remove(self, path: str) -> None:
        return None


@dataclass
class _FakeStore:
    sessions: dict[str, CodingSession] = field(default_factory=dict)

    async def save(self, session: CodingSession) -> None:
        self.sessions[session.id] = session

    async def get(self, session_id: str) -> CodingSession | None:
        return self.sessions.get(session_id)

    async def active(self) -> tuple[CodingSession, ...]:
        ordered = sorted(self.sessions.values(), key=lambda s: (s.created_at, s.id))
        return tuple(s for s in ordered if not is_terminal(s.state))


@dataclass
class _FakePROpener:
    async def open(self, branch: str, title: str, body: str) -> str:
        return "https://github.com/x/bob/pull/11"


@dataclass
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


@dataclass
class _FakeOwner:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


@dataclass
class _FakeClock:
    def now(self) -> datetime:
        return _NOW


class _EchoDistiller:
    """Дистиллятор-эхо: выливает в эпизод ВСЁ, что дошло до снимка фактов сессии.

    Нарочно «дырявый» — так тест видит не только то, что мы пишем сегодня, но и всё,
    что вообще способно доехать до памяти этим трактом.
    """

    async def distill(
        self, task: str, facts: SessionKeyFacts, outcome: WorkOutcome
    ) -> tuple[WorkEpisode, ...]:
        return (WorkEpisode(content=f"я вёл сессию «{task}»: {facts} → {outcome}"),)


def _ids() -> Callable[[], str]:
    counter = {"n": 0}

    def _factory() -> str:
        counter["n"] += 1
        return f"cs-{counter['n']}"

    return _factory


def _edit(path: str) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": path}}]
        },
    }


def _episodes(db: Path) -> list[tuple[str, str]]:
    """Прочитать (event_type, content) ВСЕХ эпизодов из настоящей базы."""
    connection = sqlite3.connect(db)
    try:
        rows = connection.execute(
            "SELECT event_type, content FROM episodic_log ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    return [(str(kind), str(content)) for kind, content in rows]


@pytest.mark.asyncio
async def test_guppi_lines_never_land_in_memory_as_bobs_voice(tmp_path: Path) -> None:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    clock = _FakeClock()
    guppi = _FakeNotifier()
    bob = _FakeNotifier()
    assistant = CodingAssistant(
        runner=_FakeRunner(
            events={
                "plan": [
                    {"type": "result", "subtype": "success", "result": "Итоговый план"}
                ],
                "acceptEdits": [
                    _edit("parser.py"),
                    _edit("tokenizer.py"),
                    {"type": "result", "subtype": "success"},
                ],
            }
        ),
        worktree=_FakeWorktree(),
        store=_FakeStore(),
        pr_opener=_FakePROpener(),
        notifier=bob,
        stream_notifier=guppi,  # канал GUPPI включён (флаг ON)
        owner=_FakeOwner(),
        clock=clock,
        id_factory=_ids(),
        # Оба пишущих в память тракта — РЕАЛЬНЫЕ и включены (худший случай).
        recorder=MemoryBackedSelfActionRecorder(repo, clock=clock),
        work_journal=DistillingWorkJournalRecorder(
            distiller=_EchoDistiller(), store=repo, clock=clock
        ),
    )

    await assistant.start("Починить парсер", _OWNER_ID)
    outcome = await assistant.approve_plan(_OWNER_ID)
    await repo.close()

    assert outcome.ok is True
    assert guppi.sent, "механика вообще должна была уйти каналом GUPPI"
    episodes = _episodes(tmp_path / "bob.db")

    # Позитивный контроль: память в этом прогоне ПИСАЛАСЬ — иначе ассерты ниже пустые.
    assert any(kind == "self_action" for kind, _ in episodes)
    assert any(kind == "work" for kind, _ in episodes)

    remembered = [content for _, content in episodes]
    # 1) Ни одна отправленная GUPPI строка не осела в памяти.
    for line in guppi.sent:
        assert all(line not in content for content in remembered), line
    # 2) И шире: в памяти нет ни одной машинной строки его канала.
    assert all("GUPPI: " not in content for content in remembered)


@pytest.mark.asyncio
async def test_memory_keeps_bobs_own_first_person_deed(tmp_path: Path) -> None:
    """Обратная сторона: не «память молчит», а «в памяти ровно голос Боба».

    Осевшее — его поступок от ПЕРВОГО ЛИЦА (self_action) и его операторская вспоминка
    (work). Именно это и должно потом припоминаться, а не отчёт исполнителя.
    """
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    clock = _FakeClock()
    assistant = CodingAssistant(
        runner=_FakeRunner(
            events={
                "plan": [
                    {"type": "result", "subtype": "success", "result": "Итоговый план"}
                ],
                "acceptEdits": [_edit("parser.py"), {"type": "result", "subtype": "success"}],
            }
        ),
        worktree=_FakeWorktree(),
        store=_FakeStore(),
        pr_opener=_FakePROpener(),
        notifier=_FakeNotifier(),
        stream_notifier=_FakeNotifier(),
        owner=_FakeOwner(),
        clock=clock,
        id_factory=_ids(),
        recorder=MemoryBackedSelfActionRecorder(repo, clock=clock),
        work_journal=DistillingWorkJournalRecorder(
            distiller=_EchoDistiller(), store=repo, clock=clock
        ),
    )

    await assistant.start("Починить парсер", _OWNER_ID)
    await assistant.approve_plan(_OWNER_ID)
    await repo.close()

    deeds = [content for kind, content in _episodes(tmp_path / "bob.db") if kind == "self_action"]
    assert deeds
    assert any(content.startswith("я ") or content.startswith("Я ") for content in deeds)
