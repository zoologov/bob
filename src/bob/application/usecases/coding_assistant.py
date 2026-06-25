# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""CodingAssistant — гейтед оркестратор «Боб запускает Claude Code» (BOB-039 .3).

Чисто-оркестрационный use-case над ЧИСТЫМ доменом coding-сессии и инъектированными
портами (раннер Claude Code / worktree / стор / PR-открывашка / нотификатор owner /
authz / часы). Домен остаётся I/O-free; вся машинерия безопасности — здесь, и она
повторяет идиомы Goal Engine (BOB-015): owner-only на КАЖДОЙ команде, непробиваемый
гейт плана, kill-switch и честный провал с уборкой worktree.

Поток (под owner-контролем, тот же двойной гейт, что у целей):

* :meth:`start` — owner-only. Создаёт изолированный worktree на безопасной ветке
  ``bob/<slug>``, персистит сессию (``PLANNING``), гоняет раннер в режиме ``plan``
  (план БЕЗ правок — это гейт), собирает план, переводит сессию в ``PLAN_READY`` и
  ПОКАЗЫВАЕТ план owner — и ОСТАНАВЛИВАЕТСЯ (ждёт явного апрува). Исполнение здесь не
  начинается.
* :meth:`approve_plan` — owner-only, валиден ТОЛЬКО из ``PLAN_READY``
  (:func:`~bob.domain.coding.state.can_approve_plan` — гейт плана). Переводит в
  ``EXECUTING``, гоняет раннер в режиме правок, НАРРАТИТ каждое событие owner через
  :func:`~bob.domain.coding.narrate.narrate`, затем ОТКРЫВАЕТ PR
  (:meth:`PullRequestOpener.open`) и переводит в ``PR_OPEN``. 🔴 Боб НИКОГДА не мержит
  и не пушит в ``main`` — такого вызова просто нет; мерж делает owner вне Боба.
* :meth:`stop` — owner-only kill-switch: гасит идущий прогон (раннер закрывается →
  процесс убивается), переводит сессию в ``CANCELLED`` и убирает worktree.
* :meth:`status` — owner-only: текущее состояние сессии.

Worktree убирается в ``finally`` на любом завершении прогона (успех → ``PR_OPEN``,
провал → ``FAILED``, стоп → ``CANCELLED``), так что висящих worktree не остаётся.
Всё инъектируется (порты + Clock + фабрика id), поэтому use-case детерминирован в
тестах и не трогает ни настоящий ``claude``/``gh``/``git``, ни глобалы.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping
from contextlib import aclosing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from bob.domain.coding.entities import CodingSession
from bob.domain.coding.naming import worktree_branch
from bob.domain.coding.narrate import narrate
from bob.domain.coding.state import CodingSessionState, can_approve_plan, is_terminal

if TYPE_CHECKING:
    from datetime import datetime

    from bob.domain.ports import (
        ClaudeCodeRunner,
        CodingSessionStore,
        PullRequestOpener,
        Worktree,
    )

logger = logging.getLogger(__name__)

__all__ = [
    "CodingAssistant",
    "CodingOutcome",
    "OwnerCheck",
    "OwnerNotifier",
]

# The execute-mode passed to the runner when the plan is approved (apply edits inside
# the isolated worktree). The default mirrors the adapter's allowlist; the composition
# root may override via ``coder.permission_mode``.
_DEFAULT_EXECUTE_MODE = "acceptEdits"

# Plan mode is fixed: a plan with NO edits — the unbypassable plan gate.
_PLAN_MODE = "plan"

# --- Owner-facing messages (Russian — project language) -----------------------
_PLAN_HEADER = "План готов. Одобрить — /code approve, отменить — /code stop."
_NO_PLAN = "Claude Code не вернул план."
_BUSY = "Уже идёт coding-сессия — сначала заверши её (/code stop)."
_CANNOT_APPROVE = "Нет сессии, ждущей апрува плана (нужно /code <задача> и план)."
_NO_SESSION = "Активной coding-сессии нет."
_STOPPED = "Остановил coding-сессию и убрал рабочую копию."
_FAILED = "Coding-сессия сорвалась: {detail}. Рабочую копию убрал."
_PR_HEADER = "Открыл PR: {url}. Мержить — твоё дело, я в main не лезу."
_STATUS_IDLE = "Активной coding-сессии нет."
_STATUS_LINE = "Сессия «{task}» — состояние {state} (ветка {branch})."


