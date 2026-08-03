# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=application

"""Запись дистиллированного рабочего журнала на конце сессии (BOB-087.B1).

:class:`DistillingWorkJournalRecorder` связывает снимок сессии → дистиллятор → стор: на
конце coding-сессии (веха, НЕ per-firehose-event — урок BOB-076 флуд) сводит
:class:`~bob.coding.work_facts.SessionKeyFacts` в первого-лица операторские эпизоды
(:class:`~bob.coding.usecases.distill_work_journal.WorkJournalDistiller`) и осаждает их
эпизодами ``work`` (:func:`~bob.memory.work_journal.work_episode_event` — теги ``work``/
``dev`` + провенанс, visibility owner-приватно).

🔴 Best-effort (урок Part D BOB-078): сбой дистиллятора/стора НИКОГДА не роняет
coding/interactive-сессию — всё под ``try/except`` + лог. Пустой снимок пропускается
(дистиллировать нечего). :class:`NoOpWorkJournalRecorder` — реализация для выключенного
флага ``memory.work_journal``: ноль записей, память байт-в-байт как сегодня.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.memory.work_journal import work_episode_event
from bob.social.disclosure import VISIBILITY_OWNER_PRIVATE

if TYPE_CHECKING:
    from bob.coding.usecases.distill_work_journal import WorkJournalDistiller
    from bob.coding.work_facts import SessionKeyFacts, WorkOutcome
    from bob.kernel.ports import Clock
    from bob.memory.entities import EpisodicEvent

logger = logging.getLogger(__name__)

__all__ = [
    "DistillingWorkJournalRecorder",
    "NoOpWorkJournalRecorder",
    "WorkEpisodeStore",
]


class WorkEpisodeStore(Protocol):
    """Ровно та часть репозитория, что нужна записи — типизированная дверь эпизода."""

    async def save_episode_entity(self, event: EpisodicEvent) -> None:
        """Append one :class:`EpisodicEvent` domain entity."""
        ...


class DistillingWorkJournalRecorder:
    """Дистиллирует снимок сессии и осаждает эпизоды ``work`` (best-effort, за флагом ON)."""

    def __init__(
        self,
        *,
        distiller: WorkJournalDistiller,
        store: WorkEpisodeStore,
        clock: Clock,
    ) -> None:
        self._distiller = distiller
        self._store = store
        self._clock = clock

    async def record_session(
        self,
        task: str,
        facts: SessionKeyFacts,
        outcome: WorkOutcome,
        *,
        sender_id: int | None = None,
    ) -> None:
        """Свести факты сессии в эпизоды и осадить их (пустой снимок/сбой → тихо ничего).

        🔴 Best-effort: любой сбой дистилляции/записи проглатывается и логируется — фоновый
        рабочий журнал не должен ронять coding/interactive-сессию (урок Part D BOB-078).
        """
        try:
            if facts.is_empty():
                return
            episodes = await self._distiller.distill(task, facts, outcome)
            ts = self._clock.now()
            for episode in episodes:
                await self._store.save_episode_entity(
                    work_episode_event(
                        episode,
                        ts=ts,
                        sender_id=sender_id,
                        visibility=VISIBILITY_OWNER_PRIVATE,
                    )
                )
        except Exception:  # a journal fault must never crash the coding session
            logger.exception("work-journal recording failed for a session")


class NoOpWorkJournalRecorder:
    """Recorder-заглушка для выключенного ``memory.work_journal`` — ничего не пишет."""

    async def record_session(
        self,
        task: str,
        facts: SessionKeyFacts,
        outcome: WorkOutcome,
        *,
        sender_id: int | None = None,
    ) -> None:
        """No-op: рабочий журнал выключен, запись отсутствует (байт-в-байт как сегодня)."""
