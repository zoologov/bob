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

Порядок разбора одного хода: сначала команда ВХОДА (открыть можно и без активного сеанса);
затем — если сеанс НЕ активен — ход инертен (обычный Боб); при активном сеансе сначала
команда ВЫХОДА (проверяется ДО feed), иначе плоский текст форвардится в stdin. Всё
инъектируется, поэтому роутинг детерминирован в тестах (нет ни живого claude, ни транспорта).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from bob.coding.interactive_intent import is_interactive_exit, parse_interactive_entry

if TYPE_CHECKING:
    from bob.coding.usecases.coding_assistant import CodingOutcome

__all__ = ["InteractiveIntakeRouter", "InteractiveManagerLike", "OwnerDmNotifierLike"]


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


class OwnerDmNotifierLike(Protocol):
    """Транспорт для короткой строки режима (вход/выход) в личку owner'а (INV-5)."""

    async def send(self, text: str) -> None: ...


class InteractiveIntakeRouter:
    """Route one owner-DM message into the live interactive session (BOB-083 .4)."""

    def __init__(
        self, *, manager: InteractiveManagerLike, notifier: OwnerDmNotifierLike
    ) -> None:
        self._manager = manager
        self._notifier = notifier

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
        """
        if not is_owner or is_group:
            return False
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

    async def _emit(self, outcome: CodingOutcome) -> None:
        """Send the explicit mode line (INV-5) when the outcome carries one."""
        if outcome.message:
            await self._notifier.send(outcome.message)
