# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``list_tasks`` — read-only tracker listing by status (BOB-081.2).

A thin wrapper over :meth:`RepoIntrospector.tasks_by_status` (``bd list
[--status <enum>]``, normalised + sanitised in the .1 port). It exposes the stable
:class:`Capability` contract, forwards the OPTIONAL ``status`` (the port maps an
unknown/absent value to the unfiltered list), and gives an honest message on empty
output. Distinct from ``list_work`` (a free-text query): ``list_tasks`` is the
by-status view. Deterministic on a fake port.
"""

from __future__ import annotations

from collections.abc import Mapping

from bob.capabilities.usecases.list_tasks import make_list_tasks_capability

from .fakes import FakeRepoIntrospector


def test_capability_advertises_the_list_tasks_contract() -> None:
    cap = make_list_tasks_capability(FakeRepoIntrospector())

    assert cap.name == "list_tasks"
    low = cap.description.lower()
    assert "реальн" in low
    assert "задач" in low
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    status = properties["status"]
    assert isinstance(status, dict)
    assert status["type"] == "string"
    assert status["enum"] == ["open", "in_progress", "blocked", "deferred", "closed"]
    # ``status`` is OPTIONAL.
    assert "required" not in schema or schema["required"] == []


async def test_execute_forwards_status_to_port() -> None:
    introspector = FakeRepoIntrospector(tasks_by_status_text="bob-1 open")
    cap = make_list_tasks_capability(introspector)

    result = await cap.execute({"status": "open"})

    assert introspector.tasks_by_status_calls == ["open"]
    assert isinstance(result, Mapping)
    assert result["tasks"] == "bob-1 open"


async def test_execute_without_status_lists_unfiltered() -> None:
    introspector = FakeRepoIntrospector(tasks_by_status_text="all")
    cap = make_list_tasks_capability(introspector)

    await cap.execute({})

    # No status → None forwarded (the port yields the unfiltered list).
    assert introspector.tasks_by_status_calls == [None]


async def test_execute_ignores_a_non_string_status() -> None:
    introspector = FakeRepoIntrospector(tasks_by_status_text="all")
    cap = make_list_tasks_capability(introspector)

    await cap.execute({"status": 7})

    assert introspector.tasks_by_status_calls == [None]


async def test_execute_with_empty_result_is_honest() -> None:
    introspector = FakeRepoIntrospector(tasks_by_status_text="")
    cap = make_list_tasks_capability(introspector)

    result = await cap.execute({"status": "closed"})

    assert isinstance(result, Mapping)
    assert "не наш" in str(result["tasks"]).lower()
