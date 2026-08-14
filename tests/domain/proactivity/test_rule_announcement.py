# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты чистого ядра доставки предложения правила (BOB-096 срез 1).

Дефект, который наблюдался вживую шесть дней: пометка «проговорено» жила в памяти
процесса, а при сбое отправки не ставилась вовсе — правило уходило owner'у на каждом
reflect-тике (раз в 5 минут) и заново после каждого перезапуска. Ядро здесь отвечает
на ровно один вопрос: «про это правило ещё говорить — и услышал ли его owner?».

Покрывают: четыре статуса (ждёт / сказано / не доставлено / нечего одобрять), границу
капа попыток (кап именно ``MAX_ANNOUNCE_ATTEMPTS``, а не «около того»), границу потолка
величины, выбор следующего кандидата (только PROPOSED, только ждущие, самое старое,
тай-брейк по id) и обе метки owner-facing списка.

🔴 Регрессия, которую ядро закрывает вторым заходом (BOB-096, ревью на копии живой базы):
вердикт «есть что одобрять» стоял только на РОЖДЕНИИ правила, поэтому вырожденные
предложения, родившиеся раньше, доезжали до владельца прежним путём — и новый живой
голос озвучивал пустую поправку как нормальное предложение. Теперь тот же вердикт стоит
и на ВЫХОДЕ, а владелец видит такое правило в ``/rules`` названным честно.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.proactivity.rule_announcement import (
    MAX_ANNOUNCE_ATTEMPTS,
    AnnounceStatus,
    announce_status,
    is_undelivered_proposal,
    next_to_announce,
    unactionable_reason,
)
from bob.proactivity.self_improvement import (
    ImprovementRule,
    Lever,
    ProposalDefect,
    RuleOrigin,
    RuleState,
)

_NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
_EARLIER = datetime(2026, 8, 6, 6, 6, tzinfo=UTC)

#: Потолок величины из живого ``config/bob.yaml`` — с ним ядру и задают вопрос.
_CEILING = 0.3


def _rule(
    rid: str = "r1",
    *,
    state: RuleState = RuleState.PROPOSED,
    announced: bool = False,
    announce_attempts: int = 0,
    created_at: datetime = _NOW,
    observation: str = "Замечаю, что отвечаю слишком сухо",
    adjustment: str = "Добавить теплоты в тон",
    magnitude: float = _CEILING,
) -> ImprovementRule:
    return ImprovementRule(
        id=rid,
        observation=observation,
        adjustment=adjustment,
        lever=Lever.TONE,
        magnitude=magnitude,
        state=state,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=created_at,
        evidence="Паттерн: короткие сухие ответы 5 раз подряд",
        announced=announced,
        announce_attempts=announce_attempts,
    )


# --- Статус доставки ----------------------------------------------------------


def test_fresh_rule_is_pending() -> None:
    assert announce_status(_rule(), max_magnitude=_CEILING) is AnnounceStatus.PENDING


def test_announced_rule_is_delivered() -> None:
    assert (
        announce_status(_rule(announced=True), max_magnitude=_CEILING) is AnnounceStatus.DELIVERED
    )


