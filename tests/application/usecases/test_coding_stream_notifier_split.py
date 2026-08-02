# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты сплита каналов coding-сессии: firehose ботом GUPPI, голос Боба ботом Боба (BOB-087.A1).

Канон: GUPPI — сухой исполнитель, Боб — личность-оператор. Механический firehose
(пер-событийный ``narrate`` прогона) уходит в ОТДЕЛЬНЫЙ ``stream_notifier`` (в композиции
он строится поверх бота GUPPI, когда флаг ``coder.stream_via_guppi`` ON), а голос Боба
(гейт-реплики берусь/план/готово-PR/провал/стоп + реплика-кап «продолжаю») остаётся на
основном ``notifier`` (бот Боба). Use-case transport-free — он лишь ЗНАЕТ два порта; выбор
бота делает композиция (wiring). Здесь проверяем сам РАСКЛАД по каналам.

🔴 Инвариант OFF (без ``stream_notifier``): оба канала — один и тот же нотификатор, поведение
байт-в-байт как раньше (нулевой регресс).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.coding import session_voice
from bob.coding.state import is_terminal
from bob.coding.usecases.coding_assistant import _MAX_NARRATION, CodingAssistant

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_NOW = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)


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
    committed: bool = True

    async def create(self, branch: str) -> str:
        return f"/wt/{branch.split('/', 1)[1]}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        return self.committed

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
    url: str = "https://github.com/x/bob/pull/7"

    async def open(self, branch: str, title: str, body: str) -> str:
        return self.url


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


def _ids() -> Callable[[], str]:
    counter = {"n": 0}

    def _factory() -> str:
        counter["n"] += 1
        return f"cs-{counter['n']}"

    return _factory


def _plan_events() -> dict[str, list[Mapping[str, object]]]:
    return {
        "plan": [{"type": "result", "subtype": "success", "result": "Итоговый план"}]
    }


def _edit(path: str) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": path}}]
        },
    }


def _execute_events(n: int) -> list[Mapping[str, object]]:
    edits: list[Mapping[str, object]] = [_edit(f"f{i}.py") for i in range(n)]
    edits.append({"type": "result", "subtype": "success"})
    return edits


def _build(
    *,
    notifier: _FakeNotifier,
    execute: list[Mapping[str, object]],
    stream_notifier: _FakeNotifier | None = None,
) -> CodingAssistant:
    runner = _FakeRunner(events={**_plan_events(), "acceptEdits": execute})
    return CodingAssistant(
        runner=runner,
        worktree=_FakeWorktree(),
        store=_FakeStore(),
        pr_opener=_FakePROpener(),
        notifier=notifier,
        stream_notifier=stream_notifier,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
    )


@pytest.mark.asyncio
async def test_firehose_narration_goes_to_stream_notifier_voice_stays_on_bob() -> None:
    bob = _FakeNotifier()
    guppi = _FakeNotifier()
    assistant = _build(notifier=bob, stream_notifier=guppi, execute=_execute_events(2))

    await assistant.start("Починить парсер", _OWNER_ID)
    outcome = await assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is True
    # Пер-событийный firehose (narrate) — на канале GUPPI, не на канале Боба.
    assert any("правлю" in t for t in guppi.sent)
    assert not any("правлю" in t for t in bob.sent)
    # Голос Боба (берусь / план / готово-PR) — на канале Боба, не на GUPPI.
    assert session_voice.accepted() in bob.sent
    assert session_voice.pr("https://github.com/x/bob/pull/7") in bob.sent
    assert session_voice.accepted() not in guppi.sent
    assert not any("pull/7" in t for t in guppi.sent)


@pytest.mark.asyncio
async def test_capped_notice_is_bob_voice_flood_narration_is_firehose() -> None:
    bob = _FakeNotifier()
    guppi = _FakeNotifier()
    n = _MAX_NARRATION + 20
    assistant = _build(notifier=bob, stream_notifier=guppi, execute=_execute_events(n))

    await assistant.start("Починить парсер", _OWNER_ID)
    await assistant.approve_plan(_OWNER_ID)

    # Кап-нотис «продолжаю» — голос Боба (бот Боба), а не firehose.
    assert session_voice.narration_capped() in bob.sent
    assert session_voice.narration_capped() not in guppi.sent
    # Пер-правочный нарратив капается ровно на _MAX_NARRATION строк, и он на канале GUPPI.
    narrated = [t for t in guppi.sent if "правлю" in t]
    assert len(narrated) == _MAX_NARRATION
    assert not any("правлю" in t for t in bob.sent)


@pytest.mark.asyncio
async def test_off_path_single_notifier_is_byte_identical() -> None:
    # Без stream_notifier (флаг OFF) firehose И голос идут в ОДИН нотификатор — как раньше.
    notifier = _FakeNotifier()
    assistant = _build(notifier=notifier, execute=_execute_events(2))  # stream_notifier=None

    await assistant.start("Починить парсер", _OWNER_ID)
    await assistant.approve_plan(_OWNER_ID)

    # И firehose, и голос Боба — в одном канале (никакого раздвоения без флага).
    assert any("правлю" in t for t in notifier.sent)
    assert session_voice.accepted() in notifier.sent
    assert session_voice.pr("https://github.com/x/bob/pull/7") in notifier.sent
