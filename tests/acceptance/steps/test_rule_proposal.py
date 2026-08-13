# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Шаги сценариев «Боб предлагает поправить себя» (BOB-096, срезы 1/2/5).

Связывают ``rule_proposal.feature`` с :mod:`tests.acceptance.rule_proposal_harness`,
который гоняет настоящую сборку самоулучшения над настоящей SQLite. Утверждения — только
о наблюдаемом снаружи: что пришло владельцу в чат, что он видит по ``/rules``, на какой
тир ушёл запрос детектора и что пережило перезапуск.

Сценарии синхронные (pytest-bdd), поэтому асинхронные тики гоняются через ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from bob.proactivity.rule_announcement import MAX_ANNOUNCE_ATTEMPTS
from bob.proactivity.self_improvement import RuleState
from tests.acceptance.rule_proposal_harness import (
    CONFIGURED_CEILING,
    DETECTOR_TEXT,
    LENGTH_LEVER_MARKER,
    OWNER_DM_CHAT_ID,
    ProposalOutcome,
    ProposalRun,
    another_detector_says,
    detector_says,
    run_self_observation,
)

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/rule_proposal.feature")

# «Боб» отдельным словом — то самое третье лицо о себе из живого дефекта.
_THIRD_PERSON = re.compile(r"\bБоб\w*", re.IGNORECASE)
# Первое лицо: он говорит про себя, а не про какого-то Боба.
_FIRST_PERSON = re.compile(r"\b(я|меня|мне|себя|себе)\b", re.IGNORECASE)
_UNDELIVERED_MARK = "не доставлено"
_APPROVE_COMMAND = "/rule approve"


@dataclass(slots=True)
class _ProposalContext:
    """Общая доска сценария: как поставлен прогон и что он произвёл."""

    db_root: Path
    run: ProposalRun = field(default_factory=ProposalRun)
    outcome: ProposalOutcome = field(default_factory=ProposalOutcome)


@pytest.fixture
def proposal_context(tmp_path: Path) -> _ProposalContext:
    """Свежая доска на сценарий: своя база, свой чат, свои часы."""
    return _ProposalContext(db_root=tmp_path)


def _only_message(context: _ProposalContext) -> str:
    assert len(context.outcome.said_to_owner) == 1, context.outcome.said_to_owner
    return context.outcome.said_to_owner[0]


def _speech_of(message: str) -> str:
    """Слова Боба — всё до служебной сноски (она отделена пустой строкой)."""
    return message.split("\n\n", 1)[0]


# --- Дано: что ответила модель и что с транспортом ---------------------------------


@given("модель предложила содержательную поправку")
def substantive_proposal(proposal_context: _ProposalContext) -> None:
    proposal_context.run = replace(proposal_context.run, detector_replies=(detector_says(),))


@given("модель предложила поправку с пустым «что менять»")
def empty_adjustment(proposal_context: _ProposalContext) -> None:
    # Живой симптом 12 августа: «Предлагаю: .» — слот поправки пуст.
    proposal_context.run = replace(
        proposal_context.run, detector_replies=(detector_says(adjustment="   "),)
    )


@given("модель предложила поправку без наблюдения")
def empty_observation(proposal_context: _ProposalContext) -> None:
    proposal_context.run = replace(
        proposal_context.run, detector_replies=(detector_says(observation="   "),)
    )


@given("модель предложила поправку нулевой величины")
def zero_magnitude(proposal_context: _ProposalContext) -> None:
    proposal_context.run = replace(
        proposal_context.run, detector_replies=(detector_says(magnitude=0.0),)
    )


@given("модель предложила поправку сверх потолка из конфига")
def magnitude_above_ceiling(proposal_context: _ProposalContext) -> None:
    proposal_context.run = replace(
        proposal_context.run,
        detector_replies=(detector_says(magnitude=CONFIGURED_CEILING + 0.2),),
    )


@given("модель предложила содержательную поправку, а после перезапуска — другую")
def two_different_proposals(proposal_context: _ProposalContext) -> None:
    proposal_context.run = replace(
        proposal_context.run,
        detector_replies=(detector_says(), another_detector_says()),
    )


