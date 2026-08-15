# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=interactive
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
  инъектированный :class:`~bob.coding.ports.LiveRunStreamer` (реюз ``_DmLiveStreamer``
  BOB-082).
* :meth:`feed` — форвардит owner-реплику в открытый stdin раннера (steer).
* :meth:`stop` — 🔴 ПРЯМОЙ kill: ``runner.close()`` (terminate→kill) + уборка worktree
  + перевод сессии в терминальное ``CANCELLED``. Это НЕ кооперативный break гейтед-кодера
  (живого read-loop для выхода недостаточно) — процесс завершается напрямую. Идемпотентно.
* :meth:`active` — есть ли живой сеанс (для интейк-гейта .4 и гварда «одна сессия»).

🔴 Сеанс может кончиться и БЕЗ owner-команды (bob-kv4, долг BOB-083/084): ``claude``
крашится, выходит сам или чтение его stdout обрывается. Раньше ``_pump`` при этом не
трогал ``_live``: ``active()`` продолжал отдавать ``True``, реплики owner'а уходили в
мёртвый stdin, а интейк ПОГЛОЩАЛ ходы — Боб в личке был нем до явного «стоп». Теперь
конец потока событий завершает сеанс ТЕМ ЖЕ путём, что ``stop`` (общая уборка
:class:`~bob.interactive.usecases.teardown.SessionTeardown`: судьба дерева, терминальная
строка, сохранённый ``claude_session_id``), и owner слышит ЧЕСТНУЮ реплику о том, что
сеанс кончился сам (:func:`~bob.interactive.voice.interactive_ended` — не прощание на его
«стоп»: приписывать owner'у чужое действие нельзя). Идемпотентность структурная: забрать
сеанс можно только через :meth:`_claim`, и это СИНХРОННЫЙ обмен — кто забрал первым, тот
один и закрывает, поэтому гонка «процесс умер И owner жмёт стоп» не даёт ни двойного
закрытия, ни двойной реплики.

Возобновление приостановленной работы (BOB-087.D3) — «поднять с телефона нашу
эпик-сессию»: owner явной командой просит поднять ДОЛГОЖИВУЩИЙ workspace, и это
ДВУХШАГОВЫЙ путь с подтверждением:

* :meth:`propose_resume` — owner-only. Ничего не спавнит: находит кандидата (чистая
  политика :func:`~bob.interactive.resume_policy.select_resumable`) и возвращает ВОПРОС
  голосом Боба, взводя ожидающее подтверждение (owner-скоуплено, с TTL) в
  :class:`~bob.interactive.resume_negotiation.ResumeNegotiation`.
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
INV-2). 🔴 Оговорка (BOB-087.D5b, находка M4): это верно про КОД менеджера, но при включённом
``coder.allow_bypass`` сам ``claude`` работает без пер-действенного гейта в linked worktree,
который делит с основным репо ``.git``, refs, remotes и credentials — тогда INV-2 держится на
суждении owner'а, а не на структуре.

Всё инъектируется (фабрика раннера / worktree / фабрика стримера / owner-гейт /
часы / фабрика id / режим), поэтому use-case детерминирован в тестах и не трогает ни
настоящий ``claude``/``git``, ни глобалы (зеркалит конструкцию ``CodingAssistant``).

🔴 Чего менеджер НЕ делает сам (BOB-087.E, bob-6u2): машина висящего вопроса «поднимаю?»
живёт в :class:`~bob.interactive.resume_negotiation.ResumeNegotiation`, а последствия
конца сеанса (kill раннера, судьба дерева, терминальная строка) — в
:class:`~bob.interactive.usecases.teardown.SessionTeardown`. Здесь остались РЕШЕНИЯ: кто
сейчас жив, кто забрал сеанс и что услышит owner. 🔴 :meth:`_claim` и поле ``_live``
отсюда не уедут: на их синхронном обмене держится идемпотентность гонки.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import TYPE_CHECKING

