# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты арх-контекст-префикса claude-промпта (BOB-046 .3).

Покрыто:
* префикс строится из конвенций проекта + рационала области задачи (inspect_architecture);
* объём префикса ОГРАНИЧЕН (≤ PREAMBLE_MAX_CHARS) даже на огромных входах;
* 🔴 приватный путь (``data/soul`` / ``.env``) НИКОГДА не попадает в префикс (PrivacyGuard);
* CodingAssistant подмешивает префикс в plan/execute-промпт, когда контекст-источник завязан;
* источник не завязан / пуст / упал → промпт без изменений (graceful, без падения).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from bob.coding.state import CodingSessionState, is_terminal
from bob.coding.usecases.coding_assistant import CodingAssistant
from bob.coding.usecases.coding_context import (
    PREAMBLE_MAX_CHARS,
    make_coding_context,
)
from bob.domain.introspection.privacy_guard import PrivacyGuard

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_NOW = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)
_ARCH_DOC = "docs/architecture.md"


# --- Fakes ------------------------------------------------------------------


@dataclass
class _FakeIntrospector:
    """Детерминированный порт: отдаёт замоканные файлы + арх-контекст, пишет лог чтений."""

    files: dict[str, str] = field(default_factory=dict)
    arch: dict[str, str] = field(default_factory=dict)
    reads: list[str] = field(default_factory=list)
    arch_default: str = ""

    async def read_file(self, path: str, *, max_lines: int) -> str:
        self.reads.append(path)
        return self.files.get(path, "")

    async def architecture_context(self, ref: str) -> str:
        return self.arch.get(ref, self.arch_default)


@dataclass
class _FakeContext:
    """Контекст-источник с фиксированным/падающим префиксом (для wiring-тестов)."""

    text: str = ""
    boom: bool = False

    async def preamble(self, task: str) -> str:
        if self.boom:
            raise RuntimeError("context source exploded")
        return self.text


@dataclass
class _FakeRunner:
    events: dict[str, list[Mapping[str, object]]] = field(default_factory=dict)
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        self.calls.append((workdir, prompt, mode))
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
        return "https://github.com/x/bob/pull/7"


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
        "plan": [{"type": "result", "subtype": "success", "result": "Итоговый план"}],
        "acceptEdits": [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "f.py"}}
                    ]
                },
            },
            {"type": "result", "subtype": "success"},
        ],
    }


def _assistant(context: object | None) -> tuple[CodingAssistant, _FakeRunner]:
    runner = _FakeRunner(events=_plan_events())
    assistant = CodingAssistant(
        runner=runner,
        worktree=_FakeWorktree(),
        store=_FakeStore(),
        pr_opener=_FakePROpener(),
        notifier=_FakeNotifier(),
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        context=context,  # type: ignore[arg-type]
    )
    return assistant, runner


# --- Builder: conventions + rationale ---------------------------------------


@pytest.mark.asyncio
async def test_preamble_includes_conventions_and_task_rationale() -> None:
    introspector = _FakeIntrospector(
        files={_ARCH_DOC: "# Архитектура Боба\nСлои: application/domain/infrastructure."},
        arch={"Добавить ручку health": "domain bob — слой application, шов Capability."},
    )
    builder = make_coding_context(introspector, PrivacyGuard(repo_root=Path("/repo")))

    preamble = await builder.preamble("Добавить ручку health")

    # Conventions essentials (DDD layering) AND the task-area rationale are both present.
    assert "DDD" in preamble or "domain" in preamble.lower()
    assert "Capability" in preamble
    assert "# Архитектура Боба" in preamble


@pytest.mark.asyncio
async def test_preamble_is_bounded() -> None:
    huge = "x" * 50_000
    introspector = _FakeIntrospector(
        files={_ARCH_DOC: huge}, arch={"t": huge}, arch_default=huge
    )
    builder = make_coding_context(introspector, PrivacyGuard(repo_root=Path("/repo")))

    preamble = await builder.preamble("t")

    assert len(preamble) <= PREAMBLE_MAX_CHARS


# --- Builder: privacy --------------------------------------------------------


