# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=application

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
  (:func:`~bob.coding.state.can_approve_plan` — гейт плана). Переводит в
  ``EXECUTING``, гоняет раннер в режиме правок, НАРРАТИТ каждое событие owner через
  :func:`~bob.coding.narrate.narrate`, затем ОТКРЫВАЕТ PR
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

import contextlib
import logging
import re
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from bob.coding import session_voice
from bob.coding.entities import CodingSession
from bob.coding.naming import worktree_branch
from bob.coding.narrate import narrate
from bob.coding.state import CodingSessionState, can_approve_plan, is_terminal
from bob.memory.self_action import SelfAction, SelfActionKind
from bob.social.disclosure import VISIBILITY_OWNER_PRIVATE

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime

    from bob.coding.ports import ClaudeCodeRunner, CodingSessionStore, PullRequestOpener, Worktree
    from bob.memory.ports import SelfActionRecorder

logger = logging.getLogger(__name__)

__all__ = [
    "CodingAssistant",
    "CodingContext",
    "CodingOutcome",
    "LiveRunStreamer",
    "OwnerCheck",
    "OwnerNotifier",
    "StatusPanel",
    "TypingKeepalive",
]

# The execute-mode passed to the runner when the plan is approved (apply edits inside
# the isolated worktree). The default mirrors the adapter's allowlist; the composition
# root may override via ``coder.permission_mode``.
_DEFAULT_EXECUTE_MODE = "acceptEdits"

# Plan mode is fixed: a plan with NO edits — the unbypassable plan gate.
_PLAN_MODE = "plan"

# 🔴 SAFETY (BOB-076): the ceiling on per-event PROGRESS narrations sent to the owner in
# one execute run. A run touching many files once flooded the chat with a line per edit;
# past this cap Bob sends ONE "…продолжаю" notice and goes quiet on progress until the
# final result event (which is ALWAYS sent — the cap only throttles interim progress).
_MAX_NARRATION = 12

# The reason recorded on the no-changes FAILED path (claude applied no edits, so Bob
# pushes nothing and opens no PR) — the autobiographical detail for CODING_FAILED.
_NO_CHANGES_DETAIL = "изменений не было"

# Owner-facing messages live in Bob's voice (BOB-041 .3): the gate/framing lines are
# built by :mod:`~bob.coding.session_voice` (Bob speaks, GUPPI executes) and the
# per-event narrative is GUPPI-attributed by :func:`~bob.coding.narrate.narrate` —
# both deterministic, template-based (no LLM). This use-case only orchestrates; the wording
# is the domain's.


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

    Реализуется :class:`~bob.social.usecases.Authorizer` (его ``is_owner``). Гейт
    дублируется на уровне GUPPI (команда от не-owner туда не доходит), но use-case
    проверяет owner на КАЖДОМ методе сам — никакой сессии/исполнения для чужого.
    """

    def is_owner(self, user_id: int | None) -> bool:
        """Является ли ``user_id`` owner'ом (единственный, кто вправе командовать)."""
        ...


class TypingKeepalive(Protocol):
    """Сейм индикатора «Боб печатает…» на время долгих немых прогонов claude (BOB-046 .2).

    Ноль-арг фабрика async-контекст-менеджера: на вход — typing-action в топик Боба, на
    выход — он гаснет. Реализуется в композиции адаптером над ботом Боба (реюз идиомы
    BOB-009 ``typing_indicator`` с keepalive-рефрешем, чтобы 5-секундный typing не
    истекал в минутной паузе). Use-case ОБОРАЧИВАЕТ им plan- и execute-прогоны; незавязан
    (``None``) → no-op (индикатор просто отсутствует, без падения).
    """

    def __call__(self) -> AbstractAsyncContextManager[None]:
        """Открыть keepalive на время прогона (закрытие гасит индикатор)."""
        ...


