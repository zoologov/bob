# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``task_comments`` — read-only tracker comments/checkpoints (BOB-081.2).

A thin wrapper over :meth:`RepoIntrospector.task_comments` (``bd comments <id>``,
the id validated + sanitised in the .1 port). It exposes the stable
:class:`Capability` contract, delegates the required ``id``, gives an honest
message on empty output, and turns an id-shape :class:`ValueError` from the port
into a short honest message instead of crashing the turn. Deterministic on a fake.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from bob.capabilities.usecases.task_comments import make_task_comments_capability

from .fakes import FakeRepoIntrospector


def test_capability_advertises_the_task_comments_contract() -> None:
    cap = make_task_comments_capability(FakeRepoIntrospector())

    assert cap.name == "task_comments"
    low = cap.description.lower()
    assert "коммент" in low or "чекпоинт" in low
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["id"] == {"type": "string"}
    assert schema["required"] == ["id"]


async def test_execute_delegates_id_to_port() -> None:
    introspector = FakeRepoIntrospector(comments="CHECKPOINT: done")
    cap = make_task_comments_capability(introspector)

    result = await cap.execute({"id": "  BOB-076  "})

    assert introspector.task_comments_calls == ["BOB-076"]
    assert isinstance(result, Mapping)
    assert result["comments"] == "CHECKPOINT: done"


async def test_execute_requires_a_string_id() -> None:
    cap = make_task_comments_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="id"):
        await cap.execute({})


class _RaisingIntrospector(FakeRepoIntrospector):
    async def task_comments(self, bead_id: str) -> str:
        raise ValueError(f"not a valid bead id: {bead_id!r}")


async def test_execute_bad_id_yields_honest_message_not_crash() -> None:
    cap = make_task_comments_capability(_RaisingIntrospector())

    result = await cap.execute({"id": "; rm -rf"})

    assert isinstance(result, Mapping)
    assert "id" in str(result["comments"]).lower()


async def test_execute_with_empty_comments_is_honest() -> None:
    introspector = FakeRepoIntrospector(comments="")
    cap = make_task_comments_capability(introspector)

    result = await cap.execute({"id": "bob-0gj"})

    assert isinstance(result, Mapping)
    assert "не наш" in str(result["comments"]).lower()
