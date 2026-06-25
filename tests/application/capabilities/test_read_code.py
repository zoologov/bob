# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``read_code`` — read-only repo search + file read (BOB-017 .2).

A thin wrapper over :meth:`RepoIntrospector.search_code` and
:meth:`RepoIntrospector.read_file` (privacy-guarded in .1). A plain ``query``
searches the repo/graph; a ``path``-shaped argument reads that file. It exposes
the stable :class:`Capability` contract, delegates to the port, renders a compact
result and gives an honest "not found" (US-5) on empty output. Deterministic on a
fake port — the guard/subprocess live behind the port, never exercised here.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from bob.application.capabilities.read_code import make_read_code_capability

from .fakes import FakeRepoIntrospector


def test_capability_advertises_the_read_code_contract() -> None:
    cap = make_read_code_capability(FakeRepoIntrospector())

    assert cap.name == "read_code"
    assert cap.description
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["query"] == {"type": "string"}
    assert schema["required"] == ["query"]


async def test_execute_searches_when_query_is_not_a_path() -> None:
    introspector = FakeRepoIntrospector(search="src/bob/app.py: build_application")
    cap = make_read_code_capability(introspector)

    result = await cap.execute({"query": "build_application"})

    assert introspector.search_calls == ["build_application"]
    assert introspector.read_calls == []
    assert isinstance(result, Mapping)
    assert result["matches"] == "src/bob/app.py: build_application"


async def test_execute_reads_file_when_query_is_a_repo_path() -> None:
    introspector = FakeRepoIntrospector(file_text="line one\nline two")
    cap = make_read_code_capability(introspector)

    result = await cap.execute({"query": "src/bob/app.py"})

    assert introspector.read_calls == [("src/bob/app.py", 200)]
    assert introspector.search_calls == []
    assert isinstance(result, Mapping)
    assert result["matches"] == "line one\nline two"


async def test_execute_with_empty_search_is_honest_not_found() -> None:
    introspector = FakeRepoIntrospector(search="")
    cap = make_read_code_capability(introspector)

    result = await cap.execute({"query": "missing-symbol"})

    assert isinstance(result, Mapping)
    assert "не нашёл" in str(result["matches"]).lower()


async def test_execute_requires_a_string_query() -> None:
    cap = make_read_code_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="query"):
        await cap.execute({"query": None})