class StatusPanel(Protocol):
    """Сейм одного editable сообщения-статуса по фазам сессии (BOB-046 .2).

    «Живая панель»: ОДНО сообщение, отправленное на старте (``open``) и РЕДАКТИРУЕМОЕ по
    фазам (``update``: план → выполняю → PR/провал/стоп) — не спам новых сообщений.
    Реализуется адаптером над ботом Боба (``editMessageText``); если редактировать нечем
    (нет id / не поддержано) — деградирует в no-op (current behavior: без статус-строки).
    Незавязан (``None``) → no-op. Дополняет, а НЕ заменяет гейт/нарратив-сообщения.
    """

    async def open(self, text: str) -> None:
        """Послать стартовое сообщение-статус (best-effort, транспорт за адаптером)."""
        ...

    async def update(self, text: str) -> None:
        """Отредактировать то же сообщение под новую фазу (no-op, если нечего править)."""
        ...


class LiveRunStreamer(Protocol):
    """Сейм ЛАЙВ-стрима сырых событий execute-прогона в dev-канал owner'а (BOB-082.3).

    Когда завязан (флаг ``coder.dev_dm`` ON), use-case делегирует сюда ВЕСЬ поток
    execute-событий: адаптер (:class:`~bob.coding.adapters.live_stream._DmLiveStreamer`)
    рендерит каждое сырое событие через :func:`~bob.coding.stream_render.render_stream_event`
    (не lossy ``narrate``) и льёт БЕЗ капа в ЛИЧКУ owner'а — прогрессивная «терминальная»
    панель + отдельные сообщения. Групповой топик при этом получает только короткий
    указатель (INV-5: firehose не флудит группу). Незавязан (``None``) → use-case идёт
    прежним путём: капнутый групповой нарратив ``narrate`` (поведение без флага не меняется).

    Порт transport-free: use-case не знает про DM chat_id / edit_message_text — только
    вызывает :meth:`stream`; выбор цели/рендера делает композиция (wiring).
    """

    async def stream(
        self,
        events: AsyncIterator[Mapping[str, object]],
        *,
        is_cancelled: Callable[[], bool],
    ) -> None:
        """Пролить сырые события прогона в dev-канал (пока ``is_cancelled()`` ложно)."""
        ...


