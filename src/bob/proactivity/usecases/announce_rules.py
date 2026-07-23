# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=application

"""AnnounceProposedRules — Боб проговаривает свежее правило owner'у (BOB-028 .3).

После того как детектор (.2) сложил кандидата-правило в ``PROPOSED``, Боб при случае
тактично проговаривает его owner'у — «Заметил за собой: …. Предлагаю: …. Включить?
(/rule approve <id>)» — и owner решает (apply читает только ``active_rules``, то есть
лишь APPROVED). Этот use-case драйвится медленным reflect-кадэнсом (как детектор) и
держит границы «не спамить»:

* ОДНО за раз — при нескольких PROPOSED проговаривается ровно одно (самое старое
  непроговорённое), чтобы не заваливать owner'а;
* помечается «announced» (in-memory, на процесс) — повторный прогон не повторяет уже
  проговорённое правило; следующий прогон берёт следующее непроговорённое;
* проговариваются ТОЛЬКО ``PROPOSED`` — одобренное уже применяется, отклонённое/убранное
  owner закрыл, приостановленное он сам выключил;
* best-effort: сбой гейтвея логируется и НЕ валит тик.

Опционально и аддитивно: без гейтвея/стора (unwired) — no-op, поведение ровно как до
BOB-028. Никакого ПРИМЕНЕНИЯ здесь — Боб лишь предлагает; включает owner командой.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.proactivity.self_improvement import RuleState

if TYPE_CHECKING:
    from bob.proactivity.self_improvement import ImprovementRule

logger = logging.getLogger(__name__)

__all__ = [
    "AnnounceProposedRules",
    "RuleAnnounceGateway",
    "RuleReader",
]


class RuleReader(Protocol):
    """The read seam the announcer needs: load Bob's persisted rules (BOB-028 .3)."""

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]: ...


class RuleAnnounceGateway(Protocol):
    """The post seam the announcer needs: send Bob's proposal into a chat (BOB-028 .3).

    A structural subset of the reply gateway (Bob's own voice — HE proposes), so the
    live Telegram gateway and a fake both satisfy it. The returned ``message_id``
    (BOB-050) is ignored here — the announcer only posts.
    """

    async def reply(
        self, *, chat_id: int, markdown: str, thinking: str | None = None
    ) -> int | None: ...


# Шаблон тактичного предложения (рус, голос Боба). Грундирован в реальном правиле:
# наблюдение + поправка + как включить. Cyrillic look-alikes intentional.
_PROPOSAL_TEMPLATE = (
    "Заметил за собой: {observation}. Предлагаю: {adjustment}. "
    "Включить? (/rule approve {rule_id})"
)


class AnnounceProposedRules:
    """Проговорить owner'у ОДНО свежее PROPOSED-правило за прогон (BOB-028 .3)."""

    def __init__(
        self,
        *,
        store: RuleReader,
        gateway: RuleAnnounceGateway,
        chat_id: int,
        persona_id: str,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._chat_id = chat_id
        self._persona_id = persona_id
        # In-memory «announced» guard (на процесс): не повторять одно и то же правило.
        # Намеренно не персист — переживший рестарт повтор предложения owner'у не
        # критичен и не нарушает безопасность (apply читает только APPROVED).
        self._announced: set[str] = set()

    async def run(self) -> None:
        """Проговорить самое старое непроговорённое PROPOSED-правило (best-effort)."""
        rules = await self._store.load(self._persona_id)
        target = self._pick(rules)
        if target is None:
            return
        try:
            await self._gateway.reply(
                chat_id=self._chat_id, markdown=_render(target)
            )
        except Exception:
            logger.exception("Announcing a proposed rule failed (best-effort)")
            return
        self._announced.add(target.id)

    def _pick(self, rules: tuple[ImprovementRule, ...]) -> ImprovementRule | None:
        """Самое старое PROPOSED-правило, ещё не проговорённое (или ``None``)."""
        pending = [
            rule
            for rule in rules
            if rule.state is RuleState.PROPOSED and rule.id not in self._announced
        ]
        if not pending:
            return None
        return min(pending, key=lambda rule: (rule.created_at, rule.id))


def _render(rule: ImprovementRule) -> str:
    """Render Bob's tactful one-rule proposal (observation + adjustment + how to enable)."""
    return _PROPOSAL_TEMPLATE.format(
        observation=rule.observation,
        adjustment=rule.adjustment,
        rule_id=rule.id,
    )
