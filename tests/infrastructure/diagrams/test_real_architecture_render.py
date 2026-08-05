# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 END-TO-END on the REAL tools: «нарисуй архитектуру» → настоящий PNG (BOB-091.6).

The whole defect this module exists for: `draw_architecture` was called, the mermaid was
real, every unit test and BDD scenario was green — and no picture ever reached the owner.
A fake renderer proves the FAKE's contract (§0.3 п.4), so this module drives the seam on
the REAL tools of THIS repository:

1. the REAL ``SubprocessRepoIntrospector`` runs the REAL ``beadloom graph`` (no fake
   mermaid, no fixture that can drift from the CLI);
2. the REAL ``SubprocessMmdcRenderer`` shells the REAL local ``mmdc``;
3. the REAL ``draw_architecture`` capability wires them through the REAL per-turn sink —
   the same object the reply path drains to post the photo.

The assertions are the owner's two halves: PNG bytes in the sink (a decodable image,
inside Telegram's photo limits) and the mermaid source back to the model. Guarded against
environment flakiness: no ``beadloom`` / no ``mmdc`` → an explicit skip, so a stripped
checkout stays green. In THIS repo both are present, so the tests really run and must pass.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from bob.app import _build_registry
from bob.capabilities.adapters.diagrams.mmdc_renderer import SubprocessMmdcRenderer
from bob.capabilities.adapters.introspection.subprocess_introspector import (
    SubprocessRepoIntrospector,
)
from bob.capabilities.introspection.privacy_guard import PrivacyGuard
from bob.capabilities.usecases.diagram_attachment import DiagramAttachment
from bob.capabilities.usecases.draw_architecture import (
    make_draw_architecture_capability,
)
from bob.capabilities.usecases.render_diagram import CollectingDiagramSink

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.capabilities.ports import Capability

pytestmark = pytest.mark.integration

# Repo root: this file is tests/infrastructure/diagrams/<file>, so up three.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# The PNG signature every decoder checks first.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Telegram's photo limits (BOB-035): 10 MB per photo and 10000 for width+height. A
# rendered architecture graph must fit, or the send would fail AFTER a successful render.
_TELEGRAM_PHOTO_MAX_BYTES = 10 * 1024 * 1024
_TELEGRAM_PHOTO_MAX_DIMENSION_SUM = 10_000

# Wall-clock ceiling for ONE real render inside a turn: mmdc on this repo's graph takes
# ~1-2s locally. The point of the assertion is not micro-benchmarking but the product
# question — does attaching the picture keep the turn conversational?
_TURN_BUDGET_S = 30.0