class CodingContext(Protocol):
    """Сейм лёгкого арх-контекст-префикса для claude-промпта (BOB-046 .3).

    Перед прогоном Боб ПРИНОСИТ в промпт конвенции проекта + рационал области задачи
    (T3.A⁺): реализуется :func:`~bob.coding.usecases.coding_context.make_coding_context`
    над read-only-интроспектором, ограничен по объёму и 🔴 приватно-безопасен
    (PrivacyGuard). Use-case ПОДМЕШИВАЕТ результат в plan/execute-промпт; незавязан
    (``None``) или пустой/упавший источник → промпт без изменений (graceful).
    """

    async def preamble(self, task: str) -> str:
        """Построить контекст-префикс для ``task`` (``""`` → префикса нет)."""
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
        typing_keepalive: TypingKeepalive | None = None,
        status_panel: StatusPanel | None = None,
        context: CodingContext | None = None,
        recorder: SelfActionRecorder | None = None,
        live_streamer: LiveRunStreamer | None = None,
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
        # Autobiography (BOB-079.2): first-person self-action episodes recorded at each
        # lifecycle transition through the narrow ``SelfActionRecorder``. Unwired → a local
        # null recorder (zero writes), so the gated flow is byte-identical when off, and the
        # composition root's flag-gated NoOp/memory recorder decides whether it truly writes.
        self._recorder: SelfActionRecorder = recorder or _NullSelfActionRecorder()
        # Work indicators (BOB-046 .2): both degrade to a no-op when unwired, so the gated
        # flow is unchanged and never depends on the indicator being present.
        self._typing: TypingKeepalive = typing_keepalive or _no_typing
        self._panel: StatusPanel = status_panel or _NullStatusPanel()
        # Architectural-context preamble (BOB-046 .3): when wired, Bob prepends a bounded,
        # privacy-safe project-context block to the claude prompt; unwired (``None``) →
        # the prompt is unchanged, so the flow never depends on the context being present.
        self._context = context
        # DM live-stream (BOB-082.3): when wired (flag ``coder.dev_dm`` ON) the raw,
        # UNCAPPED execute stream is rendered into the owner's private dev-channel and the
        # group topic gets only a brief pointer (INV-5). Unwired (``None``, the default) →
        # the run is narrated to the group capped exactly as before (zero behaviour change).
        self._live_streamer = live_streamer
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
            return await self._reply(False, session_voice.busy(), session=None)
        # Bob's voice: he takes the task on (first person) and directs GUPPI — sent
        # before planning so the owner sees Bob accept immediately (BOB-041 .3).
        await self._notifier.send(session_voice.accepted())
        # Work indicator (BOB-046 .2): one editable status panel opened up front, so the
        # owner sees "⏳ Прикидываю план…" during the silent claude wait instead of a minute
        # of nothing. It is EDITED (never re-sent) through the phases below.
        await self._panel.open(session_voice.panel_planning())
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
            async with self._typing():  # "Bob is typing…" through the long plan wait
                plan = await self._run_plan(session, path)
        except Exception as exc:  # fault isolation: a runner fault is an honest FAILED
            logger.exception("coding: plan run failed for %s", session.id)
            return await self._fail(session, exc, cleanup=True, sender=sender)
        session = session.with_plan(plan, at=self._clock.now()).with_state(
            CodingSessionState.PLAN_READY, at=self._clock.now()
        )
        await self._store.save(session)
        await self._record(SelfAction(SelfActionKind.CODING_STARTED, target=task), sender)
        await self._panel.update(session_voice.panel_plan_ready())
        return await self._reply(True, session_voice.plan(plan), session=session)

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
            return await self._reply(False, session_voice.cannot_approve(), session=session)
        path = session.worktree_path
        if path is None:  # pragma: no cover - PLAN_READY always carries a worktree
            return await self._reply(False, session_voice.cannot_approve(), session=session)
        session = session.with_state(CodingSessionState.EXECUTING, at=self._clock.now())
        await self._store.save(session)
        try:
            return await self._execute_and_open_pr(session, path, sender)
        except Exception as exc:  # fault isolation: a runner/PR fault is an honest FAILED
            logger.exception("coding: execute run failed for %s", session.id)
            return await self._fail(session, exc, cleanup=False, sender=sender)
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
            return await self._reply(False, session_voice.no_session(), session=None)
        # Signal any in-flight narrate loop to break (→ runner closed → process killed).
        self._cancelled.add(session.id)
        session = session.with_state(CodingSessionState.CANCELLED, at=self._clock.now())
        await self._store.save(session)
        await self._record(SelfAction(SelfActionKind.CODING_ABORTED, target=session.task), sender)
        await self._cleanup(session.worktree_path)
        await self._panel.update(session_voice.panel_stopped())
        return await self._reply(True, session_voice.stopped(), session=session)

    async def status(self, sender: int | None) -> CodingOutcome:
        """Owner-only: доложить состояние текущей сессии (или что её нет)."""
        if not self._owner.is_owner(sender):
            return _refused()
        session = await self._active_session()
        if session is None:
            return await self._reply(True, session_voice.status_idle(), session=None)
        return await self._reply(True, _status_message(session), session=session)

    async def active_state(self) -> CodingSessionState | None:
        """The in-flight (non-terminal) session's state, or ``None`` (no side effects).

        A read-only query for the natural-language routing (BOB-041 .2): it lets the
        caller tell whether a session is waiting for an approve (``PLAN_READY``) or is
        otherwise live — WITHOUT notifying the owner (unlike :meth:`status`). Owner-only
        is NOT enforced here because it neither starts nor advances a session and sends
        nothing; the gated mutators (:meth:`start` / :meth:`approve_plan` / :meth:`stop`)
        each re-check the owner, so this read can never bypass a gate.
        """
        session = await self._active_session()
        return session.state if session is not None else None

    # --- Internal orchestration ----------------------------------------------

    async def _execute_and_open_pr(
        self, session: CodingSession, path: str, sender: int | None
    ) -> CodingOutcome:
        """Run the approved plan (narrated), commit+push, open a PR, advance to ``PR_OPEN``.

        🔴 Commit + push are Bob's DETERMINISTIC step (BOB-040): ``claude`` in
        ``acceptEdits`` applies file edits but never runs git, so the branch would have
        no commits and ``gh pr create`` would fail. Bob commits + pushes the session's
        ``bob/<slug>`` branch himself (validated inside the adapter — never ``main``)
        BEFORE opening the PR. If ``claude`` changed nothing, the push reports nothing to
        commit and the session FAILS honestly with no PR.
        """
        await self._panel.update(session_voice.panel_executing())
        async with self._typing():  # "Bob is typing…" through the long execute wait
            await self._narrate_run(session, path, sender)
        if session.id in self._cancelled:  # a stop landed mid-run — do not open a PR
            return CodingOutcome(ok=False, message=session_voice.stopped(), session=session)
        committed = await self._worktree.commit_and_push(
            path, session.branch, _commit_message(session)
        )
        if not committed:  # claude applied no change — fail honestly, open no PR
            session = session.with_state(
                CodingSessionState.FAILED, at=self._clock.now()
            )
            await self._store.save(session)
            await self._record(
                SelfAction(
                    SelfActionKind.CODING_FAILED,
                    target=session.task,
                    detail=_NO_CHANGES_DETAIL,
                ),
                sender,
            )
            await self._panel.update(session_voice.panel_failed())
            return await self._reply(False, session_voice.no_changes(), session=session)
        pr_url = await self._pr_opener.open(
            session.branch, _pr_title(session), _pr_body(session)
        )
        session = session.with_pr_url(pr_url, at=self._clock.now()).with_state(
            CodingSessionState.PR_OPEN, at=self._clock.now()
        )
        await self._store.save(session)
        await self._record(SelfAction(SelfActionKind.CODING_FINISHED, target=session.task), sender)
        await self._panel.update(session_voice.panel_pr())
        return await self._reply(True, session_voice.pr(pr_url), session=session)

    async def _run_plan(self, session: CodingSession, path: str) -> str:
        """Run plan-mode, collecting the plan text (a plan with NO edits — the gate).

        claude in plan-mode emits the plan TWICE — once as ``assistant`` text and again
        in the final ``result`` — so the parts are reduced by :func:`_clean_plan` to the
        authoritative single plan (no duplicated ``## План``), with the planning preamble
        stripped. The collect/clean split keeps the reduction a pure, testable transform.
        """
        prompt = _with_preamble(
            await self._preamble(session.task), _plan_prompt(session.task)
        )
        parts: list[_PlanPart] = []
        async with aclosing(
            _closeable(self._runner.run(path, prompt, mode=_PLAN_MODE))
        ) as stream:
            async for event in stream:
                if session.id in self._cancelled:
                    break
                part = _plan_part(event)
                if part is not None:
                    parts.append(part)
        return _clean_plan(parts)

    async def _narrate_run(
        self, session: CodingSession, path: str, sender: int | None
    ) -> None:
        """Run execute-mode, streaming its events to the owner (DM live or capped group).

        Two mutually-exclusive shapes, chosen by whether a live streamer is wired:

        * **DM live-stream (BOB-082.3, flag ``coder.dev_dm`` ON):** the group topic gets
          ONE brief pointer and the raw, UNCAPPED stream renders into the owner's private
          dev-channel through the injected :class:`LiveRunStreamer` (INV-5: the firehose
          never floods the group).
        * **Capped group narration (default):** each non-noise event is narrated to the
          group capped at ``_MAX_NARRATION`` — behaviour unchanged when the flag is off.
        """
        prompt = _with_preamble(
            await self._preamble(session.task), _execute_prompt(session.task)
        )
        async with aclosing(
            _closeable(self._runner.run(path, prompt, mode=self._execute_mode))
        ) as stream:
            if self._live_streamer is not None:
                await self._stream_to_dev_channel(session, stream)
            else:
                await self._narrate_capped(session, stream, sender)

    async def _stream_to_dev_channel(
        self, session: CodingSession, stream: AsyncIterator[Mapping[str, object]]
    ) -> None:
        """Post a one-line group pointer, then hand the raw stream to the DM live-streamer.

        The group topic sees ONLY the pointer (INV-5); the full, uncapped firehose renders
        into the owner's private dev-channel via the wired :class:`LiveRunStreamer`. A
        concurrent ``stop`` is honoured through the ``is_cancelled`` predicate the streamer
        polls (it breaks → the runner is closed → the ``claude`` process is killed).
        """
        await self._notifier.send(session_voice.dev_pointer())
        assert self._live_streamer is not None  # narrowed by the caller
        await self._live_streamer.stream(
            stream, is_cancelled=lambda: session.id in self._cancelled
        )

    async def _narrate_capped(
        self,
        session: CodingSession,
        stream: AsyncIterator[Mapping[str, object]],
        sender: int | None,
    ) -> None:
        """Narrate each non-noise event to the group, capped against flooding (BOB-076).

        🔴 SAFETY (BOB-076): interim PROGRESS narration is capped at ``_MAX_NARRATION``
        lines per run. Once the cap is hit Bob sends ONE "…продолжаю" notice and stays
        quiet on progress. The FINAL ``result`` event is ALWAYS sent (session outcome /
        error must reach the owner), so the cap only throttles the per-file flood, never
        the result. A plain counter — it does not touch the stop/cancel break.
        """
        progress = 0
        capped = False
        async for event in stream:
            if session.id in self._cancelled:
                break
            line = narrate(event)
            if line is None:
                continue
            if _is_result_event(event):  # the final outcome ALWAYS reaches the owner
                await self._notifier.send(line)
                continue
            if capped:  # past the cap: swallow interim progress until the result
                continue
            if progress >= _MAX_NARRATION:  # cap hit: one notice, then go quiet
                await self._notifier.send(session_voice.narration_capped())
                # Autobiographical trace of the flood (BOB-076): recorded EXACTLY ONCE
                # per run — right here where the cap trips, not per narration line.
                await self._record(
                    SelfAction(SelfActionKind.CODING_RUNAWAY, target=session.task), sender
                )
                capped = True
                continue
            await self._notifier.send(line)
            progress += 1

    async def _preamble(self, task: str) -> str:
        """Build the architectural-context preamble for ``task`` (BOB-046 .3).

        Returns ``""`` when no context source is wired or it degrades/fails — so a
        missing or broken context never blocks the run; the prompt is just unchanged.
        """
        if self._context is None:
            return ""
        try:
            return await self._context.preamble(task)
        except Exception:  # a context fault must never crash the coding session
            logger.exception("coding: context preamble failed for task")
            return ""

    async def _fail(
        self, session: CodingSession, exc: Exception, *, cleanup: bool, sender: int | None
    ) -> CodingOutcome:
        """Move the session to ``FAILED`` with an honest report.

        ``cleanup`` is ``True`` only for the plan path (``start`` has no surrounding
        ``finally``); the execute path passes ``False`` because its own ``finally``
        removes the worktree — so the worktree is never leaked and never double-removed.
        """
        session = session.with_state(CodingSessionState.FAILED, at=self._clock.now())
        await self._store.save(session)
        await self._record(
            SelfAction(SelfActionKind.CODING_FAILED, target=session.task, detail=str(exc)),
            sender,
        )
        await self._panel.update(session_voice.panel_failed())
        if cleanup:
            await self._cleanup(session.worktree_path)
        return await self._reply(False, session_voice.failed(str(exc)), session=session)

    async def _record(self, action: SelfAction, sender: int | None) -> None:
        """Best-effort autobiography write — a recording fault NEVER breaks coding.

        The self-action episode is a side channel: whether it lands or throws, the gated
        coding path must complete/fail EXACTLY as before (lesson Part D BOB-078). The
        visibility is owner-private — a coding session is an owner-only action, so its
        trace must never surface initiatively to a guest.
        """
        try:
            await self._recorder.record(
                action, sender_id=sender, visibility=VISIBILITY_OWNER_PRIVATE
            )
        except Exception:  # a recorder fault must never crash the coding session
            logger.exception("coding: self-action recording failed (%s)", action.kind)

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

    Both the live :class:`~bob.coding.adapters.claude_runner.SubprocessClaudeRunner`
    and the test fakes implement :meth:`ClaudeCodeRunner.run` as an async generator, so it
    supports ``aclose`` — and closing it on an early break (a mid-run ``stop``) runs the
    adapter's ``finally`` that kills + reaps the ``claude`` subprocess. The port advertises
    the wider ``AsyncIterator`` type, so this documented cast restores the ``aclose`` view.
    """
    return cast("AsyncGenerator[Mapping[str, object], None]", stream)


def _is_result_event(event: Mapping[str, object]) -> bool:
    """Whether ``event`` is the run's final ``result`` (its narration is never capped)."""
    return str(event.get("type", "")) == "result"