def test_delivered_wins_over_exhausted_attempts() -> None:
    # Доставили с последней попытки: попытки исчерпаны, но owner УСЛЫШАЛ.
    rule = _rule(announced=True, announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert announce_status(rule, max_magnitude=_CEILING) is AnnounceStatus.DELIVERED


def test_attempt_below_cap_is_still_pending() -> None:
    rule = _rule(announce_attempts=MAX_ANNOUNCE_ATTEMPTS - 1)

    assert announce_status(rule, max_magnitude=_CEILING) is AnnounceStatus.PENDING


def test_attempts_at_cap_are_exhausted() -> None:
    rule = _rule(announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert announce_status(rule, max_magnitude=_CEILING) is AnnounceStatus.UNDELIVERED


def test_attempts_beyond_cap_are_exhausted() -> None:
    rule = _rule(announce_attempts=MAX_ANNOUNCE_ATTEMPTS + 7)

    assert announce_status(rule, max_magnitude=_CEILING) is AnnounceStatus.UNDELIVERED


def test_cap_is_three_attempts() -> None:
    # Кап — контракт поведения, а не деталь: две неудачи ещё можно повторить, три —
    # это уже не «моргнула сеть», и Боб замолкает (шесть дней долбёжки — из-за их
    # отсутствия). Проверяется на ДЕФОЛТНОМ капе, без передачи max_attempts.
    assert (
        announce_status(_rule(announce_attempts=2), max_magnitude=_CEILING)
        is AnnounceStatus.PENDING
    )
    assert (
        announce_status(_rule(announce_attempts=3), max_magnitude=_CEILING)
        is AnnounceStatus.UNDELIVERED
    )


def test_cap_is_configurable_per_call() -> None:
    rule = _rule(announce_attempts=1)

    assert (
        announce_status(rule, max_attempts=1, max_magnitude=_CEILING) is AnnounceStatus.UNDELIVERED
    )
    assert announce_status(rule, max_attempts=2, max_magnitude=_CEILING) is AnnounceStatus.PENDING


# --- Выбор следующего кандидата ----------------------------------------------


def test_no_rules_means_nothing_to_announce() -> None:
    assert next_to_announce((), max_magnitude=_CEILING) is None


def test_picks_the_only_pending_proposal() -> None:
    picked = next_to_announce((_rule("r1"),), max_magnitude=_CEILING)

    assert picked is not None
    assert picked.id == "r1"


def test_picks_the_oldest_pending_proposal() -> None:
    rules = (_rule("young", created_at=_NOW), _rule("old", created_at=_EARLIER))

    picked = next_to_announce(rules, max_magnitude=_CEILING)

    assert picked is not None
    assert picked.id == "old"


def test_ties_break_on_id() -> None:
    rules = (_rule("b"), _rule("a"))

    picked = next_to_announce(rules, max_magnitude=_CEILING)

    assert picked is not None
    assert picked.id == "a"


def test_already_announced_is_never_picked_again() -> None:
    assert next_to_announce((_rule("r1", announced=True),), max_magnitude=_CEILING) is None


def test_exhausted_proposal_is_not_picked() -> None:
    rules = (_rule("r1", announce_attempts=MAX_ANNOUNCE_ATTEMPTS),)

    assert next_to_announce(rules, max_magnitude=_CEILING) is None


def test_exhausted_proposal_does_not_block_a_fresh_one() -> None:
    rules = (
        _rule("stuck", announce_attempts=MAX_ANNOUNCE_ATTEMPTS, created_at=_EARLIER),
        _rule("fresh", created_at=_NOW),
    )

    picked = next_to_announce(rules, max_magnitude=_CEILING)

    assert picked is not None
    assert picked.id == "fresh"


def test_next_to_announce_honours_a_tighter_cap() -> None:
    # 🔴 Кап, с которым спросили, и есть кап, по которому отбирают: при дефолтном (3)
    # это правило ещё кандидат, при переданном (1) — уже нет. Без этой проверки
    # проброс max_attempts можно было выбросить, и функция молча жила бы на дефолте
    # (мутант x_next_to_announce__mutmut_7 выживал именно так).
    rules = (_rule("r1", announce_attempts=1),)

    assert next_to_announce(rules, max_magnitude=_CEILING) is not None
    assert next_to_announce(rules, max_attempts=1, max_magnitude=_CEILING) is None


def test_next_to_announce_honours_a_looser_cap() -> None:
    rules = (_rule("r1", announce_attempts=MAX_ANNOUNCE_ATTEMPTS),)
    looser = MAX_ANNOUNCE_ATTEMPTS + 2

    assert next_to_announce(rules, max_magnitude=_CEILING) is None
    picked = next_to_announce(rules, max_attempts=looser, max_magnitude=_CEILING)

    assert picked is not None
    assert picked.id == "r1"


def test_is_undelivered_proposal_honours_a_tighter_cap() -> None:
    rule = _rule(announce_attempts=1)

    assert is_undelivered_proposal(rule, max_magnitude=_CEILING) is False
    assert is_undelivered_proposal(rule, max_attempts=1, max_magnitude=_CEILING) is True


def test_is_undelivered_proposal_honours_a_looser_cap() -> None:
    rule = _rule(announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert is_undelivered_proposal(rule, max_magnitude=_CEILING) is True
    assert (
        is_undelivered_proposal(
            rule, max_attempts=MAX_ANNOUNCE_ATTEMPTS + 2, max_magnitude=_CEILING
        )
        is False
    )


@pytest.mark.parametrize(
    "state",
    [RuleState.APPROVED, RuleState.PAUSED, RuleState.REJECTED, RuleState.REMOVED],
)
def test_only_proposed_rules_are_candidates(state: RuleState) -> None:
    assert next_to_announce((_rule("r1", state=state),), max_magnitude=_CEILING) is None


def test_picks_the_proposal_past_a_non_proposed_rule() -> None:
    rules = (
        _rule("approved", state=RuleState.APPROVED, created_at=_EARLIER),
        _rule("proposed", created_at=_NOW),
    )

    picked = next_to_announce(rules, max_magnitude=_CEILING)

    assert picked is not None
    assert picked.id == "proposed"


# --- «Предложение потерялось» — то, что owner видит в /rules ------------------


def test_exhausted_proposal_is_flagged_as_undelivered() -> None:
    rule = _rule(announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert is_undelivered_proposal(rule, max_magnitude=_CEILING) is True


def test_pending_proposal_is_not_flagged() -> None:
    assert is_undelivered_proposal(_rule(), max_magnitude=_CEILING) is False


def test_delivered_proposal_is_not_flagged() -> None:
    rule = _rule(announced=True, announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert is_undelivered_proposal(rule, max_magnitude=_CEILING) is False


def test_a_rule_owner_already_decided_is_not_flagged() -> None:
    # Owner отклонил правило — его недоставленность больше не его проблема.
    rule = _rule(state=RuleState.REJECTED, announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert is_undelivered_proposal(rule, max_magnitude=_CEILING) is False


# --- «Нечего одобрять» — вердикт на ВЫХОДЕ, а не только на рождении -----------
#
# 🔴 Регрессия BOB-096, найденная ревью на КОПИИ живой базы владельца: отбраковка
# вырожденных предложений стояла только на рождении правила, поэтому пять правил,
# родившихся ДО неё, доезжали прежним путём — и голос среза 5 озвучивал пустую
# поправку как нормальное предложение («Хочу чуть поправить тон. Попробуем?»).
# Стало ХУЖЕ исходного дефекта: мусор перестал выглядеть мусором.


def test_a_proposal_with_no_adjustment_has_nothing_to_approve() -> None:
    # Ровно живое правило rule-20260806060649-0: величина 0.0, поправка пустая.
    rule = _rule(adjustment="", magnitude=0.0)

    assert announce_status(rule, max_magnitude=_CEILING) is AnnounceStatus.NOT_ACTIONABLE


def test_a_zero_tilt_proposal_has_nothing_to_approve() -> None:
    rule = _rule(magnitude=0.0)

    assert announce_status(rule, max_magnitude=_CEILING) is AnnounceStatus.NOT_ACTIONABLE


def test_a_proposal_above_the_ceiling_has_nothing_to_approve() -> None:
    # «Хочу сильно осмелеть» при потолке 0.3 — применение всё равно урежет до 0.3,
    # то есть владелец одобрял бы не то число, которое ему показали.
    rule = _rule(magnitude=0.7)

    assert announce_status(rule, max_magnitude=_CEILING) is AnnounceStatus.NOT_ACTIONABLE


def test_nothing_to_approve_outranks_pending() -> None:
    # Порядок вердиктов: сперва «есть ли что одобрять», потом бухгалтерия доставки.
    # Иначе вырожденное правило числится ждущим и уходит владельцу.
    rule = _rule(adjustment="", magnitude=0.0)

    assert announce_status(rule, max_magnitude=_CEILING) is not AnnounceStatus.PENDING


def test_nothing_to_approve_outranks_delivered_and_exhausted() -> None:
    # Правило, уже проговорённое ДО фикса, всё равно нечего одобрять — и владельцу
    # честнее видеть именно это, а не «доставлено» / «не доставлено».
    delivered = _rule(magnitude=0.0, announced=True)
    exhausted = _rule(magnitude=0.0, announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert announce_status(delivered, max_magnitude=_CEILING) is AnnounceStatus.NOT_ACTIONABLE
    assert announce_status(exhausted, max_magnitude=_CEILING) is AnnounceStatus.NOT_ACTIONABLE


def test_a_degenerate_proposal_already_in_the_store_is_not_announced() -> None:
    # 🔴 Сердце фикса: правило УЖЕ лежит в базе (родилось до отбраковки) — и всё равно
    # не проговаривается.
    rules = (_rule("legacy", adjustment="", magnitude=0.0),)

    assert next_to_announce(rules, max_magnitude=_CEILING) is None


def test_a_degenerate_proposal_does_not_block_the_actionable_one() -> None:
    # Расклад живой базы владельца: четыре вырожденных правила старше одного годного.
    rules = (
        _rule("empty", adjustment="", magnitude=0.0, created_at=_EARLIER),
        _rule("bold", magnitude=0.4, created_at=_EARLIER),
        _rule("bolder", magnitude=0.5, created_at=_EARLIER),
        _rule("boldest", magnitude=0.7, created_at=_EARLIER),
        _rule("real", magnitude=0.2, created_at=_NOW),
    )

    picked = next_to_announce(rules, max_magnitude=_CEILING)

    assert picked is not None
    assert picked.id == "real"


def test_next_to_announce_honours_a_tighter_ceiling() -> None:
    # 🔴 Потолок, с которым спросили, и есть потолок, по которому отбирают: величина
    # 0.3 проходит при потолке 0.3 и не проходит при 0.2. Без этой пары проброс
    # max_magnitude можно выбросить, и отбор молча жил бы на чужом потолке.
    rules = (_rule("r1", magnitude=0.3),)

    assert next_to_announce(rules, max_magnitude=0.3) is not None
    assert next_to_announce(rules, max_magnitude=0.2) is None


def test_next_to_announce_honours_a_looser_ceiling() -> None:
    rules = (_rule("r1", magnitude=0.5),)

    assert next_to_announce(rules, max_magnitude=_CEILING) is None
    picked = next_to_announce(rules, max_magnitude=0.9)

    assert picked is not None
    assert picked.id == "r1"


# --- Почему Боб молчит — глазами владельца: молчание ≠ исчезновение -----------


def test_a_degenerate_proposal_has_nothing_to_approve() -> None:
    rule = _rule(adjustment="", magnitude=0.0)

    assert (
        unactionable_reason(rule, max_magnitude=_CEILING)
        is ProposalDefect.NOTHING_TO_APPROVE
    )


def test_an_over_ceiling_proposal_names_the_ceiling_not_emptiness() -> None:
    # 🔴 Три из четырёх отклонённых правил живой базы — ИМЕННО этот случай: поправка
    # осмысленная, не хватает лишь разрешения на величину. Одна метка на оба случая
    # сказала бы владельцу неправду и отняла у него настоящее решение.
    rule = _rule(magnitude=0.7)

    assert (
        unactionable_reason(rule, max_magnitude=_CEILING) is ProposalDefect.ABOVE_CEILING
    )


def test_an_actionable_proposal_has_no_reason_to_be_silent() -> None:
    assert unactionable_reason(_rule(), max_magnitude=_CEILING) is None


def test_a_degenerate_rule_owner_already_decided_is_not_flagged() -> None:
    # Владелец уже отклонил его — обсуждать нечего в любом случае.
    rule = _rule(state=RuleState.REJECTED, adjustment="", magnitude=0.0)

    assert unactionable_reason(rule, max_magnitude=_CEILING) is None


def test_the_reason_honours_the_ceiling_it_was_asked_with() -> None:
    rule = _rule(magnitude=0.5)

    assert (
        unactionable_reason(rule, max_magnitude=_CEILING) is ProposalDefect.ABOVE_CEILING
    )
    assert unactionable_reason(rule, max_magnitude=0.9) is None


def test_a_degenerate_exhausted_proposal_is_never_called_undelivered() -> None:
    # 🔴 Две РАЗНЫЕ вещи: «пробовали и не дошло» и «говорить не о чем». Назвать вторую
    # первой значило бы соврать владельцу — он бы ждал повторной доставки.
    rule = _rule(adjustment="", magnitude=0.0, announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert is_undelivered_proposal(rule, max_magnitude=_CEILING) is False
    assert (
        unactionable_reason(rule, max_magnitude=_CEILING)
        is ProposalDefect.NOTHING_TO_APPROVE
    )
