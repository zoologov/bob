# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root self-action wiring — автобиография Боба за ``memory.autobiography``.

Единственное место, где читается голый флаг ``memory.autobiography`` (по образцу
``presence.stream_read``): OFF (default) → :class:`NoOpSelfActionRecorder` (ноль
записей, поведение как раньше); ON → :class:`MemoryBackedSelfActionRecorder` поверх
общего репозитория памяти. Consumer'ы (coding-сессия, tool-loop — беады .2/.3)
всегда получают recorder; выбор no-op решает флаг, без ветвлений у потребителя.

Здесь же — колбэк, которым монитор здоровья LLM записывает эпизод «я молчал» (BOB-116):
это тот же recorder, а ``application`` в ``memory`` не ходит, поэтому мост — в сборке.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.kernel.local_time import in_local_zone
from bob.kernel.visibility import VISIBILITY_OWNER_PRIVATE
from bob.memory.adapters.self_action_recorder import (
    MemoryBackedSelfActionRecorder,
    NoOpSelfActionRecorder,
)
from bob.memory.self_action import OutageSpan, SelfAction, SelfActionKind
from bob.runtime.config import _flag, _section

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from bob.application.router.health_monitor import OutageRecovered
    from bob.kernel.ports import Clock
    from bob.memory.adapters.self_action_recorder import SelfActionEpisodeStore
    from bob.memory.ports import SelfActionRecorder

__all__ = ["build_outage_episode_writer", "build_self_action_recorder"]


def build_self_action_recorder(
    config: Mapping[str, object],
    *,
    store: SelfActionEpisodeStore,
    clock: Clock,
) -> SelfActionRecorder:
    """Собрать recorder самодействия: no-op при OFF, memory-backed при ON.

    OFF (default) → :class:`NoOpSelfActionRecorder` (автобиография выключена). ON →
    :class:`MemoryBackedSelfActionRecorder` над общим репозиторием. Всегда возвращает
    объект порта — потребитель не ветвится по флагу.
    """
    if not _flag(_section(config, "memory"), "autobiography"):
        return NoOpSelfActionRecorder()
    return MemoryBackedSelfActionRecorder(store, clock=clock)


def build_outage_episode_writer(recorder: SelfActionRecorder) -> OutageRecovered:
    """Колбэк монитора здоровья LLM → эпизод «я молчал» в автобиографии (BOB-116).

    Монитор зовёт его только после настоящей немоты (правило «думать было нечем» — его, не
    сборки). Эпизод — про внутреннюю жизнь Боба, поэтому только владельцу
    (``owner_private``) и без отправителя. Время переводится в пояс процесса — тот же, в
    котором GUPPI ``/status`` показывает «деградирован с …», — чтобы Боб и статус называли
    одно и то же время одинаково (:mod:`bob.kernel.local_time`). Без
    ``memory.autobiography`` recorder — no-op.
    """

    async def write(
        provider_id: str, since: datetime, until: datetime, failure_class: str | None
    ) -> None:
        outage = OutageSpan(
            since=in_local_zone(since),
            until=in_local_zone(until),
            failure_class=failure_class,
            provider=provider_id,
        )
        await recorder.record(
            SelfAction(kind=SelfActionKind.OUTAGE_RECOVERED, outage=outage),
            sender_id=None,
            visibility=VISIBILITY_OWNER_PRIVATE,
        )

    return write