@contextlib.asynccontextmanager
async def _no_typing() -> AsyncGenerator[None, None]:
    """No-op typing keepalive: unwired indicator → no typing action, just runs the body."""
    yield


class _NullStatusPanel:
    """No-op status panel: unwired indicator → no status message (graceful degrade)."""

    async def open(self, text: str) -> None:
        """Drop the open — the owner simply gets no status line (current behavior)."""

    async def update(self, text: str) -> None:
        """Drop the edit — nothing to edit when no panel was ever opened."""


class _NullSelfActionRecorder:
    """No-op recorder: autobiography unwired → no self-action episode (graceful degrade).

    A local null object (like :class:`_NullStatusPanel`) so an unwired ``recorder`` needs
    no branch at each call site and the application use-case never imports an infra adapter.
    """

    async def record(
        self,
        action: SelfAction,
        *,
        sender_id: int | None = None,
        visibility: str | None = None,
    ) -> None:
        """Drop the write — autobiography is unwired (byte-identical behaviour)."""


def _refused() -> CodingOutcome:
    """A silent refusal for a non-owner — no session, no run, no owner message."""
    return CodingOutcome(ok=False, message="", session=None)


def _status_message(session: CodingSession) -> str:
    """Render the owner-facing status line for the in-flight session (Bob's voice)."""
    return session_voice.status_line(
        task=session.task, state=session.state.value, branch=session.branch
    )


