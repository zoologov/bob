# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tier-1 на основном пути ответа докладывает здоровье (BOB-116 F1, ревью M1).

Ход владельца идёт через :class:`~bob.capabilities.usecases.tool_loop.ToolLoop`. ToolLoop
получает провайдера Tier-1 из сборки (:func:`~bob.runtime.wiring.access._as_tool_provider`)
и зовёт провайдера напрямую, мимо роутера. До F1 этот вызов не докладывал ничего: 403 на ответе
человеку монитор не видел, владелец не получал сигнала, ``/status`` говорил «tier1 — ок».

Проверяется на НАСТОЯЩИХ loopback-эндпоинтах харнесса
``tests/acceptance/tier0_fallback_harness.py`` и настоящей фабрике
:func:`~bob.infrastructure.llm.factory.build_tier_providers`: ToolLoop и роутер получают
провайдеров ровно так, как их получает ``build_application``. Утверждается то, что видно
снаружи: сколько запросов увидел эндпоинт Tier-1 — столько записей получил монитор (ни потерянной,
ни двойной), сигнал владельцу и строка ``/status``.
"""

from __future__ import annotations

import contextlib
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.application.router import LLMRequest, LLMRouter, TaskType
from bob.application.router.health_monitor import ProviderHealthMonitor
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.infrastructure.llm.factory import build_tier_providers
from bob.infrastructure.telegram.health_status import render_health_status
from bob.kernel.provider_health import TIER0_PRIMARY, TIER1, HealthPolicy
from bob.runtime.wiring.access import _as_tool_provider
from tests.acceptance.tier0_fallback_harness import (
    ANSWERS,
    FORBIDDEN,
    SERVER_ERROR,
    LoopbackEndpoint,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from bob.capabilities.ports import Permission
    from bob.kernel.ports import HealthObserver, ToolCallingProvider

_OWNER_TURN = [{"role": "user", "content": "Боб, что нового?"}]
_NOW = datetime(2026, 10, 1, 6, 10, tzinfo=UTC)


class _CountingObserver:
    """Считает записи по id провайдера — их сверяют по числу HTTP-вызовов."""

    def __init__(self) -> None:
        self.records: Counter[str] = Counter()

    async def record_success(self, provider_id: str) -> None:
        self.records[provider_id] += 1

    async def record_failure(self, provider_id: str, failure_class: str) -> None:
        del failure_class  # здесь важен только факт записи
        self.records[provider_id] += 1


class _Clock:
    def now(self) -> datetime:
        return _NOW


class _OwnerInbox:
    """Личка владельца: что монитор ему сказал."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def notify_owner(self, text: str) -> None:
        self.texts.append(text)


class _RecallCapability:
    """Одна способность в реестре — чтобы ход владельца шёл через инструменты, как в проде."""

    name = "recall_memory"
    description = "Search memory."
    input_schema: Mapping[str, object] = {"type": "object", "properties": {}}
    permission: Permission = "safe"

    async def execute(self, args: Mapping[str, object]) -> object:  # noqa: ARG002
        return "ничего"


class _Stack:
    """Провайдеры из настоящей фабрики, роутер и ToolLoop — как их собирает сборка."""

    def __init__(self, *, cloud: LoopbackEndpoint, tier1: LoopbackEndpoint) -> None:
        self.cloud = cloud
        self.tier1 = tier1

    def build(self, health: HealthObserver) -> tuple[LLMRouter, ToolLoop]:
        config = {
            "llm": {
                "tier0_base_url": self.cloud.base_url,
                "tier0_model": "cloud-tier0",
                "tier1_base_url": self.tier1.base_url,
                "tier1_model": "cloud-tier1",
                "timeout_seconds": 5.0,
            }
        }
        providers = build_tier_providers(config, health=health)
        router = LLMRouter(providers=providers, health=health)
        tool_provider: ToolCallingProvider | None = _as_tool_provider(providers)
        assert tool_provider is not None  # Tier-1 умеет инструменты — ToolLoop жив
        registry = CapabilityRegistry()
        registry.register(_RecallCapability())
        return router, ToolLoop(provider=tool_provider, registry=registry)


