# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 Acceptance/guardrails for BOB-046 block A — голос Боба + индикатор + арх-контекст.

Эти тесты — ПОВЕДЕНЧЕСКИЕ инварианты блока A поверх отдельных .1/.2/.3-юнитов
(``test_coding_sender_is_bob`` / ``test_coding_work_indicator`` /
``test_coding_context``), которые те не выражают целиком:

* **Голос Боба (полная сессия):** прогон plan → approve → PR через РЕАЛЬНЫЙ
  ``_CodingOwnerNotifier`` поверх бота Боба шлёт ВСЕ owner-реплики (берусь / план /
  нарратив / PR) через бот Боба rich-путём; бот GUPPI молчит; per-event нарратив
  по-прежнему GUPPI-атрибутирован («GUPPI: …»).
* **Индикатор:** kill-switch финализирует живую панель в ⏹️ (одно editable сообщение,
  не спам) — фаза стопа, которую .2-юнит не покрывает.
* **🔴 Арх-контекст приватность/бэкстоп:** sanitize ВЫРЕЗАЕТ секрет, просочившийся
  через разрешённый шов ``architecture_context`` (не только denied-doc-path); denied
  корни (``config`` / ``data/bob.db`` / ``.env`` / ``data/soul``) не читаются и не
  попадают в префикс; объём ограничен.
* **🔴 Регрессии (additive):** со ВСЕМИ швами блока A (typing + panel + context)
  гейт плана держится — не-owner отказан на каждом мутаторе, свежая сессия не
  апрувится, апрув без PLAN_READY не даёт EXECUTING; стоп без сессии чист.

Всё на ФЕЙКАХ (бот / typing / panel / context / runner) — никакого живого
LLM / Telegram / git.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from bob.app import _CodingOwnerNotifier
from bob.coding import session_voice
from bob.coding.state import CodingSessionState, is_terminal
from bob.coding.usecases.coding_assistant import CodingAssistant
from bob.coding.usecases.coding_context import (
    PREAMBLE_MAX_CHARS,
    make_coding_context,
)
from bob.domain.introspection.privacy_guard import PrivacyGuard

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from aiogram.types import InputRichMessage

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_GUEST_ID = 99
_NOW = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)
_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 77
_ARCH_DOC = "docs/architecture.md"


# --- Shared fakes ------------------------------------------------------------


@dataclass
class _FakeMessage:
    message_id: int = 1
    text: str | None = None
    message_thread_id: int | None = None


@dataclass
class _Rich:
    chat_id: int
    markdown: str | None
    message_thread_id: int | None


@dataclass
class _Plain:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
    """Records which sends it received (Bob vs GUPPI identity), rich + plain paths."""

    rich: list[_Rich] = field(default_factory=list)
    plain: list[_Plain] = field(default_factory=list)

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        self.rich.append(_Rich(chat_id, rich_message.markdown, message_thread_id))
        return _FakeMessage(text=rich_message.markdown)

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> _FakeMessage:
        self.plain.append(_Plain(chat_id, text, message_thread_id))
        return _FakeMessage(text=text)

    def markdowns(self) -> list[str]:
        """All markdown strings Bob's bot was asked to send (rich path)."""
        return [r.markdown or "" for r in self.rich]


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
    opens: list[tuple[str, str, str]] = field(default_factory=list)

    async def open(self, branch: str, title: str, body: str) -> str:
        self.opens.append((branch, title, body))
        return self.url


@dataclass
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


@dataclass
class _FakePanel:
    opens: list[str] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)

    async def open(self, text: str) -> None:
        self.opens.append(text)

    async def update(self, text: str) -> None:
        self.updates.append(text)


@dataclass
class _CountingTyping:
    enters: int = 0

    def __call__(self) -> _CountingTyping._Cm:
        return _CountingTyping._Cm(self)

    @dataclass
    class _Cm:
        owner: _CountingTyping

        async def __aenter__(self) -> None:
            self.owner.enters += 1

        async def __aexit__(self, *exc: object) -> None:
            return None


@dataclass
class _FakeContext:
    text: str = "ПРЕФИКС-КОНТЕКСТА"
    calls: int = 0

    async def preamble(self, task: str) -> str:
        self.calls += 1
        return self.text


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


def _edit_event(path: str) -> Mapping[str, object]:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": path}}]
        },
    }


def _events() -> dict[str, list[Mapping[str, object]]]:
    return {
        "plan": [{"type": "result", "subtype": "success", "result": "Итоговый план"}],
        "acceptEdits": [_edit_event("f.py"), {"type": "result", "subtype": "success"}],
    }


