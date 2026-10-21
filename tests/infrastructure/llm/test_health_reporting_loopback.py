# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Один HTTP-вызов — одна запись монитора здоровья (BOB-116 D3, риск RFC «двойной учёт»).

Исходы докладывают ДВА места — роутер и дублёр-обёртка. Если оба доложат один вызов,
порог деградации (5 отказов) наступит за 2–3 настоящих отказа и владельца разбудят зря; если
не доложит никто — простой, который видит только голос Боба, останется невидим. Проверяется
на НАСТОЯЩИХ loopback-эндпоинтах харнесса ``tests/acceptance/tier0_fallback_harness.py``
(реальный роутер, реальная фабрика, реальный ``ConfigLoader``): сколько запросов увидел
каждый эндпоинт, столько записей монитор получил под его id.

Харнесс не правится — в его модуле подменяются ровно два имени, через которые он собирает
роутер и провайдеры, чтобы в обе точки доклада пришёл один и тот же счётчик.
"""

from __future__ import annotations

from collections import Counter
from functools import partial
from typing import TYPE_CHECKING

import pytest

from bob.application.router import LLMRouter, TaskType
from bob.application.router.health_monitor import TIER0_PRIMARY, TIER0_UNDERSTUDY, TIER1
from bob.infrastructure.llm.factory import build_tier_providers
from tests.acceptance import tier0_fallback_harness as harness
from tests.acceptance.tier0_fallback_harness import (
    ANSWERS,
    BAD_REQUEST,
    BROKEN_SHAPE,
    DISCONNECTS,
    FORBIDDEN,
    HANGS,
    SERVER_ERROR,
    UNAUTHORIZED,
    TurnRequest,
    run_turn,
)

if TYPE_CHECKING:
    from bob.infrastructure.config.loader import Config
    from bob.kernel.ports import LLMProvider


class _CountingObserver:
    """Считает записи по id провайдера — то, что сравнивается с числом HTTP-вызовов."""

    def __init__(self) -> None:
        self.records: Counter[str] = Counter()

    async def record_success(self, provider_id: str) -> None:
        self.records[provider_id] += 1

    async def record_failure(self, provider_id: str, failure_class: str) -> None:
        del failure_class  # здесь важен только факт записи
        self.records[provider_id] += 1


_CASES = [
    # служебная дверь Tier-0 через обёртку
    TurnRequest(cloud_tier0=ANSWERS),
    TurnRequest(cloud_tier0=FORBIDDEN, local=ANSWERS),
    TurnRequest(cloud_tier0=UNAUTHORIZED, local=SERVER_ERROR),
    TurnRequest(cloud_tier0=SERVER_ERROR, local=SERVER_ERROR),
    TurnRequest(cloud_tier0=BAD_REQUEST),
    TurnRequest(cloud_tier0=BROKEN_SHAPE, local=ANSWERS),
    TurnRequest(cloud_tier0=HANGS, local=ANSWERS),
    TurnRequest(cloud_tier0=DISCONNECTS, local=ANSWERS),
    # голос Боба на Tier-0 — мимо обёртки к «голому» облаку, эскалация наверх
    TurnRequest(cloud_tier0=FORBIDDEN, task_type=TaskType.REPLY_TO_USER, tier_override=0),
    TurnRequest(
        cloud_tier0=SERVER_ERROR,
        tier1=SERVER_ERROR,
        task_type=TaskType.REPLY_TO_USER,
        tier_override=0,
    ),
    # Tier-1 и его спуск на Tier-0
    TurnRequest(task_type=TaskType.ROOM_READ),
    TurnRequest(tier1=FORBIDDEN, cloud_tier0=FORBIDDEN, task_type=TaskType.ROOM_READ),
    TurnRequest(tier1=SERVER_ERROR, task_type=TaskType.REPLY_TO_USER),
    TurnRequest(tier1=BAD_REQUEST, task_type=TaskType.ROOM_READ),
    # дублёр выключен — Tier-0 докладывает роутер
    TurnRequest(cloud_tier0=FORBIDDEN, fallback_on=False),
    TurnRequest(cloud_tier0=ANSWERS, fallback_on=False),
]


def _case_id(case: TurnRequest) -> str:
    return (
        f"{case.task_type.value}-t0:{case.cloud_tier0}-local:{case.local}-t1:{case.tier1}"
        f"-fallback:{case.fallback_on}-override:{case.tier_override}"
    )


@pytest.mark.parametrize("case", _CASES, ids=_case_id)
async def test_every_http_call_is_recorded_exactly_once(
    case: TurnRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = _CountingObserver()

    def _providers(config: Config) -> dict[int, LLMProvider]:
        return build_tier_providers(config, health=observer)

    monkeypatch.setattr(harness, "build_tier_providers", _providers)
    monkeypatch.setattr(harness, "LLMRouter", partial(LLMRouter, health=observer))

    outcome = await run_turn(case)

    seen_by_endpoints = {
        TIER0_PRIMARY: outcome.cloud_tier0_calls,
        TIER0_UNDERSTUDY: outcome.local_calls,
        TIER1: outcome.tier1_calls,
    }
    assert sum(seen_by_endpoints.values()) > 0  # прогон не вакуумный: вызовы были
    assert {pid: observer.records[pid] for pid in seen_by_endpoints} == seen_by_endpoints
    assert set(observer.records) <= set(seen_by_endpoints)
