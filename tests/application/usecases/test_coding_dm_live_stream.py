# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты маршрутизации лайв-стрима coding-прогона: DM-канал vs групповой топик (BOB-082.3).

Use-case (:class:`CodingAssistant`) остаётся transport-free — он лишь ЗНАЕТ порт
``LiveRunStreamer``. Здесь проверяем сам ВЫБОР пути в ``approve_plan`` execute-прогоне:

* завязан live-streamer (флаг ``coder.dev_dm`` ON) → сырые execute-события уходят В
  СТРИМЕР (личка), а групповой ``notifier`` получает ТОЛЬКО короткий указатель — без
  пер-правочного нарратива и без капа (INV-5: firehose не флудит группу);
* НЕ завязан (default, флаг OFF) → капнутый групповой нарратив ``narrate`` как раньше
  (нулевое изменение поведения без флага).

Рендер сырых событий в строки покрыт отдельно (test_stream_render); адаптер DM —
test_dm_live_streamer. Здесь — только развилка use-case.
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
    removed: list[str] = field(default_factory=list)
    committed: bool = True

    async def create(self, branch: str) -> str:
        return f"/wt/{branch.split('/', 1)[1]}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        return self.committed

    async def remove(self, path: str) -> None:
        self.removed.append(path)


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


@dataclass
class _RecordingStreamer:
    """Fake ``LiveRunStreamer``: records the raw events it was handed (the DM firehose)."""

    events: list[Mapping[str, object]] = field(default_factory=list)

    async def stream(
        self,
        events: AsyncIterator[Mapping[str, object]],
        *,
        is_cancelled: Callable[[], bool],
    ) -> None:
        async for event in events:
            if is_cancelled():
                break
            self.events.append(event)


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
    live_streamer: _RecordingStreamer | None = None,
) -> CodingAssistant:
    runner = _FakeRunner(events={**_plan_events(), "acceptEdits": execute})
    return CodingAssistant(
        runner=runner,
        worktree=_FakeWorktree(),
        store=_FakeStore(),
        pr_opener=_FakePROpener(),
        notifier=notifier,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        live_streamer=live_streamer,
    )


@pytest.mark.asyncio
async def test_flag_on_streams_raw_uncapped_events_to_dm_group_gets_only_pointer() -> None:
    notifier = _FakeNotifier()
    streamer = _RecordingStreamer()
    # Far more edits than the group cap — the DM firehose must take them ALL, uncapped.
    n = _MAX_NARRATION + 20
    assistant = _build(notifier=notifier, execute=_execute_events(n), live_streamer=streamer)

    await assistant.start("Починить парсер", _OWNER_ID)
    notifier.sent.clear()
    outcome = await assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is True
    # Every raw edit event (+ the result) reached the DM streamer, uncapped.
    edit_events = [e for e in streamer.events if e.get("type") == "assistant"]
    assert len(edit_events) == n
    # The GROUP notifier saw ONLY the one-line pointer during the run — no per-edit
    # narration and no "capped" notice (the firehose never floods the group; INV-5).
    assert session_voice.dev_pointer() in notifier.sent
    assert not any("правлю" in text for text in notifier.sent)
    assert session_voice.narration_capped() not in notifier.sent
    # The PR url still reaches the owner through the normal (non-firehose) notifier.
    assert any("pull/7" in text for text in notifier.sent)


@pytest.mark.asyncio
async def test_flag_off_narrates_capped_to_group_unchanged() -> None:
    notifier = _FakeNotifier()
    n = _MAX_NARRATION + 20
    assistant = _build(notifier=notifier, execute=_execute_events(n))  # no streamer → OFF

    await assistant.start("Починить парсер", _OWNER_ID)
    notifier.sent.clear()
    await assistant.approve_plan(_OWNER_ID)

    # OFF path unchanged: per-edit narration goes to the group, capped, plus one "capped"
    # notice — and NO dev-channel pointer is emitted.
    narrated = [t for t in notifier.sent if "правлю" in t]
    assert len(narrated) == _MAX_NARRATION
    assert session_voice.narration_capped() in notifier.sent
    assert session_voice.dev_pointer() not in notifier.sent
