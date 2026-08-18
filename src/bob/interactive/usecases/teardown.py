# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=interactive
# beadloom:layer=application

"""SessionTeardown — терминальное завершение ЗАБРАННОГО сеанса (BOB-087.E, bob-6u2).

ОДНА ответственность: довести уже забранный сеанс до конца — прибить процесс, решить
судьбу рабочего дерева и записать терминальную строку. Всё здесь best-effort по одному
правилу: **уборка не смеет отменить уже случившийся конец сеанса** — ни сбой ``close``,
ни сбой ``git worktree remove``, ни сбой стора не имеют права съесть прощальную реплику
owner'а или уронить ход.

🔴 Почему отдельный коллаборатор: менеджер живого сеанса
(:class:`~bob.interactive.usecases.session.InteractiveSessionManager`) держит РЕШЕНИЯ —
кто сейчас жив, кто забрал сеанс, что сказать owner'у. Здесь — только ПОСЛЕДСТВИЯ,
одинаковые для обоих концов сеанса (явный ``stop`` и смерть процесса), и они нарочно
ОДНИ: судьба дерева и терминальная запись не смеют разъезжаться по поводу окончания
(bob-kv4). Этот объект не знает ни про ``_live``, ни про переговоры — он получает
готовый :class:`~bob.interactive.entities.LiveSession` и заканчивает его.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.coding.state import CodingSessionState

if TYPE_CHECKING:
    from datetime import datetime
    from typing import Protocol

    from bob.coding.entities import CodingSession
    from bob.coding.ports import CodingSessionStore, InteractiveRunner, Worktree
    from bob.interactive.entities import LiveSession

    class _Clock(Protocol):
        """Часы, которые нужны уборке (инъектируются для детерминизма тестов)."""

        def now(self) -> datetime: ...


logger = logging.getLogger(__name__)

__all__ = ["SessionTeardown"]


class SessionTeardown:
    """Конец забранного сеанса: раннер убит, дерево по судьбе, строка терминальна."""

    def __init__(
        self, *, worktree: Worktree, store: CodingSessionStore, clock: _Clock
    ) -> None:
        self._worktree = worktree
        self._store = store
        self._clock = clock

    async def finalize(self, live: LiveSession) -> CodingSession:
        """Довести ЗАБРАННЫЙ сеанс до терминального конца: дерево + строка в сторе.

        Общий хвост обоих концов сеанса — явного ``stop`` и смерти процесса — нарочно
        ОДИН (bob-kv4). 🔴 Персистентный workspace переживает конец сеанса (в нём
        накопленная работа), эфемерный — убирается.

        BOB-087.D1: id claude-сессии из init-события дописывается на терминальную строку,
        чтобы позже её можно было поднять через ``--resume``. Начиная с D5b это лишь
        БЭКСТОП — id уже сохранён в момент прихода init-кадра; здесь он только
        подтверждается. Без увиденного init-id поле остаётся ``None`` (байт-в-байт
        до-D1), а уже сохранённый id не затирается.
        """
        if not live.persistent:  # 🔴 a persistent workspace keeps its accumulated work
            await self.cleanup(live.session.worktree_path)
        return await self.hand_over(live)

    async def hand_over(self, live: LiveSession) -> CodingSession:
        """Закрыть СТРОКУ забранного сеанса, НЕ трогая рабочее дерево.

        🔴 Отличие от :meth:`finalize` ровно одно и оно про судьбу дерева: сюда приходят,
        когда в то же самое место сейчас же ВЕРНУТСЯ — повторным заходом ``--resume``
        после того, как владелец разрешил словами упершийся шаг (BOB-088, срез 3). Убрать
        дерево здесь значило бы стереть работу той самой сессии, которую поднимаем: путь
        у нового процесса тот же, а эфемерность к разрешению отношения не имеет.

        Строка при этом закрывается по-настоящему (терминальное состояние + сохранённый
        ``claude_session_id``): у нового захода будет СВОЯ строка, как и у ``resume``, —
        цепочка «сессия за сессией» остаётся видимой, а нетерминальных сирот не остаётся.
        """
        now = self._clock.now()
        ended = live.session
        claude_session_id = live.runner.session_id
        if claude_session_id is not None:
            ended = ended.with_claude_session_id(claude_session_id, at=now)
        session = ended.with_state(CodingSessionState.CANCELLED, at=now)
        await self._persist_terminal(session)
        return session

    async def close_runner(self, runner: InteractiveRunner) -> None:
        """Прямой kill раннера (best-effort — уже мёртвый процесс не должен падать)."""
        try:
            await runner.close()
        except Exception:  # a close fault must never mask the stop outcome
            logger.exception("coding: interactive runner close failed")

    async def cleanup(self, path: str | None) -> None:
        """Убрать worktree (идемпотентно best-effort; не течём, не роняем ход)."""
        if path is None:
            return
        try:
            await self._worktree.remove(path)
        except Exception:  # cleanup must never mask the real outcome
            logger.exception("coding: interactive worktree cleanup failed for %s", path)

    async def _persist_terminal(self, session: CodingSession) -> None:
        """Записать терминальную строку сессии (best-effort — прощание не теряем).

        🔴 BOB-087.D5c (N2): запись жила вне защиты, и сбой стора съедал прощальную
        реплику ``stop`` — процесс УЖЕ убит и дерево УЖЕ убрано, а owner про это не
        слышал. Осиротевшую ``INTERACTIVE``-строку подберёт стартовый свип (D5b), так
        что цена сбоя — устаревшая строка, а не немой Боб.
        """
        try:
            await self._store.save(session)
        except Exception:  # a persistence fault must never eat the farewell
            logger.exception(
                "coding: persisting the terminal interactive session failed for %s",
                session.id,
            )