class OwnerNotifier(Protocol):
    """Узкий порт уведомления owner: послать одну строку в его чат (GUPPI-бот).

    Реализуется в композиции адаптером над GUPPI-ботом (шлёт в General). Use-case
    шлёт сюда план, нарратив-строки прогона, URL PR и короткие подтверждения —
    единственный канал общения с owner, чтобы use-case не знал про chat_id/транспорт.
    """

    async def send(self, text: str) -> None:
        """Послать ``text`` owner (best-effort, транспорт за адаптером)."""
        ...


class OwnerCheck(Protocol):
    """Узкий порт authz: только owner управляет coding-сессией (defense-in-depth).

    Реализуется :class:`~bob.application.authz.Authorizer` (его ``is_owner``). Гейт
    дублируется на уровне GUPPI (команда от не-owner туда не доходит), но use-case
    проверяет owner на КАЖДОМ методе сам — никакой сессии/исполнения для чужого.
    """

    def is_owner(self, user_id: int | None) -> bool:
        """Является ли ``user_id`` owner'ом (единственный, кто вправе командовать)."""
        ...


@dataclass(frozen=True, slots=True)
class CodingOutcome:
    """Итог одной команды: успех/отказ, owner-сообщение и итоговая сессия.

    ``ok`` ложно при отказе authz / нелегальной команде / провале. ``message`` —
    короткий owner-текст (уже отправлен через нотификатор, кроме «тихого» отказа
    не-owner'у). ``session`` — итоговая сессия (``None``, если её нет/не создавалась).
    """

    ok: bool
    message: str
    session: CodingSession | None = None