@pytest.mark.asyncio
async def test_preamble_omits_privacy_denied_doc() -> None:
    private_text = "SOUL: интимные данные Боба"
    introspector = _FakeIntrospector(
        files={"data/soul/SOUL.md": private_text, ".env": "API_KEY=x"}
    )
    builder = make_coding_context(
        introspector,
        PrivacyGuard(repo_root=Path("/repo")),
        doc_paths=("data/soul/SOUL.md", ".env"),
    )

    preamble = await builder.preamble("любая задача")

    # Privacy-denied roots are never read and never reach the preamble.
    assert private_text not in preamble
    assert "API_KEY" not in preamble
    assert introspector.reads == []


@pytest.mark.asyncio
async def test_preamble_reads_only_allowed_docs() -> None:
    introspector = _FakeIntrospector(files={_ARCH_DOC: "слои проекта"})
    builder = make_coding_context(
        introspector,
        PrivacyGuard(repo_root=Path("/repo")),
        doc_paths=(_ARCH_DOC, "data/soul/SOUL.md"),
    )

    await builder.preamble("задача")

    assert introspector.reads == [_ARCH_DOC]


@dataclass
class _BoomIntrospector:
    """Порт, падающий на любом чтении/арх-запросе — проверка graceful-деградации."""

    async def read_file(self, path: str, *, max_lines: int) -> str:
        raise RuntimeError("read exploded")

    async def architecture_context(self, ref: str) -> str:
        raise RuntimeError("arch exploded")


@pytest.mark.asyncio
async def test_preamble_degrades_when_sources_fail() -> None:
    builder = make_coding_context(
        _BoomIntrospector(),
        PrivacyGuard(repo_root=Path("/repo")),
        doc_paths=(_ARCH_DOC,),
    )

    preamble = await builder.preamble("задача")

    # A failing doc-read / graph-query never crashes — the conventions block still stands.
    assert "DDD" in preamble
    assert "read exploded" not in preamble


# --- Wiring into CodingAssistant --------------------------------------------


@pytest.mark.asyncio
async def test_plan_prompt_includes_preamble_when_context_wired() -> None:
    assistant, runner = _assistant(_FakeContext(text="ПРЕФИКС-КОНТЕКСТА"))

    await assistant.start("Добавить ручку health", _OWNER_ID)

    plan_prompt = next(p for _, p, mode in runner.calls if mode == "plan")
    assert "ПРЕФИКС-КОНТЕКСТА" in plan_prompt
    assert "Добавить ручку health" in plan_prompt  # base prompt preserved


@pytest.mark.asyncio
async def test_execute_prompt_includes_preamble_when_context_wired() -> None:
    assistant, runner = _assistant(_FakeContext(text="ПРЕФИКС-КОНТЕКСТА"))

    await assistant.start("Добавить ручку health", _OWNER_ID)
    await assistant.approve_plan(_OWNER_ID)

    exec_prompt = next(p for _, p, mode in runner.calls if mode == "acceptEdits")
    assert "ПРЕФИКС-КОНТЕКСТА" in exec_prompt
    assert "Добавить ручку health" in exec_prompt


@pytest.mark.asyncio
async def test_prompt_unchanged_when_no_context() -> None:
    assistant, runner = _assistant(None)

    await assistant.start("Добавить ручку health", _OWNER_ID)

    plan_prompt = next(p for _, p, mode in runner.calls if mode == "plan")
    assert plan_prompt.startswith("Задача: Добавить ручку health")


@pytest.mark.asyncio
async def test_prompt_unchanged_when_context_empty() -> None:
    assistant, runner = _assistant(_FakeContext(text=""))

    await assistant.start("Добавить ручку health", _OWNER_ID)

    plan_prompt = next(p for _, p, mode in runner.calls if mode == "plan")
    assert plan_prompt.startswith("Задача: Добавить ручку health")


@pytest.mark.asyncio
async def test_context_failure_degrades_to_base_prompt() -> None:
    assistant, runner = _assistant(_FakeContext(boom=True))

    outcome = await assistant.start("Добавить ручку health", _OWNER_ID)

    # A failing context source never crashes the session — the plan still completes.
    assert outcome.ok is True
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.PLAN_READY
    plan_prompt = next(p for _, p, mode in runner.calls if mode == "plan")
    assert plan_prompt.startswith("Задача: Добавить ручку health")
