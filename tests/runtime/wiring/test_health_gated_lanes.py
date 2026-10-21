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

BOB-116 F2 (ревью M2): гейт закрывается, только когда Tier-0 думать НЕЧЕМ — облако лежит и
дублёра нет, он снят при старте или лежит тоже. Пока дублёр держит, рефлексия, проактивность
и цели идут в обычном ритме (PRD US-2), а зонд по-прежнему идёт к облаку. Вторая половина
файла держит это на НАСТОЯЩЕМ мониторе: сначала матрица исходов, затем настоящая обёртка
дублёра над loopback-эндпоинтами (П.0.3 п.4).
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from bob.application.router import LLMRequest, LLMRouter, TaskType
from bob.application.router.health_monitor import (
    TIER0_EFFECTIVE,
    TIER0_PRIMARY,
    TIER0_UNDERSTUDY,
    ProviderHealthMonitor,
)
from bob.infrastructure.config.loader import ConfigLoader
from bob.infrastructure.llm.factory import build_tier_providers
from bob.kernel.ports import HealthView
from bob.kernel.provider_health import HealthPolicy, HealthState
from bob.runtime.wiring import _background_tasks
from tests.acceptance.tier0_fallback_harness import (
    ANSWERS,
    CLOUD_REPLY,
    FORBIDDEN,
    LOCAL_REPLY,
    TIER1_REPLY,
    LoopbackEndpoint,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

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
        self.asked: list[tuple[str, str]] = []

    def snapshot(self) -> Mapping[str, HealthView]:
        state = HealthState.DEGRADED if self._degraded else HealthState.HEALTHY
        return {
            TIER0_PRIMARY: HealthView(
                state=state, consecutive_failures=0, failure_class=None, failing_since=None
            )
        }

    def is_degraded(self, provider_id: str) -> bool:
        self.asked.append(("is_degraded", provider_id))
        return self._degraded

    def probe_due(self, provider_id: str) -> bool:
        self.asked.append(("probe_due", provider_id))
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


async def test_lanes_close_on_the_whole_tier0_and_probe_the_cloud() -> None:
    """Гейт спрашивает о Tier-0 целиком, зонд — о облаке, под которым докладывается вызов."""
    reader = _Reader(degraded=True, probe_due=True)

    await _one_iteration(reader)

    assert {pid for method, pid in reader.asked if method == "is_degraded"} == {TIER0_EFFECTIVE}
    assert {pid for method, pid in reader.asked if method == "probe_due"} == {TIER0_PRIMARY}


# --- настоящий монитор: матрица исходов ------------------------------------------------
# Исходы докладываются так, как их докладывают роутер и обёртка дублёра; расписание —
# настоящее ``_background_tasks``. Наблюдаемое — какие тики позвали.

_THRESHOLD = 5
_ALL_LANES = set(_LANES)
_CLOSED = {"poll", "mood_drift"}
_CLOSED_WITH_PROBE = {"poll", "mood_drift", "inner_monologue"}


class _Clock:
    def __init__(self) -> None:
        self.moment = datetime(2026, 10, 1, 6, 10, tzinfo=UTC)

    def now(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += timedelta(seconds=seconds)


class _OwnerSink:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def notify_owner(self, text: str) -> None:
        self.texts.append(text)


def _monitor(*, has_understudy: bool) -> tuple[ProviderHealthMonitor, _Clock, _OwnerSink]:
    clock, sink = _Clock(), _OwnerSink()
    monitor = ProviderHealthMonitor(
        clock=clock, policy=HealthPolicy(), sink=sink, has_understudy=has_understudy
    )
    return monitor, clock, sink


async def _dies(monitor: ProviderHealthMonitor, clock: _Clock, provider_id: str) -> None:
    for _ in range(_THRESHOLD):
        await monitor.record_failure(provider_id, "auth")
        clock.advance(30)


async def test_real_monitor_understudy_holding_keeps_every_lane_running() -> None:
    monitor, clock, sink = _monitor(has_understudy=True)
    await _dies(monitor, clock, TIER0_PRIMARY)

    assert monitor.is_degraded(TIER0_PRIMARY)
    assert "держусь на дублёре" in sink.texts[0]
    assert await _one_iteration(monitor) == _ALL_LANES


async def test_real_monitor_both_floors_down_close_the_gate_and_probe_when_due() -> None:
    monitor, clock, _ = _monitor(has_understudy=True)
    await _dies(monitor, clock, TIER0_PRIMARY)
    await _dies(monitor, clock, TIER0_UNDERSTUDY)

    assert await _one_iteration(monitor) == _CLOSED_WITH_PROBE
    await monitor.record_failure(TIER0_PRIMARY, "auth")  # the probe went and failed
    assert await _one_iteration(monitor) == _CLOSED


async def test_real_monitor_dead_cloud_without_an_understudy_closes_the_gate() -> None:
    monitor, clock, _ = _monitor(has_understudy=False)
    await _dies(monitor, clock, TIER0_PRIMARY)
    await monitor.record_failure(TIER0_PRIMARY, "auth")

    assert await _one_iteration(monitor) == _CLOSED


async def test_real_monitor_dead_cloud_after_the_stand_down_closes_the_gate() -> None:
    monitor, clock, _ = _monitor(has_understudy=True)
    monitor.stand_down_understudy("модели qwen3:8b нет")
    await _dies(monitor, clock, TIER0_PRIMARY)
    await monitor.record_failure(TIER0_PRIMARY, "auth")

    assert await _one_iteration(monitor) == _CLOSED


async def test_real_monitor_dead_understudy_alone_keeps_every_lane_running() -> None:
    monitor, clock, _ = _monitor(has_understudy=True)
    await _dies(monitor, clock, TIER0_UNDERSTUDY)

    assert await _one_iteration(monitor) == _ALL_LANES


# --- настоящая обёртка дублёра над loopback ---------------------------------------------
# Облако отвечает 403, дублёр — как настроен. Тик монолога — настоящий вызов через роутер,
# поэтому исходы монитору докладывает сама обёртка; остальные дорожки считают свои тики.

_ROUND_SECONDS = 300
_ROUNDS = 20  # 100 минут — замер ревью M2: 0 из 20 тиков reflect на HEAD 5218e81


class _Monologue:
    """Тик монолога: один настоящий вызов Tier-0 через роутер."""

    def __init__(self, router: LLMRouter, log: list[str]) -> None:
        self._router = router
        self._log = log
        self.finished = 0

    async def run(self) -> None:
        self._log.append("inner_monologue")
        try:
            await self._router.run(
                LLMRequest(
                    task_type=TaskType.INNER_MONOLOGUE,
                    messages=[{"role": "user", "content": "о чём я думаю?"}],
                )
            )
        finally:
            self.finished += 1


class _Counted:
    def __init__(self, name: str, log: list[str]) -> None:
        self._name = name
        self._log = log

    async def run(self) -> None:
        self._log.append(self._name)


class _Stack:
    def __init__(self, *, understudy: str) -> None:
        self.cloud = LoopbackEndpoint(behaviour=FORBIDDEN, reply=CLOUD_REPLY)
        self.local = LoopbackEndpoint(behaviour=understudy, reply=LOCAL_REPLY)
        self.tier1 = LoopbackEndpoint(behaviour=ANSWERS, reply=TIER1_REPLY)
        self.clock, self.sink = _Clock(), _OwnerSink()
        self.monitor = ProviderHealthMonitor(
            clock=self.clock, policy=HealthPolicy(), sink=self.sink, has_understudy=True
        )
        self.log: list[str] = []
        self.router: LLMRouter

    async def start(self) -> None:
        for endpoint in (self.cloud, self.local, self.tier1):
            await endpoint.start()
        config = ConfigLoader(
            yaml_path=None,
            env={
                "BOB_LLM__TIER0_BASE_URL": self.cloud.base_url,
                "BOB_LLM__TIER0_MODEL": "cloud-tier0",
                "BOB_LLM__TIER1_BASE_URL": self.tier1.base_url,
                "BOB_LLM__TIER1_MODEL": "cloud-tier1",
                "BOB_LLM__TIMEOUT_SECONDS": "5.0",
                "BOB_LLM__TIER0_FALLBACK": "ollama",
                "BOB_LLM__TIER0_FALLBACK_BASE_URL": self.local.base_url,
                "BOB_LLM__TIER0_FALLBACK_MODEL": "local-understudy",
            },
        ).load()
        self.router = LLMRouter(
            providers=build_tier_providers(config, health=self.monitor), health=self.monitor
        )

    async def stop(self) -> None:
        for endpoint in (self.cloud, self.local, self.tier1):
            await endpoint.stop()

    def stand_down_understudy(self) -> None:
        """То, что делает startup при неготовом дублёре (D11): роутер и монитор вместе."""
        self.router.stand_down_tier0_understudy()
        self.monitor.stand_down_understudy("модели local-understudy нет")

    async def cloud_dies(self) -> None:
        """Пять настоящих 403 подряд, раз в 30 с — мимо гейта, как ответы людям."""
        for _ in range(_THRESHOLD):
            with contextlib.suppress(Exception):
                await _Monologue(self.router, []).run()
            self.clock.advance(30)

    async def one_round(self) -> list[str]:
        """Собрать расписание, дать каждой задаче один круг, вернуть, чьи тики позвали."""
        self.log.clear()
        monologue = _Monologue(self.router, self.log)
        tasks = _background_tasks(
            {"runtime": {"heartbeat_seconds": 30}, "goals": {"tick_seconds": 60}},
            multibot=cast("MultiBotGateway", _Multibot(set())),
            inner_monologue_tick=cast("InnerMonologueTick", monologue),
            mood_drift_tick=cast("MoodDriftTick", _Counted("mood_drift", self.log)),
            reflect_tick=cast("ReflectTick", _Counted("reflect", self.log)),
            proactive_tick=cast("ProactiveTick", _Counted("proactive", self.log)),
            pursue_goals_tick=cast("PursueGoalsTick", _Counted("pursue_goals", self.log)),
            health=self.monitor,
        )
        running = [asyncio.create_task(task()) for task in tasks]
        for _ in range(10):
            await asyncio.sleep(0)
        # Гейт решает синхронно; настоящий HTTP монолога — ждём, пока вызов вернётся.
        for _ in range(500):
            if monologue.finished or "inner_monologue" not in self.log:
                break
            await asyncio.sleep(0.01)
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        return list(self.log)


@contextlib.asynccontextmanager
async def _stack(*, understudy: str) -> AsyncIterator[_Stack]:
    stack = _Stack(understudy=understudy)
    await stack.start()
    try:
        yield stack
    finally:
        await stack.stop()


async def test_understudy_holding_a_dead_cloud_keeps_reflect_on_its_rhythm() -> None:
    """PRD US-2: 20 раундов по 5 минут, облако мертво, дублёр отвечает — reflect идёт 20 раз."""
    async with _stack(understudy=ANSWERS) as stack:
        await stack.cloud_dies()
        assert stack.monitor.is_degraded(TIER0_PRIMARY)
        assert "держусь на дублёре" in stack.sink.texts[0]
        cloud_before = stack.cloud.calls

        rounds = []
        for _ in range(_ROUNDS):
            stack.clock.advance(_ROUND_SECONDS)
            rounds.append(await stack.one_round())

    for lane in ("reflect", "proactive", "pursue_goals", "inner_monologue"):
        assert sum(r.count(lane) for r in rounds) == _ROUNDS, (lane, rounds)
    # Монолог каждый раунд идёт сначала в облако — вернувшееся облако будет замечено.
    assert stack.cloud.calls - cloud_before == _ROUNDS
    assert stack.local.calls >= _ROUNDS


async def test_cloud_returning_while_the_understudy_holds_is_seen_by_the_monologue() -> None:
    async with _stack(understudy=ANSWERS) as stack:
        await stack.cloud_dies()
        stack.cloud.behaviour = ANSWERS
        stack.clock.advance(_ROUND_SECONDS)
        await stack.one_round()

    assert not stack.monitor.is_degraded(TIER0_PRIMARY)
    assert "снова отвечает" in stack.sink.texts[-1]


async def test_both_floors_dead_close_the_gate_and_the_cloud_is_probed_on_schedule() -> None:
    """Облако и дублёр мертвы: 10 минут шагами по минуте — зонд на 1-й, 3-й и 8-й минуте."""
    async with _stack(understudy=FORBIDDEN) as stack:
        await stack.cloud_dies()
        assert stack.monitor.is_degraded(TIER0_EFFECTIVE)
        cloud_before = stack.cloud.calls

        rounds = []
        for _ in range(10):
            stack.clock.advance(60)
            rounds.append(await stack.one_round())

    probed = [minute for minute, r in enumerate(rounds, start=1) if "inner_monologue" in r]
    assert probed == [1, 3, 8], rounds
    assert stack.cloud.calls - cloud_before == 3
    for lane in ("reflect", "proactive", "pursue_goals"):
        assert all(lane not in r for r in rounds), (lane, rounds)


async def test_dead_cloud_after_the_understudy_was_stood_down_closes_the_gate() -> None:
    async with _stack(understudy=ANSWERS) as stack:
        stack.stand_down_understudy()
        await stack.cloud_dies()
        rounds = []
        for _ in range(3):
            stack.clock.advance(30)
            rounds.append(await stack.one_round())

    assert stack.local.calls == 0
    for lane in ("reflect", "proactive", "pursue_goals"):
        assert all(lane not in r for r in rounds), (lane, rounds)


@pytest.mark.parametrize("understudy", [ANSWERS, FORBIDDEN])
async def test_healthy_cloud_runs_every_lane_whatever_the_understudy(understudy: str) -> None:
    async with _stack(understudy=understudy) as stack:
        stack.cloud.behaviour = ANSWERS
        called = await stack.one_round()

    assert set(called) == {"inner_monologue", "mood_drift", "reflect", "proactive", "pursue_goals"}