def _assistant(
    *,
    notifier: object,
    runner: _FakeRunner | None = None,
    worktree: _FakeWorktree | None = None,
    store: _FakeStore | None = None,
    pr_opener: _FakePROpener | None = None,
    typing: object | None = None,
    panel: object | None = None,
    context: object | None = None,
) -> CodingAssistant:
    return CodingAssistant(
        runner=runner or _FakeRunner(events=_events()),
        worktree=worktree or _FakeWorktree(),
        store=store or _FakeStore(),
        pr_opener=pr_opener or _FakePROpener(),
        notifier=notifier,  # type: ignore[arg-type]
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        typing_keepalive=typing,  # type: ignore[arg-type]
        status_panel=panel,  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
    )


# --- Theme 1: Bob's voice — a whole session speaks through Bob's bot ----------


@pytest.mark.asyncio
async def test_full_session_speaks_through_bobs_bot_guppi_silent() -> None:
    # Arrange: the REAL owner-notifier over Bob's bot; a separate GUPPI bot that must
    # stay silent. A fake runner drives plan → an edit narrative → result.
    bob_bot = _FakeBot()
    guppi_bot = _FakeBot()
    notifier = _CodingOwnerNotifier(
        bot=bob_bot, chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID
    )
    runner = _FakeRunner(events=_events())
    pr_opener = _FakePROpener()
    assistant = _assistant(notifier=notifier, runner=runner, pr_opener=pr_opener)

    # Act: a full gated session.
    await assistant.start("Добавить ручку health", _OWNER_ID)
    approved = await assistant.approve_plan(_OWNER_ID)

    # Assert: the session completed and EVERY owner-facing line went through Bob's bot
    # (rich/markdown path) into Bob's topic — GUPPI's bot never spoke.
    assert approved.ok is True
    assert approved.session is not None
    assert approved.session.state is CodingSessionState.PR_OPEN
    assert guppi_bot.rich == []
    assert guppi_bot.plain == []
    assert all(r.chat_id == _CHAT_ID for r in bob_bot.rich)
    assert all(r.message_thread_id == _BOB_TOPIC_ID for r in bob_bot.rich)

    sent = bob_bot.markdowns()
    # Bob accepts in the first person, presents the plan, then reports the PR.
    assert session_voice.accepted() in sent
    assert any("Итоговый план" in m for m in sent)
    assert any(pr_opener.url in m for m in sent)
    # 🔴 The per-event narrative TEXT stays GUPPI-attributed even though Bob is the
    # speaker: a tool event renders «GUPPI: …».
    assert any(m.startswith("GUPPI:") for m in sent)


# --- Theme 2: work indicator — kill-switch finalizes the live panel to ⏹️ -----


@pytest.mark.asyncio
async def test_stop_finalizes_status_panel_to_stopped() -> None:
    panel = _FakePanel()
    assistant = _assistant(notifier=_FakeNotifier(), panel=panel)

    await assistant.start("Добавить ручку health", _OWNER_ID)
    outcome = await assistant.stop(_OWNER_ID)

    # ONE message opened, then EDITED through to the stopped phase — never a re-send.
    assert outcome.ok is True
    assert panel.opens == [session_voice.panel_planning()]
    assert panel.updates[-1] == session_voice.panel_stopped()
    assert session_voice.panel_pr() not in panel.updates


# --- Theme 3: arch-context privacy backstop + bound --------------------------


@pytest.mark.asyncio
async def test_sanitize_backstop_redacts_secret_from_arch_context() -> None:
    # A secret that slips through the ALLOWED architecture_context seam is scrubbed by
    # the sanitize() backstop — not only denied DOC PATHS are protected.
    @dataclass
    class _LeakyIntrospector:
        async def read_file(self, path: str, *, max_lines: int) -> str:
            return ""

        async def architecture_context(self, ref: str) -> str:
            return "Слой application.\nsk-LIVEKEY1234567\nAPI_KEY=topsecret\n"

    builder = make_coding_context(
        _LeakyIntrospector(), PrivacyGuard(repo_root=Path("/repo"))
    )

    preamble = await builder.preamble("задача")

    assert "sk-LIVEKEY1234567" not in preamble
    assert "topsecret" not in preamble
    assert "[REDACTED]" in preamble  # the backstop fired
    assert "application" in preamble  # public structure survives


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "denied",
    [
        "config/secrets.yaml",
        "data/bob.db",
        ".env.local",
        "data/soul/SOUL.md",
        "../../etc/passwd",
        ".claude/settings.json",
    ],
)
async def test_denied_doc_root_is_never_read_or_included(denied: str) -> None:
    @dataclass
    class _RecordingIntrospector:
        reads: list[str] = field(default_factory=list)

        async def read_file(self, path: str, *, max_lines: int) -> str:
            self.reads.append(path)
            return "SECRET-PAYLOAD"

        async def architecture_context(self, ref: str) -> str:
            return ""

    introspector = _RecordingIntrospector()
    builder = make_coding_context(
        introspector,
        PrivacyGuard(repo_root=Path("/repo")),
        doc_paths=(denied,),
    )

    preamble = await builder.preamble("задача")

    # 🔴 The guard rejects the path BEFORE any read — never requested, never included.
    assert introspector.reads == []
    assert "SECRET-PAYLOAD" not in preamble


