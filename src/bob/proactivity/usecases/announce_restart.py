# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=application

"""AnnounceRestart — Боб предупреждает об обновлении и говорит, что вернулся (BOB-094 срез 1).

Оркестрация вокруг чистого ядра :mod:`bob.proactivity.restart_voice` (голос) и маркера
в ``kv`` (память между запусками). Канон BOB-090.D: это ГОЛОС Боба (его бот), не строка
деплой-скрипта — поэтому реплику подбирает ядро голоса, а этот use-case решает лишь
КОГДА и КУДА говорить и как НЕ подвесить завершение.

Два момента:

* :meth:`announce_leaving` зовётся в graceful-shutdown ДО закрытия транспорта. Он
  предупреждает owner'а И группу и кладёт маркер апдейт-остановки в ``kv``. 🔴 Отправка
  ограничена ТАЙМАУТОМ: если сеть легла, реплика молча не уходит, но завершение НЕ
  блокируется (``systemctl restart`` шлёт SIGTERM — окно короткое). Маркер ставится
  ДАЖЕ при неудачной отправке: следующий старт всё равно должен знать, что это был
  апдейт, а не падение.
* :meth:`announce_returned` зовётся на старте. Он говорит «вернулся, обновился» ТОЛЬКО
  когда маркер апдейт-остановки есть, и КОНСУМИТ его (одно возвращение на один апдейт).
  Маркера нет (Боб упал сам) → он молчит: притворяться апдейтом — ложь. Маркер снимается
  и при неудачной отправке — иначе Боб пытался бы «вернуться» на каждом старте вечно.

Best-effort и не-блокирующе по построению: любой сбой/таймаут отправки логируется и
проглатывается, завершение и старт продолжаются. Без гейтвея/стора (unwired) весь хук
не собирается — флаг ``restart_notice`` (default OFF) держит поведение байт-в-байт.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from bob.proactivity.restart_voice import RestartMoment, restart_voice

logger = logging.getLogger(__name__)

__all__ = [
    "AnnounceRestart",
    "RestartMarkerStore",
    "RestartNotifier",
]

# Дефолтный потолок ожидания одной отправки. Окно рестарта короткое (SIGTERM →
# graceful-shutdown), поэтому таймаут мал: успели — хорошо, легла сеть — молча вышли.
_DEFAULT_TIMEOUT_SECONDS = 5.0


class RestartNotifier(Protocol):
    """Куда Боб объявляет рестарт: owner-DM И группа (решение owner'а, BOB-094).

    Две узкие двери — личка owner'а и групповой топик. Структурный субсет: живой
    адаптер над ботом Боба и фейк оба его удовлетворяют. Реплику даёт use-case; notifier
    только доставляет.
    """

    async def notify_owner(self, text: str) -> None: ...
    async def notify_group(self, text: str) -> None: ...


class RestartMarkerStore(Protocol):
    """Память между запусками: был ли прошлый выход апдейт-остановкой (BOB-094).

    ``mark_update_pending`` кладёт маркер в ``kv`` при уходе; ``consume_update_pending``
    на старте читает-и-снимает его (маркер есть → это был апдейт; нет → падение).
    ``next_epoch`` даёт растущий детерминированный номер рестарта — им ядро голоса
    ВАРЬИРУЕТ реплику от раза к разу без ``random``/времени.
    """

    async def mark_update_pending(self, marker: str) -> None: ...
    async def consume_update_pending(self) -> str | None: ...
    async def next_epoch(self) -> int: ...


class AnnounceRestart:
    """Объявить уход на обновление и возвращение после него (BOB-094 срез 1)."""

    def __init__(
        self,
        *,
        notifier: RestartNotifier,
        marker_store: RestartMarkerStore,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._notifier = notifier
        self._marker_store = marker_store
        self._timeout = timeout_seconds

    async def announce_leaving(self) -> None:
        """Предупредить owner'а и группу об обновлении и оставить маркер (best-effort).

        🔴 Порядок намеренный: маркер ставится в самом начале, ДО отправки, поэтому его
        не теряет ни таймаут, ни падение процесса посреди отправки — следующий старт всё
        равно узнает апдейт. Затем — одна отправка каждой двери, ограниченная общим
        таймаутом, чтобы завершение не подвисло на легшей сети.
        """
        marker = await self._marker(RestartMoment.LEAVING)
        await self._marker_store.mark_update_pending(marker)
        line = restart_voice(RestartMoment.LEAVING, marker=marker)
        await self._deliver(line)

    async def announce_returned(self) -> None:
        """Сказать «вернулся, обновился» — ТОЛЬКО если прошлый выход был апдейтом.

        Маркер читается-и-снимается: есть → это был апдейт, говорим и консумим (одно
        возвращение на один апдейт); нет → Боб упал сам, молчим (притворяться апдейтом
        нельзя). Маркер снят в любом случае, даже если отправка не удалась, — иначе Боб
        «возвращался» бы на каждом последующем старте.
        """
        marker = await self._marker_store.consume_update_pending()
        if marker is None:
            return
        line = restart_voice(RestartMoment.RETURNED, marker=marker)
        await self._deliver(line)

    async def _marker(self, moment: RestartMoment) -> str:
        """Собрать маркер рестарта: растущий epoch, чтобы реплики не были однообразны."""
        epoch = await self._marker_store.next_epoch()
        return f"{moment.value}-{epoch}"

    async def _deliver(self, line: str) -> None:
        """Отправить реплику owner'у и в группу под общим таймаутом (не блокируя).

        🔴 ``asyncio.wait_for`` — тот самый предохранитель против зависшей сети: истёк
        таймаут → отправка отменяется, хук возвращается, завершение/старт не подвисают.
        Любой сбой (таймаут, транспорт) логируется и проглатывается — объявление
        рестарта декоративно, оно не вправе уронить lifecycle.
        """
        try:
            await asyncio.wait_for(self._send_both(line), timeout=self._timeout)
        except Exception:
            logger.warning(
                "Restart announcement did not complete (best-effort, not blocking)",
                exc_info=True,
            )

    async def _send_both(self, line: str) -> None:
        """Отправить в обе двери: сперва owner-DM, затем группа."""
        await self._notifier.notify_owner(line)
        await self._notifier.notify_group(line)