def _commit_message(session: CodingSession) -> str:
    """The commit message for Bob's deterministic commit — the task's one-line subject."""
    subject = session.task.strip().splitlines()[0][:72] if session.task.strip() else session.branch
    return f"[bob] {subject}"


def _pr_title(session: CodingSession) -> str:
    """The PR title — the task, trimmed to a one-line subject."""
    return session.task.strip().splitlines()[0][:72] if session.task.strip() else session.branch


def _pr_body(session: CodingSession) -> str:
    """The PR body — the task plus the approved plan (transparency for the owner)."""
    plan = session.plan or ""
    return f"Задача: {session.task}\n\nПлан:\n{plan}".strip()


def _with_preamble(preamble: str, prompt: str) -> str:
    """Prepend the architectural-context preamble to the claude prompt (BOB-046 .3).

    An empty preamble (no context source wired, or a graceful degrade) leaves the
    prompt EXACTLY as-is — the additive enrichment never changes the base prompt when
    there is nothing to add.
    """
    if not preamble.strip():
        return prompt
    return f"{preamble}\n\n{prompt}"


def _plan_prompt(task: str) -> str:
    """The plan-mode prompt — produce a plan with NO edits (the plan gate)."""
    return (
        f"Задача: {task}\n\n"
        "Построй детальный план реализации. НЕ вноси изменений — только план."
    )


