# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the batch top-k budget WIRING scenarios (BOB-066 Срез W.2).

Binds ``series_budget_wiring.feature`` to the real-dispatcher harness (real ChatDispatcher +
focus predicate + series-salience plan, scripted handler acting on the scope ceiling). The
scenarios pin the observable collapse through the boundary:

* an ambient burst collapses to ONE reply + one budget-capped like (budget ON);
* a direct address in the burst is always answered (INV-1);
* with the budget OFF every message in the burst is replied to (byte-identical regression).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pytest_bdd import given, scenarios, then, when

from tests.acceptance.series_budget_harness import (
    SeriesObservations,
    drive_ambient_burst,
    drive_burst_with_a_direct_address,
)

scenarios("../features/series_budget_wiring.feature")


@dataclass(slots=True)
class _Ctx:
    """The mutable slate the series-budget scenario's steps share."""

    enabled: bool = True
    observations: SeriesObservations = field(default_factory=SeriesObservations)


@given("бюджет действий на серию включён", target_fixture="series_ctx")
def budget_on() -> _Ctx:
    return _Ctx(enabled=True)


@given("бюджет действий на серию ВЫКЛючен", target_fixture="series_ctx")
def budget_off() -> _Ctx:
    return _Ctx(enabled=False)


@when("в окно падает всплеск из трёх реплик в воздух")
def ambient_burst(series_ctx: _Ctx) -> None:
    series_ctx.observations = asyncio.run(drive_ambient_burst(enabled=series_ctx.enabled))


@when("во всплеск вклинивается прямое обращение к Бобу")
def burst_with_address(series_ctx: _Ctx) -> None:
    series_ctx.observations = asyncio.run(
        drive_burst_with_a_direct_address(enabled=series_ctx.enabled)
    )


@then("Боб отвечает ровно один раз")
def replies_once(series_ctx: _Ctx) -> None:
    assert series_ctx.observations.reply_count == 1, (
        f"ожидался один ответ, было {series_ctx.observations.reply_count}"
    )


@then("Боб ставит не больше одного лайка на серию")
def at_most_one_like(series_ctx: _Ctx) -> None:
    assert series_ctx.observations.like_count <= 1, (
        f"лайков больше одного: {series_ctx.observations.like_count}"
    )


@then("Боб отвечает на прямое обращение")
def answers_the_address(series_ctx: _Ctx) -> None:
    # message_id 2 is the direct address in the harness burst.
    assert 2 in series_ctx.observations.replies, "прямое обращение осталось без ответа"


@then("Боб отвечает на каждую из трёх реплик")
def replies_to_each(series_ctx: _Ctx) -> None:
    assert series_ctx.observations.reply_count == 3, (
        f"ожидалось три ответа (регресс), было {series_ctx.observations.reply_count}"
    )
