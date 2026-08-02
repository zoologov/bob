# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=application

"""InteractiveSessionManager — живой двусторонний claude-сеанс в личке (BOB-083 .3).

Owner-only оркестратор ОДНОГО живого интерактивного сеанса «Боб держит запущенный
claude, owner направляет его в реальном времени». В отличие от гейтед
:class:`~bob.coding.usecases.coding_assistant.CodingAssistant` (эфемерный прогон
план→апрув→PR), этот менеджер держит ДОЛГОЖИВУЩИЙ процесс через
:class:`~bob.coding.ports.InteractiveRunner` и правит им напрямую:

* :meth:`open` — owner-only. Создаёт ИЗОЛИРОВАННЫЙ worktree (реюз
  :class:`~bob.coding.ports.Worktree` — правки в ветке ``bob/<slug>``, НИКОГДА не main),
  спавнит раннер в валидном ``permission_mode``, персистит сессию в состоянии
  ``INTERACTIVE`` и заводит фоновую перекачку вывода раннера в ЛИЧКУ owner'а через
  инъектированный :class:`~bob.coding.usecases.coding_assistant.LiveRunStreamer` (реюз
  ``_DmLiveStreamer`` BOB-082).
* :meth:`feed` — форвардит owner-реплику в открытый stdin раннера (steer).
* :meth:`stop` — 🔴 ПРЯМОЙ kill: ``runner.close()`` (terminate→kill) + уборка worktree
  + перевод сессии в терминальное ``CANCELLED``. Это НЕ кооперативный break гейтед-кодера
  (живого read-loop для выхода недостаточно) — процесс завершается напрямую. Идемпотентно.
* :meth:`active` — есть ли живой сеанс (для интейк-гейта .4 и гварда «одна сессия»).

🔴 ОДНА сессия за раз: :meth:`open` при живой сессии отказывает. 🔴 Менеджер НЕ открывает
PR / не пушит / не мержит — таких вызовов здесь просто нет; правки остаются в worktree,
owner ревьюит и открывает/мержит PR через СУЩЕСТВУЮЩИЙ гейт BOB-039 (main неприкосновенен,
INV-2). Всё инъектируется (фабрика раннера / worktree / фабрика стримера / owner-гейт /
часы / фабрика id / режим), поэтому use-case детерминирован в тестах и не трогает ни
настоящий ``claude``/``git``, ни глобалы (зеркалит конструкцию ``CodingAssistant``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.coding import session_voice
from bob.coding.entities import CodingSession
from bob.coding.naming import worktree_branch
from bob.coding.state import CodingSessionState
from bob.coding.usecases.coding_assistant import CodingOutcome, OwnerCheck

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from typing import Protocol

    from bob.coding.ports import CodingSessionStore, InteractiveRunner, Worktree
    from bob.coding.usecases.coding_assistant import LiveRunStreamer

    class _Clock(Protocol):
        """Часы, которые нужны менеджеру (инъектируются для детерминизма тестов)."""

        def now(self) -> datetime: ...


logger = logging.getLogger(__name__)

__all__ = ["InteractiveSessionManager"]

# Режим по умолчанию для живого сеанса: правки авто-принимаются В WORKTREE (spросов нет),
# main при этом неприкосновенен (изоляция worktree + отсутствие push/PR). Композиция может
# переопределить через ``coder.permission_mode``; раннер валидирует против allowlist.
_DEFAULT_INTERACTIVE_MODE = "acceptEdits"


@dataclass(slots=True)
class _LiveSession:
    """Держатель живого сеанса: персистнутая сессия + её запущенный раннер."""

    session: CodingSession
    runner: InteractiveRunner


class InteractiveSessionManager:
    """Owner-only оркестратор одного живого двустороннего claude-сеанса (BOB-083 .3)."""

    def __init__(
        self,
        *,
        runner_factory: Callable[[], InteractiveRunner],
        worktree: Worktree,
        store: CodingSessionStore,
        streamer_factory: Callable[[], LiveRunStreamer],
        owner: OwnerCheck,
        clock: _Clock,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
        permission_mode: str = _DEFAULT_INTERACTIVE_MODE,
    ) -> None:
        self._runner_factory = runner_factory
        self._worktree = worktree
        self._store = store
        self._streamer_factory = streamer_factory
        self._owner = owner
        self._clock = clock
        self._id_factory = id_factory
        self._permission_mode = permission_mode
        # The single live session (``None`` when idle — the one-session guard reads this).
        self._live: _LiveSession | None = None
        # The background output-pump task streaming the runner's events to the DM.
        self._task: asyncio.Task[None] | None = None
        # Per-session cancel flag (like CodingAssistant): a ``stop`` adds the id so the
        # DM streamer's ``is_cancelled`` breaks even before the process's stdout EOFs.
        self._cancelled: set[str] = set()

    async def open(self, task: str, sender: int | None) -> CodingOutcome:
        """Owner-only: завести ИЗОЛИРОВАННЫЙ сеанс, спавнить раннер, лить вывод в личку.

        Создаёт worktree на безопасной ветке ``bob/<slug>`` (никогда main), спавнит
        живой раннер в ``permission_mode``, персистит сессию в ``INTERACTIVE`` и заводит
        фоновую перекачку вывода в DM owner'а. 🔴 Одна сессия за раз: при живой сессии —
        отказ. Не-owner получает тихий отказ (нет worktree, нет спавна).
        """
        if not self._owner.is_owner(sender):
            return _refused()
        if self._live is not None:
            return CodingOutcome(
                ok=False, message=session_voice.interactive_busy(), session=self._live.session
            )
        now = self._clock.now()
        branch = worktree_branch(task)
        path = await self._worktree.create(branch)
        try:
            runner = self._runner_factory()
            await runner.open(path, mode=self._permission_mode)
        except Exception:  # spawn/mode fault: clean up the worktree, no live session
            logger.exception("coding: interactive open failed for task")
            await self._cleanup(path)
            return CodingOutcome(
                ok=False, message=session_voice.interactive_failed(), session=None
            )
        session = CodingSession(
            id=self._id_factory(),
            task=task,
            state=CodingSessionState.INTERACTIVE,
            branch=branch,
            created_at=now,
            updated_at=now,
            worktree_path=path,
        )
        await self._store.save(session)
        self._live = _LiveSession(session=session, runner=runner)
        self._task = asyncio.create_task(self._pump(session.id, runner))
        return CodingOutcome(
            ok=True, message=session_voice.interactive_opened(), session=session
        )

    async def feed(self, text: str) -> None:
        """Форвард owner-реплики в открытый stdin живого раннера (steer path).

        Нет живой сессии → no-op (реплика после закрытия сеанса просто теряется, не
        падает). Owner-гейт — на вызывающей стороне (интейк-гейт .4 отдаёт сюда только
        owner-plain-text при активном режиме); менеджер лишь форвардит.
        """
        live = self._live
        if live is None:
            return
        await live.runner.feed(text)

    async def stop(self, sender: int | None) -> CodingOutcome:
        """Owner-only 🔴 ПРЯМОЙ kill: закрыть раннер, убрать worktree, ``→ CANCELLED``.

        Прямой ``runner.close()`` (terminate→kill) завершает ДОЛГОЖИВУЩИЙ процесс — это
        не кооперативный break гейтед-кодера. Затем worktree убирается (реюз ``_cleanup``)
        и сессия переводится в терминальное ``CANCELLED``. Идемпотентно/best-effort: без
        живой сессии — честная заметка, без падения.
        """
        if not self._owner.is_owner(sender):
            return _refused()
        live = self._live
        if live is None:
            return CodingOutcome(ok=False, message=session_voice.no_session(), session=None)
        # Drop the live handle up front (active() is false at once) and signal the pump.
        self._live = None
        self._cancelled.add(live.session.id)
        await self._close_runner(live.runner)  # 🔴 direct terminate of the process
        await self._await_pump()
        await self._cleanup(live.session.worktree_path)
        now = self._clock.now()
        # BOB-087.D1: persist the claude session id captured off the init event so a
        # later /code (D3) can look it up for --resume. None when no init id was seen —
        # the field then stays None (byte-identical to a pre-D1 session).
        ended = live.session
        claude_session_id = live.runner.session_id
        if claude_session_id is not None:
            ended = ended.with_claude_session_id(claude_session_id, at=now)
        session = ended.with_state(CodingSessionState.CANCELLED, at=now)
        await self._store.save(session)
        self._cancelled.discard(session.id)
        self._task = None
        return CodingOutcome(ok=True, message=session_voice.stopped(), session=session)

    def active(self) -> bool:
        """Есть ли живой интерактивный сеанс (интейк-гейт .4 + гвард «одна сессия»)."""
        return self._live is not None

    # --- Internal orchestration ----------------------------------------------

    async def _pump(self, session_id: str, runner: InteractiveRunner) -> None:
        """Перекачивать вывод раннера в DM owner'а, пока сеанс жив (fault-isolated).

        Делегирует ВЕСЬ поток событий инъектированному :class:`LiveRunStreamer`
        (``_DmLiveStreamer`` реюз): каждое сырое stream-json событие рендерится и льётся
        в личку. ``is_cancelled`` (kill-switch ``stop``) обрывает поток; сбой стрима
        изолирован — он не валит менеджер.
        """
        streamer = self._streamer_factory()
        try:
            await streamer.stream(
                runner.events(), is_cancelled=lambda: session_id in self._cancelled
            )
        except Exception:  # an output-stream fault must never crash the manager
            logger.exception("coding: interactive output stream failed for %s", session_id)

    async def _close_runner(self, runner: InteractiveRunner) -> None:
        """Прямой kill раннера (best-effort — уже мёртвый процесс не должен падать)."""
        try:
            await runner.close()
        except Exception:  # a close fault must never mask the stop outcome
            logger.exception("coding: interactive runner close failed")

    async def _await_pump(self) -> None:
        """Дождаться завершения фоновой перекачки вывода (после close раннер EOF'ит)."""
        task = self._task
        if task is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _cleanup(self, path: str | None) -> None:
        """Убрать worktree (идемпотентно best-effort; не течём, не роняем ход)."""
        if path is None:
            return
        try:
            await self._worktree.remove(path)
        except Exception:  # cleanup must never mask the real outcome
            logger.exception("coding: interactive worktree cleanup failed for %s", path)


def _refused() -> CodingOutcome:
    """Тихий отказ не-owner'у — ни сессии, ни worktree, ни спавна, ни сообщения."""
    return CodingOutcome(ok=False, message="", session=None)
