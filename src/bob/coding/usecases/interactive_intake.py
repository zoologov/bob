# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=application

"""InteractiveIntakeRouter — интейк-режим живого терминала в личке (BOB-083 .4).

Единственная ответственность: решить, что делать с ОДНИМ owner-DM сообщением в контексте
живого интерактивного сеанса — ОТКРЫТЬ сеанс, СФОРВАРДИТЬ реплику в stdin (steer),
ЗАКРЫТЬ сеанс — и вернуть, был ли ход ПОГЛОЩЁН (чтобы приём не пошёл обычным chat-путём).
Аналог :class:`~bob.coding.usecases.coding_intent_router.CodingIntentRouter` для гейтед-
кодера, но для двустороннего живого сеанса.

🔴 Безопасность (INV-3, «режим не залипает»):

* **owner-only + DM-only** — оба гейта проверяются ЗДЕСЬ (defense-in-depth поверх
  owner-гейта самого менеджера): не-owner или групповое сообщение НИКОГДА не открывает
  сеанс и не течёт в stdin — ход не поглощается, идёт обычным путём.
* **режим строго по активной сессии** — steer-гейт (форвард реплики в stdin) срабатывает
  ТОЛЬКО пока :meth:`~bob.coding.usecases.interactive_session.InteractiveSessionManager.
  active` истинно. Нет живого сеанса → плоское сообщение НЕ поглощается (обычный Боб) →
  после ``stop`` / смерти процесса личка возвращается к обычному общению.
* **явный вход/выход (INV-5)** — на открытии/закрытии роутер шлёт owner'у короткую
  строку режима (``CodingOutcome.message`` из ``session_voice``), чтобы owner всегда знал,
  в каком режиме находится.

Порядок разбора одного хода: сначала ответ на висящий вопрос ВОЗОБНОВЛЕНИЯ (если resume
вообще собран); затем команда ВХОДА (открыть можно и без активного сеанса); затем команда
ВОЗОБНОВЛЕНИЯ; затем — если сеанс НЕ активен — ход инертен (обычный Боб); при активном
сеансе сначала команда ВЫХОДА (проверяется ДО feed), иначе плоский текст форвардится в
stdin. Всё инъектируется, поэтому роутинг детерминирован в тестах (нет ни живого claude,
ни транспорта).

🔴 Возобновление (BOB-087.D3) собирается ТОЛЬКО при флаге ``coder.resume``: seam
:class:`ResumeSupportLike` опционален и по умолчанию ``None``, поэтому при выключенном
флаге роутер физически не держит ссылки на resume — команда ``/resume …`` не
распознаётся, ход идёт обычным путём, и поведение байт-в-байт равно BOB-083.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from bob.coding.interactive_intent import (
    is_interactive_exit,
    parse_interactive_entry,
    parse_interactive_resume,
)

if TYPE_CHECKING:
    from bob.coding.usecases.coding_assistant import CodingOutcome

__all__ = [
    "InteractiveIntakeRouter",
    "InteractiveManagerLike",
    "OwnerDmNotifierLike",
    "ResumeSupportLike",
]


class InteractiveManagerLike(Protocol):
    """Узкая поверхность живого сеанса, которой правит роутер (BOB-083 .3).

    Структурное подмножество
    :class:`~bob.coding.usecases.interactive_session.InteractiveSessionManager`:
    ``active`` — синхронный запрос «есть ли живой сеанс» (гейт режима), ``open`` / ``feed``
    / ``stop`` — owner-проверенные мутаторы (каждый ре-чекает owner'а внутри). Роутер не
    тянется дальше этих четырёх методов.
    """

    def active(self) -> bool: ...
    async def open(self, task: str, sender: int | None) -> CodingOutcome: ...
    async def feed(self, text: str) -> None: ...
    async def stop(self, sender: int | None) -> CodingOutcome: ...


class ResumeSupportLike(Protocol):
    """Узкая поверхность ВОЗОБНОВЛЕНИЯ приостановленной работы (BOB-087.D3).

    Структурное подмножество
    :class:`~bob.coding.usecases.interactive_session.InteractiveSessionManager`, вынесенное
    в ОТДЕЛЬНЫЙ опциональный seam нарочно: при выключенном флаге ``coder.resume``
    композиция просто не передаёт его, и роутер не может выразить возобновление вообще
    (а старые фейки менеджера остаются валидны). ``propose_resume`` — переспросить по
    явной команде (ничего не поднимает), ``resolve_pending_resume`` — разрешить висящий
    вопрос очередным ходом (``None`` = ход резюме не касается, вести обычным путём).
    """

    async def propose_resume(self, name: str, sender: int | None) -> CodingOutcome: ...
    async def resolve_pending_resume(
        self, text: str, sender: int | None
    ) -> CodingOutcome | None: ...


class OwnerDmNotifierLike(Protocol):
    """Транспорт для короткой строки режима (вход/выход) в личку owner'а (INV-5)."""

    async def send(self, text: str) -> None: ...


class InteractiveIntakeRouter:
    """Route one owner-DM message into the live interactive session (BOB-083 .4)."""

    def __init__(
        self,
        *,
        manager: InteractiveManagerLike,
        notifier: OwnerDmNotifierLike,
        resume: ResumeSupportLike | None = None,
    ) -> None:
        self._manager = manager
        self._notifier = notifier
        # Resume seam (BOB-087.D3) — ``None`` unless ``coder.resume`` is on: the whole
        # resume path (pending answer + the ``/resume`` command) is then unreachable.
        self._resume = resume

    async def route(
        self, *, text: str, sender: int | None, is_owner: bool, is_group: bool
    ) -> bool:
        """Maybe route ``text`` into the live session; return whether it was consumed.

        🔴 owner-only + DM-only: a non-owner or a group message is NEVER routed (returns
        ``False`` so the normal chat path handles it — the guest/group never enters
        interactive or feeds stdin). An entry command opens a fresh session (and emits the
        explicit mode line); with a live session an exit command stops it (checked BEFORE
        feed) and any other plain reply is fed to stdin; with no live session a plain
        message is left to the chat path (the mode does not stick).

        When the resume seam is wired (BOB-087.D3, ``coder.resume``), the turn is FIRST
        offered to the pending «поднимаю?» question: only an explicit answer is consumed
        there, anything else falls through to the ordinary path (having dropped the
        question). A leading ``/resume <workspace>`` command then merely ASKS — it raises
        nothing by itself.
        """
        if not is_owner or is_group:
            return False
        if await self._route_resume(text, sender):
            return True
        task = parse_interactive_entry(text)
        if task is not None:
            await self._emit(await self._manager.open(task, sender))
            return True
        if not self._manager.active():
            return False
        if is_interactive_exit(text):
            await self._emit(await self._manager.stop(sender))
            return True
        await self._manager.feed(text)
        return True

    async def _route_resume(self, text: str, sender: int | None) -> bool:
        """Отработать resume-путь этого хода; вернуть, был ли ход ПОГЛОЩЁН (BOB-087.D3).

        Порядок внутри пути: сначала ответ на висящий вопрос «поднимаю?» (поглощается
        только явное «да»/«нет» — всё прочее лишь СНИМАЕТ вопрос и идёт дальше), затем
        ведущая команда ``/resume <workspace>``, которая только ПЕРЕСПРАШИВАЕТ. Resume-путь
        и путь входа не пересекаются по командам, поэтому их порядок не важен. Без
        собранного seam'а (флаг ``coder.resume`` выключен) путь целиком инертен.
        """
        resume = self._resume
        if resume is None:
            return False
        settled = await resume.resolve_pending_resume(text, sender)
        if settled is not None:
            await self._emit(settled)
            return True
        workspace = parse_interactive_resume(text)
        if workspace is None:
            return False
        await self._emit(await resume.propose_resume(workspace, sender))
        return True

    async def _emit(self, outcome: CodingOutcome) -> None:
        """Send the explicit mode line (INV-5) when the outcome carries one."""
        if outcome.message:
            await self._notifier.send(outcome.message)
