# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the Tier-0 fallback scenarios (BOB-087 Срез E).

Binds ``tier0_fallback.feature`` to :mod:`tests.acceptance.tier0_fallback_harness`, which
stages three REAL loopback HTTP endpoints (cloud Tier-0, the local understudy, Tier-1),
resolves the effective config through the REAL loader and drives one turn through the REAL
factory + router. Every assertion here is on what crossed that boundary — the text that
came back, which endpoint was actually contacted, the failure that surfaced, the operator's
log — never on a provider's internals.

The scenarios are synchronous (pytest-bdd), so the async turn runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace

import pytest
from pytest_bdd import given, scenarios, then, when

from bob.application.router import TaskType
from tests.acceptance.tier0_fallback_harness import (
    ANSWERS,
    BAD_REQUEST,
    BROKEN_SHAPE,
    CLOUD_REFUSAL,
    CLOUD_REPLY,
    DISCONNECTS,
    HANGS,
    LOCAL_REPLY,
    PRIVATE_CONTEXT,
    REFUSES,
    SERVER_ERROR,
    SHAREABLE_CONTEXT,
    TIER1_REPLY,
    UNREACHABLE,
    TurnOutcome,
    TurnRequest,
    default_fallback_setting,
    run_turn,
)

scenarios("../features/tier0_fallback.feature")


@dataclass(slots=True)
class _FallbackContext:
    """The slate the steps share: how the turn is staged, and what it produced."""

    request: TurnRequest = field(default_factory=TurnRequest)
    outcome: TurnOutcome = field(default_factory=TurnOutcome)


@pytest.fixture
def fallback_context() -> _FallbackContext:
    """A fresh staging slate per scenario (fresh ports, fresh config, fresh log)."""
    return _FallbackContext()


# --- Given: the flag and what each endpoint does --------------------------------


@given("локальный фолбэк Tier-0 включён в конфиге")
def fallback_on(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, fallback_on=True)


@given("локальный фолбэк Tier-0 выключен")
def fallback_off(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, fallback_on=False)


@given("облачный Tier-0 отвечает нормально")
def cloud_answers(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, cloud_tier0=ANSWERS)


@given("облачный Tier-0 не отвечает вовсе")
def cloud_hangs(fallback_context: _FallbackContext) -> None:
    # A REAL timeout: the endpoint accepts the request and never answers within the
    # turn budget — the BOB-084 outage shape.
    fallback_context.request = replace(fallback_context.request, cloud_tier0=HANGS)


@given("облачный Tier-0 отвечает ошибкой 503")
def cloud_server_error(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, cloud_tier0=SERVER_ERROR)


@given("облачный Tier-0 обрывает соединение на полуслове")
def cloud_disconnects(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, cloud_tier0=DISCONNECTS)


@given("облачный Tier-0 недоступен — соединение отвергнуто")
def cloud_unreachable(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, cloud_tier0=UNREACHABLE)


@given("облачный Tier-0 отвечает осмысленным отказом модели")
def cloud_refuses(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, cloud_tier0=REFUSES)


@given("облачный Tier-0 отвечает ошибкой 400")
def cloud_bad_request(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, cloud_tier0=BAD_REQUEST)


@given("облачный Tier-0 отвечает телом без choices")
def cloud_broken_shape(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, cloud_tier0=BROKEN_SHAPE)


@given("локальная модель не запущена")
def local_unreachable(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, local=UNREACHABLE)


@given("Tier-1 отвечает ошибкой 503")
def tier1_server_error(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, tier1=SERVER_ERROR)


@given("Tier-1 не отвечает вовсе")
def tier1_hangs(fallback_context: _FallbackContext) -> None:
    # Настоящий таймаут на верхнем тире — аварийная форма, на которой фолбэк вниз законен.
    fallback_context.request = replace(fallback_context.request, tier1=HANGS)


@given("Tier-1 отвечает ошибкой 400")
def tier1_bad_request(fallback_context: _FallbackContext) -> None:
    # Не авария, а наш дефект: кривой запрос, протухший ключ, несуществующая модель.
    fallback_context.request = replace(fallback_context.request, tier1=BAD_REQUEST)


