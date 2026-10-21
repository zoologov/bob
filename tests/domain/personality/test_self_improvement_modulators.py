# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты мягкого применения правил — сборка модуляторов из active_rules (BOB-028 .3).

Покрывают чистый доменный сборщик :func:`build_modulators`: из набора правил он
строит :class:`RuleModulators`, где КАЖДЫЙ рычаг наклоняет СВОЮ точку, а величина
клампится к ``max_magnitude``. Safety-инварианты под тестами:

* применяются ТОЛЬКО ``APPROVED`` правила (PROPOSED/PAUSED/REJECTED/REMOVED не влияют);
* читается ТОЛЬКО :class:`Lever`-allowlist (правило с любым другим намерением просто
  не имеет рычага — представить его нечем);
* наклон ограничен: величина клампится, LENGTH-шаг не больше одной ступени, суммарный
  байес ограничен ``max_magnitude`` — это наклон, НИКОГДА не перехват/инверсия;
* пустой набор (или нет APPROVED) → пустые модуляторы (поведение как до BOB-028).
"""

from __future__ import annotations

from datetime import UTC, datetime

from bob.kernel.modulators import RuleModulators
from bob.proactivity.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
    build_modulators,
)

_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
_CAP = 0.3


def _rule(
    rid: str = "r1",
    *,
    lever: Lever = Lever.TONE,
    magnitude: float = 0.2,
    state: RuleState = RuleState.APPROVED,
    observation: str = "Замечаю, что отвечаю слишком сухо",
    adjustment: str = "Добавить теплоты в тон",
) -> ImprovementRule:
    return ImprovementRule(
        id=rid,
        observation=observation,
        adjustment=adjustment,
        lever=lever,
        magnitude=magnitude,
        state=state,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=_NOW,
        evidence="",
    )


def test_empty_rules_give_empty_modulators() -> None:
    mods = build_modulators((), max_magnitude=_CAP)
    assert mods == RuleModulators()
    assert mods.voice_adjustments == ()
    assert mods.length_step == 0
    assert mods.proactivity_bias == 0.0
    assert mods.addressivity_bias == 0.0
    assert not mods.has_any()


def test_only_approved_rules_apply() -> None:
    rules = [
        _rule("p", state=RuleState.PROPOSED, lever=Lever.PROACTIVITY),
        _rule("pa", state=RuleState.PAUSED, lever=Lever.PROACTIVITY),
        _rule("rej", state=RuleState.REJECTED, lever=Lever.PROACTIVITY),
        _rule("rem", state=RuleState.REMOVED, lever=Lever.PROACTIVITY),
    ]
    mods = build_modulators(rules, max_magnitude=_CAP)
    # Ни одно правило не APPROVED → ноль применения.
    assert not mods.has_any()
    assert mods.proactivity_bias == 0.0


def test_tone_and_humor_fold_into_voice_adjustments() -> None:
    rules = [
        _rule("t", lever=Lever.TONE, adjustment="говорить теплее"),
        _rule("h", lever=Lever.HUMOR, adjustment="чуть больше иронии"),
    ]
    mods = build_modulators(rules, max_magnitude=_CAP)
    # Поправки обоих правил видны (грундированы в реальном adjustment; прозу лепит voice).
    assert "говорить теплее" in mods.voice_adjustments
    assert "чуть больше иронии" in mods.voice_adjustments


def test_length_lever_yields_a_single_bounded_step() -> None:
    # Сильная (заклампленная) величина LENGTH даёт мягкий наклон — но не больше одной
    # ступени (наклон, не перехват: лестница многословия не переворачивается).
    mods = build_modulators(
        [_rule(lever=Lever.LENGTH, magnitude=1.0)], max_magnitude=_CAP
    )
    assert mods.length_step in (-1, 0)
    assert mods.length_step == -1  # консервативное направление — короче


def test_tiny_length_magnitude_does_not_tilt() -> None:
    mods = build_modulators(
        [_rule(lever=Lever.LENGTH, magnitude=0.01)], max_magnitude=_CAP
    )
    assert mods.length_step == 0


def test_proactivity_bias_clamped_to_cap() -> None:
    mods = build_modulators(
        [_rule(lever=Lever.PROACTIVITY, magnitude=1.0)], max_magnitude=_CAP
    )
    assert mods.proactivity_bias == _CAP  # величина зажата потолком (не перехват)


def test_addressivity_bias_clamped_to_cap() -> None:
    mods = build_modulators(
        [_rule(lever=Lever.ADDRESSIVITY_BIAS, magnitude=0.9)], max_magnitude=_CAP
    )
    assert mods.addressivity_bias == _CAP


def test_summed_bias_per_lever_is_bounded_by_cap() -> None:
    # Несколько правил по одному рычагу не дают неограниченного дрейфа — суммарный
    # байес рычага зажат потолком (max_active_rules ограничивает число, кламп — величину).
    rules = [
        _rule("a", lever=Lever.PROACTIVITY, magnitude=0.3),
        _rule("b", lever=Lever.PROACTIVITY, magnitude=0.3),
        _rule("c", lever=Lever.PROACTIVITY, magnitude=0.3),
    ]
    mods = build_modulators(rules, max_magnitude=_CAP)
    assert mods.proactivity_bias <= _CAP
