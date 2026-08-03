# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=domain

"""Дистиллированный рабочий эпизод Боба — чистое доменное ядро (BOB-087.B1).

:class:`WorkEpisode` — детальная первого-лица «операторская» вспоминка dev-сессии Боба
(«я попросил GUPPI починить X в файле Y; тесты Z падали; подняли лимит — позеленело»).
:func:`work_episode_event` осаждает её в :class:`~bob.memory.entities.EpisodicEvent` на
ОТДЕЛЬНОМ ``event_type`` ``work`` (а не ``self_action``): существующая self-action
озвучка/recall (:func:`~bob.personality.voice.recall_has_self_action`, ключ по
``self_action``) остаётся байт-в-байт, а register-aware recall Среза C получает чистый
шов по домену ``work``.

Сам термин ``work`` (:data:`~bob.kernel.episode_types.WORK_EVENT_TYPE`) — ОБЩИЙ словарь
трёх контекстов (memory пишет, conversation фильтрует нить, personality озвучивает), поэтому
он живёт в ядре (``kernel``) и ре-экспортируется отсюда ради совместимости импортов
(bob-abk.32: хранение термина в ``memory`` заставляло ``conversation`` импортировать соседний
домен и замыкало цикл ``conversation → memory → runtime-app → conversation``).

Провенанс (INV-3 чистота, разделение акторства): эпизод помечается тегами ``work``/``dev``
и маркером актора ``actor:bob`` — это ОПЕРАТОРСКАЯ вспоминка Боба; где сделал GUPPI/тест,
атрибуция живёт В контенте от первого лица («я попросил GUPPI…, GUPPI сделал…»).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.kernel.episode_types import WORK_EVENT_TYPE
from bob.memory.entities import EpisodicEvent

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "WORK_EVENT_TYPE",
    "WorkEpisode",
    "work_episode_event",
]

# Domain tags (recall labels) + a provenance marker: the deed is Bob's OWN operator
# recollection (``actor:bob``); GUPPI/tool/test attribution lives inside the content.
_TAG_WORK = "work"
_TAG_DEV = "dev"
_PROVENANCE_BOB = "actor:bob"
_WORK_TAGS = (_TAG_WORK, _TAG_DEV, _PROVENANCE_BOB)


@dataclass(frozen=True, slots=True)
class WorkEpisode:
    """Одна дистиллированная первого-лица операторская вспоминка dev-сессии."""

    content: str


def work_episode_event(
    episode: WorkEpisode,
    *,
    ts: datetime,
    sender_id: int | None,
    visibility: str | None,
) -> EpisodicEvent:
    """Осадить :class:`WorkEpisode` эпизодом ``work`` с тегами домена + провенансом.

    ``event_type`` = ``work`` (отдельный от ``self_action``); теги — ``work``/``dev`` +
    ``actor:bob`` (провенанс); ``visibility``/``sender_id`` пробрасываются вызывающим
    (coding-сессия owner-приватна).
    """
    return EpisodicEvent(
        ts=ts,
        event_type=WORK_EVENT_TYPE,
        content=episode.content,
        mood_snapshot=None,
        tags=_WORK_TAGS,
        sender_id=sender_id,
        visibility=visibility,
    )