@given("Tier-1 отвечает телом без choices")
def tier1_broken_shape(fallback_context: _FallbackContext) -> None:
    # Вызов удался, СОДЕРЖИМОЕ сломано — контрактная поломка, а не отвал связи.
    fallback_context.request = replace(fallback_context.request, tier1=BROKEN_SHAPE)


@given("у хода есть приватный контекст")
def turn_carries_private_context(fallback_context: _FallbackContext) -> None:
    # Both halves of the split (Variant 2): the shareable half MAY travel to the cloud, the
    # private half never may. Staging both is what makes the privacy assertions meaningful
    # — «не пересекло границу» proves nothing about a turn that carried nothing.
    fallback_context.request = replace(
        fallback_context.request,
        shareable_context=SHAREABLE_CONTEXT,
        private_context=PRIVATE_CONTEXT,
    )


# --- When: the turn -------------------------------------------------------------


@when("Бобу нужен Tier-0 для рабочего хода")
def run_tier0_turn(fallback_context: _FallbackContext) -> None:
    # WORK_TALK is a Tier-0 classifier (BOB-087.C2) — the shape an outage silences.
    fallback_context.request = replace(fallback_context.request, task_type=TaskType.WORK_TALK)
    fallback_context.outcome = asyncio.run(run_turn(fallback_context.request))


@when("Бобу нужен Tier-1 для ответа владельцу")
def run_tier1_turn(fallback_context: _FallbackContext) -> None:
    fallback_context.request = replace(fallback_context.request, task_type=TaskType.REPLY_TO_USER)
    fallback_context.outcome = asyncio.run(run_turn(fallback_context.request))


@when("Бобу нужен Tier-0 для короткой реплики владельцу")
def run_casual_reply_turn(fallback_context: _FallbackContext) -> None:
    # 🔴 The turn the whole voice-integrity policy exists for: a REPLY_TO_USER that BOB-006
    # hybrid tiering pinned to the fast Tier-0 model. It is Bob's own voice on the cheap
    # tier — the one place an understudy could quietly ship a 0.5b answer as him.
    fallback_context.request = replace(
        fallback_context.request, task_type=TaskType.REPLY_TO_USER, tier_override=0
    )
    fallback_context.outcome = asyncio.run(run_turn(fallback_context.request))


# --- Then: what crossed the boundary --------------------------------------------


@then("ответ получен от локальной модели")
def reply_is_local(fallback_context: _FallbackContext) -> None:
    assert fallback_context.outcome.reply == LOCAL_REPLY


@then("ответ получен от облачной модели")
def reply_is_cloud(fallback_context: _FallbackContext) -> None:
    assert fallback_context.outcome.reply == CLOUD_REPLY


@then("ответ получен от Tier-1")
def reply_is_tier1(fallback_context: _FallbackContext) -> None:
    # The escalation UP actually happened: the text is the quality tier's, not the
    # understudy's and not the (dead) cloud Tier-0's.
    assert fallback_context.outcome.reply == TIER1_REPLY


@then("Tier-1 не получил ни одного запроса")
def tier1_never_called(fallback_context: _FallbackContext) -> None:
    assert fallback_context.outcome.tier1_calls == 0


@then("облачный Tier-0 не получил ни одного запроса")
def cloud_tier0_never_called(fallback_context: _FallbackContext) -> None:
    # 🔴 Суть строгости верхнего этажа (bob-41o): более слабый тир ЗДОРОВ и готов ответить —
    # и именно поэтому его не спрашивают. Ответ Tier-0 здесь был бы маскировкой дефекта.
    assert fallback_context.outcome.cloud_tier0_calls == 0


@then("приватная строка не пересекла границу к Tier-1")
def private_context_never_reached_tier1(fallback_context: _FallbackContext) -> None:
    # 🔴 Asserted on the RAW BODY Tier-1 actually received — the boundary itself, not the
    # router's intention. Nothing internal may travel to the cloud along an outage path.
    assert PRIVATE_CONTEXT not in fallback_context.outcome.tier1_payload


@then("разделяемый контекст к Tier-1 дошёл")
def shareable_context_reached_tier1(fallback_context: _FallbackContext) -> None:
    # The counterweight to the assertion above: the escalated call is a REAL, useful call
    # carrying the reply-shaping context — the payload was redacted, not emptied.
    assert SHAREABLE_CONTEXT in fallback_context.outcome.tier1_payload