from bob.coding.entities import CodingOutcome, CodingSession
from bob.coding.naming import workspace_branch, worktree_branch
from bob.coding.state import CodingSessionState
from bob.interactive import voice
from bob.interactive.argv_policy import extract_session_id
from bob.interactive.entities import LiveSession
from bob.interactive.pipeline_prompt import pipeline_first_frame
from bob.interactive.resume_negotiation import ResumeConfirmed, ResumeNegotiation
from bob.interactive.resume_policy import select_resumable
from bob.interactive.usecases.teardown import SessionTeardown

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping
    from datetime import datetime
    from typing import Protocol

    from bob.coding.ports import (
        CodingSessionStore,
        InteractiveRunner,
        LiveRunStreamer,
        OwnerCheck,
        OwnerNotifier,
        PersistentWorkspace,
        ResumableSessionLookup,
        Worktree,
    )

    class _Clock(Protocol):
        """Часы, которые нужны менеджеру (инъектируются для детерминизма тестов)."""

        def now(self) -> datetime: ...


logger = logging.getLogger(__name__)

__all__ = ["InteractiveSessionManager"]

# Режим по умолчанию для живого сеанса: правки авто-принимаются В WORKTREE (spросов нет),
# main при этом неприкосновенен (изоляция worktree + отсутствие push/PR). Композиция может
# переопределить через ``coder.permission_mode``; раннер валидирует против allowlist —
# и именно этот allowlist расширяет owner-флаг ``coder.allow_bypass``, под которым
# «неприкосновенность main» перестаёт быть структурной (BOB-087.D5b, находка M4).
_DEFAULT_INTERACTIVE_MODE = "acceptEdits"

