# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты AnnounceProposedRules — Боб проговаривает свежее правило owner'у (BOB-028 .3).

При случае (драйвится медленным reflect-кадэнсом) Боб тактично проговаривает ОДНО
свежее PROPOSED-правило: «Заметил за собой: …. Предлагаю: …. Включить? /rule approve
<id>». Покрывают:

* одно за раз (не спам): при нескольких PROPOSED шлётся ровно одно;
* помечается «announced» В ХРАНИЛИЩЕ — повторный прогон молчит, и НОВЫЙ экземпляр над
  тем же хранилищем (то есть перезапуск процесса) тоже молчит (BOB-096 срез 1);
* шлёт ТОЛЬКО PROPOSED (APPROVED/PAUSED/REJECTED/REMOVED не проговариваются —
  одобренное уже применяется, отклонённое owner закрыл);
* в тексте есть id и /rule approve (owner знает, как включить);
* нет PROPOSED → тишина; нет гейтвея/стора → no-op (поведение как до BOB-028);
* best-effort: сбой гейтвея не валит тик — и не превращается в вечный повтор: попытки
  капятся, после исчерпания Боб молчит, а правило остаётся видимым в /rules (BOB-096).

🔴 ХРАНИЛИЩЕ ЗДЕСЬ — ФЕЙК, то есть доказывает контракт фейка (§0.3 п.4). Те же две
проверки на НАСТОЯЩЕМ SQLite (перезапуск = закрыть и открыть файл базы) живут в
tests/infrastructure/persistence/test_announce_rules_durability.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from bob.proactivity.rule_announcement import MAX_ANNOUNCE_ATTEMPTS
from bob.proactivity.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
)
from bob.proactivity.usecases.announce_rules import AnnounceProposedRules

_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
_CHAT_ID = -100123
_PERSONA = "bob"


@dataclass
class _FakeGateway:
    posts: list[tuple[int, str]] = field(default_factory=list)
    fail: bool = False

    async def reply(
        self,
        *,
        chat_id: int,
        markdown: str,
        thinking: str | None = None,  # noqa: ARG002
        reply_to_message_id: int | None = None,  # noqa: ARG002
    ) -> None:
        if self.fail:
            raise RuntimeError("gateway down")
        self.posts.append((chat_id, markdown))


@dataclass
class _FakeRuleStore:
    """Хранилище правил, переживающее пересоздание use-case'а (как настоящая база).

    Держит правила по id и обновляет ИМЕННО поля доставки — то, что до BOB-096 жило в
    памяти самого use-case'а и потому обнулялось перезапуском.
    """

    rules: tuple[ImprovementRule, ...] = ()

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]:  # noqa: ARG002
        return self.rules

    async def record_announce_attempt(self, persona_id: str, rule_id: str) -> None:  # noqa: ARG002
        self._patch(rule_id, announce_attempts_delta=1)

    async def mark_announced(self, persona_id: str, rule_id: str) -> None:  # noqa: ARG002
        self._patch(rule_id, announced=True)

    def _patch(
        self,
        rule_id: str,
        *,
        announced: bool | None = None,
        announce_attempts_delta: int = 0,
    ) -> None:
        updated = []
        for rule in self.rules:
            if rule.id != rule_id:
                updated.append(rule)
                continue
            updated.append(
                ImprovementRule(
                    id=rule.id,
                    observation=rule.observation,
                    adjustment=rule.adjustment,
                    lever=rule.lever,
                    magnitude=rule.magnitude,
                    state=rule.state,
                    origin=rule.origin,
                    created_at=rule.created_at,
                    evidence=rule.evidence,
                    announced=rule.announced if announced is None else announced,
                    announce_attempts=rule.announce_attempts + announce_attempts_delta,
                )
            )
        self.rules = tuple(updated)


def _rule(
    rid: str,
    *,
    state: RuleState = RuleState.PROPOSED,
    observation: str = "Отвечаю слишком сухо",
    adjustment: str = "Добавить теплоты в тон",
    created_at: datetime = _NOW,
) -> ImprovementRule:
    return ImprovementRule(
        id=rid,
        observation=observation,
        adjustment=adjustment,
        lever=Lever.TONE,
        magnitude=0.3,
        state=state,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=created_at,
        evidence="",
    )


def _build(
    rules: tuple[ImprovementRule, ...],
    *,
    gateway: _FakeGateway | None = None,
    store: _FakeRuleStore | None = None,
) -> tuple[AnnounceProposedRules, _FakeGateway]:
    gw = gateway if gateway is not None else _FakeGateway()
    use_case = AnnounceProposedRules(
        store=store if store is not None else _FakeRuleStore(rules=rules),
        gateway=gw,
        chat_id=_CHAT_ID,
        persona_id=_PERSONA,
    )
    return use_case, gw


async def test_announces_one_proposed_rule() -> None:
    use_case, gw = _build((_rule("r1"),))

    await use_case.run()

    assert len(gw.posts) == 1
    chat_id, text = gw.posts[0]
    assert chat_id == _CHAT_ID
    assert "Отвечаю слишком сухо" in text
    assert "Добавить теплоты в тон" in text
    assert "r1" in text
    assert "/rule approve" in text


async def test_announces_only_one_at_a_time() -> None:
    use_case, gw = _build((_rule("r1"), _rule("r2"), _rule("r3")))

    await use_case.run()

    assert len(gw.posts) == 1


async def test_does_not_repeat_an_announced_rule() -> None:
    use_case, gw = _build((_rule("r1"),))

    await use_case.run()
    await use_case.run()

    # Помечено announced → второй прогон молчит (не спамит одним и тем же).
    assert len(gw.posts) == 1


