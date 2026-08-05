# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""The ``introspection.architecture_tools`` registration gate (BOB-091.1).

``_build_registry`` advertises ``draw_architecture`` + ``architecture_impact`` ONLY when
the sub-flag is on. The gate is the whole safety story of the slice's rollout: OFF (the
default) the registry is byte-for-byte what it was before this bead, so Bob cannot even
see the new tools; ON they join the other read-only introspection skills. The master
``introspection.enabled`` still dominates — an architecture flag under a disabled master
advertises nothing.

Driven directly over a duck-typed recall fake (the memory-capability factories only hold
the reference; the gate never invokes recall), so nothing spawns and no disk is touched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.app import _build_registry

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_NEW_TOOLS = ("draw_architecture", "architecture_impact")


class _FakeRecall:
    """A duck-typed MemoryRecall: never called by the registration gate."""

    async def recall(self, query: str, *, k: int = 5) -> Sequence[object]:  # noqa: ARG002
        return []


def _tool_names(config: Mapping[str, object]) -> list[str]:
    registry, _sink, _renderer = _build_registry(config, recall=_FakeRecall())  # type: ignore[arg-type]
    return [
        str(tool["function"]["name"])  # type: ignore[index]
        for tool in registry.manifest()
    ]


def test_architecture_tools_absent_by_default() -> None:
    # No flag → the registry is exactly what it was before BOB-091 (OFF path unchanged).
    names = _tool_names({"introspection": {"enabled": True}})

    for tool in _NEW_TOOLS:
        assert tool not in names
    # …and the pre-existing introspection skills are all still there.
    assert "inspect_architecture" in names
    assert "read_code" in names


def test_architecture_tools_registered_when_the_flag_is_on() -> None:
    names = _tool_names(
        {"introspection": {"enabled": True, "architecture_tools": True}}
    )

    for tool in _NEW_TOOLS:
        assert tool in names


def test_master_introspection_flag_still_dominates() -> None:
    # A sub-flag can never re-enable a disabled master.
    names = _tool_names(
        {"introspection": {"enabled": False, "architecture_tools": True}}
    )

    for tool in _NEW_TOOLS:
        assert tool not in names


def test_flag_only_adds_the_two_architecture_tools() -> None:
    # The gate is surgical: turning it on changes the manifest by exactly two entries.
    off = _tool_names({"introspection": {"enabled": True}})
    on = _tool_names({"introspection": {"enabled": True, "architecture_tools": True}})

    assert sorted(set(on) - set(off)) == sorted(_NEW_TOOLS)
    assert set(off) - set(on) == set()


def test_architecture_tools_are_not_autonomously_safe_listed() -> None:
    # Conversation-only, like the other introspection skills: the wiring must not put
    # them on ``goals.safe_capabilities`` behind the owner's back.
    config: dict[str, object] = {
        "introspection": {"enabled": True, "architecture_tools": True},
        "goals": {},
    }
    goals = config["goals"]
    assert isinstance(goals, dict)

    _tool_names(config)

    assert goals.get("safe_capabilities") is None
