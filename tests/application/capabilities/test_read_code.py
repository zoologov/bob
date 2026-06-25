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
from bob.infrastructure.introspection.subprocess_introspector import DeniedPathError

from .fakes import FakeRepoIntrospector


class _DenyingIntrospector(FakeRepoIntrospector):
    """A port whose file read is refused by the privacy guard (raises DeniedPathError)."""

    async def read_file(self, path: str, *, max_lines: int) -> str:
        raise DeniedPathError(
            f"reading {path!r} (max_lines={max_lines}) is denied by the privacy guard"
        )


def test_capability_advertises_the_read_code_contract() -> None:
    cap = make_read_code_capability(FakeRepoIntrospector())

    assert cap.name == "read_code"
    assert cap.description
    # BOB-034: the model is told it can now read the roadmap / feature specs too.
    low = cap.description.lower()
    assert "roadmap" in low or "dev-docs" in low
    assert "feature" in low or "development/docs" in low
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


async def test_execute_with_missing_query_key_raises() -> None:
    # ``args.get('query')`` is None when the key is absent -> the same validation path.
    cap = make_read_code_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="query"):
        await cap.execute({})


async def test_bare_symbol_with_no_separator_is_searched_not_read() -> None:
    # A query without a path separator is a search term, never a file read.
    introspector = FakeRepoIntrospector(search="hit")
    cap = make_read_code_capability(introspector)

    await cap.execute({"query": "PrivacyGuard"})

    assert introspector.search_calls == ["PrivacyGuard"]
    assert introspector.read_calls == []


async def test_path_shaped_query_without_extension_is_searched() -> None:
    # ``src/bob/domain`` (a dir-like ref, no file extension) is treated as a search
    # query — only a path WITH an extension routes to read_file.
    introspector = FakeRepoIntrospector(search="dir-hit")
    cap = make_read_code_capability(introspector)

    await cap.execute({"query": "src/bob/domain"})

    assert introspector.search_calls == ["src/bob/domain"]
    assert introspector.read_calls == []


async def test_read_max_lines_is_configurable_and_forwarded_to_port() -> None:
    # The line cap passed to the factory reaches the port's read_file call.
    introspector = FakeRepoIntrospector(file_text="x")
    cap = make_read_code_capability(introspector, read_max_lines=42)

    await cap.execute({"query": "src/bob/app.py"})

    assert introspector.read_calls == [("src/bob/app.py", 42)]


async def test_denied_path_refusal_propagates_not_fabricated() -> None:
    # 🔴 US-6 at the capability layer: a guarded path read that the port REFUSES
    # (DeniedPathError) surfaces as an error, never a fabricated "matches" answer.
    cap = make_read_code_capability(_DenyingIntrospector())

    with pytest.raises(DeniedPathError):
        await cap.execute({"query": "data/soul/SOUL.md"})
