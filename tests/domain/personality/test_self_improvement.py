# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты чистого домена self-improvement (BOB-028 .1).

Покрывают: жёсткий allowlist рычагов (Lever — и ТОЛЬКО разрешённые члены, без
authz/гостя/SOUL/safety по конструкции), машину состояний правила (все ветки
переходов: валидные/невалидные/терминальные, ключевой PROPOSED->APPROVED),
выбор активных правил (только APPROVED) и кламп величины наклона (границы/края).
Всё детерминированно, без I/O и рандома.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.domain.personality.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
    active_rules,
    can_transition,
    clamp_magnitude,
    rules_for_lever,
)

_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def _rule(
    rid: str = "r1",
    *,
    lever: Lever = Lever.TONE,
    magnitude: float = 0.3,
    state: RuleState = RuleState.PROPOSED,
    origin: RuleOrigin = RuleOrigin.BOB_PROPOSED,
) -> ImprovementRule:
    return ImprovementRule(
        id=rid,
        observation="Замечаю, что отвечаю слишком сухо",
        adjustment="Добавить теплоты в тон",
        lever=lever,
        magnitude=magnitude,
        state=state,
        origin=origin,
        created_at=_NOW,
        evidence="Паттерн: короткие сухие ответы 5 раз подряд",
    )


# --- Lever allowlist (граница безопасности по конструкции) --------------------


def test_lever_contains_only_allowed_members() -> None:
    assert {lever.name for lever in Lever} == {
        "TONE",
        "LENGTH",
        "PROACTIVITY",
        "ADDRESSIVITY_BIAS",
        "HUMOR",
    }


def test_lever_has_no_safety_boundary_member() -> None:
    forbidden = {"AUTHZ", "GUEST", "SOUL", "SAFETY", "AUTONOMY", "OWNER"}
    assert forbidden.isdisjoint({lever.name for lever in Lever})


def test_lever_values_are_stable_strings() -> None:
    assert Lever.TONE.value == "tone"
    assert Lever.ADDRESSIVITY_BIAS.value == "addressivity_bias"


# --- RuleState machine --------------------------------------------------------


def test_proposed_can_be_approved() -> None:
    # КЛЮЧЕВОЕ: owner-апрув (use-case .3) переводит PROPOSED -> APPROVED.
    assert can_transition(RuleState.PROPOSED, RuleState.APPROVED) is True


def test_proposed_can_be_rejected() -> None:
    assert can_transition(RuleState.PROPOSED, RuleState.REJECTED) is True


def test_proposed_cannot_jump_to_paused_or_removed() -> None:
    assert can_transition(RuleState.PROPOSED, RuleState.PAUSED) is False
    assert can_transition(RuleState.PROPOSED, RuleState.REMOVED) is False


def test_approved_can_pause_or_remove() -> None:
    assert can_transition(RuleState.APPROVED, RuleState.PAUSED) is True
    assert can_transition(RuleState.APPROVED, RuleState.REMOVED) is True


def test_approved_cannot_return_to_proposed_or_rejected() -> None:
    assert can_transition(RuleState.APPROVED, RuleState.PROPOSED) is False
    assert can_transition(RuleState.APPROVED, RuleState.REJECTED) is False


def test_paused_can_resume_or_remove() -> None:
    assert can_transition(RuleState.PAUSED, RuleState.APPROVED) is True
    assert can_transition(RuleState.PAUSED, RuleState.REMOVED) is True


def test_paused_cannot_go_to_proposed_or_rejected() -> None:
    assert can_transition(RuleState.PAUSED, RuleState.PROPOSED) is False
    assert can_transition(RuleState.PAUSED, RuleState.REJECTED) is False


@pytest.mark.parametrize("terminal", [RuleState.REJECTED, RuleState.REMOVED])
@pytest.mark.parametrize("target", list(RuleState))
def test_terminal_states_have_no_outgoing_transitions(
    terminal: RuleState, target: RuleState
) -> None:
    assert can_transition(terminal, target) is False


def test_self_transition_is_not_a_transition() -> None:
    for state in RuleState:
        assert can_transition(state, state) is False


# --- active_rules -------------------------------------------------------------


def test_active_rules_keeps_only_approved() -> None:
    rules = (
        _rule("a", state=RuleState.APPROVED),
        _rule("b", state=RuleState.PROPOSED),
        _rule("c", state=RuleState.PAUSED),
        _rule("d", state=RuleState.REJECTED),
        _rule("e", state=RuleState.REMOVED),
    )

    active = active_rules(rules)

    assert tuple(r.id for r in active) == ("a",)


def test_active_rules_empty_when_none_approved() -> None:
    rules = (_rule("a", state=RuleState.PAUSED), _rule("b", state=RuleState.PROPOSED))

    assert active_rules(rules) == ()


def test_active_rules_preserves_order() -> None:
    rules = (
        _rule("a", state=RuleState.APPROVED),
        _rule("b", state=RuleState.PROPOSED),
        _rule("c", state=RuleState.APPROVED),
    )

    assert tuple(r.id for r in active_rules(rules)) == ("a", "c")


def test_active_rules_returns_tuple() -> None:
    assert isinstance(active_rules([_rule(state=RuleState.APPROVED)]), tuple)


# --- clamp_magnitude ----------------------------------------------------------


def test_clamp_within_range_is_identity() -> None:
    assert clamp_magnitude(0.3, cap=0.5) == 0.3


def test_clamp_above_cap_is_capped() -> None:
    assert clamp_magnitude(0.9, cap=0.5) == 0.5


def test_clamp_negative_is_zero() -> None:
    assert clamp_magnitude(-0.4, cap=0.5) == 0.0


def test_clamp_at_boundaries() -> None:
    assert clamp_magnitude(0.0, cap=0.5) == 0.0
    assert clamp_magnitude(0.5, cap=0.5) == 0.5


def test_clamp_zero_cap_pins_to_zero() -> None:
    assert clamp_magnitude(0.7, cap=0.0) == 0.0


# --- rules_for_lever ----------------------------------------------------------


def test_rules_for_lever_filters_by_lever() -> None:
    rules = (
        _rule("a", lever=Lever.TONE),
        _rule("b", lever=Lever.LENGTH),
        _rule("c", lever=Lever.TONE),
    )

    matched = rules_for_lever(rules, Lever.TONE)

    assert tuple(r.id for r in matched) == ("a", "c")


def test_rules_for_lever_empty_when_no_match() -> None:
    assert rules_for_lever([_rule(lever=Lever.HUMOR)], Lever.PROACTIVITY) == ()


# --- ImprovementRule value object ---------------------------------------------


def test_rule_is_frozen() -> None:
    rule = _rule()
    with pytest.raises(AttributeError):
        rule.magnitude = 0.9  # type: ignore[misc]


def test_rule_origin_values() -> None:
    assert RuleOrigin.BOB_PROPOSED.value == "bob_proposed"