class CodingAssistant:
    """Гейтед оркестратор coding-сессии «Боб запускает Claude Code» под owner-контролем."""

    def __init__(
        self,
        *,
        runner: ClaudeCodeRunner,
        worktree: Worktree,
        store: CodingSessionStore,
        pr_opener: PullRequestOpener,
        notifier: OwnerNotifier,
        owner: OwnerCheck,
        clock: _Clock,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
        execute_mode: str = _DEFAULT_EXECUTE_MODE,
    ) -> None:
        self._runner = runner
        self._worktree = worktree
        self._store = store
        self._pr_opener = pr_opener
        self._notifier = notifier
        self._owner = owner
        self._clock = clock
        self._id_factory = id_factory
        self._execute_mode = execute_mode
        # Per-session cancel flags: a concurrent ``stop`` adds the session id, and the
        # narrate loop breaks at the next event (closing the runner → killing the proc).
        self._cancelled: set[str] = set()

    async def start(self, task: str, sender: int | None) -> CodingOutcome:
        """Owner-only: завести сессию, построить план (гейт) и показать его owner.

        Создаёт изолированный worktree, персистит сессию в ``PLANNING``, гоняет
        раннер в режиме ``plan`` (БЕЗ правок), переводит в ``PLAN_READY`` и шлёт план
        owner. Исполнение НЕ начинается — ждём явного :meth:`approve_plan`.
        """
        if not self._owner.is_owner(sender):
            return _refused()
        if await self._active_session() is not None:
            return await self._reply(False, _BUSY, session=None)
        now = self._clock.now()
        branch = worktree_branch(task)
        path = await self._worktree.create(branch)
        session = CodingSession(
            id=self._id_factory(),
            task=task,
            state=CodingSessionState.PLANNING,
            branch=branch,
            created_at=now,
            updated_at=now,
            worktree_path=path,
        )
        await self._store.save(session)
        try:
            plan = await self._run_plan(session, path)
        except Exception as exc:  # fault isolation: a runner fault is an honest FAILED
            logger.exception("coding: plan run failed for %s", session.id)
            return await self._fail(session, exc, cleanup=True)
        session = session.with_plan(plan, at=self._clock.now()).with_state(
            CodingSessionState.PLAN_READY, at=self._clock.now()
        )
        await self._store.save(session)
        return await self._reply(True, _plan_message(plan), session=session)

    async def approve_plan(self, sender: int | None) -> CodingOutcome:
        """Owner-only гейт плана: ``PLAN_READY → EXECUTING`` → нарратив → открыть PR.

        Валиден ТОЛЬКО из ``PLAN_READY`` (домен :func:`can_approve_plan`): исполнение
        недостижимо без явного апрува. Гоняет раннер в режиме правок, наррратит каждое
        событие owner, открывает PR (:meth:`PullRequestOpener.open`) и переводит в
        ``PR_OPEN``. 🔴 Никакого мержа/пуша в main. worktree убирается в ``finally``.
        """
        if not self._owner.is_owner(sender):
            return _refused()
        session = await self._active_session()
        if session is None or not can_approve_plan(session.state):
            return await self._reply(False, _CANNOT_APPROVE, session=session)
        path = session.worktree_path
        if path is None:  # pragma: no cover - PLAN_READY always carries a worktree
            return await self._reply(False, _CANNOT_APPROVE, session=session)
        session = session.with_state(CodingSessionState.EXECUTING, at=self._clock.now())
        await self._store.save(session)
        try:
            return await self._execute_and_open_pr(session, path)
        except Exception as exc:  # fault isolation: a runner/PR fault is an honest FAILED
            logger.exception("coding: execute run failed for %s", session.id)
            return await self._fail(session, exc, cleanup=False)
        finally:
            # The worktree's job (running claude) is over on ANY exit of the run —
            # success (PR_OPEN, branch pushed), failure (FAILED) or a mid-run stop — so
            # it is removed here exactly once, leaving no worktree to leak.
            await self._cleanup(path)

    async def stop(self, sender: int | None) -> CodingOutcome:
        """Owner-only kill-switch: погасить прогон, ``→ CANCELLED`` и убрать worktree."""
        if not self._owner.is_owner(sender):
            return _refused()
        session = await self._active_session()
        if session is None:
            return await self._reply(False, _NO_SESSION, session=None)
        # Signal any in-flight narrate loop to break (→ runner closed → process killed).
        self._cancelled.add(session.id)
        session = session.with_state(CodingSessionState.CANCELLED, at=self._clock.now())
        await self._store.save(session)
        await self._cleanup(session.worktree_path)
        return await self._reply(True, _STOPPED, session=session)

    async def status(self, sender: int | None) -> CodingOutcome:
        """Owner-only: доложить состояние текущей сессии (или что её нет)."""
        if not self._owner.is_owner(sender):
            return _refused()
        session = await self._active_session()
        if session is None:
            return await self._reply(True, _STATUS_IDLE, session=None)
        return await self._reply(True, _status_message(session), session=session)

    # --- Internal orchestration ----------------------------------------------

    async def _execute_and_open_pr(
        self, session: CodingSession, path: str
    ) -> CodingOutcome:
        """Run the approved plan (narrated), open a PR, advance to ``PR_OPEN``."""
        await self._narrate_run(session, path)
        if session.id in self._cancelled:  # a stop landed mid-run — do not open a PR
            return CodingOutcome(ok=False, message=_STOPPED, session=session)
        pr_url = await self._pr_opener.open(
            session.branch, _pr_title(session), _pr_body(session)
        )
        session = session.with_pr_url(pr_url, at=self._clock.now()).with_state(
            CodingSessionState.PR_OPEN, at=self._clock.now()
        )
        await self._store.save(session)
        return await self._reply(True, _pr_message(pr_url), session=session)

    async def _run_plan(self, session: CodingSession, path: str) -> str:
        """Run plan-mode, collecting the plan text (a plan with NO edits — the gate)."""
        parts: list[str] = []
        async with aclosing(
            _closeable(self._runner.run(path, _plan_prompt(session.task), mode=_PLAN_MODE))
        ) as stream:
            async for event in stream:
                if session.id in self._cancelled:
                    break
                text = _event_text(event)
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()

    async def _narrate_run(self, session: CodingSession, path: str) -> None:
        """Run execute-mode, sending each non-noise narrate line to the owner."""
        async with aclosing(
            _closeable(
                self._runner.run(path, _execute_prompt(session.task), mode=self._execute_mode)
            )
        ) as stream:
            async for event in stream:
                if session.id in self._cancelled:
                    break
                line = narrate(event)
                if line is not None:
                    await self._notifier.send(line)

    async def _fail(
        self, session: CodingSession, exc: Exception, *, cleanup: bool
    ) -> CodingOutcome:
        """Move the session to ``FAILED`` with an honest report.

        ``cleanup`` is ``True`` only for the plan path (``start`` has no surrounding
        ``finally``); the execute path passes ``False`` because its own ``finally``
        removes the worktree — so the worktree is never leaked and never double-removed.
        """
        session = session.with_state(CodingSessionState.FAILED, at=self._clock.now())
        await self._store.save(session)
        if cleanup:
            await self._cleanup(session.worktree_path)
        return await self._reply(False, _FAILED.format(detail=str(exc)), session=session)

    async def _cleanup(self, path: str | None) -> None:
        """Remove the worktree (idempotent best-effort; never leak, never crash a turn)."""
        if path is None:
            return
        try:
            await self._worktree.remove(path)
        except Exception:  # cleanup must never mask the real outcome
            logger.exception("coding: worktree cleanup failed for %s", path)

    async def _active_session(self) -> CodingSession | None:
        """The single in-flight (non-terminal) session, or ``None``."""
        active = await self._store.active()
        for session in active:
            if not is_terminal(session.state):
                return session
        return None

    async def _reply(
        self, ok: bool, message: str, *, session: CodingSession | None
    ) -> CodingOutcome:
        """Send ``message`` to the owner and wrap the outcome."""
        await self._notifier.send(message)
        return CodingOutcome(ok=ok, message=message, session=session)


