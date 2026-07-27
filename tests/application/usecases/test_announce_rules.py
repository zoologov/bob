# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты AnnounceProposedRules — Боб проговаривает свежее правило owner'у (BOB-028 .3).

При случае (драйвится медленным reflect-кадэнсом) Боб тактично проговаривает ОДНО
свежее PROPOSED-правило: «Заметил за собой: …. Предлагаю: …. Включить? /rule approve
<id>». Покрывают:

* одно за раз (не спам): при нескольких PROPOSED шлётся ровно одно;
* помечается «announced» — повторный прогон молчит (не повторяет одно и то же);
* шлёт ТОЛЬКО PROPOSED (APPROVED/PAUSED/REJECTED/REMOVED не проговариваются —
  одобренное уже применяется, отклонённое owner закрыл);
* в тексте есть id и /rule approve (owner знает, как включить);
* нет PROPOSED → тишина; нет гейтвея/стора → no-op (поведение как до BOB-028);
* best-effort: сбой гейтвея не валит тик.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

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
        self, *, chat_id: int, markdown: str, thinking: str | None = None  # noqa: ARG002
    ) -> None:
        if self.fail:
            raise RuntimeError("gateway down")
        self.posts.append((chat_id, markdown))


@dataclass
class _FakeRuleStore:
    rules: tuple[ImprovementRule, ...] = ()

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]:  # noqa: ARG002
        return self.rules


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
    rules: tuple[ImprovementRule, ...], *, gateway: _FakeGateway | None = None
) -> tuple[AnnounceProposedRules, _FakeGateway]:
    gw = gateway if gateway is not None else _FakeGateway()
    use_case = AnnounceProposedRules(
        store=_FakeRuleStore(rules=rules),
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
