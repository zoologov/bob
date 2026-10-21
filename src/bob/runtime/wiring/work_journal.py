# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root work-journal wiring — дистиллированная память за ``memory.work_journal``.

Единственное место, где читается голый флаг ``memory.work_journal`` (по образцу
``memory.autobiography``): OFF (default) → :class:`NoOpWorkJournalRecorder` (ноль записей,
память байт-в-байт как сегодня); ON → :class:`DistillingWorkJournalRecorder` поверх Tier-0
дистиллятора (:class:`Tier0WorkJournalDistiller`) и общего репозитория памяти.

🔴 Флаг по умолчанию OFF: НИЧЕГО не пишется live, пока Срез C не приземлит register-aware
recall (иначе work-эпизоды всплывали бы в casual — окно засорения). Consumer (CodingAssistant)
всегда получает recorder; выбор no-op решает флаг, без ветвлений у потребителя.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.coding.usecases.distill_work_journal import Tier0WorkJournalDistiller
from bob.coding.usecases.work_journal_recorder import (
    DistillingWorkJournalRecorder,
    NoOpWorkJournalRecorder,
)
from bob.runtime.config import _flag, _section

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.router.llm_router import LLMRouter
    from bob.coding.usecases.coding_assistant import WorkJournalRecorder
    from bob.coding.usecases.work_journal_recorder import WorkEpisodeStore
    from bob.kernel.ports import Clock

__all__ = ["build_work_journal_recorder"]


def build_work_journal_recorder(
    config: Mapping[str, object],
    *,
    router: LLMRouter,
    store: WorkEpisodeStore,
    clock: Clock,
) -> WorkJournalRecorder:
    """Собрать recorder рабочего журнала: no-op при OFF, дистиллирующий при ON.

    OFF (default) → :class:`NoOpWorkJournalRecorder` (рабочий журнал выключен, память
    байт-в-байт). ON → :class:`DistillingWorkJournalRecorder` над Tier-0 дистиллятором и
    общим репозиторием. Всегда возвращает объект порта — потребитель не ветвится по флагу.
    """
    if not _flag(_section(config, "memory"), "work_journal"):
        return NoOpWorkJournalRecorder()
    return DistillingWorkJournalRecorder(
        distiller=Tier0WorkJournalDistiller(router=router),
        store=store,
        clock=clock,
    )