@pytest.mark.asyncio
async def test_preamble_bounded_even_with_arch_and_doc_flood() -> None:
    huge = "B" * 80_000

    @dataclass
    class _FloodIntrospector:
        async def read_file(self, path: str, *, max_lines: int) -> str:
            return huge

        async def architecture_context(self, ref: str) -> str:
            return huge

    builder = make_coding_context(
        _FloodIntrospector(),
        PrivacyGuard(repo_root=Path("/repo")),
        doc_paths=(_ARCH_DOC,),
    )

    preamble = await builder.preamble("задача")

    assert len(preamble) <= PREAMBLE_MAX_CHARS


# --- Theme 4: regressions — block-A additions are ADDITIVE, gate intact ------


@pytest.mark.asyncio
async def test_non_owner_refused_on_every_mutator_with_all_seams_wired() -> None:
    # With typing + panel + context ALL wired, a non-owner is still refused on every
    # mutator: no session, no run, no context lookup, no status panel — the additions
    # never weaken the owner gate.
    runner = _FakeRunner(events=_events())
    panel = _FakePanel()
    typing = _CountingTyping()
    context = _FakeContext()
    store = _FakeStore()
    assistant = _assistant(
        notifier=_FakeNotifier(),
        runner=runner,
        store=store,
        typing=typing,
        panel=panel,
        context=context,
    )

    refusals = [
        await assistant.start("взлом", _GUEST_ID),
        await assistant.approve_plan(_GUEST_ID),
        await assistant.stop(_GUEST_ID),
    ]
    for outcome in refusals:
        assert outcome.ok is False
        assert outcome.message == ""  # a silent refusal — nothing leaked to the guest

    assert runner.calls == []  # the runner never ran for a non-owner
    assert context.calls == 0  # no context preamble was even built
    assert panel.opens == []
    assert panel.updates == []
    assert typing.enters == 0
    assert store.sessions == {}  # no session was ever created


@pytest.mark.asyncio
async def test_approve_without_plan_ready_never_executes_with_seams_wired() -> None:
    # No session exists yet → an approve cannot reach EXECUTING (the plan gate), even
    # with every block-A seam wired. The runner is never asked to apply edits.
    runner = _FakeRunner(events=_events())
    context = _FakeContext()
    assistant = _assistant(
        notifier=_FakeNotifier(),
        runner=runner,
        typing=_CountingTyping(),
        panel=_FakePanel(),
        context=context,
    )

    outcome = await assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is False
    assert outcome.message == session_voice.cannot_approve()
    assert [mode for *_rest, mode in runner.calls] == []  # nothing ran, no edits applied


@pytest.mark.asyncio
async def test_context_preamble_prepended_to_plan_prompt_when_wired() -> None:
    # The additive arch-context is genuinely prepended ahead of the base task prompt
    # (order matters: the context frames the task, it does not replace it).
    runner = _FakeRunner(events=_events())
    assistant = _assistant(
        notifier=_FakeNotifier(),
        runner=runner,
        context=_FakeContext(text="ПРЕФИКС-КОНТЕКСТА"),
    )

    await assistant.start("Добавить ручку health", _OWNER_ID)

    plan_prompt = next(p for _w, p, mode in runner.calls if mode == "plan")
    assert plan_prompt.startswith("ПРЕФИКС-КОНТЕКСТА")
    assert plan_prompt.index("ПРЕФИКС-КОНТЕКСТА") < plan_prompt.index("Добавить ручку health")


@pytest.mark.asyncio
async def test_stop_without_active_session_reports_no_session() -> None:
    # A kill-switch with nothing running is a clean no-op report — no session, no panel
    # churn (covers the "no active session" stop branch).
    panel = _FakePanel()
    assistant = _assistant(notifier=_FakeNotifier(), panel=panel)

    outcome = await assistant.stop(_OWNER_ID)

    assert outcome.ok is False
    assert outcome.message == session_voice.no_session()
    assert outcome.session is None
    assert panel.opens == []
    assert panel.updates == []
