# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests: ``self_improvement.{detector_tier,max_magnitude}`` РЕАЛЬНО доезжают до детектора.

🔴 BOB-096. До этого среза ``detector_tier`` был МЁРТВЫМ КЛЮЧОМ: он лежал в
``config/bob.yaml`` и в дефолтах загрузчика, но сборка детектора строила
детектор без тира, упоминание тира жило только в докстроке. Ключ конфига без читателя хуже
отсутствующего — он читается как обещание (§0.3 п.10 про allowlist, только про конфиг).

Поэтому тесты проверяют не «значение прочитано», но ПОПЫТКУ, и наблюдают её ЧЕРЕЗ ГРАНИЦУ:
собранный композицией проход детектора гоняется целиком (конфиг → детектор → роутер →
провайдер тира → хранилище правил), и утверждения читают только наблюдаемое — кто из
провайдеров тиров получил запрос, что модель увидела в промпте и что легло в хранилище.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from bob.application.router.llm_router import LLMRouter
from bob.runtime.wiring.self_improvement import _build_self_improvement

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from bob.kernel.ports import ReplyGateway
    from bob.proactivity.adapters import SqliteSelfImprovementStore
    from bob.proactivity.self_improvement import ImprovementRule

_NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

_NO_CANDIDATES = "[]"


def _proposal_json(magnitude: float) -> str:
    """Осмысленный кандидат от модели для заданной величины наклона."""
    return (
        '[{"observation": "Отвечаю резче, когда разговор долгий.", '
        '"adjustment": "Добавить теплоты к концу разговора.", '
        f'"lever": "tone", "magnitude": {magnitude}}}]'
    )


class _ScriptedProvider:
    """Фейк провайдера тира: отдаёт канонный ответ и пишет полученные payload'ы."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.payloads: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — часть протокола LLMProvider
    ) -> str | AsyncIterator[str]:
        self.payloads.append([dict(m) for m in messages])
        return self.reply


class _FakeRuleStore:
    """In-memory хранилище правил: пустая загрузка + перехват сохранений."""

    def __init__(self) -> None:
        self.saved: list[ImprovementRule] = []

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]:  # noqa: ARG002
        return tuple(self.saved)

    async def save_rule(self, persona_id: str, rule: ImprovementRule) -> None:  # noqa: ARG002
        self.saved.append(rule)


class _StubGateway:
    """Шлюз, который в этом тесте не используется (анонс правил здесь не гоняется).

    Сборка требует шлюз, потому что кладёт шлюз в анонсёр (срез 1). Проход детектора
    анонсёра не касается, поэтому любой вызов — сигнал, что тест поехал не туда.
    """

    async def reply(self, *, chat_id: int, markdown: str) -> None:
        raise AssertionError(f"шлюз не используется в этом тесте: {chat_id} {markdown}")


class _FixedClock:
    """Часы, застывшие на фиксированном моменте (детектор штампует ими id правила)."""

    def now(self) -> datetime:
        return _NOW


class _Wired:
    """Результат прогона: кто из тиров ответил и что легло в хранилище."""

    def __init__(
        self, tier0: _ScriptedProvider, tier1: _ScriptedProvider, store: _FakeRuleStore
    ) -> None:
        self.tier0 = tier0
        self.tier1 = tier1
        self.store = store


async def _run_detection(
    config: Mapping[str, object], *, reply: str = _NO_CANDIDATES
) -> _Wired:
    """Собрать self-improvement по конфигу и прогнать ОДИН проход детектора."""
    tier0 = _ScriptedProvider(reply)
    tier1 = _ScriptedProvider(reply)
    store = _FakeRuleStore()
    wired = _build_self_improvement(
        config,
        router=LLMRouter(providers={0: tier0, 1: tier1}),
        # Стор берётся как порт (load + save_rule); настоящий SQLite здесь был бы шумом,
        # поэтому фейк приводится к типу параметра сборки.
        rule_store=cast("SqliteSelfImprovementStore", store),
        # Анонсёр (срез 1) на этом пути не участвует, поэтому шлюз-заглушка
        # приводится к типу параметра сборки (любой её вызов — AssertionError).
        gateway=cast("ReplyGateway", _StubGateway()),
        chat_id=1,
        clock=_FixedClock(),
    )
    assert wired.detect_patterns is not None
    await wired.detect_patterns.run()
    return _Wired(tier0, tier1, store)


@pytest.mark.parametrize(
    ("tier", "tier0_calls", "tier1_calls"),
    [(0, 1, 0), (1, 0, 1)],
)
async def test_configured_detector_tier_is_where_the_request_lands(
    tier: int, tier0_calls: int, tier1_calls: int
) -> None:
    # ПОПЫТКА, не просто чтение: тир из конфига определяет, какой провайдер
    # получил запрос детектора.
    run = await _run_detection({"self_improvement": {"detector_tier": tier}})

    assert len(run.tier0.payloads) == tier0_calls
    assert len(run.tier1.payloads) == tier1_calls


async def test_default_detector_tier_is_the_reasoning_tier() -> None:
    # Ключ не задан -> дефолт 1 (reasoning), то есть как в отгруженном config/bob.yaml.
    run = await _run_detection({})

    assert len(run.tier1.payloads) == 1
    assert run.tier0.payloads == []


async def test_configured_max_magnitude_reaches_the_detector_prompt() -> None:
    # Потолок величины виден МОДЕЛИ: иначе отбраковка «вне max_magnitude» тихо стала бы
    # выключателем самоулучшения (модель просила бы недопустимые значения).
    run = await _run_detection(
        {"self_improvement": {"detector_tier": 0, "max_magnitude": 0.25}}
    )

    system = run.tier0.payloads[0][0]["content"]
    assert "0.25" in system


async def test_a_proposal_above_the_configured_ceiling_is_not_stored() -> None:
    # Сквозь всю провязку: величина выше конфигурного потолка -> правила нет в хранилище
    # (значит, и анонсу нечего брать — он читает только хранилище).
    run = await _run_detection(
        {"self_improvement": {"max_magnitude": 0.25}}, reply=_proposal_json(0.9)
    )

    assert run.store.saved == []


async def test_a_proposal_within_the_configured_ceiling_is_stored() -> None:
    # КОНТРОЛЬ: тот же путь при допустимой величине доезжает до хранилища — иначе
    # тест выше был бы вакуумным («по этой провязке не сохраняется вообще ничего»).
    run = await _run_detection(
        {"self_improvement": {"max_magnitude": 0.25}}, reply=_proposal_json(0.2)
    )

    assert [rule.magnitude for rule in run.store.saved] == [0.2]