async def test_announces_the_next_unannounced_rule_on_a_later_run() -> None:
    use_case, gw = _build((_rule("r1"), _rule("r2")))

    await use_case.run()
    await use_case.run()

    assert len(gw.posts) == 2
    assert {gw.posts[0][1].count("r1"), gw.posts[1][1].count("r2")}


async def test_only_proposed_rules_are_announced() -> None:
    rules = (
        _rule("a", state=RuleState.APPROVED),
        _rule("pa", state=RuleState.PAUSED),
        _rule("rej", state=RuleState.REJECTED),
        _rule("rem", state=RuleState.REMOVED),
    )
    use_case, gw = _build(rules)

    await use_case.run()

    assert gw.posts == []


async def test_no_proposed_rules_is_silent() -> None:
    use_case, gw = _build(())

    await use_case.run()

    assert gw.posts == []


async def test_gateway_failure_does_not_raise() -> None:
    gw = _FakeGateway(fail=True)
    use_case, _gw = _build((_rule("r1"),), gateway=gw)

    # Best-effort: a flaky gateway must never break the slow tick.
    await use_case.run()

    assert gw.posts == []


# --- BOB-096 срез 1: доставка переживает перезапуск и не долбит ----------------


async def test_announced_mark_lives_in_the_store() -> None:
    store = _FakeRuleStore(rules=(_rule("r1"),))
    use_case, _gw = _build((), store=store)

    await use_case.run()

    # Пометка легла в ХРАНИЛИЩЕ, а не в память use-case'а.
    assert store.rules[0].announced is True
    assert store.rules[0].announce_attempts == 1


async def test_a_restarted_process_does_not_re_announce() -> None:
    # 🔴 Ровно то, что владелец видел после каждого перезапуска: полный комплект заново.
    store = _FakeRuleStore(rules=(_rule("r1"),))
    first, first_gw = _build((), store=store)
    await first.run()

    # «Перезапуск»: НОВЫЙ экземпляр use-case'а над ТЕМ ЖЕ хранилищем.
    second, second_gw = _build((), store=store)
    await second.run()

    assert len(first_gw.posts) == 1
    assert second_gw.posts == []


async def test_a_restarted_process_still_announces_what_was_not_said() -> None:
    store = _FakeRuleStore(rules=(_rule("said"), _rule("unsaid", created_at=_NOW)))
    first, _first_gw = _build((), store=store)
    await first.run()

    second, second_gw = _build((), store=store)
    await second.run()

    # Не «замолчал вообще», а «не повторяется»: непроговорённое всё ещё доезжает.
    assert len(second_gw.posts) == 1
    assert "unsaid" in second_gw.posts[0][1]


async def test_a_broken_gateway_stops_after_the_attempt_cap() -> None:
    # 🔴 Сердце дефекта: шесть дней одно и то же на каждом reflect-тике при битой сети.
    gw = _FakeGateway(fail=True)
    store = _FakeRuleStore(rules=(_rule("r1"),))
    attempts_before_giving_up = MAX_ANNOUNCE_ATTEMPTS + 5

    for _ in range(attempts_before_giving_up):
        use_case, _gw = _build((), store=store, gateway=gw)
        await use_case.run()

    assert gw.posts == []
    assert store.rules[0].announced is False
    # Попыток потрачено ровно столько, сколько разрешено — дальше Боб молчит.
    assert store.rules[0].announce_attempts == MAX_ANNOUNCE_ATTEMPTS


async def test_the_attempt_is_counted_before_the_send() -> None:
    # Попытка засчитана даже когда отправка не удалась — иначе кап не кап.
    gw = _FakeGateway(fail=True)
    store = _FakeRuleStore(rules=(_rule("r1"),))
    use_case, _gw = _build((), store=store, gateway=gw)

    await use_case.run()

    assert store.rules[0].announce_attempts == 1


async def test_an_exhausted_rule_does_not_block_a_fresh_proposal() -> None:
    gw = _FakeGateway(fail=True)
    store = _FakeRuleStore(rules=(_rule("stuck"),))
    for _ in range(MAX_ANNOUNCE_ATTEMPTS):
        use_case, _gw = _build((), store=store, gateway=gw)
        await use_case.run()

    # Сеть ожила, появилось новое предложение — оно доезжает, застрявшее не мешает.
    gw.fail = False
    store.rules = (*store.rules, _rule("fresh", created_at=_NOW))
    use_case, _gw = _build((), store=store, gateway=gw)
    await use_case.run()

    assert len(gw.posts) == 1
    assert "fresh" in gw.posts[0][1]


async def test_the_use_case_honours_a_non_default_cap() -> None:
    # Кап use-case'а — тестовый шов (не ключ конфига), но он обязан РАБОТАТЬ: с капом 1
    # Боб сдаётся после первой неудачи, хотя доменный дефолт разрешил бы ещё две.
    gw = _FakeGateway(fail=True)
    store = _FakeRuleStore(rules=(_rule("r1"),))

    for _ in range(MAX_ANNOUNCE_ATTEMPTS + 2):
        use_case = AnnounceProposedRules(
            store=store,
            gateway=gw,
            chat_id=_CHAT_ID,
            persona_id=_PERSONA,
            max_attempts=1,
        )
        await use_case.run()

    assert store.rules[0].announce_attempts == 1


async def test_a_recovered_gateway_delivers_within_the_cap() -> None:
    gw = _FakeGateway(fail=True)
    store = _FakeRuleStore(rules=(_rule("r1"),))
    use_case, _gw = _build((), store=store, gateway=gw)
    await use_case.run()

    gw.fail = False
    use_case, _gw = _build((), store=store, gateway=gw)
    await use_case.run()

    assert len(gw.posts) == 1
    assert store.rules[0].announced is True
