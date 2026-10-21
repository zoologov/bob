# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Расписание дорожек heartbeat под гейтом здоровья LLM (BOB-116 D10, RFC «Гейт дорожек»).

Проверяется поведение собранного расписания: каждую фоновую задачу из ``_background_tasks``
запускают на одну итерацию и смотрят, ПОЗВАЛИ ли её тик. Читатель здоровья — фейк порта
:class:`~bob.kernel.ports.HealthReader`: он говорит «Tier-0 лежит» и «зонд (не) пора».

Матрица RFC: ``inner_monologue`` — зонд (идёт, когда зонд пора); ``reflect``, ``proactive``,
``pursue_goals`` — под гейтом без зонда (молчат, пока провайдер лежит); ``poll`` и
``mood_drift`` гейта не знают.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from bob.application.router.health_monitor import TIER0_PRIMARY
from bob.kernel.ports import HealthView
from bob.kernel.provider_health import HealthState
from bob.runtime.wiring import _background_tasks

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.usecases.heartbeat import (
        InnerMonologueTick,
        MoodDriftTick,
        ReflectTick,
    )
    from bob.infrastructure.telegram.multibot import MultiBotGateway
    from bob.kernel.ports import HealthReader
    from bob.proactivity.usecases import ProactiveTick
    from bob.proactivity.usecases.pursue_goals import PursueGoalsTick

_LANES = ("poll", "inner_monologue", "mood_drift", "reflect", "proactive", "pursue_goals")


class _Reader:
    """HealthReader, у которого Tier-0 лежит или здоров, а зонд пора или нет."""

    def __init__(self, *, degraded: bool, probe_due: bool) -> None:
        self._degraded = degraded
        self._probe_due = probe_due
        self.asked: list[str] = []

    def snapshot(self) -> Mapping[str, HealthView]:
        state = HealthState.DEGRADED if self._degraded else HealthState.HEALTHY
        return {
            TIER0_PRIMARY: HealthView(
                state=state, consecutive_failures=0, failure_class=None, failing_since=None
            )
        }

    def is_degraded(self, provider_id: str) -> bool:
        self.asked.append(provider_id)
        return self._degraded

    def probe_due(self, provider_id: str) -> bool:
        self.asked.append(provider_id)
        return self._probe_due


class _Lane:
    """Тик, который запоминает, что его позвали."""

    def __init__(self, name: str, called: set[str]) -> None:
        self._name = name
        self._called = called

    async def run(self) -> None:
        self._called.add(self._name)


class _Multibot:
    def __init__(self, called: set[str]) -> None:
        self._called = called

    async def poll_once(self) -> None:
        self._called.add("poll")


async def _one_iteration(reader: HealthReader | None) -> set[str]:
    """Собрать расписание, дать каждой задаче один круг и вернуть, чьи тики позвали."""
    called: set[str] = set()
    tasks = _background_tasks(
        {"runtime": {"heartbeat_seconds": 30}, "goals": {"tick_seconds": 60}},
        multibot=cast("MultiBotGateway", _Multibot(called)),
        inner_monologue_tick=cast("InnerMonologueTick", _Lane("inner_monologue", called)),
        mood_drift_tick=cast("MoodDriftTick", _Lane("mood_drift", called)),
        reflect_tick=cast("ReflectTick", _Lane("reflect", called)),
        proactive_tick=cast("ProactiveTick", _Lane("proactive", called)),
        pursue_goals_tick=cast("PursueGoalsTick", _Lane("pursue_goals", called)),
        health=reader,
    )
    running = [asyncio.create_task(task()) for task in tasks]
    for _ in range(10):
        await asyncio.sleep(0)
    for task in running:
        task.cancel()
    await asyncio.gather(*running, return_exceptions=True)
    return called


async def test_without_a_reader_every_lane_runs() -> None:
    """Сборка без монитора — расписание как до BOB-116."""
    assert await _one_iteration(None) == set(_LANES)


async def test_healthy_provider_lets_every_lane_run() -> None:
    assert await _one_iteration(_Reader(degraded=False, probe_due=True)) == set(_LANES)


async def test_degraded_provider_without_a_due_probe_silences_the_llm_lanes() -> None:
    """Tier-0 лежит, зонд не пора: тики LLM-дорожек не зовутся; poll и mood_drift идут."""
    called = await _one_iteration(_Reader(degraded=True, probe_due=False))

    assert called == {"poll", "mood_drift"}


async def test_due_probe_runs_only_the_inner_monologue() -> None:
    """Зонд пора: идёт ровно дорожка монолога; reflect/proactive/pursue_goals ждут."""
    called = await _one_iteration(_Reader(degraded=True, probe_due=True))

    assert called == {"poll", "mood_drift", "inner_monologue"}


async def test_lanes_are_gated_on_the_tier0_primary() -> None:
    """Гейт спрашивает о том id, под которым роутер и обёртка докладывают Tier-0."""
    reader = _Reader(degraded=True, probe_due=True)

    await _one_iteration(reader)

    assert set(reader.asked) == {TIER0_PRIMARY}