@contextlib.asynccontextmanager
async def _stack(tier1_behaviour: str) -> AsyncIterator[_Stack]:
    cloud = LoopbackEndpoint(behaviour=ANSWERS, reply="Отвечаю из облачного Tier-0.")
    tier1 = LoopbackEndpoint(behaviour=tier1_behaviour, reply="Отвечаю из Tier-1.")
    for endpoint in (cloud, tier1):
        await endpoint.start()
    try:
        yield _Stack(cloud=cloud, tier1=tier1)
    finally:
        for endpoint in (cloud, tier1):
            await endpoint.stop()


@pytest.fixture
async def forbidden_tier1() -> AsyncIterator[_Stack]:
    async with _stack(FORBIDDEN) as stack:
        yield stack


@pytest.fixture
async def answering_tier1() -> AsyncIterator[_Stack]:
    async with _stack(ANSWERS) as stack:
        yield stack


@pytest.fixture
async def failing_tier1() -> AsyncIterator[_Stack]:
    async with _stack(SERVER_ERROR) as stack:
        yield stack


async def _owner_turn_fails(loop: ToolLoop) -> None:
    with pytest.raises(Exception, match="403"):
        await loop.run(_OWNER_TURN)


async def test_tool_loop_403_on_tier1_is_recorded_once_per_http_call(
    forbidden_tier1: _Stack,
) -> None:
    observer = _CountingObserver()
    router, loop = forbidden_tier1.build(observer)

    await _owner_turn_fails(loop)
    # И та же основная модель через роутер: Tier-1 падает, Tier-0 спасает.
    reply = await router.run(LLMRequest(task_type=TaskType.ROOM_READ, messages=_OWNER_TURN))

    assert reply == "Отвечаю из облачного Tier-0."
    assert forbidden_tier1.tier1.calls == 2  # прогон не вакуумный: каждый путь дошёл до HTTP
    assert observer.records[TIER1] == forbidden_tier1.tier1.calls
    assert observer.records[TIER0_PRIMARY] == forbidden_tier1.cloud.calls == 1


async def test_tool_loop_success_on_tier1_is_recorded(answering_tier1: _Stack) -> None:
    observer = _CountingObserver()
    _, loop = answering_tier1.build(observer)

    assert await loop.run(_OWNER_TURN) == "Отвечаю из Tier-1."

    assert answering_tier1.tier1.calls == 1
    assert observer.records == Counter({TIER1: 1})


async def test_tool_loop_server_error_on_tier1_is_recorded_as_server(
    failing_tier1: _Stack,
) -> None:
    monitor = ProviderHealthMonitor(clock=_Clock(), policy=HealthPolicy(), sink=_OwnerInbox())
    _, loop = failing_tier1.build(monitor)

    with pytest.raises(Exception, match="503"):
        await loop.run(_OWNER_TURN)

    view = monitor.snapshot()[TIER1]
    assert (view.consecutive_failures, view.failure_class) == (1, "server")


async def test_repeated_403_on_the_owner_turn_reaches_the_owner_and_status(
    forbidden_tier1: _Stack,
) -> None:
    inbox = _OwnerInbox()
    monitor = ProviderHealthMonitor(clock=_Clock(), policy=HealthPolicy(), sink=inbox)
    _, loop = forbidden_tier1.build(monitor)
    threshold = HealthPolicy().failures_threshold

    for _ in range(threshold - 1):
        await _owner_turn_fails(loop)
    assert inbox.texts == []  # до порога — тишина: одиночный отказ не диагноз
    await _owner_turn_fails(loop)

    assert forbidden_tier1.tier1.calls == threshold
    assert len(inbox.texts) == 1, inbox.texts
    assert "основная модель отказывает мне в доступе" in inbox.texts[0].lower()
    status = render_health_status(monitor.snapshot(), tz=UTC)
    tier1_line = next(line for line in status.splitlines() if line.startswith("tier1 — "))
    assert tier1_line.startswith("tier1 — деградирован с "), status  # noqa: RUF001 — русский предлог
    assert tier1_line.endswith(f"(не пускало по ключу/квоте, {threshold} подряд)"), status
