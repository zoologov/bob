# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``inspect_architecture`` — read-only self-introspection (BOB-017 .2).

A thin wrapper over :meth:`RepoIntrospector.architecture_context` (beadloom
ctx/graph/why/search). It exposes the stable :class:`Capability` contract,
delegates a graph ``ref`` to the port, renders a compact result, and gives an
honest "not found" (US-5) when the port yields nothing. Deterministic on a fake
port — no subprocess, no disk.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from bob.capabilities.usecases.inspect_architecture import (
    make_inspect_architecture_capability,
)

from .fakes import FakeRepoIntrospector


def test_capability_advertises_the_inspect_architecture_contract() -> None:
    cap = make_inspect_architecture_capability(FakeRepoIntrospector())

    assert cap.name == "inspect_architecture"
    assert cap.description
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["ref"] == {"type": "string"}
    assert schema["required"] == ["ref"]


async def test_execute_delegates_ref_to_port_and_renders_compactly() -> None:
    introspector = FakeRepoIntrospector(architecture="domain bob → infrastructure")
    cap = make_inspect_architecture_capability(introspector)

    result = await cap.execute({"ref": "bob"})

    assert introspector.architecture_calls == ["bob"]
    assert isinstance(result, Mapping)
    assert result["context"] == "domain bob → infrastructure"


async def test_execute_with_empty_port_output_is_honest_not_found() -> None:
    introspector = FakeRepoIntrospector(architecture="   ")
    cap = make_inspect_architecture_capability(introspector)

    result = await cap.execute({"ref": "nope"})

    assert isinstance(result, Mapping)
    assert "не нашёл" in str(result["context"]).lower()


async def test_execute_requires_a_string_ref() -> None:
    cap = make_inspect_architecture_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="ref"):
        await cap.execute({"ref": 123})


async def test_execute_with_missing_ref_key_raises() -> None:
    cap = make_inspect_architecture_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="ref"):
        await cap.execute({})
