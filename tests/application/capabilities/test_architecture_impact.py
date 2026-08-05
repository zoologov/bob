# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``architecture_impact`` — «что сломается, если тронуть X» (BOB-091.1).

A thin wrapper over :meth:`RepoIntrospector.impact` (read-only ``beadloom why``, already
condensed by the pure digest). What matters here: the ref reaches the port, an unknown
ref answers honestly instead of inventing dependents, and a refused (non-ref) value comes
back as a readable error rather than a crashed turn.
"""

from __future__ import annotations

from collections.abc import Mapping

from bob.capabilities.usecases.architecture_impact import (
    make_architecture_impact_capability,
)

from .fakes import FakeRepoIntrospector

_DIGEST = (
    "memory (feature) — Memory module.\n"
    "Зависит от: bob-domain (domain).\n"
    "Влияет на: capabilities (feature)."
)


def test_capability_advertises_the_architecture_impact_contract() -> None:
    cap = make_architecture_impact_capability(FakeRepoIntrospector())

    assert cap.name == "architecture_impact"
    assert cap.permission == "safe"
    schema = cap.input_schema
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["ref"] == {"type": "string"}
    assert schema["required"] == ["ref"]


async def test_execute_delegates_the_ref_and_returns_the_digest() -> None:
    introspector = FakeRepoIntrospector(impact_text=_DIGEST)
    cap = make_architecture_impact_capability(introspector)

    result = await cap.execute({"ref": "memory"})

    assert introspector.impact_calls == ["memory"]
    assert isinstance(result, Mapping)
    assert result["impact"] == _DIGEST


async def test_unknown_ref_is_honest_not_found() -> None:
    introspector = FakeRepoIntrospector(impact_text="")
    cap = make_architecture_impact_capability(introspector)

    result = await cap.execute({"ref": "nosuchnode"})

    assert isinstance(result, Mapping)
    assert "не нашёл" in str(result["impact"]).lower()


async def test_refused_ref_becomes_a_readable_error() -> None:
    introspector = FakeRepoIntrospector(raise_on_impact=True)
    cap = make_architecture_impact_capability(introspector)

    result = await cap.execute({"ref": "memory; reindex"})

    assert isinstance(result, Mapping)
    assert "ref" in str(result["error"]).lower()


async def test_missing_ref_is_refused_without_touching_the_port() -> None:
    introspector = FakeRepoIntrospector(impact_text=_DIGEST)
    cap = make_architecture_impact_capability(introspector)

    result = await cap.execute({})

    assert isinstance(result, Mapping)
    assert "error" in result
    assert introspector.impact_calls == []