@given("в конфиге детектору назначен быстрый тир")
def detector_pinned_to_the_fast_tier(proposal_context: _ProposalContext) -> None:
    # 🔴 Значение, ОТЛИЧНОЕ от дефолта: только так видно, что ключ читается, а не
    # просто совпадает с тем, что роутер сделал бы и без него.
    proposal_context.run = replace(proposal_context.run, detector_tier=0)


@given("отправка сообщений владельцу не проходит")
def transport_is_down(proposal_context: _ProposalContext) -> None:
    # Битая сеть: НИ ОДНА попытка не проходит, сколько бы их ни было.
    proposal_context.run = replace(proposal_context.run, broken_attempts=99)


@given("первая отправка владельцу срывается")
def transport_fails_once(proposal_context: _ProposalContext) -> None:
    proposal_context.run = replace(proposal_context.run, broken_attempts=1)


# --- Когда: медленные тики Боба ----------------------------------------------------


def _drive(context: _ProposalContext, *, ticks: int = 1, restarts: int = 0) -> None:
    context.run = replace(context.run, ticks_per_start=ticks, restarts=restarts)
    context.outcome = asyncio.run(run_self_observation(context.run, db_root=context.db_root))


@when("Боб проводит тик самонаблюдения")
def one_tick(proposal_context: _ProposalContext) -> None:
    _drive(proposal_context)


@when("Боб проводит три тика самонаблюдения подряд")
def three_ticks(proposal_context: _ProposalContext) -> None:
    _drive(proposal_context, ticks=3)


@when("Боб проводит тик самонаблюдения и перезапускается")
def one_restart(proposal_context: _ProposalContext) -> None:
    _drive(proposal_context, restarts=1)


@when("Боб проводит тик самонаблюдения и трижды перезапускается")
def three_restarts(proposal_context: _ProposalContext) -> None:
    _drive(proposal_context, restarts=3)


@when("Боб проводит тик самонаблюдения и семь раз перезапускается")
def seven_restarts(proposal_context: _ProposalContext) -> None:
    _drive(proposal_context, restarts=7)


# --- Тогда: что пересекло границу --------------------------------------------------


@then("владельцу ничего не пришло")
def owner_heard_nothing(proposal_context: _ProposalContext) -> None:
    assert proposal_context.outcome.said_to_owner == ()


@then("правил самоулучшения у Боба нет")
def no_rules_at_all(proposal_context: _ProposalContext) -> None:
    # Не только «не сказал», но и «не завёл»: иначе предложение всплыло бы позже.
    assert proposal_context.outcome.stored == ()


@then("владелец получил ровно одно предложение")
def exactly_one_proposal(proposal_context: _ProposalContext) -> None:
    assert len(proposal_context.outcome.said_to_owner) == 1, proposal_context.outcome.said_to_owner


@then("предложение пришло владельцу в личку")
def proposal_went_to_the_owners_dm(proposal_context: _ProposalContext) -> None:
    assert proposal_context.outcome.chats == (OWNER_DM_CHAT_ID,)


@then("правило ждёт решения владельца")
def the_rule_waits_for_the_owner(proposal_context: _ProposalContext) -> None:
    # Боб только предлагает: включает правило владелец командой, и никто больше.
    states = [rule.state for rule in proposal_context.outcome.stored]
    assert states == [RuleState.PROPOSED]


@then("модель видела потолок величины в задании")
def the_model_was_told_the_ceiling(proposal_context: _ProposalContext) -> None:
    said = "\n".join(proposal_context.outcome.tier1_saw)
    assert str(CONFIGURED_CEILING) in said, said


@then("думать над предложением просили рассуждающий тир")
def the_reasoning_tier_did_the_thinking(proposal_context: _ProposalContext) -> None:
    assert len(proposal_context.outcome.tier1_saw) == 1


@then("быстрый тир к предложению не привлекали")
def the_fast_tier_was_not_asked(proposal_context: _ProposalContext) -> None:
    assert proposal_context.outcome.tier0_saw == ()


@then("думать над предложением просили быстрый тир")
def the_fast_tier_did_the_thinking(proposal_context: _ProposalContext) -> None:
    assert len(proposal_context.outcome.tier0_saw) == 1


@then("рассуждающий тир к предложению не привлекали")
def the_reasoning_tier_was_not_asked(proposal_context: _ProposalContext) -> None:
    assert proposal_context.outcome.tier1_saw == ()


