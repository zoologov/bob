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
* пометка «проговорено» живёт В ХРАНИЛИЩЕ правил (BOB-096 срез 1) — повторный прогон
  молчит, и перезапуск процесса тоже: следующий прогон берёт следующее непроговорённое;
* проговариваются ТОЛЬКО ``PROPOSED`` — одобренное уже применяется, отклонённое/убранное
  owner закрыл, приостановленное он сам выключил;
* best-effort: сбой гейтвея логируется и НЕ валит тик — но и не повторяется вечно:
  попытка засчитывается ДО отправки, и после ``MAX_ANNOUNCE_ATTEMPTS`` Боб об этом
  правиле молчит (владелец видит его в ``/rules`` как недоставленное).

Опционально и аддитивно: без гейтвея/стора (unwired) — no-op, поведение ровно как до
BOB-028. Никакого ПРИМЕНЕНИЯ здесь — Боб лишь предлагает; включает owner командой.

🔴 ЧТО ЛОМАЛОСЬ ДО BOB-096 (наблюдалось вживую шесть дней, 6–12 августа 2026). Пометка
была ``set`` в памяти процесса и ставилась ПОСЛЕ успешной отправки, а сбой уходил в
``return`` до неё. При битой сети правило уходило на КАЖДОМ reflect-тике (раз в 5 минут),
а каждый перезапуск проговаривал владельцу заново ВСЕ предложения. Здесь исправлен
именно этот путь доставки; ФОРМУЛИРОВКА реплики — отдельная работа (срез 5).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.proactivity.rule_announcement import MAX_ANNOUNCE_ATTEMPTS, next_to_announce

if TYPE_CHECKING:
    from bob.proactivity.self_improvement import ImprovementRule

logger = logging.getLogger(__name__)

__all__ = [
    "AnnounceProposedRules",
    "RuleAnnounceGateway",
    "RuleAnnounceStore",
]


class RuleAnnounceStore(Protocol):
    """The rule-store seam the announcer needs (BOB-028 .3, BOB-096 срез 1).

    Read: ``load`` gives Bob's persisted rules (with their delivery bookkeeping). Write:
    the two narrow marks that make «уже говорил» outlive the process —
    ``record_announce_attempt`` (one attempt spent) and ``mark_announced`` (the owner
    heard it). A structural subset of
    :class:`~bob.proactivity.ports.SelfImprovementStore`, so the live SQLite store and a
    fake both satisfy it; the announcer never moves a rule's :class:`RuleState` (owner
    approval is not its business).
    """

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]: ...
    async def record_announce_attempt(self, persona_id: str, rule_id: str) -> None: ...
    async def mark_announced(self, persona_id: str, rule_id: str) -> None: ...


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
        store: RuleAnnounceStore,
        gateway: RuleAnnounceGateway,
        chat_id: int,
        persona_id: str,
        max_attempts: int = MAX_ANNOUNCE_ATTEMPTS,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._chat_id = chat_id
        self._persona_id = persona_id
        # Кап попыток доставки ОДНОГО предложения. Дефолт — доменный
        # MAX_ANNOUNCE_ATTEMPTS; параметр оставлен ради тестов, а не как ручка конфига.
        self._max_attempts = max_attempts

    async def run(self) -> None:
        """Проговорить самое старое непроговорённое PROPOSED-правило (best-effort).

        Порядок записей — то, что делает кап настоящим капом: попытка засчитывается
        ДО отправки, поэтому её не теряет ни сбой гейтвея, ни падение процесса посреди
        отправки. Успех дополнительно ставит «owner услышал», и правило больше не
        проговаривается — ни на следующем тике, ни после перезапуска.
        """
        rules = await self._store.load(self._persona_id)
        target = next_to_announce(rules, max_attempts=self._max_attempts)
        if target is None:
            return
        await self._store.record_announce_attempt(self._persona_id, target.id)
        try:
            await self._gateway.reply(
                chat_id=self._chat_id, markdown=_render(target)
            )
        except Exception:
            logger.exception(
                "Announcing a proposed rule failed (best-effort): rule=%s attempt=%d/%d",
                target.id,
                target.announce_attempts + 1,
                self._max_attempts,
            )
            return
        await self._store.mark_announced(self._persona_id, target.id)


def _render(rule: ImprovementRule) -> str:
    """Render Bob's tactful one-rule proposal (observation + adjustment + how to enable)."""
    return _PROPOSAL_TEMPLATE.format(
        observation=rule.observation,
        adjustment=rule.adjustment,
        rule_id=rule.id,
    )
