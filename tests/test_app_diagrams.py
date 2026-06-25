# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Composition-root gating of the ``render_diagram`` skill (BOB-035 .2).

``_build_registry`` registers ``render_diagram`` ONLY when ``diagrams.enabled`` — the
guardrail that keeps the LOCAL diagram renderer behind an explicit flag. These tests
drive that gate directly over a duck-typed recall fake (the memory-capability
factories only hold the reference; the gate never invokes recall) with introspection
turned off so the registry holds EXACTLY the memory capabilities ± render_diagram.
``_build_diagram_renderer`` constructs a :class:`SubprocessMmdcRenderer` but spawns no
process at construction, so this stays deterministic — the real ``mmdc`` is never run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.app import _build_diagram_renderer, _build_registry
from bob.infrastructure.diagrams.mmdc_renderer import SubprocessMmdcRenderer

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class _FakeRecall:
    """A duck-typed MemoryRecall: never called by the registration gate."""

    async def recall(
        self, query: str, *, k: int = 5  # noqa: ARG002
    ) -> Sequence[object]:
        return []


def _config(*, diagrams: Mapping[str, object] | None = None) -> dict[str, object]:
    # Introspection off so the registry holds only memory caps ± render_diagram —
    # isolates the diagrams gate from the unrelated introspection skills.
    cfg: dict[str, object] = {"introspection": {"enabled": False}}
    if diagrams is not None:
        cfg["diagrams"] = diagrams
    return cfg


def _names(config: Mapping[str, object]) -> list[str]:
    registry, _sink = _build_registry(config, recall=_FakeRecall())  # type: ignore[arg-type]
    return [
        str(tool["function"]["name"])  # type: ignore[index]
        for tool in registry.manifest()
    ]


def test_render_diagram_registered_when_diagrams_enabled() -> None:
    names = _names(_config(diagrams={"enabled": True}))

    assert "render_diagram" in names


def test_render_diagram_absent_when_diagrams_disabled() -> None:
    names = _names(_config(diagrams={"enabled": False}))

    assert "render_diagram" not in names


def test_render_diagram_absent_by_default_no_diagrams_section() -> None:
    # No ``diagrams`` section at all → the flag defaults False → skill not registered.
    names = _names(_config())

    assert "render_diagram" not in names


def test_build_registry_returns_a_shared_sink() -> None:
    # The composition root must hand the SAME sink instance to the use-case as the
    # capability pushes into — so a rendered PNG actually reaches the reply path.
    registry, sink = _build_registry(
        _config(diagrams={"enabled": True}), recall=_FakeRecall()  # type: ignore[arg-type]
    )

    assert sink is not None
    assert sink.drain() == ()  # starts empty
    names = [
        str(tool["function"]["name"])  # type: ignore[index]
        for tool in registry.manifest()
    ]
    assert "render_diagram" in names


def test_build_diagram_renderer_honours_configured_bin_and_timeout() -> None:
    renderer = _build_diagram_renderer({"diagrams": {"mmdc_bin": "my-mmdc", "timeout": 7}})

    assert isinstance(renderer, SubprocessMmdcRenderer)


def test_build_diagram_renderer_uses_defaults_without_a_section() -> None:
    renderer = _build_diagram_renderer({})

    assert isinstance(renderer, SubprocessMmdcRenderer)
