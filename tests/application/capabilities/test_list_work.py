# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``list_work`` — read-only tracker state (BOB-017 .2).

A thin wrapper over :meth:`RepoIntrospector.list_tasks` (``bd`` ready/show). It
exposes the stable :class:`Capability` contract, delegates a ``query`` to the
port, renders a compact result and gives an honest "not found" (US-5) on empty
output. Deterministic on a fake port — no subprocess.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from bob.application.capabilities.list_work import make_list_work_capability

from .fakes import FakeRepoIntrospector


def test_capability_advertises_the_list_work_contract() -> None:
    cap = make_list_work_capability(FakeRepoIntrospector())

    assert cap.name == "list_work"
    assert cap.description
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["query"] == {"type": "string"}
    assert schema["required"] == ["query"]


async def test_execute_delegates_query_to_port_and_renders_compactly() -> None:
    introspector = FakeRepoIntrospector(tasks="bob-9eh.2  in_progress")
    cap = make_list_work_capability(introspector)

    result = await cap.execute({"query": "bob-9eh.2"})

    assert introspector.task_calls == ["bob-9eh.2"]
    assert isinstance(result, Mapping)
    assert result["tasks"] == "bob-9eh.2  in_progress"


async def test_execute_with_empty_port_output_is_honest_not_found() -> None:
    introspector = FakeRepoIntrospector(tasks="")
    cap = make_list_work_capability(introspector)

    result = await cap.execute({"query": ""})

    assert introspector.task_calls == [""]
    assert isinstance(result, Mapping)
    assert "не нашёл" in str(result["tasks"]).lower()


async def test_execute_requires_a_string_query() -> None:
    cap = make_list_work_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="query"):
        await cap.execute({"query": 5})


async def test_execute_with_missing_query_key_raises() -> None:
    cap = make_list_work_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="query"):
        await cap.execute({})


async def test_execute_ready_queue_when_query_is_blank() -> None:
    # US-3: a whitespace-only query still grounds an answer (the port maps it to the
    # ready queue) and renders it compactly — not an honest-not-found shortcut here.
    introspector = FakeRepoIntrospector(tasks="bob-9eh.4  ready")
    cap = make_list_work_capability(introspector)

    result = await cap.execute({"query": "   "})

    assert introspector.task_calls == ["   "]
    assert isinstance(result, Mapping)
    assert result["tasks"] == "bob-9eh.4  ready"