@then("в предложении Боб говорит о себе от первого лица")
def the_proposal_is_first_person(proposal_context: _ProposalContext) -> None:
    message = _only_message(proposal_context)
    assert _FIRST_PERSON.search(message), message


@then("он не говорит о себе в третьем лице")
def the_proposal_is_not_third_person(proposal_context: _ProposalContext) -> None:
    # «Заметил за собой: Боб замечает, что…» — так это звучало у владельца.
    message = _only_message(proposal_context)
    assert not _THIRD_PERSON.search(message), message


@then("он говорит именно о той черте, которую за собой заметил")
def the_proposal_names_the_right_trait(proposal_context: _ProposalContext) -> None:
    # 🔴 Не «какая-нибудь человеческая фраза», а ИМЕННО про длину ответов — рычаг,
    # который вернулся из настоящей SQLite. Запасная формулировка «заметил кое-что»
    # тут краснеет, а именно ею маскируется ошибка типа рычага (находка координатора
    # к срезу 5: Lever — StrEnum, словарь по строке не попадает).
    message = _only_message(proposal_context)
    assert LENGTH_LEVER_MARKER in message, message


@then("в предложении нет следов пустого слота")
def no_empty_slot_artefacts(proposal_context: _ProposalContext) -> None:
    message = _only_message(proposal_context)
    assert ".." not in message, message
    assert ": ." not in message, message
    assert "  " not in message, message


@then("предложение заканчивается вопросом владельцу")
def the_speech_ends_with_a_question(proposal_context: _ProposalContext) -> None:
    assert _speech_of(_only_message(proposal_context)).endswith("?")


@then("слов детектора в предложении нет")
def the_detector_text_never_reaches_the_owner(proposal_context: _ProposalContext) -> None:
    message = _only_message(proposal_context)
    for fragment in DETECTOR_TEXT:
        assert fragment not in message, message


@then("идентификатор правила не стоит внутри фразы")
def the_rule_id_is_not_inside_the_phrase(proposal_context: _ProposalContext) -> None:
    speech = _speech_of(_only_message(proposal_context))
    stored = proposal_context.outcome.stored
    assert len(stored) == 1, stored
    assert stored[0].id not in speech, speech
    assert "/" not in speech, speech


@then("команда для владельца стоит отдельной служебной строкой")
def the_command_is_a_service_footnote(proposal_context: _ProposalContext) -> None:
    message = _only_message(proposal_context)
    rule_id = proposal_context.outcome.stored[0].id
    footnote = message.split("\n\n", 1)[1]
    assert footnote == f"`{_APPROVE_COMMAND} {rule_id}`", footnote


@then("правило помечено проговорённым в базе")
def the_rule_is_marked_as_said(proposal_context: _ProposalContext) -> None:
    # Пометка пережила перезапуск — она в базе, а не в памяти процесса.
    assert [rule.announced for rule in proposal_context.outcome.stored] == [True]


@then("владелец получил два разных предложения")
def two_distinct_proposals(proposal_context: _ProposalContext) -> None:
    said = proposal_context.outcome.said_to_owner
    assert len(said) == 2, said
    assert said[0] != said[1], said


@then("попыток доставки было ровно три")
def exactly_three_attempts(proposal_context: _ProposalContext) -> None:
    # Кап — настоящий потолок: попытка считается ДО отправки, поэтому её не теряет
    # ни сбой, ни перезапуск посреди отправки.
    assert proposal_context.outcome.send_attempts == MAX_ANNOUNCE_ATTEMPTS
    assert [rule.announce_attempts for rule in proposal_context.outcome.stored] == [
        MAX_ANNOUNCE_ATTEMPTS
    ]


@then("правило видно владельцу в /rules как недоставленное")
def the_owner_sees_it_as_undelivered(proposal_context: _ProposalContext) -> None:
    # Боб о нём молчит — значит, список у GUPPI единственное место, где владелец о нём
    # узнаёт. Молча потерять предложение было бы хуже, чем не доставить.
    listing = proposal_context.outcome.rules_listing
    assert _UNDELIVERED_MARK in listing, listing
    assert [rule.state for rule in proposal_context.outcome.stored] == [RuleState.PROPOSED]


@then("в /rules нет пометки о недоставленном")
def nothing_is_marked_undelivered(proposal_context: _ProposalContext) -> None:
    listing = proposal_context.outcome.rules_listing
    assert _UNDELIVERED_MARK not in listing, listing