class _Clock(Protocol):
    """The clock surface the assistant needs (injected for deterministic tests)."""

    def now(self) -> datetime: ...


def _closeable(
    stream: AsyncIterator[Mapping[str, object]],
) -> AsyncGenerator[Mapping[str, object], None]:
    """Narrow the runner's ``AsyncIterator`` port type to a closeable async generator.

    Both the live :class:`~bob.infrastructure.coding.claude_runner.SubprocessClaudeRunner`
    and the test fakes implement :meth:`ClaudeCodeRunner.run` as an async generator, so it
    supports ``aclose`` — and closing it on an early break (a mid-run ``stop``) runs the
    adapter's ``finally`` that kills + reaps the ``claude`` subprocess. The port advertises
    the wider ``AsyncIterator`` type, so this documented cast restores the ``aclose`` view.
    """
    return cast("AsyncGenerator[Mapping[str, object], None]", stream)


def _refused() -> CodingOutcome:
    """A silent refusal for a non-owner — no session, no run, no owner message."""
    return CodingOutcome(ok=False, message="", session=None)


def _plan_message(plan: str) -> str:
    """Render the owner-facing plan message (the plan body + the approve/stop hint)."""
    body = plan if plan else _NO_PLAN
    return f"{body}\n\n{_PLAN_HEADER}"


def _pr_message(url: str) -> str:
    """Render the owner-facing PR message (url + the never-merge reminder)."""
    return _PR_HEADER.format(url=url)


def _status_message(session: CodingSession) -> str:
    """Render the owner-facing status line for the in-flight session."""
    return _STATUS_LINE.format(
        task=session.task, state=session.state.value, branch=session.branch
    )


def _pr_title(session: CodingSession) -> str:
    """The PR title — the task, trimmed to a one-line subject."""
    return session.task.strip().splitlines()[0][:72] if session.task.strip() else session.branch


def _pr_body(session: CodingSession) -> str:
    """The PR body — the task plus the approved plan (transparency for the owner)."""
    plan = session.plan or ""
    return f"Задача: {session.task}\n\nПлан:\n{plan}".strip()


def _plan_prompt(task: str) -> str:
    """The plan-mode prompt — produce a plan with NO edits (the plan gate)."""
    return (
        f"Задача: {task}\n\n"
        "Построй детальный план реализации. НЕ вноси изменений — только план."
    )


def _execute_prompt(task: str) -> str:
    """The execute-mode prompt — apply the approved plan and commit to the branch.

    🔴 Commit + push happen on the ISOLATED feature branch only — NEVER ``main``, and
    NEVER a merge: Bob opens a PR and stops, the owner lands the change by hand.
    """
    return (
        f"Задача: {task}\n\n"
        "Реализуй одобренный план. Закоммить изменения в ТЕКУЩУЮ ветку и запушь её. "
        "НЕ переключайся на main, НЕ мержи, НЕ пушь в main — только эту ветку."
    )


def _event_text(event: Mapping[str, object]) -> str:
    """Collect the plain plan text from one stream-json event (assistant text / result).

    Plan-mode's value is the plan PROSE, which :func:`narrate` deliberately treats as
    noise — so the plan is assembled here from the assistant message's text blocks and
    the final ``result`` event's ``result`` field. Tool/system events yield ``""``.
    """
    kind = str(event.get("type", ""))
    if kind == "result" and not _is_error_result(event):
        return str(event.get("result", "")).strip()
    if kind == "assistant":
        return _assistant_text(event)
    return ""


def _is_error_result(event: Mapping[str, object]) -> bool:
    """Whether a ``result`` event is an error (then its text is not a plan)."""
    return bool(event.get("is_error")) or str(event.get("subtype", "success")) != "success"


def _assistant_text(event: Mapping[str, object]) -> str:
    """Join the text blocks of an assistant message into one plan fragment."""
    message = event.get("message")
    if not isinstance(message, Mapping):
        return ""
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    parts = [
        str(block.get("text", "")).strip()
        for block in content
        if isinstance(block, Mapping) and block.get("type") == "text"
    ]
    return "\n".join(part for part in parts if part)
