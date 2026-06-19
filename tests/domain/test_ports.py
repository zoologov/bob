# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for domain port protocols (contracts, no implementations)."""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import get_type_hints, runtime_checkable

import pytest

from bob.domain import ports


@pytest.mark.parametrize(
    "name",
    ["Clock", "EventBus", "LLMProvider", "MemoryRepo", "MemoryRecall"],
)
def test_port_is_exported_protocol(name: str) -> None:
    # Arrange / Act
    port = getattr(ports, name)

    # Assert: every port is a typing.Protocol class.
    assert getattr(port, "_is_protocol", False) is True


def test_clock_is_runtime_checkable_and_structural() -> None:
    # Arrange
    class SystemClock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    # Act / Assert: Clock is structurally satisfiable (runtime_checkable).
    assert ports.Clock is runtime_checkable(ports.Clock)
    assert isinstance(SystemClock(), ports.Clock)


def test_clock_now_returns_datetime_annotation() -> None:
    # Assert the Clock.now contract returns a datetime.
    hints = get_type_hints(ports.Clock.now)
    assert hints["return"] is datetime


def test_event_bus_declares_publish_and_subscribe() -> None:
    # Assert EventBus port exposes publish + subscribe.
    members = dict(inspect.getmembers(ports.EventBus))
    assert "publish" in members
    assert "subscribe" in members


def test_llm_provider_declares_complete() -> None:
    assert hasattr(ports.LLMProvider, "complete")


def test_memory_repo_declares_persistence_methods() -> None:
    assert hasattr(ports.MemoryRepo, "save_episode")
    assert hasattr(ports.MemoryRepo, "load_episodes")


def test_memory_recall_declares_recall() -> None:
    assert hasattr(ports.MemoryRecall, "recall")


def _imported_modules(module_source: str) -> set[str]:
    tree = ast.parse(module_source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_domain_imports_nothing_outward() -> None:
    # Architecture guard: the domain layer must not import application/infrastructure.
    source = Path(inspect.getfile(ports)).read_text(encoding="utf-8")
    imported = _imported_modules(source)
    outward = [
        name for name in imported if name.startswith(("bob.application", "bob.infrastructure"))
    ]
    assert outward == []
