# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты детектора паттернов (BOB-028 .2): LlmPatternDetector + DetectPatterns.

Всё внешнее фейкается (детерминизм, без сети): scripted LLM-роутер возвращает
строгий JSON; узкие read-seam'ы отдают сигналы; in-memory стор ловит сохранённых
кандидатов. Проверяем контракт:

* детектор парсит строгий JSON устойчиво (markdown-fence / преамбула / мусор),
  выбирает рычаг ТОЛЬКО из Lever-allowlist, клампит magnitude, и СОЗДАЁТ ТОЛЬКО
  PROPOSED (origin=BOB_PROPOSED); невалидный/мусорный выход -> пустой список;
* use-case собирает сигналы из seam'ов (unwired -> пустые), дедупит против
  существующих правил (рычаг+близость наблюдения) и не плодит сверх лимита, и
  НИЧЕГО не применяет — только save_rule в PROPOSED.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.application.usecases.detect_patterns import (
    DetectPatterns,
    LlmPatternDetector,
)
from bob.domain.personality.self_improvement import (
    ImprovementRule,
    ImprovementSignals,
    Lever,
    RuleOrigin,
    RuleState,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


class FixedClock:
    """Clock возвращает фиксированный момент (детерминизм)."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class ScriptedProvider:
    """Фейк LLMProvider: отдаёт канонный ответ, пишет полученные запросы."""

    def __init__(self, *, reply: str = "", raises: bool = False) -> None:
        self.reply = reply
        self.raises = raises
        self.payloads: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — часть протокола LLMProvider
    ) -> str | AsyncIterator[str]:
        self.payloads.append([dict(m) for m in messages])
        if self.raises:
            msg = "provider boom"
            raise RuntimeError(msg)
        return self.reply


def _router(*, reply: str = "", raises: bool = False) -> tuple[LLMRouter, ScriptedProvider]:
    provider = ScriptedProvider(reply=reply, raises=raises)
    router = LLMRouter(providers={0: provider, 1: provider})
    return router, provider


def _detector(*, reply: str = "", raises: bool = False) -> LlmPatternDetector:
    router, _ = _router(reply=reply, raises=raises)
    return LlmPatternDetector(router=router, clock=FixedClock(_NOW))


class FakeStore:
    """In-memory SelfImprovementStore surface: load + capture save_rule."""

    def __init__(self, *, existing: tuple[ImprovementRule, ...] = ()) -> None:
        self._existing = existing
        self.saved: list[ImprovementRule] = []

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]:  # noqa: ARG002
        return (*self._existing, *self.saved)

    async def save_rule(self, persona_id: str, rule: ImprovementRule) -> None:  # noqa: ARG002
        self.saved.append(rule)


class FixedDetector:
    """Фейк PatternDetector: отдаёт заранее заданных кандидатов, ловит сигналы."""

    def __init__(self, candidates: tuple[ImprovementRule, ...]) -> None:
        self._candidates = candidates
        self.seen: list[ImprovementSignals] = []

    async def detect(self, signals: ImprovementSignals) -> Sequence[ImprovementRule]:
        self.seen.append(signals)
        return self._candidates


def _candidate(
    *,
    rid: str = "c1",
    observation: str = "Я часто повторяю одну и ту же мысль.",
    lever: Lever = Lever.TONE,
    state: RuleState = RuleState.PROPOSED,
) -> ImprovementRule:
    return ImprovementRule(
        id=rid,
        observation=observation,
        adjustment="Стоит разнообразить формулировки.",
        lever=lever,
        magnitude=0.3,
        state=state,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=_NOW,
        evidence="self_repeat_count=4",
    )


# --- LlmPatternDetector -------------------------------------------------------


async def test_detector_parses_strict_json_into_proposed_rules() -> None:
    reply = (
        '[{"observation": "Я часто повторяю одну и ту же мысль.", '
        '"adjustment": "Разнообразить формулировки.", "lever": "tone", '
        '"magnitude": 0.3, "evidence": "self_repeat_count=4"}]'
    )
    rules = await _detector(reply=reply).detect(ImprovementSignals(self_repeat_count=4))

    assert len(rules) == 1
    rule = rules[0]
    assert rule.lever is Lever.TONE
    assert rule.state is RuleState.PROPOSED
    assert rule.origin is RuleOrigin.BOB_PROPOSED
    assert rule.observation == "Я часто повторяю одну и ту же мысль."
    assert 0.0 <= rule.magnitude <= 1.0


async def test_detector_uses_detect_patterns_task() -> None:
    router, provider = _router(reply="[]")
    detector = LlmPatternDetector(router=router, clock=FixedClock(_NOW))
    await detector.detect(ImprovementSignals())
    # роутер отправил запрос (системный промпт на русском про рычаги)
    assert provider.payloads
    system = provider.payloads[0][0]["content"]
    assert "tone" in system
    assert "length" in system


async def test_detector_tolerates_markdown_fence_and_preamble() -> None:
    reply = (
        "Подумав, предлагаю:\n```json\n"
        '[{"observation": "Я слишком многословен.", "adjustment": "Короче.", '
        '"lever": "length", "magnitude": 0.4}]\n```\nвот так.'
    )
    rules = await _detector(reply=reply).detect(ImprovementSignals(verbosity_misses=3))
    assert len(rules) == 1
    assert rules[0].lever is Lever.LENGTH


async def test_detector_rejects_lever_outside_allowlist() -> None:
    # Рычаг не из Lever-allowlist (попытка тронуть authz) -> элемент отброшен.
    reply = (
        '[{"observation": "x", "adjustment": "y", "lever": "authz", "magnitude": 0.5}, '
        '{"observation": "Я молчалив.", "adjustment": "Чаще включаюсь.", '
        '"lever": "proactivity", "magnitude": 0.2}]'
    )
    rules = await _detector(reply=reply).detect(ImprovementSignals())
    assert [r.lever for r in rules] == [Lever.PROACTIVITY]


async def test_detector_clamps_magnitude_into_unit_range() -> None:
    reply = (
        '[{"observation": "Я слишком резок.", "adjustment": "Мягче.", '
        '"lever": "tone", "magnitude": 9.0}, '
        '{"observation": "Я зануден.", "adjustment": "Живее.", '
        '"lever": "humor", "magnitude": -3.0}]'
    )
    rules = await _detector(reply=reply).detect(ImprovementSignals())
    assert all(0.0 <= r.magnitude <= 1.0 for r in rules)


async def test_detector_returns_empty_on_garbage() -> None:
    rules = await _detector(reply="никакого json тут нет").detect(ImprovementSignals())
    assert list(rules) == []


async def test_detector_returns_empty_on_provider_error() -> None:
    rules = await _detector(raises=True).detect(ImprovementSignals())
    assert list(rules) == []


async def test_detector_skips_entries_missing_required_fields() -> None:
    reply = (
        '[{"adjustment": "нет наблюдения", "lever": "tone", "magnitude": 0.3}, '
        '{"observation": "нет рычага", "adjustment": "y", "magnitude": 0.3}]'
    )
    rules = await _detector(reply=reply).detect(ImprovementSignals())
    assert list(rules) == []


# --- DetectPatterns use-case --------------------------------------------------


async def test_use_case_saves_new_proposed_candidate() -> None:
    store = FakeStore()
    detector = FixedDetector((_candidate(),))
    use_case = DetectPatterns(detector=detector, store=store, persona_id="bob")

    await use_case.run()

    assert len(store.saved) == 1
    assert store.saved[0].state is RuleState.PROPOSED


async def test_use_case_dedups_against_existing_rule() -> None:
    existing = _candidate(
        rid="e1", observation="Я часто повторяю одну и ту же мысль.", lever=Lever.TONE
    )
    store = FakeStore(existing=(existing,))
    # тот же рычаг + near-идентичное наблюдение -> дубль, не сохраняется
    candidate = _candidate(
        rid="c2", observation="Я часто повторяю одну и ту же мысль!", lever=Lever.TONE
    )
    detector = FixedDetector((candidate,))
    use_case = DetectPatterns(detector=detector, store=store, persona_id="bob")

    await use_case.run()

    assert store.saved == []


async def test_use_case_dedups_among_a_batch() -> None:
    # Два кандидата на один и тот же паттерн в одном проходе -> сохраняется один.
    detector = FixedDetector(
        (
            _candidate(rid="a", observation="Я слишком многословен.", lever=Lever.LENGTH),
            _candidate(rid="b", observation="Я слишком многословен!", lever=Lever.LENGTH),
        )
    )
    store = FakeStore()
    use_case = DetectPatterns(detector=detector, store=store, persona_id="bob")

    await use_case.run()

    assert len(store.saved) == 1


async def test_use_case_respects_max_active_rules() -> None:
    # Уже два «живых» правила, лимит 2 -> новых не добавляем.
    existing = (
        _candidate(rid="e1", observation="первое", lever=Lever.TONE, state=RuleState.APPROVED),
        _candidate(rid="e2", observation="второе", lever=Lever.LENGTH, state=RuleState.PROPOSED),
    )
    store = FakeStore(existing=existing)
    detector = FixedDetector(
        (_candidate(rid="c3", observation="третье", lever=Lever.HUMOR),)
    )
    use_case = DetectPatterns(
        detector=detector, store=store, persona_id="bob", max_active_rules=2
    )

    await use_case.run()

    assert store.saved == []


async def test_use_case_passes_collected_signals_to_detector() -> None:
    captured = FixedDetector(())
    signals = ImprovementSignals(self_repeat_count=7, owner_friction=2)
    store = FakeStore()
    use_case = DetectPatterns(
        detector=captured,
        store=store,
        persona_id="bob",
        signal_source=_StaticSignalSource(signals),
    )

    await use_case.run()

    assert captured.seen == [signals]


async def test_use_case_without_signal_source_uses_empty_signals() -> None:
    captured = FixedDetector(())
    use_case = DetectPatterns(detector=captured, store=FakeStore(), persona_id="bob")

    await use_case.run()

    assert captured.seen == [ImprovementSignals()]


class _StaticSignalSource:
    """Фейк SignalSource: всегда отдаёт один и тот же срез сигналов."""

    def __init__(self, signals: ImprovementSignals) -> None:
        self._signals = signals

    async def collect(self) -> ImprovementSignals:
        return self._signals


_TASK = TaskType.DETECT_PATTERNS  # импорт-якорь: убеждаемся, что тип задачи существует
