# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Маршрутизация реплик coding-сессии по вердикту ядра «кто говорит» (BOB-090.D2).

Канон: механику озвучивает GUPPI (сухой исполнитель, свой бот), живое и адресованное
людям — Боб (его бот). Раньше расклад по каналам был РАЗМАЗАН по местам отправки — тут
пинуется, что он идёт от ЧИСТОГО ЯДРА :func:`~bob.coding.speaker.speaker_for`:

* :func:`~bob.coding.usecases.coding_assistant.notifier_for` переводит вердикт в канал
  для КАЖДОГО вида сообщения (никакой ветки «мимо канона» не остаётся);
* полный прогон сессии раскладывается по двум каналам ЦЕЛИКОМ (равенство множеств, а
  не «где-то встречается»), включая финальный технический итог;
* OFF-путь (нет отдельного канала GUPPI) — один нотификатор, байт-в-байт как раньше.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.coding import session_voice
from bob.coding.speaker import MessageKind, Speaker, speaker_for
from bob.coding.state import is_terminal
from bob.coding.usecases.coding_assistant import CodingAssistant, notifier_for

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
_PR_URL = "https://github.com/x/bob/pull/9"


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
        return _PR_URL


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


def _edit(path: str) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": path}}]
        },
    }


def _build(
    *, notifier: _FakeNotifier, stream_notifier: _FakeNotifier | None = None
) -> CodingAssistant:
    runner = _FakeRunner(
        events={
            "plan": [{"type": "result", "subtype": "success", "result": "Итоговый план"}],
            "acceptEdits": [_edit("parser.py"), {"type": "result", "subtype": "success"}],
        }
    )
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


@pytest.mark.parametrize("kind", list(MessageKind))
def test_channel_of_every_kind_follows_the_core_verdict(kind: MessageKind) -> None:
    bob = _FakeNotifier()
    guppi = _FakeNotifier()

    chosen = notifier_for(kind, bob=bob, guppi=guppi)

    expected = guppi if speaker_for(kind) is Speaker.GUPPI else bob
    assert chosen is expected


def test_off_path_routes_every_kind_to_the_single_channel() -> None:
    # Флаг OFF: канала GUPPI нет, оба голоса живут в одном нотификаторе — как раньше.
    only = _FakeNotifier()

    assert all(notifier_for(kind, bob=only, guppi=only) is only for kind in MessageKind)


@pytest.mark.asyncio
async def test_whole_session_splits_between_the_two_voices() -> None:
    bob = _FakeNotifier()
    guppi = _FakeNotifier()
    assistant = _build(notifier=bob, stream_notifier=guppi)

    await assistant.start("Починить парсер", _OWNER_ID)
    outcome = await assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is True
    # Живое (гейты сессии) — ЦЕЛИКОМ голосом Боба, ничего лишнего.
    assert bob.sent == [
        session_voice.accepted(),
        session_voice.plan("Итоговый план"),
        session_voice.pr(_PR_URL),
    ]
    # Механика — ЦЕЛИКОМ голосом GUPPI: пошаговый нарратив + технический итог прогона.
    assert guppi.sent == ["GUPPI: правлю `parser.py`", "GUPPI: готово"]


@pytest.mark.asyncio
async def test_technical_run_status_is_guppi_not_bob() -> None:
    # Финальный итог прогона — технический статус (RUN_STATUS), а не реплика Боба.
    bob = _FakeNotifier()
    guppi = _FakeNotifier()
    assistant = _build(notifier=bob, stream_notifier=guppi)

    await assistant.start("Починить парсер", _OWNER_ID)
    await assistant.approve_plan(_OWNER_ID)

    assert any("готово" in text for text in guppi.sent)
    assert not any(text.startswith("GUPPI: ") for text in bob.sent)