def _execute_prompt(task: str) -> str:
    """The execute-mode prompt — apply the approved plan (edits only).

    🔴 claude is asked ONLY to apply the file edits — NOT to run git. In ``acceptEdits``
    mode claude auto-accepts file edits but not Bash/git, so a commit/push it tried would
    silently not happen and leave the branch empty. Bob commits + pushes the feature
    branch DETERMINISTICALLY himself (BOB-040), so the prompt stays focused on the edits.
    """
    return (
        f"Задача: {task}\n\n"
        "Реализуй одобренный план: внеси необходимые правки в файлы. "
        "Не нужно коммитить или пушить — это сделаю я сам."
    )


@dataclass(frozen=True, slots=True)
class _PlanPart:
    """One collected plan fragment, tagged by its stream-json source.

    ``kind`` is ``"result"`` (the final authoritative plan) or ``"assistant"`` (the
    streamed draft) — :func:`_clean_plan` prefers the single ``result`` over the
    assistant echo so the plan is captured exactly once.
    """

    kind: str
    text: str


def _plan_part(event: Mapping[str, object]) -> _PlanPart | None:
    """Extract one plan fragment from a stream-json event (assistant text / result).

    Plan-mode's value is the plan PROSE, which :func:`narrate` deliberately treats as
    noise — so the plan is assembled here from the assistant message's text blocks and
    the final ``result`` event's ``result`` field. Tool/system events (and empty text)
    yield ``None``.
    """
    kind = str(event.get("type", ""))
    if kind == "result" and not _is_error_result(event):
        text = str(event.get("result", "")).strip()
        return _PlanPart("result", text) if text else None
    if kind == "assistant":
        text = _assistant_text(event)
        return _PlanPart("assistant", text) if text else None
    return None


