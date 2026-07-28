# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=application

"""ActiveRulesReader — application-адаптер чтения APPROVED-правил для применения (BOB-028 .3).

Реализует ``SelfImprovementReader`` (read seam :class:`HandleMessage`): грузит
персистнутые правила из :class:`~bob.proactivity.ports.SelfImprovementStore` и возвращает
ТОЛЬКО ``active_rules`` (APPROVED) — applied-сторона никогда не видит PROPOSED/PAUSED/
REJECTED/REMOVED (authz-before-autonomy держится здесь, ещё до доменного
``build_modulators``, который перефильтрует повторно). Без I/O в домене: вся работа со
стором — здесь, в application.

Best-effort: сбой стора → ПУСТО (правил нет), а не исключение — самоулучшение никогда
не должно валить ход сообщения; в худшем случае Боб просто отвечает как до BOB-028.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.proactivity.self_improvement import active_rules

if TYPE_CHECKING:
    from bob.proactivity.self_improvement import ImprovementRule

logger = logging.getLogger(__name__)

__all__ = [
    "ActiveRulesReader",
    "RuleLoader",
]


class RuleLoader(Protocol):
    """The load seam the reader needs (a structural subset of SelfImprovementStore)."""

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]: ...


class ActiveRulesReader:
    """Чтение APPROVED-правил для мягкого применения (``SelfImprovementReader``)."""

    def __init__(self, *, store: RuleLoader, persona_id: str) -> None:
        self._store = store
        self._persona_id = persona_id

    async def active(self) -> tuple[ImprovementRule, ...]:
        """Вернуть только APPROVED-правила (пусто при отсутствии / сбое стора)."""
        try:
            rules = await self._store.load(self._persona_id)
        except Exception:
            logger.exception("Loading self-improvement rules failed; none applied")
            return ()
        return active_rules(rules)
