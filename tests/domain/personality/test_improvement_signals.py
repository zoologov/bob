# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты чистого домена сигналов самоулучшения + дедуп-предиката (BOB-028 .2).

Покрывают: структуру :class:`ImprovementSignals` (frozen/slots, разумные пустые
дефолты — unwired-источники дают «нет сигналов»), и чистый предикат
:func:`is_duplicate_rule` (дубль = тот же рычаг И близкое наблюдение; difflib, как
анти-повтор BOB-026). Всё детерминированно, без I/O и рандома.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bob.domain.personality.self_improvement import (
    ImprovementRule,
    ImprovementSignals,
    Lever,
    RuleOrigin,
    RuleState,
    is_duplicate_rule,
)

_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def _rule(
    *,
    rid: str = "r1",
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


def test_signals_default_to_empty_no_signal() -> None:
    # Unwired-источники -> разумные пустые дефолты: детектору нечего предлагать.
    signals = ImprovementSignals()
    assert signals.self_repeat_count == 0
    assert signals.verbosity_misses == 0
    assert signals.owner_friction == 0
    assert signals.mood_stuck is False
    assert signals.mood_stuck_tone == ""
    assert signals.addressivity_outcomes == {}
    assert signals.relationship_deltas == {}
    assert signals.positive_signals == ()
    assert signals.recent_observations == ()


def test_signals_are_frozen() -> None:
    signals = ImprovementSignals(self_repeat_count=3)
    try:
        signals.self_repeat_count = 5  # type: ignore[misc]
    except AttributeError:
        return
    msg = "ImprovementSignals must be frozen"
    raise AssertionError(msg)


def test_signals_carry_observed_slice() -> None:
    signals = ImprovementSignals(
        self_repeat_count=4,
        addressivity_outcomes={"SILENT": 5, "ENGAGE": 1},
        verbosity_misses=2,
        relationship_deltas={"warmth": -0.2},
        mood_stuck=True,
        mood_stuck_tone="подавленное",
        owner_friction=3,
        positive_signals=("шутка зашла",),
        recent_observations=("обсуждали орбиты",),
    )
    assert signals.self_repeat_count == 4
    assert signals.addressivity_outcomes["SILENT"] == 5
    assert signals.mood_stuck is True
    assert signals.positive_signals == ("шутка зашла",)


def test_duplicate_when_same_lever_and_near_identical_observation() -> None:
    existing = (_rule(observation="Я часто повторяю одну и ту же мысль.", lever=Lever.TONE),)
    candidate = _rule(
        rid="r2",
        observation="Я часто повторяю одну и ту же мысль!",
        lever=Lever.TONE,
    )
    assert is_duplicate_rule(candidate, existing) is True


def test_not_duplicate_when_different_lever() -> None:
    existing = (_rule(observation="Я часто повторяю одну и ту же мысль.", lever=Lever.TONE),)
    candidate = _rule(
        rid="r2",
        observation="Я часто повторяю одну и ту же мысль.",
        lever=Lever.LENGTH,
    )
    assert is_duplicate_rule(candidate, existing) is False


def test_not_duplicate_when_observation_differs_in_substance() -> None:
    existing = (_rule(observation="Я слишком многословен в ответах.", lever=Lever.LENGTH),)
    candidate = _rule(
        rid="r2",
        observation="Я редко проявляю инициативу первым.",
        lever=Lever.LENGTH,
    )
    assert is_duplicate_rule(candidate, existing) is False


def test_not_duplicate_against_empty_existing() -> None:
    assert is_duplicate_rule(_rule(), ()) is False


def test_duplicate_only_considers_live_rules_by_default() -> None:
    # Отклонённое/убранное правило не должно блокировать новое предложение —
    # дедуп смотрит на «живые» (не терминальные) правила.
    existing = (
        _rule(observation="Я часто повторяю одну и ту же мысль.", state=RuleState.REJECTED),
    )
    candidate = _rule(
        rid="r2",
        observation="Я часто повторяю одну и ту же мысль.",
        lever=Lever.TONE,
    )
    assert is_duplicate_rule(candidate, existing) is False
