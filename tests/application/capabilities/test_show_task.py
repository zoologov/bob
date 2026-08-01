# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``show_task`` — read-only details of one tracker task (BOB-081.2).

A thin wrapper over :meth:`RepoIntrospector.show_task` (``bd show <id>``, the id
validated + sanitised in the .1 port). It exposes the stable :class:`Capability`
contract, delegates the required ``id``, gives an honest message on empty output,
and — crucially — turns an id-shape :class:`ValueError` from the port into a short
honest message instead of crashing the turn. Deterministic on a fake port.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from bob.capabilities.usecases.show_task import make_show_task_capability

from .fakes import FakeRepoIntrospector


def test_capability_advertises_the_show_task_contract() -> None:
    cap = make_show_task_capability(FakeRepoIntrospector())

    assert cap.name == "show_task"
    assert "задач" in cap.description.lower()
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["id"] == {"type": "string"}
    assert schema["required"] == ["id"]


async def test_execute_delegates_id_to_port() -> None:
    introspector = FakeRepoIntrospector(task_detail="bob-0gj: title")
    cap = make_show_task_capability(introspector)

    result = await cap.execute({"id": "  bob-0gj  "})

    assert introspector.show_task_calls == ["bob-0gj"]
    assert isinstance(result, Mapping)
    assert result["task"] == "bob-0gj: title"


async def test_execute_requires_a_string_id() -> None:
    cap = make_show_task_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="id"):
        await cap.execute({"id": None})


class _RaisingIntrospector(FakeRepoIntrospector):
    async def show_task(self, bead_id: str) -> str:
        raise ValueError(f"not a valid bead id: {bead_id!r}")


async def test_execute_bad_id_yields_honest_message_not_crash() -> None:
    cap = make_show_task_capability(_RaisingIntrospector())

    result = await cap.execute({"id": "--force"})

    assert isinstance(result, Mapping)
    assert "id" in str(result["task"]).lower()


async def test_execute_with_empty_details_is_honest() -> None:
    introspector = FakeRepoIntrospector(task_detail="")
    cap = make_show_task_capability(introspector)

    result = await cap.execute({"id": "bob-0gj"})

    assert isinstance(result, Mapping)
    assert "не наш" in str(result["task"]).lower()
