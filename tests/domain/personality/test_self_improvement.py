# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты чистого домена self-improvement (BOB-028 .1, BOB-096).

Покрывают: жёсткий allowlist рычагов (Lever — и ТОЛЬКО разрешённые члены, без
authz/гостя/SOUL/safety по конструкции), машину состояний правила (все ветки
переходов: валидные/невалидные/терминальные, ключевой PROPOSED->APPROVED),
выбор активных правил (только APPROVED), кламп величины наклона (границы/края) и
вердикт «есть ли в предложении что одобрять» (BOB-096).
Всё детерминированно, без I/O и рандома.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.proactivity.self_improvement import (
    ImprovementRule,
    Lever,
    ProposalDefect,
    RuleOrigin,
    RuleState,
    active_rules,
    can_transition,
    clamp_magnitude,
    is_actionable_proposal,
    is_duplicate_rule,
    proposal_defect,
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


# --- is_duplicate_rule (дедуп против существующих, реюз идеи анти-повтора BOB-026) ---


def _obs_rule(
    observation: str,
    *,
    lever: Lever = Lever.TONE,
    state: RuleState = RuleState.PROPOSED,
) -> ImprovementRule:
    """ImprovementRule с заданным наблюдением/рычагом/состоянием (для дедуп-тестов)."""
    return ImprovementRule(
        id="x",
        observation=observation,
        adjustment="поправка",
        lever=lever,
        magnitude=0.2,
        state=state,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=_NOW,
        evidence="",
    )


def test_duplicate_exact_match_same_lever_is_a_dup() -> None:
    candidate = _obs_rule("Отвечаю слишком сухо")
    existing = _obs_rule("отвечаю   слишком  СУХО")  # нормализация: reginstr/case/space
    assert is_duplicate_rule(candidate, [existing]) is True


def test_empty_candidate_observation_is_never_a_dup() -> None:
    # Пустое (после нормализации) наблюдение кандидата дублем не считается (ветка 248).
    candidate = _obs_rule("   ")
    existing = _obs_rule("Отвечаю слишком сухо")
    assert is_duplicate_rule(candidate, [existing]) is False


def test_empty_prior_observation_is_skipped() -> None:
    # Существующее правило с пустым наблюдением пропускается, не блокирует (ветка 254).
    candidate = _obs_rule("Отвечаю слишком сухо")
    existing = _obs_rule("   ")
    assert is_duplicate_rule(candidate, [existing]) is False


def test_different_lever_is_not_a_dup_even_with_same_observation() -> None:
    candidate = _obs_rule("Отвечаю слишком сухо", lever=Lever.TONE)
    existing = _obs_rule("Отвечаю слишком сухо", lever=Lever.HUMOR)
    assert is_duplicate_rule(candidate, [existing]) is False


@pytest.mark.parametrize("state", [RuleState.REJECTED, RuleState.REMOVED])
def test_terminal_prior_does_not_block_a_new_proposal(state: RuleState) -> None:
    # Отклонённое/убранное правило (owner уже разобрался) НЕ блокирует новое предложение.
    candidate = _obs_rule("Отвечаю слишком сухо")
    existing = _obs_rule("Отвечаю слишком сухо", state=state)
    assert is_duplicate_rule(candidate, [existing]) is False


def test_distinct_observations_same_lever_are_not_dups() -> None:
    candidate = _obs_rule("Слишком часто шучу не к месту")
    existing = _obs_rule("Отвечаю слишком сухо и формально без эмпатии")
    assert is_duplicate_rule(candidate, [existing]) is False


# --- is_actionable_proposal (вырожденное предложение не рождается, BOB-096) ---
#
# Живой прецедент: rule-20260806060649-0 — наблюдение-тавтология, adjustment ПУСТО,
# magnitude 0.0. Owner получил вопрос «включить?», на который нельзя ответить
# осмысленно. Вердикт ниже — ровно про это: есть ли в предложении что одобрять.

_CEILING = 0.3


def _proposal(
    *,
    observation: str = "Отвечаю owner'у резче, когда устал",
    adjustment: str = "Добавить теплоты, когда разговор долгий",
    magnitude: float = 0.2,
) -> ImprovementRule:
    """ImprovementRule с заданными наблюдением/поправкой/величиной (для вердикта)."""
    return ImprovementRule(
        id="p1",
        observation=observation,
        adjustment=adjustment,
        lever=Lever.TONE,
        magnitude=magnitude,
        state=RuleState.PROPOSED,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=_NOW,
        evidence="",
    )


def test_substantive_proposal_is_actionable() -> None:
    assert is_actionable_proposal(_proposal(), max_magnitude=_CEILING) is True


@pytest.mark.parametrize("observation", ["", "   ", "\n\t "])
def test_empty_observation_is_not_actionable(observation: str) -> None:
    # Нечего одобрять: Боб не назвал, что именно он за собой заметил.
    rule = _proposal(observation=observation)
    assert is_actionable_proposal(rule, max_magnitude=_CEILING) is False


@pytest.mark.parametrize("adjustment", ["", "   ", "\n\t "])
def test_empty_adjustment_is_not_actionable(adjustment: str) -> None:
    # Ровно живой дефект: «Предлагаю: .» — поправки нет, одобрять нечего.
    rule = _proposal(adjustment=adjustment)
    assert is_actionable_proposal(rule, max_magnitude=_CEILING) is False


@pytest.mark.parametrize("magnitude", [0.0, -0.0, -0.1, -1.0])
def test_non_positive_magnitude_is_not_actionable(magnitude: float) -> None:
    # Нулевой наклон ничего не меняет: одобрение было бы пустой формальностью.
    rule = _proposal(magnitude=magnitude)
    assert is_actionable_proposal(rule, max_magnitude=_CEILING) is False


def test_magnitude_above_the_configured_ceiling_is_not_actionable() -> None:
    # Величина вне max_magnitude: применение всё равно урежет её до потолка, то есть
    # owner одобрял бы не то, что ему показали.
    rule = _proposal(magnitude=_CEILING + 0.01)
    assert is_actionable_proposal(rule, max_magnitude=_CEILING) is False


def test_magnitude_exactly_at_the_ceiling_is_actionable() -> None:
    # Граница включительна: ровно потолок исполним как предложено.
    rule = _proposal(magnitude=_CEILING)
    assert is_actionable_proposal(rule, max_magnitude=_CEILING) is True


def test_the_smallest_positive_magnitude_is_actionable() -> None:
    rule = _proposal(magnitude=0.01)
    assert is_actionable_proposal(rule, max_magnitude=_CEILING) is True


def test_zero_ceiling_leaves_nothing_actionable() -> None:
    # Потолок 0 = «наклоны запрещены»: исполнимого предложения не существует.
    assert is_actionable_proposal(_proposal(), max_magnitude=0.0) is False


# --- proposal_defect: ПОЧЕМУ предложение не годится (BOB-096, фикс ревью) -----
#
# 🔴 Вердикт был прав, а ярлык врал. В живой базе владельца из четырёх отклонённых
# правил МУСОР ровно одно (пустая поправка, величина 0.0); у трёх остальных поправка
# осмысленная (47–74 символа), и отсеяны они только за превышение потолка 0.3. Одна
# метка «нечего одобрять» на все четыре сказала бы владельцу неправду: одобрять там
# есть что, и решение у него другое и действенное — поднять потолок или согласиться
# на урезанную величину. Причина отказа поэтому — часть самого вердикта, а не
# отдельная догадка вызывающего: is_actionable_proposal выведен ИЗ неё.


def test_a_substantive_proposal_has_no_defect() -> None:
    assert proposal_defect(_proposal(), max_magnitude=_CEILING) is None


@pytest.mark.parametrize("observation", ["", "   ", "\n\t "])
def test_an_empty_observation_is_nothing_to_approve(observation: str) -> None:
    rule = _proposal(observation=observation)

    assert (
        proposal_defect(rule, max_magnitude=_CEILING)
        is ProposalDefect.NOTHING_TO_APPROVE
    )


@pytest.mark.parametrize("adjustment", ["", "   ", "\n\t "])
def test_an_empty_adjustment_is_nothing_to_approve(adjustment: str) -> None:
    rule = _proposal(adjustment=adjustment)

    assert (
        proposal_defect(rule, max_magnitude=_CEILING)
        is ProposalDefect.NOTHING_TO_APPROVE
    )


@pytest.mark.parametrize("magnitude", [0.0, -0.0, -0.1, -1.0])
def test_a_non_positive_tilt_is_nothing_to_approve(magnitude: float) -> None:
    rule = _proposal(magnitude=magnitude)

    assert (
        proposal_defect(rule, max_magnitude=_CEILING)
        is ProposalDefect.NOTHING_TO_APPROVE
    )


def test_a_magnitude_above_the_ceiling_is_a_separate_defect() -> None:
    # 🔴 Сердце правки: содержание есть, не хватает только разрешения на величину.
    rule = _proposal(magnitude=_CEILING + 0.4)

    assert proposal_defect(rule, max_magnitude=_CEILING) is ProposalDefect.ABOVE_CEILING


def test_the_ceiling_itself_is_not_a_defect() -> None:
    assert proposal_defect(_proposal(magnitude=_CEILING), max_magnitude=_CEILING) is None


def test_emptiness_outranks_the_ceiling() -> None:
    # У пустого предложения сверх потолка нечего одобрять В ЛЮБОМ случае: поднятие
    # потолка его не спасёт, поэтому владельцу называется именно пустота.
    rule = _proposal(adjustment="", magnitude=_CEILING + 0.4)

    assert (
        proposal_defect(rule, max_magnitude=_CEILING)
        is ProposalDefect.NOTHING_TO_APPROVE
    )


def test_the_verdict_is_exactly_the_absence_of_a_defect() -> None:
    # Одна истина на двоих: вердикт выведен из причины, поэтому разойтись они не могут.
    for rule in (
        _proposal(),
        _proposal(adjustment=""),
        _proposal(magnitude=0.0),
        _proposal(magnitude=_CEILING + 0.4),
        _proposal(magnitude=_CEILING),
    ):
        defect = proposal_defect(rule, max_magnitude=_CEILING)
        actionable = is_actionable_proposal(rule, max_magnitude=_CEILING)

        assert actionable is (defect is None)