def _beadloom_ready() -> bool:
    """Whether the real ``beadloom graph`` runs cleanly from the repo root."""
    if shutil.which("beadloom") is None:
        return False
    try:
        proc = subprocess.run(
            ["beadloom", "graph"],  # noqa: S607 — resolved via PATH by design
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and "graph" in proc.stdout


def _mmdc_ready() -> bool:
    """Whether the local mermaid-cli is installed (the runtime dependency)."""
    return shutil.which("mmdc") is not None


def _png_dimensions(png: bytes) -> tuple[int, int]:
    """Read ``(width, height)`` out of a PNG's IHDR — proof the bytes are a real image."""
    assert png.startswith(_PNG_MAGIC), "не PNG: подпись не совпала"
    width, height = struct.unpack(">II", png[16:24])
    return width, height


def _real_drawing() -> tuple[Capability, CollectingDiagramSink]:
    """The REAL capability over the REAL introspector, REAL mmdc and a real sink."""
    sink = CollectingDiagramSink()
    introspector = SubprocessRepoIntrospector(PrivacyGuard(_REPO_ROOT))
    renderer = SubprocessMmdcRenderer()
    return (
        make_draw_architecture_capability(
            introspector, attachment=DiagramAttachment(renderer, sink)
        ),
        sink,
    )


@pytest.mark.asyncio
async def test_the_overview_request_yields_a_real_png_and_the_real_mermaid() -> None:
    """🔴 The live-smoke regression: one call → a decodable PNG + the graph source.

    Nothing here is faked: the mermaid comes from ``beadloom graph`` over this repo's
    own graph and the PNG from the local ``mmdc``. Had this test existed, the defect
    (words but no image) could not have shipped.
    """
    if not _beadloom_ready():
        pytest.skip("beadloom not on PATH or repo not indexed for it")
    if not _mmdc_ready():
        pytest.skip("mermaid-cli (mmdc) not installed")
    cap, sink = _real_drawing()

    started = time.monotonic()
    result = await cap.execute({})
    elapsed = time.monotonic() - started

    assert isinstance(result, dict), f"неожиданный результат: {result!r}"
    mermaid = str(result.get("mermaid", ""))
    # The model's half: the REAL graph source (this repo's own nodes, not a fixture).
    assert mermaid.startswith("graph"), f"это не вывод beadloom graph: {mermaid[:80]!r}"
    assert "bob" in mermaid
    # The owner's half: a real image queued for the photo send.
    queued = sink.drain()
    assert len(queued) == 1, "🔴 картинки нет — ровно тот дефект, из-за которого беада"
    png = queued[0].png
    width, height = _png_dimensions(png)
    assert width > 0
    assert height > 0
    assert len(png) <= _TELEGRAM_PHOTO_MAX_BYTES, "PNG не влезет в Telegram"
    assert width + height <= _TELEGRAM_PHOTO_MAX_DIMENSION_SUM, (
        f"сумма сторон {width}+{height} выше лимита Telegram"
    )
    # And the turn stayed conversational: one real render, inside the render timeout.
    assert elapsed < _TURN_BUDGET_S, f"ход блокировался {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_a_node_request_renders_the_real_node_view_too() -> None:
    """The detailed form is real as well: ``beadloom graph memory --depth 2`` → PNG."""
    if not _beadloom_ready():
        pytest.skip("beadloom not on PATH or repo not indexed for it")
    if not _mmdc_ready():
        pytest.skip("mermaid-cli (mmdc) not installed")
    cap, sink = _real_drawing()

    result = await cap.execute({"ref": "memory", "depth": 2})

    assert isinstance(result, dict)
    assert "memory" in str(result.get("mermaid", ""))
    queued = sink.drain()
    assert len(queued) == 1
    assert queued[0].png.startswith(_PNG_MAGIC)


@pytest.mark.asyncio
async def test_a_missing_renderer_binary_keeps_the_turn_alive_on_real_output() -> None:
    """🔴 The honest degradation on REAL mermaid: no ``mmdc`` → words, no crash.

    Same real ``beadloom graph`` source, but the renderer points at a binary that does
    not exist (the shape of a machine without mermaid-cli). Bob must still get the source
    AND an explicit "картинки не будет" line — the failure may not cost him the turn.
    """
    if not _beadloom_ready():
        pytest.skip("beadloom not on PATH or repo not indexed for it")
    sink = CollectingDiagramSink()
    cap = make_draw_architecture_capability(
        SubprocessRepoIntrospector(PrivacyGuard(_REPO_ROOT)),
        attachment=DiagramAttachment(
            SubprocessMmdcRenderer(mmdc_bin="mmdc-does-not-exist"), sink
        ),
    )

    result = await cap.execute({})

    assert isinstance(result, dict)
    assert str(result.get("mermaid", "")).startswith("graph")
    assert sink.drain() == ()
    picture = str(result.get("picture", "")).lower()
    assert "не" in picture
    assert "уже" not in picture, "нельзя делать вид, что картинка ушла"


@pytest.mark.asyncio
async def test_the_production_wiring_really_draws_a_picture_end_to_end() -> None:
    """🔴🔴 The live smoke, reproduced in the suite: PRODUCTION wiring, REAL tools.

    Nothing in this test is constructed by hand — the composition root
    (:func:`_build_registry`) builds the registry, the introspector and the renderer from
    config, exactly as the running process does, and the tool is dispatched THROUGH the
    registry by its name (the same way the tool-loop dispatches a model's call). Then the
    picture must be waiting in the sink the composition root hands to ``HandleMessage``.

    §0.3 п.10 — a permission is not a capability: this asserts the CALL, not the wiring
    comment. §0.3 п.4 — a fake renderer proves the fake; this one runs the real ``mmdc``.
    """
    if not _beadloom_ready():
        pytest.skip("beadloom not on PATH or repo not indexed for it")
    if not _mmdc_ready():
        pytest.skip("mermaid-cli (mmdc) not installed")
    config: Mapping[str, object] = {
        "introspection": {"enabled": True, "architecture_tools": True},
        "diagrams": {"enabled": True},
    }
    registry, sink, _renderer = _build_registry(config, recall=_UnusedRecall())  # type: ignore[arg-type]

    result = await registry.dispatch("draw_architecture", {})

    assert isinstance(result, dict)
    assert str(result.get("mermaid", "")).startswith("graph")
    queued = sink.drain()
    assert len(queued) == 1, (
        "🔴 боевая сборка не приложила картинку — ровно живой смоук BOB-091.6"
    )
    assert queued[0].png.startswith(_PNG_MAGIC)
    assert queued[0].caption


class _UnusedRecall:
    """A duck-typed MemoryRecall the drawing path never touches."""

    async def recall(self, query: str, *, k: int = 5) -> Sequence[object]:  # noqa: ARG002
        return []

