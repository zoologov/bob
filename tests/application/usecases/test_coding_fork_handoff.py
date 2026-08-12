# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 Честная передача работы, когда PR открывает owner, а не Боб (BOB-089, срез D).

Когда рабочее место Боба — клон с единственным remote'ом на его ПРИВАТНЫЙ форк, открыть
cross-repo PR он не может (installation-токен скоупится на одну установку — не-цель PRD).
Интеграционный путь в этом случае отдаёт owner'у предзаполненную форму сравнения, и
терминальная реплика ОБЯЗАНА идти за фактом: сказать «вот PR» там, где PR не открыт, —
неправда, которую owner проверит первым же нажатием.

Здесь проверяется ровно эта развилка use-case'а через ГРАНИЦУ (что услышал owner), а не
внутреннее состояние: по умолчанию (``opens_pr=True``, gh-путь) поведение байт-в-байт
прежнее, при ``opens_pr=False`` — честная реплика со ссылкой.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.coding.state import CodingSessionState
from bob.coding.usecases.coding_assistant import CodingAssistant

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
_COMPARE_URL = (
    "https://github.com/zoologov/bob/compare/main...bobiverse-dev:bob:bob/task?expand=1"
)


@dataclass
class _FakeRunner:
    events: dict[str, list[Mapping[str, object]]] = field(default_factory=dict)

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        for event in self.events.get(mode, []):
            yield event


@dataclass
class _FakeWorkplace:
    pushes: list[tuple[str, str, str]] = field(default_factory=list)

    async def create(self, branch: str) -> str:
        return f"/clones/{branch.split('/', 1)[1]}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        self.pushes.append((path, branch, message))
        return True

    async def remove(self, path: str) -> None: ...


@dataclass
class _FakeStore:
    sessions: dict[str, CodingSession] = field(default_factory=dict)

    async def save(self, session: CodingSession) -> None:
        self.sessions[session.id] = session

    async def get(self, session_id: str) -> CodingSession | None:
        return self.sessions.get(session_id)

    async def active(self) -> tuple[CodingSession, ...]:
        return tuple(self.sessions.values())


@dataclass
class _FakeIntegration:
    """Интеграционный путь: возвращает URL (форму сравнения ИЛИ адрес открытого PR)."""

    url: str = _COMPARE_URL

    async def open(self, branch: str, title: str, body: str) -> str:
        return self.url


@dataclass
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


class _FakeOwner:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _FakeClock:
    def now(self) -> datetime:
        return _NOW


def _events() -> dict[str, list[Mapping[str, object]]]:
    return {
        "plan": [{"type": "result", "subtype": "success", "result": "Итоговый план"}],
        "acceptEdits": [{"type": "result", "subtype": "success"}],
    }


def _assistant(notifier: _FakeNotifier, **extra: object) -> CodingAssistant:
    return CodingAssistant(
        runner=_FakeRunner(events=_events()),
        worktree=_FakeWorkplace(),
        store=_FakeStore(),
        pr_opener=_FakeIntegration(),
        notifier=notifier,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        **extra,  # type: ignore[arg-type]  # композиционный флаг под тестом
    )


async def _run_to_terminal(assistant: CodingAssistant, notifier: _FakeNotifier) -> object:
    await assistant.start("Починить парсер", _OWNER_ID)
    notifier.sent.clear()
    return await assistant.approve_plan(_OWNER_ID)


@pytest.mark.asyncio
async def test_on_the_fork_path_bob_hands_the_link_over_without_claiming_a_pr() -> None:
    notifier = _FakeNotifier()
    assistant = _assistant(notifier, opens_pr=False)

    outcome = await _run_to_terminal(assistant, notifier)

    assert outcome.ok is True  # type: ignore[attr-defined]
    said = "\n".join(notifier.sent)
    assert _COMPARE_URL in said
    assert "форк" in said.casefold()
    assert "открыл PR" not in said  # 🔴 ни одного заявления о совершённом действии
    assert "PR открыт" not in said


@pytest.mark.asyncio
async def test_the_default_gh_path_keeps_the_previous_pr_message() -> None:
    # OFF-путь (композиция ничего не передала) — прежняя реплика, байт-в-байт.
    notifier = _FakeNotifier()
    assistant = _assistant(notifier)

    await _run_to_terminal(assistant, notifier)

    said = "\n".join(notifier.sent)
    assert "Вот PR" in said
    assert "Create pull request" not in said


@pytest.mark.asyncio
async def test_the_work_still_reaches_the_fork_branch_before_the_link() -> None:
    # Ссылка не заменяет интеграцию: ветка сначала уезжает в форк, и только потом Боб
    # отдаёт форму — иначе owner получил бы ссылку на пустое сравнение.
    notifier = _FakeNotifier()
    workplace = _FakeWorkplace()
    assistant = CodingAssistant(
        runner=_FakeRunner(events=_events()),
        worktree=workplace,
        store=_FakeStore(),
        pr_opener=_FakeIntegration(),
        notifier=notifier,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        opens_pr=False,
    )

    outcome = await _run_to_terminal(assistant, notifier)

    assert len(workplace.pushes) == 1
    assert workplace.pushes[0][1].startswith("bob/")
    assert outcome.session.state is CodingSessionState.PR_OPEN  # type: ignore[attr-defined]
    assert outcome.session.pr_url == _COMPARE_URL  # type: ignore[attr-defined]
