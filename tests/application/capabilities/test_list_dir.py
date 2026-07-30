# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``list_dir`` — read-only repo directory listing (BOB-067 .1).

A thin wrapper over :meth:`RepoIntrospector.list_dir` (privacy-guarded in the .1
port). It exposes the stable :class:`Capability` contract, delegates the ``path``
argument to the port, and gives an honest message on empty output. Deterministic on
a fake port — the guard/disk live behind the port, never exercised here.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from bob.capabilities.usecases.list_dir import make_list_dir_capability

from .fakes import FakeRepoIntrospector


def test_capability_advertises_the_list_dir_contract() -> None:
    cap = make_list_dir_capability(FakeRepoIntrospector())

    assert cap.name == "list_dir"
    # The description must push the model to CALL the tool and report REAL entries.
    low = cap.description.lower()
    assert "list" in low
    assert "real" in low
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["path"] == {"type": "string"}
    assert schema["required"] == ["path"]


async def test_execute_delegates_path_to_port() -> None:
    introspector = FakeRepoIntrospector(listing="app.py\tfile\t6\nsub/\tdir")
    cap = make_list_dir_capability(introspector)

    result = await cap.execute({"path": ".beadloom"})

    assert introspector.list_dir_calls == [".beadloom"]
    assert isinstance(result, Mapping)
    assert result["entries"] == "app.py\tfile\t6\nsub/\tdir"


async def test_execute_strips_whitespace_around_path() -> None:
    introspector = FakeRepoIntrospector(listing="x")
    cap = make_list_dir_capability(introspector)

    await cap.execute({"path": "  src/bob  "})

    assert introspector.list_dir_calls == ["src/bob"]


async def test_execute_with_empty_listing_is_honest() -> None:
    introspector = FakeRepoIntrospector(listing="")
    cap = make_list_dir_capability(introspector)

    result = await cap.execute({"path": "src"})

    assert isinstance(result, Mapping)
    assert "не удалось" in str(result["entries"]).lower()


async def test_execute_requires_a_string_path() -> None:
    cap = make_list_dir_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="path"):
        await cap.execute({"path": None})


async def test_execute_with_missing_path_key_raises() -> None:
    cap = make_list_dir_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="path"):
        await cap.execute({})