def _clean_plan(parts: Sequence[_PlanPart]) -> str:
    """Reduce collected plan parts to the final plan text, once, de-noised (BOB-041 .1).

    The plan arrives TWICE — as ``assistant`` text and again in the final ``result`` —
    so the authoritative single source is the last non-empty ``result``; lacking one
    (a degraded stream) the assistant parts are joined with contained/identical
    duplicates dropped. The planning preamble (``ExitPlanMode`` chatter, "Let me write
    the plan.") is then stripped so the owner sees a clean plan.
    """
    chosen = _last_result_text(parts) or _dedup_join(parts)
    return _strip_plan_noise(chosen)


def _last_result_text(parts: Sequence[_PlanPart]) -> str:
    """The last non-empty ``result`` fragment (the authoritative final plan), or ``""``."""
    for part in reversed(parts):
        if part.kind == "result" and part.text:
            return part.text
    return ""


def _dedup_join(parts: Sequence[_PlanPart]) -> str:
    """Join fragments, dropping any identical to or contained within another (no echo)."""
    kept: list[str] = []
    for part in parts:
        text = part.text.strip()
        if not text:
            continue
        kept = [k for k in kept if k not in text]  # drop fragments superseded by text
        if any(text in k for k in kept):  # text already covered by a kept fragment
            continue
        kept.append(text)
    return "\n\n".join(kept)


def _strip_plan_noise(text: str) -> str:
    """Drop planning-preamble noise lines and collapse the blank runs they leave."""
    kept = [line for line in text.splitlines() if not _is_plan_noise(line)]
    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(kept))
    return collapsed.strip()


def _is_plan_noise(line: str) -> bool:
    """Whether ``line`` is plan-mode preamble chatter (not part of the real plan)."""
    stripped = line.strip()
    if not stripped:
        return False  # keep blanks; the run collapse handles spacing
    if "exitplanmode" in stripped.lower():
        return True
    return bool(_PLAN_CHATTER_RE.match(stripped))


# Planning-chatter preamble: a short "Let me / I'll … plan …" lead-in claude emits
# before the actual plan. Matched conservatively (must open with the lead-in verb AND
# mention "plan") so a real plan line is never mistaken for noise.
_PLAN_CHATTER_RE = re.compile(
    r"^(?:now\s+|ok(?:ay)?,?\s+|so\s+)*(?:let me|let's|i'?ll|i will)\b.{0,80}\bplan\b.*$",
    re.IGNORECASE,
)


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
