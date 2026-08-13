# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты чистого ядра доставки предложения правила (BOB-096 срез 1).

Дефект, который наблюдался вживую шесть дней: пометка «проговорено» жила в памяти
процесса, а при сбое отправки не ставилась вовсе — правило уходило owner'у на каждом
reflect-тике (раз в 5 минут) и заново после каждого перезапуска. Ядро здесь отвечает
на ровно один вопрос: «про это правило ещё говорить — и услышал ли его owner?».

Покрывают: три статуса доставки (ждёт / сказано / не доставлено), границу капа
попыток (кап именно ``MAX_ANNOUNCE_ATTEMPTS``, а не «около того»), выбор следующего
кандидата (только PROPOSED, только ждущие, самое старое, тай-брейк по id) и признак
«предложение потерялось» для owner-facing списка.
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
)
from bob.proactivity.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
)

_NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
_EARLIER = datetime(2026, 8, 6, 6, 6, tzinfo=UTC)


def _rule(
    rid: str = "r1",
    *,
    state: RuleState = RuleState.PROPOSED,
    announced: bool = False,
    announce_attempts: int = 0,
    created_at: datetime = _NOW,
) -> ImprovementRule:
    return ImprovementRule(
        id=rid,
        observation="Замечаю, что отвечаю слишком сухо",
        adjustment="Добавить теплоты в тон",
        lever=Lever.TONE,
        magnitude=0.3,
        state=state,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=created_at,
        evidence="Паттерн: короткие сухие ответы 5 раз подряд",
        announced=announced,
        announce_attempts=announce_attempts,
    )


# --- Статус доставки ----------------------------------------------------------


def test_fresh_rule_is_pending() -> None:
    assert announce_status(_rule()) is AnnounceStatus.PENDING


def test_announced_rule_is_delivered() -> None:
    assert announce_status(_rule(announced=True)) is AnnounceStatus.DELIVERED


