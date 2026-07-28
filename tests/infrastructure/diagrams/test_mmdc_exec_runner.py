# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the default ``_ExecRunner`` subprocess boundary (BOB-035 .2).

The dev wave (.1) drove :class:`SubprocessMmdcRenderer` through an INJECTED fake
runner — it never touched the real ``create_subprocess_exec`` path. This file covers
that remaining branch (the ``_ExecRunner`` the renderer uses by DEFAULT) WITHOUT ever
spawning a real ``mmdc`` (it is NOT installed in this env): ``asyncio
.create_subprocess_exec`` is monkeypatched to a deterministic fake process so the
success, ``returncode is None`` fallback, and timeout → kill → drain branches are all
exercised. The argv reaching the OS boundary is asserted (``mmdc -i ... -o ...``,
never a shell), so we know the renderer hands the right exec call to the kernel.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bob.capabilities.adapters.diagrams import mmdc_renderer
from bob.capabilities.adapters.diagrams.mmdc_renderer import (
    DiagramRenderError,
    SubprocessMmdcRenderer,
)

_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"


class _FakeProc:
    """A scripted ``asyncio.subprocess.Process``: canned returncode, optional hang.

    Models exactly the surface ``_ExecRunner`` touches: ``communicate`` (awaited under
    a timeout), ``kill`` + ``wait`` (the timeout-reap path) and ``returncode``. With
    ``hang=True`` ``communicate`` blocks forever so ``asyncio.wait_for`` raises the
    timeout, driving the kill/drain branch.
    """

    def __init__(
        self,
        *,
        returncode: int | None = 0,
        hang: bool = False,
        wait_raises: BaseException | None = None,
    ) -> None:
        self.returncode = returncode
        self._hang = hang
        self._wait_raises = wait_raises
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.Event().wait()  # never resolves → wait_for times out
        return (b"", b"")

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        if self._wait_raises is not None:
            raise self._wait_raises
        return self.returncode if self.returncode is not None else 0


def _patch_exec(
    monkeypatch: pytest.MonkeyPatch,
    proc: _FakeProc,
    recorder: list[list[str]],
    *,
    write_png: bool = False,
) -> None:
    """Replace ``create_subprocess_exec`` in the renderer module with a fake.

    With ``write_png=True`` the fake writes canned PNG bytes to the ``-o`` path (as a
    real successful ``mmdc`` would) so the success branch round-trips real bytes.
    """

    async def _fake_exec(*argv: str, **_kwargs: object) -> _FakeProc:
        recorder.append(list(argv))
        if write_png:
            Path(argv[argv.index("-o") + 1]).write_bytes(_PNG)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)


async def test_exec_runner_renders_via_the_real_subprocess_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: the DEFAULT runner (no injected fake) over a fake create_subprocess_exec
    # that writes a PNG to -o exactly like a successful mmdc would.
    argv_seen: list[list[str]] = []
    _patch_exec(monkeypatch, _FakeProc(returncode=0), argv_seen, write_png=True)
    renderer = SubprocessMmdcRenderer(mmdc_bin="mmdc")

    # Act
    png = await renderer.render("graph TD; A-->B")

    # Assert: the PNG round-tripped, and the OS-boundary argv was the no-shell exec call.
    assert png == _PNG
    argv = argv_seen[0]
    assert argv[0] == "mmdc"
    assert argv[argv.index("-i") + 1].endswith(".mmd")
    assert argv[argv.index("-o") + 1].endswith(".png")


async def test_exec_runner_writes_real_png_bytes_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fake proc does not write a PNG, so _render_in must raise "no PNG output" —
    # proving the exec runner returns rc=0 and the renderer reads the output path.
    _patch_exec(monkeypatch, _FakeProc(returncode=0), [])
    renderer = SubprocessMmdcRenderer()

    with pytest.raises(DiagramRenderError, match="no PNG"):
        await renderer.render("graph TD; A-->B")


async def test_exec_runner_maps_none_returncode_to_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A process that exits with returncode None (never observed) is treated as rc=1 —
    # so the renderer raises rather than silently returning b"".
    _patch_exec(monkeypatch, _FakeProc(returncode=None), [])
    renderer = SubprocessMmdcRenderer()

    with pytest.raises(DiagramRenderError):
        await renderer.render("graph TD; A-->B")


async def test_exec_runner_times_out_kills_and_reaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: a hanging process + a tiny timeout → wait_for raises, the runner must
    # kill the process and reap it (the _drain branch), then raise DiagramRenderError.
    proc = _FakeProc(hang=True)
    _patch_exec(monkeypatch, proc, [])
    renderer = SubprocessMmdcRenderer(timeout=0.01)

    # Act / Assert
    with pytest.raises(DiagramRenderError, match="timed out"):
        await renderer.render("graph TD; A-->B")

    # The stuck subprocess was killed and reaped — no zombie left behind.
    assert proc.killed is True
    assert proc.waited is True


async def test_drain_swallows_process_lookup_on_reap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The reap (_drain) suppresses ProcessLookupError — a process that died between
    # kill and wait must not turn the timeout into a different, noisier error.
    proc = _FakeProc(hang=True, wait_raises=ProcessLookupError())
    _patch_exec(monkeypatch, proc, [])
    renderer = SubprocessMmdcRenderer(timeout=0.01)

    with pytest.raises(DiagramRenderError, match="timed out"):
        await renderer.render("graph TD; A-->B")

    assert proc.killed is True


async def test_module_reexports_diagram_render_error() -> None:
    # The infra module re-exports the domain error so adapters import it from here
    # (per the module's documented contract) without reaching into the domain.
    assert mmdc_renderer.DiagramRenderError is DiagramRenderError