@then("локальная модель приватную строку видела")
def private_context_reached_the_local_model(fallback_context: _FallbackContext) -> None:
    # Proves the turn genuinely carried the private half, so «Tier-1 не видел её» is a
    # statement about the boundary and not about an empty context.
    assert PRIVATE_CONTEXT in fallback_context.outcome.local_payload


@then("наружу дошёл отказ модели дословно")
def reply_is_the_refusal(fallback_context: _FallbackContext) -> None:
    assert fallback_context.outcome.reply == CLOUD_REFUSAL


@then("ответа нет — наружу ушла ошибка")
def turn_failed(fallback_context: _FallbackContext) -> None:
    outcome = fallback_context.outcome
    assert outcome.reply is None
    assert outcome.failure_type != ""


@then("в ошибке видно «400»")
def failure_names_400(fallback_context: _FallbackContext) -> None:
    assert "400" in fallback_context.outcome.failure_text


@then("в ошибке видно «503»")
def failure_names_503(fallback_context: _FallbackContext) -> None:
    assert "503" in fallback_context.outcome.failure_text


@then("падение локальной модели приложено причиной, а не подменяет собой облачную ошибку")
def local_failure_is_only_the_cause(fallback_context: _FallbackContext) -> None:
    outcome = fallback_context.outcome
    # The local failure is attached (the operator can still see it) but it is NOT the
    # error that surfaced: the cloud's 503 is the informative one and stays on top.
    assert outcome.cause_text != ""
    assert "503" not in outcome.cause_text


@then("локальную модель дёрнули ровно один раз")
def local_called_once(fallback_context: _FallbackContext) -> None:
    # Exactly one — no cascade, no retry loop.
    assert fallback_context.outcome.local_calls == 1


@then("в логе оператора видно, что локальная модель тоже не вытянула")
def log_reports_the_local_failure(fallback_context: _FallbackContext) -> None:
    # The local model was genuinely attempted (its daemon is down, so it never gets to
    # count a call — the operator's log is what proves the switch happened at all).
    warnings = fallback_context.outcome.warnings
    assert any("Local fallback LLM failed too" in message for message in warnings), warnings


@then("локальную модель не дёрнули ни разу")
def local_never_called(fallback_context: _FallbackContext) -> None:
    assert fallback_context.outcome.local_calls == 0


@then("в логе оператора есть предупреждение о переключении на локальную модель")
def log_announces_the_switch(fallback_context: _FallbackContext) -> None:
    warnings = fallback_context.outcome.warnings
    assert any("falling back to the local model" in message for message in warnings), warnings


@then("в предупреждении названа причина отказа облака")
def log_names_the_cause(fallback_context: _FallbackContext) -> None:
    warnings = fallback_context.outcome.warnings
    switch = next(message for message in warnings if "falling back to the local model" in message)
    assert "Primary LLM failed" in switch
    assert "TimeoutError" in switch


@then("в логе оператора видно, что поломку Tier-1 не стали прятать")
def log_reports_the_surfaced_tier1_defect(fallback_context: _FallbackContext) -> None:
    # Никакой тихой правды: владелец узнаёт о сломанном конфиге Tier-1 из лога, а не через
    # неделю по деградировавшим ответам. В строке названы и вид поломки, и её причина.
    warnings = fallback_context.outcome.warnings
    surfaced = [message for message in warnings if "CONTRACT failure" in message]
    assert surfaced, warnings
    assert "400" in surfaced[0], surfaced


@then("лог оператора чист — предупреждений нет")
def log_is_quiet(fallback_context: _FallbackContext) -> None:
    assert fallback_context.outcome.warnings == ()


@then("в логе оператора нет ни слова о локальной модели")
def log_never_mentions_the_local_model(fallback_context: _FallbackContext) -> None:
    warnings = fallback_context.outcome.warnings
    assert not any("local model" in message for message in warnings), warnings


@then("в дефолтном конфиге локальный фолбэк Tier-0 не назван")
def default_config_names_no_fallback() -> None:
    # Ships OFF: with no YAML and no env the loader resolves an empty backend, so the
    # factory builds Tier 0 exactly as it did before this slice.
    assert default_fallback_setting() == ""
