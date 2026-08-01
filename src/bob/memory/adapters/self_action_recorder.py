# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=infrastructure

"""Адаптеры записи самодействия Боба (BOB-079.1).

:class:`MemoryBackedSelfActionRecorder` реализует узкий порт
:class:`~bob.memory.ports.SelfActionRecorder` поверх памяти: рендерит поступок от
первого лица (:func:`~bob.memory.self_action.describe_self_action`) и оседает одним
эпизодом ``self_action`` через типизированную дверь ``save_episode_entity``.
Флаг ``is_anomaly`` кодируется тегом ``anomaly`` (retrievable) — отдельная колонка
не нужна, ``event_type`` уже голая строка.

:class:`NoOpSelfActionRecorder` — реализация для выключенного флага
``memory.autobiography``: ноль записей, поведение как раньше. Consumer'ы всегда
получают recorder; выбор no-op решает флаг (без ветвлений по коду у потребителя).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from bob.memory.entities import EpisodicEvent
from bob.memory.self_action import describe_self_action

if TYPE_CHECKING:
    from bob.kernel.ports import Clock
    from bob.memory.self_action import SelfAction

__all__ = [
    "MemoryBackedSelfActionRecorder",
    "NoOpSelfActionRecorder",
    "SelfActionEpisodeStore",
]


class SelfActionEpisodeStore(Protocol):
    """Ровно та часть репозитория, что нужна записи — типизированная дверь эпизода."""

    async def save_episode_entity(self, event: EpisodicEvent) -> None:
        """Append one :class:`EpisodicEvent` domain entity."""
        ...


class MemoryBackedSelfActionRecorder:
    """Пишет самодействие эпизодом ``self_action`` через :class:`SelfActionEpisodeStore`."""

    def __init__(self, store: SelfActionEpisodeStore, *, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    async def record(
        self,
        action: SelfAction,
        *,
        sender_id: int | None = None,
        visibility: str | None = None,
    ) -> None:
        """Отрендерить поступок от первого лица и осадить одним эпизодом."""
        rendered = describe_self_action(action)
        event = EpisodicEvent(
            ts=self._clock.now(),
            event_type="self_action",
            content=rendered.content,
            mood_snapshot=None,
            tags=rendered.tags,
            sender_id=sender_id,
            visibility=visibility,
        )
        await self._store.save_episode_entity(event)


class NoOpSelfActionRecorder:
    """Recorder-заглушка для выключенного ``memory.autobiography`` — ничего не пишет."""

    async def record(
        self,
        action: SelfAction,
        *,
        sender_id: int | None = None,
        visibility: str | None = None,
    ) -> None:
        """No-op: автобиография выключена, запись отсутствует."""
