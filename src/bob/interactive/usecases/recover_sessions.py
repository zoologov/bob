# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=application

"""RecoverInteractiveSessions — свип осиротевших живых сеансов на старте (BOB-087.D5b).

ОДНА ответственность: привести стор в честное состояние после НЕЧИСТОГО завершения
процесса. Живой интерактивный сеанс (:class:`~bob.coding.state.CodingSessionState.
INTERACTIVE`) существует ровно столько, сколько живёт держащий его процесс: он привязан
к запущенному ``claude`` и к объекту менеджера в памяти. Значит любая ``INTERACTIVE``
строка, УВИДЕННАЯ НА СТАРТЕ, по определению осиротела — процесс, который мог бы её
закрыть, уже мёртв (деплой, краш, kill).

Что чинится (обе беды наблюдаемы owner'ом):

* :meth:`~bob.coding.ports.CodingSessionStore.active` вечно отдаёт такую строку как
  in-flight, и гейтед-кодер на любую новую задачу отвечает «я уже в работе»;
* :func:`~bob.coding.resume_policy.select_resumable` её ПРОПУСКАЕТ (кандидат обязан быть
  терминальным — правило «никакого live-attach»), поэтому «поднять с телефона» молча
  поднимало БОЛЕЕ СТАРУЮ нить разговора поверх свежей работы в дереве.

🔴 Свип НАРОЧНО узкий — только ``INTERACTIVE``. Гейтед стадии (``PLANNING`` /
``PLAN_READY`` / ``EXECUTING``) переживают рестарт НАМЕРЕННО: owner может одобрить
план и назавтра, и снос его сессии был бы потерей работы, а не восстановлением. Свип
идемпотентен (второй запуск ничего не находит) и best-effort: он выполняется на загрузке,
и его сбой не смеет уронить старт Боба.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.coding.state import CodingSessionState

if TYPE_CHECKING:
    from datetime import datetime
    from typing import Protocol

    from bob.coding.ports import CodingSessionStore

    class _Clock(Protocol):
        """Часы, которые нужны свипу (инъектируются для детерминизма тестов)."""

        def now(self) -> datetime: ...


logger = logging.getLogger(__name__)

__all__ = ["RecoverInteractiveSessions"]

#: Терминальное состояние осиротевшей сессии. То же, что ставит явный ``stop``: сеанс
#: действительно оборвался, не завершившись результатом, — ``CANCELLED`` это и означает.
#: Так строка становится и невидимой для ``active()``, и ЗАКОННЫМ кандидатом возобновления
#: (если успела сохранить ``claude_session_id`` — BOB-087.D5b M5а).
_RECOVERED_STATE = CodingSessionState.CANCELLED


class RecoverInteractiveSessions:
    """Перевести осиротевшие ``INTERACTIVE``-строки в терминальное состояние."""

    def __init__(self, *, store: CodingSessionStore, clock: _Clock) -> None:
        self._store = store
        self._clock = clock

    async def run(self) -> int:
        """Закрыть все осиротевшие живые сессии; вернуть, сколько их было.

        Best-effort: сбой стора логируется и возвращает ``0`` — свип идёт на загрузке
        процесса и не имеет права её сорвать. Пустой стор / отсутствие ``INTERACTIVE``
        строк — ноль записей (путь с выключенным интерактивом не пишет вообще ничего).
        """
        try:
            orphans = [
                session
                for session in await self._store.active()
                if session.state is CodingSessionState.INTERACTIVE
            ]
            now = self._clock.now()
            for session in orphans:
                await self._store.save(session.with_state(_RECOVERED_STATE, at=now))
        except Exception:  # a recovery fault must never block the boot
            logger.exception("coding: recovery of orphaned interactive sessions failed")
            return 0
        if orphans:
            logger.info(
                "coding: closed %d orphaned interactive session(s) left by a restart",
                len(orphans),
            )
        return len(orphans)
