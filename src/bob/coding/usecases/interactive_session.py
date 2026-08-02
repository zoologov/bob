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

Возобновление приостановленной работы (BOB-087.D3) — «поднять с телефона нашу
эпик-сессию»: owner явной командой просит поднять ДОЛГОЖИВУЩИЙ workspace, и это
ДВУХШАГОВЫЙ путь с подтверждением:

* :meth:`propose_resume` — owner-only. Ничего не спавнит: находит кандидата (чистая
  политика :func:`~bob.coding.resume_policy.select_resumable`) и возвращает ВОПРОС голосом
  Боба, взводя ожидающее подтверждение (owner-скоуплено, с TTL).
* :meth:`resolve_pending_resume` — разрешает висящий вопрос по следующему ходу owner'а:
  «да» → :meth:`resume`, «нет» → отмена, ЛЮБОЕ другое сообщение (или протухший TTL) →
  вопрос просто СНИМАЕТСЯ, ход идёт обычным путём. Вопрос никогда не залипает.
* :meth:`open_workspace` — owner-only НАЧАЛО этого цикла (BOB-087.D5b): явной командой
  завести сеанс СРАЗУ в долгоживущем workspace, чтобы работе было где накапливаться.
  Без него :meth:`open` всегда делал эфемерное дерево, удаляемое на ``stop``, и поднимать
  потом было нечего — фича замыкалась сама на себя.
* :meth:`resume` — поднимает ``claude --resume <id>`` в ПЕРСИСТЕНТНОМ worktree
  (:class:`~bob.coding.ports.PersistentWorkspace`, реюз накопленного дерева) и заводит
  НОВУЮ живую сессию поверх сохранённого ``claude_session_id``.

🔴 Никакого live-attach: кандидатом может быть только ТЕРМИНАЛЬНАЯ сессия (гарантия
политики), а при живой сессии возобновление отказывает — два водителя за одним процессом
структурно невозможны. 🔴 Персистентный workspace НЕ удаляется: :meth:`stop` (и провал
спавна) не трогают его дерево, иначе накопленная работа стёрлась бы.

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
from bob.coding.argv_policy import extract_session_id
from bob.coding.entities import CodingSession
from bob.coding.interactive_intent import is_confirmation, is_rejection
from bob.coding.naming import workspace_branch, worktree_branch
from bob.coding.resume_policy import is_confirmation_fresh, select_resumable
from bob.coding.state import CodingSessionState
from bob.coding.usecases.coding_assistant import CodingOutcome, OwnerCheck

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping
    from datetime import datetime
    from typing import Protocol

    from bob.coding.ports import (
        CodingSessionStore,
        InteractiveRunner,
        PersistentWorkspace,
        ResumableSessionLookup,
        Worktree,
    )
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

# Человеческая метка времени прошлой сессии в вопросе-подтверждении («…трогали 02.08 в
# 10:00 UTC») — owner отвечает «да» с телефона и должен понимать, ЧТО именно поднимает.
# 🔴 Зона В МЕТКЕ (BOB-087.D5b): время хранится в UTC, а owner прочёл бы его как местное
# и мог подтвердить не ту сессию. ``%Z`` печатает зону, если она известна, и ничего — если
# нет (тогда хвостовой пробел срезается), поэтому метка никогда не врёт о зоне.
_WHEN_FORMAT = "%d.%m в %H:%M %Z"


@dataclass(slots=True)
class _LiveSession:
    """Держатель живого сеанса: персистнутая сессия, её раннер и судьба рабочего дерева.

    ``persistent`` — 🔴 маркер «это ДОЛГОЖИВУЩИЙ workspace, его дерево не удалять»:
    ``open`` заводит эфемерный посессионный worktree (убирается на ``stop``), а
    ``open_workspace`` / ``resume`` работают в накопленном workspace, который переживает
    остановку. Маркер держится в памяти рядом с живым сеансом, а не выводится из имени
    ветки (эфемерная задача,
    названная «epic …», дала бы ту же форму ``bob/epic-…``) и не требует новой колонки в
    БД: судьба дерева нужна ровно тому сеансу, который сейчас жив в этом процессе.
    """

    session: CodingSession
    runner: InteractiveRunner
    persistent: bool = False


