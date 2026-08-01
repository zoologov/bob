# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``recent_commits`` — read-only repo-wide git history (BOB-081.2).

A thin wrapper over :meth:`RepoIntrospector.recent_commits` (the ``git log
--oneline -n N`` form, bounded + sanitised in the .1 port). It exposes the stable
:class:`Capability` contract, resolves the OPTIONAL ``count`` to a bounded int via
the pure domain clamp, delegates, and gives an honest message on empty output.
Deterministic on a fake port — the subprocess lives behind the port, never here.
"""

from __future__ import annotations

from collections.abc import Mapping

from bob.capabilities.introspection.dev_query import clamp_commit_count
from bob.capabilities.usecases.recent_commits import make_recent_commits_capability

from .fakes import FakeRepoIntrospector


def test_capability_advertises_the_recent_commits_contract() -> None:
    cap = make_recent_commits_capability(FakeRepoIntrospector())

    assert cap.name == "recent_commits"
    # The description must push the model to CALL the tool and report REAL commits.
    low = cap.description.lower()
    assert "реальн" in low
    assert "коммит" in low
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["count"] == {"type": "integer"}
    # ``count`` is OPTIONAL — no "required" entry forces it.
    assert "required" not in schema or schema["required"] == []


async def test_execute_delegates_bounded_count_to_port() -> None:
    introspector = FakeRepoIntrospector(commits="abc123 [BOB-081] feat: x")
    cap = make_recent_commits_capability(introspector)

    result = await cap.execute({"count": 5})

    assert introspector.recent_commits_calls == [5]
    assert isinstance(result, Mapping)
    assert result["commits"] == "abc123 [BOB-081] feat: x"


async def test_execute_without_count_uses_the_bounded_default() -> None:
    introspector = FakeRepoIntrospector(commits="x")
    cap = make_recent_commits_capability(introspector)

    await cap.execute({})

    assert introspector.recent_commits_calls == [clamp_commit_count(None)]


async def test_execute_ignores_a_non_integer_count() -> None:
    introspector = FakeRepoIntrospector(commits="x")
    cap = make_recent_commits_capability(introspector)

    await cap.execute({"count": "many"})

    # A non-int (or a bool) is treated as "unspecified" → the bounded default.
    assert introspector.recent_commits_calls == [clamp_commit_count(None)]


async def test_execute_with_empty_history_is_honest() -> None:
    introspector = FakeRepoIntrospector(commits="")
    cap = make_recent_commits_capability(introspector)

    result = await cap.execute({"count": 3})

    assert isinstance(result, Mapping)
    assert "не наш" in str(result["commits"]).lower()
