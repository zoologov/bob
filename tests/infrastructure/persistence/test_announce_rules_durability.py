# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Доставка предложения правила над НАСТОЯЩИМ SQLite (BOB-096 срез 1).

🔴 ЗАЧЕМ ОТДЕЛЬНО ОТ tests/application/usecases/test_announce_rules.py: там хранилище —
фейк, а тест на фейке доказывает контракт фейка (§0.3 п.4). Дефект жил ровно на стыке
«пометка в памяти процесса против пометки в базе», поэтому здесь use-case ходит в живой
:class:`SqliteSelfImprovementStore` поверх файла базы, а «перезапуск» — это ЗАКРЫТЬ базу
и ОТКРЫТЬ заново, новым репо, новым стором и новым экземпляром use-case'а (ровно то, что
делал владелец несколько раз за те шесть дней и каждый раз получал полный комплект
предложений заново).

Гейтвей остаётся фейком осознанно: это Telegram, его в тесте не поднять. Проверяется
именно ДОЛГОВЕЧНОСТЬ пометки и КАП попыток при сбое отправки.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.proactivity.adapters.self_improvement_store import SqliteSelfImprovementStore
from bob.proactivity.rule_announcement import (
    MAX_ANNOUNCE_ATTEMPTS,
    AnnounceStatus,
    announce_status,
    is_undelivered_proposal,
)
from bob.proactivity.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
)
from bob.proactivity.usecases.announce_rules import AnnounceProposedRules

if TYPE_CHECKING:
    from pathlib import Path

_PERSONA = "bob"
_CHAT_ID = -100123
_NOW = datetime(2026, 8, 6, 8, 37, 54, tzinfo=UTC)
#: Потолок величины из живого ``config/bob.yaml`` — с ним анонсёра и собирают.
_CEILING = 0.3


@dataclass
class _FakeGateway:
    posts: list[str] = field(default_factory=list)
    fail: bool = False

    async def reply(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        markdown: str,
        thinking: str | None = None,  # noqa: ARG002
    ) -> None:
        if self.fail:
            raise RuntimeError("bot bob poll failed (isolated): Request timeout")
        self.posts.append(markdown)


def _rule(rid: str, *, created_at: datetime = _NOW) -> ImprovementRule:
    return ImprovementRule(
        id=rid,
        observation="Не учитывается адресат",
        adjustment="Обращаться по имени",
        lever=Lever.ADDRESSIVITY_BIAS,
        magnitude=0.3,
        state=RuleState.PROPOSED,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=created_at,
        evidence="",
    )


class _Process:
    """Один «запуск процесса»: своё соединение с базой, свой стор, свой use-case."""

    def __init__(self, db: Path, gateway: _FakeGateway) -> None:
        self._repo = SqliteMemoryRepo(db)
        self._gateway = gateway

    async def __aenter__(self) -> _Process:
        await self._repo.initialize()
        self.store = SqliteSelfImprovementStore(self._repo)
        self.announcer = AnnounceProposedRules(
            store=self.store,
            gateway=self._gateway,
            chat_id=_CHAT_ID,
            persona_id=_PERSONA,
            max_magnitude=_CEILING,
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._repo.close()


async def test_a_real_restart_does_not_re_announce(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    gateway = _FakeGateway()

    async with _Process(db, gateway) as first:
        await first.store.save_rule(_PERSONA, _rule("rule-20260806083754-0"))
        await first.announcer.run()

    assert len(gateway.posts) == 1

    # Перезапуск: база закрыта и открыта заново, объекты новые.
    async with _Process(db, gateway) as second:
        await second.announcer.run()
        await second.announcer.run()
        rules = await second.store.load(_PERSONA)

    assert len(gateway.posts) == 1
    assert rules[0].announced is True
    assert announce_status(rules[0], max_magnitude=_CEILING) is AnnounceStatus.DELIVERED


async def test_a_real_restart_still_announces_the_unsaid_one(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    gateway = _FakeGateway()

    async with _Process(db, gateway) as first:
        await first.store.save_rule(_PERSONA, _rule("said"))
        await first.store.save_rule(
            _PERSONA, _rule("unsaid", created_at=datetime(2026, 8, 12, tzinfo=UTC))
        )
        await first.announcer.run()

    async with _Process(db, gateway) as second:
        await second.announcer.run()

    assert len(gateway.posts) == 2
    assert "said" in gateway.posts[0]
    assert "unsaid" in gateway.posts[1]


async def test_a_broken_gateway_stops_after_the_cap_across_restarts(
    tmp_path: Path,
) -> None:
    # 🔴 Та самая ситуация: битый транспорт + перезапуски. Кап держится, потому что
    # попытки лежат в базе, а не в памяти процесса.
    db = tmp_path / "bob.db"
    gateway = _FakeGateway(fail=True)
    restarts = MAX_ANNOUNCE_ATTEMPTS + 4

    async with _Process(db, gateway) as boot:
        await boot.store.save_rule(_PERSONA, _rule("rule-20260806060649-0"))

    for _ in range(restarts):
        async with _Process(db, gateway) as process:
            await process.announcer.run()

    async with _Process(db, gateway) as final:
        rules = await final.store.load(_PERSONA)

    assert gateway.posts == []
    assert rules[0].announce_attempts == MAX_ANNOUNCE_ATTEMPTS
    # Не потерялось молча: правило живо, ждёт владельца и помечено недоставленным.
    assert rules[0].state is RuleState.PROPOSED
    assert is_undelivered_proposal(rules[0], max_magnitude=_CEILING) is True
