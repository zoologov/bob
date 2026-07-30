# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``find_file`` — read-only repo file search (BOB-067 .1).

A thin wrapper over :meth:`RepoIntrospector.find_file` (privacy-guarded in the .1
port). It exposes the stable :class:`Capability` contract, delegates the ``pattern``
argument to the port, and gives an honest "not found" on empty output. Deterministic
on a fake port — the guard/disk live behind the port, never exercised here.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from bob.capabilities.usecases.find_file import make_find_file_capability

from .fakes import FakeRepoIntrospector


def test_capability_advertises_the_find_file_contract() -> None:
    cap = make_find_file_capability(FakeRepoIntrospector())

    assert cap.name == "find_file"
    # The description must push the model to CALL the tool and report REAL paths.
    low = cap.description.lower()
    assert "find" in low
    assert "real" in low
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["pattern"] == {"type": "string"}
    assert schema["required"] == ["pattern"]


async def test_execute_delegates_pattern_to_port() -> None:
    introspector = FakeRepoIntrospector(found="src/bob/app.py\nsrc/bob/cli.py")
    cap = make_find_file_capability(introspector)

    result = await cap.execute({"pattern": "*.py"})

    assert introspector.find_file_calls == ["*.py"]
    assert isinstance(result, Mapping)
    assert result["matches"] == "src/bob/app.py\nsrc/bob/cli.py"


async def test_execute_strips_whitespace_around_pattern() -> None:
    introspector = FakeRepoIntrospector(found="hit")
    cap = make_find_file_capability(introspector)

    await cap.execute({"pattern": "  nodes.yml  "})

    assert introspector.find_file_calls == ["nodes.yml"]


async def test_execute_with_empty_result_is_honest_not_found() -> None:
    introspector = FakeRepoIntrospector(found="")
    cap = make_find_file_capability(introspector)

    result = await cap.execute({"pattern": "*.rs"})

    assert isinstance(result, Mapping)
    assert "не нашёл" in str(result["matches"]).lower()


async def test_execute_requires_a_string_pattern() -> None:
    cap = make_find_file_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="pattern"):
        await cap.execute({"pattern": None})


async def test_execute_with_missing_pattern_key_raises() -> None:
    cap = make_find_file_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="pattern"):
        await cap.execute({})