@dataclass(slots=True)
class _PendingResume:
    """Висящий вопрос «поднимаю?»: чей он, про какой workspace и когда задан."""

    name: str
    sender: int | None
    requested_at: datetime


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
        lookup: ResumableSessionLookup | None = None,
        workspace: PersistentWorkspace | None = None,
    ) -> None:
        self._runner_factory = runner_factory
        self._worktree = worktree
        self._store = store
        self._streamer_factory = streamer_factory
        self._owner = owner
        self._clock = clock
        self._id_factory = id_factory
        self._permission_mode = permission_mode
        # Resume seams (BOB-087.D3), both OPTIONAL and both ``None`` unless the owner
        # switched ``coder.resume`` on: without them the resume path is structurally
        # unavailable (nothing to look up, nowhere to land) and answers inertly.
        self._lookup = lookup
        self._workspace = workspace
        # The single pending «поднимаю?» question (owner-scoped, TTL-bounded).
        self._pending: _PendingResume | None = None
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
        try:
            path = await self._worktree.create(branch)
        except Exception:  # 🔴 git/worktree fault BEFORE the spawn: answer, never go mute
            logger.exception("coding: interactive worktree create failed for task")
            return CodingOutcome(
                ok=False, message=session_voice.interactive_setup_failed(), session=None
            )
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
        await self._go_live(session, runner, persistent=False)
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

    async def open_workspace(
        self, name: str, task: str, sender: int | None
    ) -> CodingOutcome:
        """Owner-only: завести сеанс в ДОЛГОЖИВУЩЕМ workspace ``name`` (BOB-087.D5b).

        🔴 Это недостающее НАЧАЛО цикла возобновления (находка M3): :meth:`open` всегда
        создаёт ЭФЕМЕРНОЕ посессионное дерево, которое ``stop`` удаляет, поэтому
        накапливать было нечего и :meth:`propose_resume` не находил кандидата НИКОГДА —
        фича замыкалась сама на себя. Здесь работа сразу приземляется в накапливающее
        дерево (:meth:`~bob.coding.ports.PersistentWorkspace.ensure` на ветке
        :func:`~bob.coding.naming.workspace_branch`), которое переживает остановку.

        Отличие от :meth:`resume`: ``claude`` спавнится СВЕЖИЙ (без ``--resume``) — поднимать
        ещё нечего, id этой сессии сохранится по ходу и станет тем, что поднимут потом.
        Гейты те же, что у resume-пути (:meth:`_resume_refusal`): owner-only, одна сессия
        за раз, и весь путь собран только под флагом ``coder.resume``. Провал подготовки
        рабочего места — честный отказ, а не молчание.
        """
        refusal = self._resume_refusal(sender)
        if refusal is not None:
            return refusal
        now = self._clock.now()
        branch = workspace_branch(name)
        try:
            path = await self._require_workspace().ensure(branch)
            runner = self._runner_factory()
            await runner.open(path, mode=self._permission_mode)
        except Exception:  # 🔴 workspace/spawn fault: answer honestly, never go mute
            logger.exception("coding: opening the persistent workspace failed")
            return CodingOutcome(
                ok=False, message=session_voice.resume_failed(), session=None
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
        await self._go_live(session, runner, persistent=True)
        return CodingOutcome(
            ok=True, message=session_voice.workspace_opened(name), session=session
        )

    async def propose_resume(self, name: str, sender: int | None) -> CodingOutcome:
        """Owner-only: найти приостановленную сессию workspace ``name`` и ПЕРЕСПРОСИТЬ.

        🔴 Ничего не поднимает: ни worktree, ни процесса, ни записи — только находит
        кандидата и возвращает вопрос голосом Боба (с именем workspace и временем той
        сессии), взводя ожидающее подтверждение. Поднимет уже :meth:`resume`, и только
        после явного «да» (:meth:`resolve_pending_resume`).

        Отказы: не-owner — тихо (``_refused``, ни поиска, ни вопроса); живая сессия — 🔴
        отказ (одна сессия за раз, никакого live-attach); нет кандидата — честная реплика.
        """
        refusal = self._resume_refusal(sender)
        if refusal is not None:
            return refusal
        branch = workspace_branch(name)
        candidate = select_resumable(
            await self._require_lookup().by_branch(branch), branch=branch
        )
        if candidate is None:
            return CodingOutcome(
                ok=False, message=session_voice.resume_nothing(name), session=None
            )
        self._pending = _PendingResume(
            name=name, sender=sender, requested_at=self._clock.now()
        )
        return CodingOutcome(
            ok=True,
            message=session_voice.resume_confirm(
                workspace=name, when=candidate.updated_at.strftime(_WHEN_FORMAT).strip()
            ),
            session=candidate,
        )

    async def resolve_pending_resume(
        self, text: str, sender: int | None
    ) -> CodingOutcome | None:
        """Разрешить висящий вопрос «поднимаю?» очередным ходом owner'а (BOB-087.D3).

        ``None`` означает «ход резюме не касается — веди его обычным путём»: вопроса нет,
        отвечает не тот, кто спрашивал, подтверждение протухло (см.
        :func:`~bob.coding.resume_policy.is_confirmation_fresh`) или реплика не является
        ни явным «да», ни явным «нет». 🔴 Вопрос при этом ВСЕГДА снимается — он не
        залипает, поэтому «да», сказанное совсем по другому поводу, сессию не поднимет.

        Явное «да» в окне TTL → :meth:`resume`; явное «нет» → короткая отмена.
        """
        pending = self._pending
        if pending is None or not self._owner.is_owner(sender):
            return None
        if pending.sender != sender:
            return None  # чужой ответ не снимает и не подтверждает owner-вопрос
        self._pending = None
        if not is_confirmation_fresh(
            requested_at=pending.requested_at, now=self._clock.now()
        ):
            return None
        if is_confirmation(text):
            return await self.resume(pending.name, sender)
        if is_rejection(text):
            return CodingOutcome(
                ok=True, message=session_voice.resume_cancelled(), session=None
            )
        return None

    async def resume(self, name: str, sender: int | None) -> CodingOutcome:
        """Owner-only: поднять приостановленную сессию workspace ``name`` (BOB-087.D3).

        Находит кандидата (только ТЕРМИНАЛЬНОГО — никакого live-attach), обеспечивает
        ПЕРСИСТЕНТНЫЙ worktree (:meth:`~bob.coding.ports.PersistentWorkspace.ensure` —
        накопленное дерево реюзится, не пересоздаётся), спавнит раннер с
        ``resume_session_id`` того кандидата и заводит фоновую перекачку вывода в личку,
        как :meth:`open`.

        Персистится НОВАЯ запись сессии (свой ``id``) с тем же ``claude_session_id``:
        прошлая терминальная запись — исторический факт (её время/итог), переписывать его
        нельзя, а цепочка «сессия за сессией» остаётся видимой в сторе.

        🔴 Провал спавна НЕ удаляет workspace (в нём накопленная работа) — в отличие от
        эфемерного worktree в :meth:`open`, здесь убирать нечего и незачем. 🔴 Провал
        ПОДГОТОВКИ рабочего места (``ensure``) — такой же честный отказ, а не молчание
        (BOB-087.D5b): исключение, улетевшее наружу, глохло выше по стеку, и owner,
        сказавший «да», получал обычный разговорный ответ вместо правды о срыве.
        """
        refusal = self._resume_refusal(sender)
        if refusal is not None:
            return refusal
        branch = workspace_branch(name)
        candidate = select_resumable(
            await self._require_lookup().by_branch(branch), branch=branch
        )
        if candidate is None or candidate.claude_session_id is None:
            return CodingOutcome(
                ok=False, message=session_voice.resume_nothing(name), session=None
            )
        now = self._clock.now()
        try:
            path = await self._require_workspace().ensure(branch)
            runner = self._runner_factory()
            await runner.open(
                path,
                mode=self._permission_mode,
                resume_session_id=candidate.claude_session_id,
            )
        except Exception:  # workspace/spawn fault: 🔴 the workspace itself is left intact
            logger.exception("coding: interactive resume failed for workspace")
            return CodingOutcome(
                ok=False, message=session_voice.resume_failed(), session=None
            )
        session = CodingSession(
            id=self._id_factory(),
            task=candidate.task,
            state=CodingSessionState.INTERACTIVE,
            branch=branch,
            created_at=now,
            updated_at=now,
            worktree_path=path,
            claude_session_id=candidate.claude_session_id,
        )
        await self._go_live(session, runner, persistent=True)
        return CodingOutcome(
            ok=True, message=session_voice.resumed(name), session=session
        )

    async def stop(self, sender: int | None) -> CodingOutcome:
        """Owner-only 🔴 ПРЯМОЙ kill: закрыть раннер, убрать worktree, ``→ CANCELLED``.

        Прямой ``runner.close()`` (terminate→kill) завершает ДОЛГОЖИВУЩИЙ процесс — это
        не кооперативный break гейтед-кодера. Затем эфемерный worktree убирается (реюз
        ``_cleanup``) и сессия переводится в терминальное ``CANCELLED``. 🔴 У ВОЗОБНОВЛЁННОЙ
        сессии рабочее дерево — долгоживущий workspace, и оно НЕ удаляется: там накоплена
        работа, ради которой сессию и поднимали; прощальная реплика идёт ЗА судьбой дерева
        (``stopped_persistent`` вместо ``stopped``), чтобы Боб не докладывал об уборке
        того, что осталось на месте. Идемпотентно/best-effort: без живой сессии — честная
        заметка, без падения.
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
        if not live.persistent:  # 🔴 a persistent workspace keeps its accumulated work
            await self._cleanup(live.session.worktree_path)
        # 🔴 Голос идёт ЗА судьбой дерева (BOB-087.D4b): у персистентного workspace работа
        # осталась, и реплика не смеет докладывать про уборку.
        farewell = (
            session_voice.stopped_persistent()
            if live.persistent
            else session_voice.stopped()
        )
        now = self._clock.now()
        # BOB-087.D1: persist the claude session id captured off the init event so a later
        # /code (D3) can look it up for --resume. Since D5b this is only the BACKSTOP — the
        # id is already written the moment the init frame arrives (:meth:`_capture_id`), so
        # a crash mid-session no longer loses it; here it merely re-confirms it on the
        # terminal row. None when no init id was seen — the field stays None (byte-identical
        # to a pre-D1 session), and an id already persisted is kept.
        ended = live.session
        claude_session_id = live.runner.session_id
        if claude_session_id is not None:
            ended = ended.with_claude_session_id(claude_session_id, at=now)
        session = ended.with_state(CodingSessionState.CANCELLED, at=now)
        await self._store.save(session)
        self._cancelled.discard(session.id)
        self._task = None
        return CodingOutcome(ok=True, message=farewell, session=session)

    def active(self) -> bool:
        """Есть ли живой интерактивный сеанс (интейк-гейт .4 + гвард «одна сессия»)."""
        return self._live is not None

    # --- Internal orchestration ----------------------------------------------

    async def _go_live(
        self, session: CodingSession, runner: InteractiveRunner, *, persistent: bool
    ) -> None:
        """Персистнуть сессию, сделать её живой и завести перекачку вывода в личку.

        Общий финал :meth:`open` и :meth:`resume`; ``persistent`` фиксирует судьбу
        рабочего дерева (эфемерное убирается на ``stop``, workspace — нет).
        """
        await self._store.save(session)
        self._live = _LiveSession(
            session=session, runner=runner, persistent=persistent
        )
        self._task = asyncio.create_task(self._pump(session.id, runner))

    def _resume_refusal(self, sender: int | None) -> CodingOutcome | None:
        """Общий гейт resume-пути: ``None``, если можно продолжать, иначе отказ.

        Три отказа подряд: не-owner (тихо), несобранный resume-путь (флаг ``coder.resume``
        выключен → seams не инъектированы, путь инертен) и 🔴 живая сессия (одна за раз,
        никакого live-attach).
        """
        if not self._owner.is_owner(sender):
            return _refused()
        if self._lookup is None or self._workspace is None:
            return _refused()
        if self._live is not None:
            return CodingOutcome(
                ok=False,
                message=session_voice.interactive_busy(),
                session=self._live.session,
            )
        return None

    def _require_lookup(self) -> ResumableSessionLookup:
        """Инъектированный поиск сессий (гейт ``_resume_refusal`` уже проверил наличие)."""
        lookup = self._lookup
        if lookup is None:  # pragma: no cover — _resume_refusal already returned
            raise _NotWiredError
        return lookup

    def _require_workspace(self) -> PersistentWorkspace:
        """Инъектированный персистентный workspace (наличие проверил ``_resume_refusal``)."""
        workspace = self._workspace
        if workspace is None:  # pragma: no cover — _resume_refusal already returned
            raise _NotWiredError
        return workspace

    async def _pump(self, session_id: str, runner: InteractiveRunner) -> None:
        """Перекачивать вывод раннера в DM owner'а, пока сеанс жив (fault-isolated).

        Делегирует ВЕСЬ поток событий инъектированному :class:`LiveRunStreamer`
        (``_DmLiveStreamer`` реюз): каждое сырое stream-json событие рендерится и льётся
        в личку. ``is_cancelled`` (kill-switch ``stop``) обрывает поток; сбой стрима
        изолирован — он не валит менеджер. Поток проходит через :meth:`_capture_id`,
        который по дороге забирает claude-session-id из init-кадра.
        """
        streamer = self._streamer_factory()
        try:
            await streamer.stream(
                self._capture_id(session_id, runner.events()),
                is_cancelled=lambda: session_id in self._cancelled,
            )
        except Exception:  # an output-stream fault must never crash the manager
            logger.exception("coding: interactive output stream failed for %s", session_id)

    async def _capture_id(
        self, session_id: str, events: AsyncIterator[Mapping[str, object]]
    ) -> AsyncIterator[Mapping[str, object]]:
        """Пропустить поток насквозь, ПЕРСИСТНУВ claude-session-id из init-кадра.

        🔴 BOB-087.D5b (M5): id сохранялся только в :meth:`stop`, поэтому рестарт/краш
        посреди живого сеанса терял его НАВСЕГДА — и «поднять с телефона» поднимало бы
        более старую нить разговора поверх свежей работы в дереве. Теперь id уходит в стор
        в тот момент, как ``claude`` его назвал (первый же ``init``-кадр), ещё до любого
        стопа. Проходной трансформер, а не второй потребитель потока: событие идёт дальше
        в стример НЕИЗМЕНЁННЫМ, поэтому рендер в личку байт-в-байт прежний.
        """
        captured = False
        async for event in events:
            if not captured:
                claude_session_id = extract_session_id(event)
                if claude_session_id is not None:
                    captured = True
                    await self._persist_claude_id(session_id, claude_session_id)
            yield event

    async def _persist_claude_id(self, session_id: str, claude_session_id: str) -> None:
        """Записать id claude-сессии в живую строку (best-effort — поток не рушим)."""
        live = self._live
        if live is None or live.session.id != session_id:
            return  # сеанс уже закрыт/подменён — дописывать нечего
        try:
            live.session = live.session.with_claude_session_id(
                claude_session_id, at=self._clock.now()
            )
            await self._store.save(live.session)
        except Exception:  # a persistence fault must never break the live stream
            logger.exception(
                "coding: persisting the claude session id failed for %s", session_id
            )

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


class _NotWiredError(RuntimeError):
    """Resume-seam запросили при несобранном resume-пути (недостижимо: гейт впереди)."""


def _refused() -> CodingOutcome:
    """Тихий отказ не-owner'у — ни сессии, ни worktree, ни спавна, ни сообщения."""
    return CodingOutcome(ok=False, message="", session=None)