def test_delivered_wins_over_exhausted_attempts() -> None:
    # Доставили с последней попытки: попытки исчерпаны, но owner УСЛЫШАЛ.
    rule = _rule(announced=True, announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert announce_status(rule) is AnnounceStatus.DELIVERED


def test_attempt_below_cap_is_still_pending() -> None:
    rule = _rule(announce_attempts=MAX_ANNOUNCE_ATTEMPTS - 1)

    assert announce_status(rule) is AnnounceStatus.PENDING


def test_attempts_at_cap_are_exhausted() -> None:
    rule = _rule(announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert announce_status(rule) is AnnounceStatus.UNDELIVERED


def test_attempts_beyond_cap_are_exhausted() -> None:
    rule = _rule(announce_attempts=MAX_ANNOUNCE_ATTEMPTS + 7)

    assert announce_status(rule) is AnnounceStatus.UNDELIVERED


def test_cap_is_three_attempts() -> None:
    # Кап — контракт поведения, а не деталь: две неудачи ещё можно повторить, три —
    # это уже не «моргнула сеть», и Боб замолкает (шесть дней долбёжки — из-за их
    # отсутствия). Проверяется на ДЕФОЛТНОМ капе, без передачи max_attempts.
    assert announce_status(_rule(announce_attempts=2)) is AnnounceStatus.PENDING
    assert announce_status(_rule(announce_attempts=3)) is AnnounceStatus.UNDELIVERED


def test_cap_is_configurable_per_call() -> None:
    rule = _rule(announce_attempts=1)

    assert announce_status(rule, max_attempts=1) is AnnounceStatus.UNDELIVERED
    assert announce_status(rule, max_attempts=2) is AnnounceStatus.PENDING


# --- Выбор следующего кандидата ----------------------------------------------


def test_no_rules_means_nothing_to_announce() -> None:
    assert next_to_announce(()) is None


def test_picks_the_only_pending_proposal() -> None:
    picked = next_to_announce((_rule("r1"),))

    assert picked is not None
    assert picked.id == "r1"


def test_picks_the_oldest_pending_proposal() -> None:
    rules = (_rule("young", created_at=_NOW), _rule("old", created_at=_EARLIER))

    picked = next_to_announce(rules)

    assert picked is not None
    assert picked.id == "old"


def test_ties_break_on_id() -> None:
    rules = (_rule("b"), _rule("a"))

    picked = next_to_announce(rules)

    assert picked is not None
    assert picked.id == "a"


def test_already_announced_is_never_picked_again() -> None:
    assert next_to_announce((_rule("r1", announced=True),)) is None


def test_exhausted_proposal_is_not_picked() -> None:
    rules = (_rule("r1", announce_attempts=MAX_ANNOUNCE_ATTEMPTS),)

    assert next_to_announce(rules) is None


def test_exhausted_proposal_does_not_block_a_fresh_one() -> None:
    rules = (
        _rule("stuck", announce_attempts=MAX_ANNOUNCE_ATTEMPTS, created_at=_EARLIER),
        _rule("fresh", created_at=_NOW),
    )

    picked = next_to_announce(rules)

    assert picked is not None
    assert picked.id == "fresh"


def test_next_to_announce_honours_a_tighter_cap() -> None:
    # 🔴 Кап, с которым спросили, и есть кап, по которому отбирают: при дефолтном (3)
    # это правило ещё кандидат, при переданном (1) — уже нет. Без этой проверки
    # проброс max_attempts можно было выбросить, и функция молча жила бы на дефолте
    # (мутант x_next_to_announce__mutmut_7 выживал именно так).
    rules = (_rule("r1", announce_attempts=1),)

    assert next_to_announce(rules) is not None
    assert next_to_announce(rules, max_attempts=1) is None


def test_next_to_announce_honours_a_looser_cap() -> None:
    rules = (_rule("r1", announce_attempts=MAX_ANNOUNCE_ATTEMPTS),)
    looser = MAX_ANNOUNCE_ATTEMPTS + 2

    assert next_to_announce(rules) is None
    picked = next_to_announce(rules, max_attempts=looser)

    assert picked is not None
    assert picked.id == "r1"


def test_is_undelivered_proposal_honours_a_tighter_cap() -> None:
    rule = _rule(announce_attempts=1)

    assert is_undelivered_proposal(rule) is False
    assert is_undelivered_proposal(rule, max_attempts=1) is True


def test_is_undelivered_proposal_honours_a_looser_cap() -> None:
    rule = _rule(announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert is_undelivered_proposal(rule) is True
    assert is_undelivered_proposal(rule, max_attempts=MAX_ANNOUNCE_ATTEMPTS + 2) is False


@pytest.mark.parametrize(
    "state",
    [RuleState.APPROVED, RuleState.PAUSED, RuleState.REJECTED, RuleState.REMOVED],
)
def test_only_proposed_rules_are_candidates(state: RuleState) -> None:
    assert next_to_announce((_rule("r1", state=state),)) is None


def test_picks_the_proposal_past_a_non_proposed_rule() -> None:
    rules = (
        _rule("approved", state=RuleState.APPROVED, created_at=_EARLIER),
        _rule("proposed", created_at=_NOW),
    )

    picked = next_to_announce(rules)

    assert picked is not None
    assert picked.id == "proposed"


# --- «Предложение потерялось» — то, что owner видит в /rules ------------------


def test_exhausted_proposal_is_flagged_as_undelivered() -> None:
    rule = _rule(announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert is_undelivered_proposal(rule) is True


def test_pending_proposal_is_not_flagged() -> None:
    assert is_undelivered_proposal(_rule()) is False


def test_delivered_proposal_is_not_flagged() -> None:
    rule = _rule(announced=True, announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert is_undelivered_proposal(rule) is False


def test_a_rule_owner_already_decided_is_not_flagged() -> None:
    # Owner отклонил правило — его недоставленность больше не его проблема.
    rule = _rule(state=RuleState.REJECTED, announce_attempts=MAX_ANNOUNCE_ATTEMPTS)

    assert is_undelivered_proposal(rule) is False