# Человеческая метка времени прошлой сессии в вопросе-подтверждении («…трогали 02.08 в
# 10:00 UTC») — owner отвечает «да» с телефона и должен понимать, ЧТО именно поднимает.
# 🔴 Зона В МЕТКЕ (BOB-087.D5b): время хранится в UTC, а owner прочёл бы его как местное
# и мог подтвердить не ту сессию. ``%Z`` печатает зону, если она известна, и ничего — если
# нет (тогда хвостовой пробел срезается), поэтому метка никогда не врёт о зоне.
_WHEN_FORMAT = "%d.%m в %H:%M %Z"


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
        notifier: OwnerNotifier | None = None,
        pipeline_prompt: bool = False,
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
        # The owner's DM line for what the manager says on its OWN initiative (bob-kv4:
        # «сеанс кончился сам»). Every OTHER reply travels back as a ``CodingOutcome`` to
        # the turn that asked for it; this one has no turn to answer, so it needs its own
        # way out. Optional: unwired → the session still ends honestly, just silently.
        self._notifier = notifier
        # 🔴 Ставится ли задача ПЕРВЫМ кадром (``coder.pipeline_prompt``, BOB-088 срез 2).
        # OFF (дефолт) → сессия открывается ровно как до среза: пустой контекст, ожидание
        # owner'а. Текст постановки решает НЕ этот класс, а домен
        # (:func:`bob.interactive.pipeline_prompt.pipeline_first_frame`) — здесь только «когда».
        self._pipeline_prompt = pipeline_prompt
        # The single pending «поднимаю?» question — its own collaborator (BOB-087.E):
        # owner-scoped, TTL-bounded, never sticky.
        self._negotiation = ResumeNegotiation(clock=clock)
        # The CONSEQUENCES of an ending (kill the runner, the tree's fate, the terminal
        # row) — one path for BOTH ends of a session: the explicit ``stop`` and the
        # process dying on its own.
        self._teardown = SessionTeardown(worktree=worktree, store=store, clock=clock)
        # The single live session (``None`` when idle — the one-session guard reads this).
        self._live: LiveSession | None = None
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
        отказ. Не-owner получает тихий отказ (нет worktree, нет спавна). 🔴 ОТМЕНА хода
        прямо посреди спавна (bob-1qc) сворачивает его так же, как сбой: раннер закрыт,
        эфемерное дерево убрано — и только потом отмена летит дальше.
        """
        if not self._owner.is_owner(sender):
            return _refused()
        if self._live is not None:
            return CodingOutcome(
                ok=False, message=voice.interactive_busy(), session=self._live.session
            )
        now = self._clock.now()
        branch = worktree_branch(task)
        try:
            path = await self._worktree.create(branch)
        except Exception:  # 🔴 git/worktree fault BEFORE the spawn: answer, never go mute
            logger.exception("coding: interactive worktree create failed for task")
            return CodingOutcome(
                ok=False, message=voice.interactive_setup_failed(), session=None
            )
        try:
            runner = await self._spawn(path, task)
        except asyncio.CancelledError:  # 🔴 отмена: дерево тоже не остаётся сиротой
            await self._teardown.cleanup(path)
            raise
        except Exception:  # spawn/mode fault: clean up the worktree, no live session
            logger.exception("coding: interactive open failed for task")
            await self._teardown.cleanup(path)
            return CodingOutcome(
                ok=False, message=voice.interactive_failed(), session=None
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
        if not await self._go_live(session, runner, persistent=False):
            return CodingOutcome(
                ok=False, message=voice.interactive_failed(), session=None
            )
        return CodingOutcome(
            ok=True, message=voice.interactive_opened(), session=session
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
            runner = await self._spawn(path, task)
        except Exception:  # 🔴 workspace/spawn fault: answer honestly, never go mute
            logger.exception("coding: opening the persistent workspace failed")
            return CodingOutcome(
                ok=False, message=voice.resume_failed(), session=None
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
        if not await self._go_live(session, runner, persistent=True):
            return CodingOutcome(
                ok=False, message=voice.resume_failed(), session=None
            )
        return CodingOutcome(
            ok=True, message=voice.workspace_opened(name), session=session
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
        found = await self._resumable_or_refusal(name, branch)
        if isinstance(found, CodingOutcome):
            return found
        candidate = found
        self._negotiation.ask(name=name, sender=sender)
        return CodingOutcome(
            ok=True,
            message=voice.resume_confirm(
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
        :func:`~bob.interactive.resume_policy.is_confirmation_fresh`) или реплика не
        является ни явным «да», ни явным «нет». 🔴 Вопрос при этом ВСЕГДА снимается — он
        не залипает, поэтому «да», сказанное совсем по другому поводу, сессию не поднимет.

        Явное «да» в окне TTL → :meth:`resume`; явное «нет» → короткая отмена. Саму машину
        вопроса держит :class:`~bob.interactive.resume_negotiation.ResumeNegotiation`;
        здесь остаётся owner-гейт и решение, что делать с её вердиктом.
        """
        if not self._negotiation.is_pending() or not self._owner.is_owner(sender):
            return None
        answer = self._negotiation.settle(text, sender)
        if answer is None:
            return None
        if isinstance(answer, ResumeConfirmed):
            return await self.resume(answer.workspace, sender)
        return CodingOutcome(ok=True, message=voice.resume_cancelled(), session=None)

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
        found = await self._resumable_or_refusal(name, branch)
        if isinstance(found, CodingOutcome):
            return found
        candidate = found
        if candidate.claude_session_id is None:
            return CodingOutcome(
                ok=False, message=voice.resume_nothing(name), session=None
            )
        now = self._clock.now()
        try:
            path = await self._require_workspace().ensure(branch)
            runner = await self._spawn(
                path, candidate.task, resume_session_id=candidate.claude_session_id
            )
        except Exception:  # workspace/spawn fault: 🔴 the workspace itself is left intact
            logger.exception("coding: interactive resume failed for workspace")
            return CodingOutcome(
                ok=False, message=voice.resume_failed(), session=None
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
        if not await self._go_live(session, runner, persistent=True):
            return CodingOutcome(
                ok=False, message=voice.resume_failed(), session=None
            )
        return CodingOutcome(ok=True, message=voice.resumed(name), session=session)

    async def stop(self, sender: int | None) -> CodingOutcome:
        """Owner-only 🔴 ПРЯМОЙ kill: закрыть раннер, убрать worktree, ``→ CANCELLED``.

        Прямой ``runner.close()`` (terminate→kill) завершает ДОЛГОЖИВУЩИЙ процесс — это
        не кооперативный break гейтед-кодера. Затем эфемерный worktree убирается и сессия
        переводится в терминальное ``CANCELLED`` (общая уборка
        :class:`~bob.interactive.usecases.teardown.SessionTeardown`). 🔴 У ВОЗОБНОВЛЁННОЙ
        сессии рабочее дерево — долгоживущий workspace, и оно НЕ удаляется: там накоплена
        работа, ради которой сессию и поднимали; прощальная реплика идёт ЗА судьбой дерева
        (``stopped_persistent`` вместо ``stopped``), чтобы Боб не докладывал об уборке
        того, что осталось на месте. Идемпотентно/best-effort: без живой сессии — честная
        заметка, без падения. 🔴 Сеанс забирается через :meth:`_claim`, поэтому «процесс
        умер И owner жмёт стоп» закрывает его РОВНО один раз (bob-kv4).
        """
        if not self._owner.is_owner(sender):
            return _refused()
        # Take the live handle in ONE synchronous step (active() is false at once) — the
        # pump cannot then end the same session behind our back — and signal the pump.
        live = self._claim()
        if live is None:
            return CodingOutcome(ok=False, message=voice.no_session(), session=None)
        self._cancelled.add(live.session.id)
        # 🔴 direct terminate of the process
        await self._teardown.close_runner(live.runner)
        await self._await_pump()
        session = await self._teardown.finalize(live)
        # 🔴 Голос идёт ЗА судьбой дерева (BOB-087.D4b): у персистентного workspace работа
        # осталась, и реплика не смеет докладывать про уборку.
        farewell = voice.stopped_persistent() if live.persistent else voice.stopped()
        self._cancelled.discard(session.id)
        self._task = None
        return CodingOutcome(ok=True, message=farewell, session=session)

    def active(self) -> bool:
        """Есть ли живой интерактивный сеанс (интейк-гейт .4 + гвард «одна сессия»)."""
        return self._live is not None

    # --- Internal orchestration ----------------------------------------------

    async def _go_live(
        self, session: CodingSession, runner: InteractiveRunner, *, persistent: bool
    ) -> bool:
        """Персистнуть сессию, сделать её живой и завести перекачку вывода в личку.

        Общий финал :meth:`open`, :meth:`open_workspace` и :meth:`resume`; ``persistent``
        фиксирует судьбу рабочего дерева (эфемерное убирается на ``stop``, workspace — нет).

        🔴 ``False`` = сессия НЕ поднялась (BOB-087.D5c, N2). Персист жил вне защиты, а
        ``claude`` к этому моменту УЖЕ ЖИВЁТ: сбой стора улетал наружу, ``_live``/``_task``
        не выставлялись — процесс оставался СИРОТОЙ (``stop`` его не видит, дерево занято),
        и owner не получал ничего. Правило шва одно: любой сбой после спавна сворачивает
        спавн (раннер закрывается, эфемерное дерево убирается — накопленный workspace нет)
        и возвращает вызывающему честный отказ вместо молчания.
        """
        try:
            await self._store.save(session)
        except Exception:
            logger.exception("coding: persisting the interactive session failed")
            # 🔴 никаких неостановимых сирот
            await self._teardown.close_runner(runner)
            if not persistent:
                await self._teardown.cleanup(session.worktree_path)
            return False
        self._live = LiveSession(session=session, runner=runner, persistent=persistent)
        self._task = asyncio.create_task(self._pump(session.id, runner))
        return True

    async def _spawn(
        self, path: str, task: str, *, resume_session_id: str | None = None
    ) -> InteractiveRunner:
        """Спавнить живой раннер в ``path`` так, чтобы НЕДОСПАВНЕННЫЙ не остался сиротой.

        Единственная точка спавна на все три входа (:meth:`open`, :meth:`open_workspace`,
        :meth:`resume`) — и, с BOB-088 (срез 2), единственная точка ПОСТАНОВКИ задачи
        (:meth:`_put_the_task`). Обе двери свежей сессии проходят здесь, поэтому «одну
        научили, вторую забыли» невыразимо: раньше именно так и было бы, ведь эпик
        открывается ``open_workspace``, а не ``open``.

        🔴 bob-1qc (защита в глубину): свёртка живёт в ``finally``, а не
        в ``except Exception``, потому что :class:`asyncio.CancelledError` — ``BaseException``
        и мимо ``except Exception`` пролетает. Отмена хода прямо внутри ``runner.open``
        (шатдаун, таймаут внешней задачи) раскручивала стек мимо всякой очистки, а
        запущенный процесс оставался БЕЗ живой сессии — неостановимый сирота, которого
        ``stop`` не видит. Теперь и сбой, и отмена закрывают раннер одним и тем же путём;
        отмена после этого летит дальше нетронутой. Постановка стоит ВНУТРИ той же защиты:
        сессия, которой не удалось отдать задачу, не остаётся жить пустой и незакрытой.
        """
        runner = self._runner_factory()
        spawned = False
        try:
            await runner.open(
                path, mode=self._permission_mode, resume_session_id=resume_session_id
            )
            if resume_session_id is None:
                await self._put_the_task(runner, task)
            spawned = True
        finally:
            if not spawned:
                await self._teardown.close_runner(runner)
        return runner

    async def _put_the_task(self, runner: InteractiveRunner, task: str) -> None:
        """Отдать свежей сессии ПЕРВЫЙ кадр — задачу и указание идти по процессу.

        🔴 До BOB-088 (срез 2) сюда не уходило ничего: ``claude`` стартовал с пустым
        контекстом и ждал, пока owner напишет сам, а задача работала лишь меткой сессии и
        именем ветки. Живая проба подтвердила обратное: первый кадр в открытый stdin
        принимается и ЗАПУСКАЕТ ход.

        Инертно без owner-флага ``coder.pipeline_prompt`` (дефолт OFF → спавн байт-в-байт
        прежний) и при пустой задаче (:func:`~bob.interactive.pipeline_prompt.
        pipeline_first_frame` возвращает ``None``: додуманная моделью задача, которую
        поведёт конвейер, хуже отсутствия постановки).

        🔴 ТОЛЬКО СВЕЖАЯ сессия (вызывается при ``resume_session_id is None``): у поднятой
        задача уже в её контексте, и повторная постановка велела бы начать эпик заново —
        поверх работы, ради которой сессию и поднимали.
        """
        if not self._pipeline_prompt:
            return
        frame = pipeline_first_frame(task)
        if frame is None:
            return
        await runner.feed(frame)

    def _claim(self, session_id: str | None = None) -> LiveSession | None:
        """🔴 СИНХРОННО забрать живой сеанс — единственная точка выхода из ``_live``.

        Идемпотентность закрытия держится именно здесь, и держится СТРУКТУРНО: проверка
        и обнуление ``_live`` идут без единого ``await``, поэтому между ними не может
        вклиниться ни ``stop``, ни фоновая перекачка. Кто забрал сеанс первым, тот один
        его и закрывает; проигравший получает ``None`` и не делает НИЧЕГО — ни второго
        ``close``, ни второй уборки дерева, ни второй прощальной реплики.

        ``session_id`` (перекачка знает, ЗА КАКИМ сеансом пришла) сверяется с живым: если
        сеанс уже сменился, старая перекачка не тронет чужой.
        """
        live = self._live
        if live is None:
            return None
        if session_id is not None and live.session.id != session_id:
            return None
        self._live = None
        return live

    async def _end_on_its_own(self, session_id: str) -> None:
        """Завершить сеанс, который кончился САМ: процесс умер / поток событий иссяк.

        🔴 bob-kv4 (долг BOB-083/084). Раньше конец потока не значил ничего: ``_live``
        оставался выставленным, ``active()`` отдавал ``True``, реплики owner'а уходили в
        мёртвый stdin, интейк ПОГЛОЩАЛ ходы — Боб в личке был нем до явного «стоп».
        Теперь это такой же честный конец, как ``stop``: сеанс забирается (:meth:`_claim`),
        мёртвый процесс всё равно пожимается (никаких зомби), дерево и терминальная строка
        идут общей уборкой (:class:`~bob.interactive.usecases.teardown.SessionTeardown`),
        и owner слышит правду.

        Ничего не делает, если сеанс уже забрал ``stop`` (или он давно сменился) — это и
        есть идемпотентность на гонке «умер И жмут стоп».
        """
        live = self._claim(session_id)
        if live is None:
            return
        # пожать мёртвого ребёнка, без зомби
        await self._teardown.close_runner(live.runner)
        session = await self._teardown.finalize(live)
        self._cancelled.discard(session.id)
        # 🔴 Реплика идёт ЗА судьбой дерева и НЕ выдаёт смерть процесса за owner-«стоп».
        await self._say(
            voice.interactive_ended_persistent()
            if live.persistent
            else voice.interactive_ended()
        )

    async def _say(self, text: str) -> None:
        """Сказать owner'у одну строку по СОБСТВЕННОЙ инициативе (best-effort).

        Незавязанный нотификатор → молчание (сеанс всё равно завершён честно), сбой
        отправки изолирован: транспорт не смеет отменить уже случившийся конец сеанса.
        """
        notifier = self._notifier
        if notifier is None:
            return
        try:
            await notifier.send(text)
        except Exception:  # a transport fault must never break the ending itself
            logger.exception("coding: telling the owner the session ended failed")

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
                message=voice.interactive_busy(),
                session=self._live.session,
            )
        return None

    async def _resumable_or_refusal(
        self, name: str, branch: str
    ) -> CodingSession | CodingOutcome:
        """Найти терминального кандидата на подъём — либо вернуть ГОТОВЫЙ отказ.

        Общий вход :meth:`propose_resume` и :meth:`resume`. Два разных «нет», и путать их
        нельзя: 🔴 сбой стора (SQLite locked) — это ``resume_failed`` (BOB-087.D5c, N2:
        запрос жил вне защиты, исключение глохло выше по стеку, и owner получал обычный
        разговорный ход вместо правды), а пустой результат — ``resume_nothing``. Врать про
        «нечего поднимать», когда стор просто не ответил, Боб не станет.
        """
        try:
            rows = await self._require_lookup().by_branch(branch)
        except Exception:
            logger.exception("coding: the resumable-session lookup failed")
            return CodingOutcome(
                ok=False, message=voice.resume_failed(), session=None
            )
        candidate = select_resumable(rows, branch=branch)
        if candidate is None:
            return CodingOutcome(
                ok=False, message=voice.resume_nothing(name), session=None
            )
        return candidate

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

        Делегирует ВЕСЬ поток событий инъектированному
        :class:`~bob.coding.ports.LiveRunStreamer` (``_DmLiveStreamer`` реюз): каждое сырое
        stream-json событие рендерится и льётся в личку. ``is_cancelled`` (kill-switch
        ``stop``) обрывает поток; сбой стрима изолирован — он не валит менеджер. Поток
        проходит через :meth:`_capture_id`, который по дороге забирает claude-session-id
        из init-кадра.

        🔴 Конец потока = конец сеанса (bob-kv4): дочитав до конца, перекачка ЗАВЕРШАЕТ
        сеанс (:meth:`_end_on_its_own`) — процесс либо умер сам, либо его закрыл ``stop``
        (тогда завершать уже нечего, сеанс забран). Молча вернуться, оставив ``_live``
        выставленным, нельзя: это и был немой режим.
        """
        streamer = self._streamer_factory()
        try:
            await streamer.stream(
                self._capture_id(session_id, runner.events()),
                is_cancelled=lambda: session_id in self._cancelled,
            )
        except Exception:  # an output-stream fault must never crash the manager
            logger.exception("coding: interactive output stream failed for %s", session_id)
            return
        await self._end_on_its_own(session_id)

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

    async def _await_pump(self) -> None:
        """Дождаться завершения фоновой перекачки вывода (после close раннер EOF'ит)."""
        task = self._task
        if task is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            await task


class _NotWiredError(RuntimeError):
    """Resume-seam запросили при несобранном resume-пути (недостижимо: гейт впереди)."""


def _refused() -> CodingOutcome:
    """Тихий отказ не-owner'у — ни сессии, ни worktree, ни спавна, ни сообщения."""
    return CodingOutcome(ok=False, message="", session=None)
