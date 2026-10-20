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
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.memory.adapters.self_action_recorder import (
    MemoryBackedSelfActionRecorder,
    NoOpSelfActionRecorder,
)
from bob.runtime.config import _flag, _section

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.kernel.ports import Clock
    from bob.memory.adapters.self_action_recorder import SelfActionEpisodeStore
    from bob.memory.ports import SelfActionRecorder

__all__ = ["build_self_action_recorder"]


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
