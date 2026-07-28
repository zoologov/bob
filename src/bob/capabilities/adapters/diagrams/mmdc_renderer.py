# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=infrastructure

"""SubprocessMmdcRenderer — render mermaid to a LOCAL PNG via mermaid-cli (BOB-035).

The infrastructure adapter realising :class:`~bob.domain.ports.DiagramRenderer`. It
runs the local mermaid-cli (``mmdc``) and does NO network I/O — the diagram source
never leaves the machine (privacy). One render:

1. writes the mermaid source to a temp ``in.mmd`` in a fresh, isolated temp dir;
2. runs ``mmdc -i in.mmd -o out.png`` via ``asyncio.create_subprocess_exec`` (NEVER
   a shell, so no metacharacter injection) under a hard timeout;
3. reads the PNG bytes back and returns them;
4. removes the temp dir (always — even on failure).

When ``mmdc`` is not on PATH, exits non-zero, times out, or produces no PNG, it
raises a clear :class:`DiagramRenderError` so the ``render_diagram`` capability can
degrade to an honest "renderer unavailable" line and never crash the turn. The
subprocess boundary is injected (``runner``) so tests drive the argv / timeout /
not-found paths with a fake — the real ``mmdc`` is a documented runtime dependency,
never spawned in tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from bob.capabilities.ports import DiagramRenderError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["DiagramRenderError", "SubprocessMmdcRenderer"]

logger = logging.getLogger(__name__)

# Default per-render wall-clock ceiling (seconds): generous enough for a real mmdc
# render, low enough that a stuck process cannot wedge a turn. Config-tunable via
# ``diagrams.timeout``.
_DEFAULT_TIMEOUT_S = 30.0

# High-quality render defaults (BOB-037 B). ``-s`` is mermaid-cli's deviceScaleFactor
# — a 3x raster keeps dense diagrams crisp (tap → real pixels) instead of the blurry
# 1x default; ``-b`` is the page background — ``white`` so a diagram is readable on
# Telegram's dark theme (a transparent default goes invisible). Both are config-tunable
# via ``diagrams.scale`` / ``diagrams.background``.
_DEFAULT_SCALE = 3
_DEFAULT_BACKGROUND = "white"

# The mermaid source / output filenames inside the isolated temp dir.
_INPUT_NAME = "in.mmd"
_OUTPUT_NAME = "out.png"


class _MmdcRunner(Protocol):
    """The injected subprocess boundary: run ``argv`` with a timeout, return the rc.

    Realised by :class:`_ExecRunner` (``create_subprocess_exec``); a fake substitutes
    in tests. A missing binary surfaces as ``FileNotFoundError``; a non-zero return
    code signals a render failure.
    """

    async def __call__(self, argv: list[str], *, timeout: float) -> int: ...


class SubprocessMmdcRenderer:
    """Render mermaid to a LOCAL PNG by shelling the mermaid-cli (``mmdc``), no shell."""

    def __init__(
        self,
        *,
        runner: _MmdcRunner | None = None,
        mmdc_bin: str = "mmdc",
        timeout: float = _DEFAULT_TIMEOUT_S,
        scale: int = _DEFAULT_SCALE,
        background: str = _DEFAULT_BACKGROUND,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be > 0")
        if scale <= 0:
            raise ValueError("scale must be > 0")
        self._runner: _MmdcRunner = runner or _ExecRunner()
        self._mmdc_bin = mmdc_bin
        self._timeout = timeout
        self._scale = scale
        self._background = background

    async def render(self, mermaid_source: str) -> bytes:
        """Render ``mermaid_source`` to PNG bytes (raises :class:`DiagramRenderError`)."""
        if not mermaid_source.strip():
            raise DiagramRenderError("mermaid source is empty")
        workdir = Path(tempfile.mkdtemp(prefix="bob-diagram-"))
        try:
            return await self._render_in(workdir, mermaid_source)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _render_in(self, workdir: Path, mermaid_source: str) -> bytes:
        """Run one render inside ``workdir`` (the temp dir is cleaned up by the caller)."""
        input_path = workdir / _INPUT_NAME
        output_path = workdir / _OUTPUT_NAME
        input_path.write_text(mermaid_source, encoding="utf-8")
        argv = [
            self._mmdc_bin,
            "-i",
            str(input_path),
            "-o",
            str(output_path),
            "-s",
            str(self._scale),
            "-b",
            self._background,
        ]
        returncode = await self._run(argv)
        if returncode != 0:
            raise DiagramRenderError(
                f"mmdc exited with code {returncode} while rendering the diagram"
            )
        if not output_path.exists():
            raise DiagramRenderError("mmdc produced no PNG output")
        return output_path.read_bytes()

    async def _run(self, argv: Sequence[str]) -> int:
        """Run ``argv`` via the injected boundary; map a missing binary to a clear error."""
        try:
            return await self._runner(list(argv), timeout=self._timeout)
        except FileNotFoundError as exc:
            raise DiagramRenderError(
                f"mermaid-cli ('{self._mmdc_bin}') is not installed or not on PATH"
            ) from exc


class _ExecRunner:
    """Default runner: ``create_subprocess_exec`` with a hard timeout, no shell."""

    async def __call__(self, argv: list[str], *, timeout: float) -> int:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError as exc:
            proc.kill()
            await _drain(proc)
            raise DiagramRenderError(
                f"mmdc render timed out after {timeout:g}s"
            ) from exc
        return proc.returncode if proc.returncode is not None else 1


async def _drain(proc: asyncio.subprocess.Process) -> None:
    """Reap a killed subprocess so no zombie/transport warning is left behind."""
    with contextlib.suppress(ProcessLookupError):
        await proc.wait()
