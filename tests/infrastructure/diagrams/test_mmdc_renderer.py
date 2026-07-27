# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for SubprocessMmdcRenderer (BOB-035 .1).

The adapter realises :class:`bob.domain.ports.DiagramRenderer` by running the local
mermaid-cli (``mmdc``) via ``asyncio.create_subprocess_exec`` (NEVER a shell): it
writes the mermaid source to a temp ``.mmd`` file, runs ``mmdc -i in.mmd -o
out.png`` with a hard timeout, reads the PNG bytes, and cleans the temp dir up. The
subprocess boundary is injected as a fake here so the tests are deterministic and
never spawn the real ``mmdc`` (which is NOT installed in this env) — the fake writes
canned PNG bytes to the output path, raises FileNotFoundError to model a missing
binary, or times out, so the not-found / timeout / argv paths are all exercised
without a real process.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bob.capabilities.adapters.diagrams.mmdc_renderer import (
    DiagramRenderError,
    SubprocessMmdcRenderer,
)

_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"


class _FakeMmdc:
    """A scripted ``mmdc`` runner: records argv, writes a canned PNG to ``-o``."""

    def __init__(
        self,
        *,
        png: bytes = _PNG,
        returncode: int = 0,
        raises: BaseException | None = None,
        delay: float = 0.0,
    ) -> None:
        self.calls: list[list[str]] = []
        self.seen_timeout: float = 0.0
        self._png = png
        self._returncode = returncode
        self._raises = raises
        self._delay = delay

    async def __call__(self, argv: list[str], *, timeout: float) -> int:
        self.seen_timeout = timeout
        self.calls.append(list(argv))
        if self._raises is not None:
            raise self._raises
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._returncode == 0:
            out_path = Path(argv[argv.index("-o") + 1])
            out_path.write_bytes(self._png)
        return self._returncode


async def test_render_returns_the_png_bytes() -> None:
    runner = _FakeMmdc()
    renderer = SubprocessMmdcRenderer(runner=runner)

    png = await renderer.render("graph TD; A-->B")

    assert png == _PNG


async def test_render_invokes_mmdc_with_input_and_output_flags() -> None:
    runner = _FakeMmdc()
    renderer = SubprocessMmdcRenderer(runner=runner, mmdc_bin="my-mmdc")

    await renderer.render("graph TD; A-->B")

    argv = runner.calls[0]
    assert argv[0] == "my-mmdc"
    assert "-i" in argv
    assert "-o" in argv
    in_path = argv[argv.index("-i") + 1]
    out_path = argv[argv.index("-o") + 1]
    assert in_path.endswith(".mmd")
    assert out_path.endswith(".png")


async def test_render_writes_the_mermaid_source_to_the_input_file() -> None:
    seen: dict[str, str] = {}

    async def _capture(argv: list[str], *, timeout: float) -> int:
        in_path = Path(argv[argv.index("-i") + 1])
        seen["source"] = in_path.read_text(encoding="utf-8")
        Path(argv[argv.index("-o") + 1]).write_bytes(_PNG)
        return 0

    renderer = SubprocessMmdcRenderer(runner=_capture)

    await renderer.render("graph TD; A-->B")

    assert seen["source"] == "graph TD; A-->B"


async def test_render_passes_high_quality_scale_and_background_flags() -> None:
    # BOB-037 B: by default the argv carries a high deviceScaleFactor (-s 3) and a
    # readable white background (-b white) so dense diagrams stay legible on
    # Telegram's dark theme.
    runner = _FakeMmdc()
    renderer = SubprocessMmdcRenderer(runner=runner)

    await renderer.render("graph TD; A-->B")

    argv = runner.calls[0]
    assert argv[argv.index("-s") + 1] == "3"
    assert argv[argv.index("-b") + 1] == "white"


async def test_render_quality_flags_are_configurable() -> None:
    # BOB-037 B: scale / background are config-tunable (diagrams.scale / .background).
    runner = _FakeMmdc()
    renderer = SubprocessMmdcRenderer(runner=runner, scale=2, background="transparent")

    await renderer.render("graph TD; A-->B")

    argv = runner.calls[0]
    assert argv[argv.index("-s") + 1] == "2"
    assert argv[argv.index("-b") + 1] == "transparent"


async def test_render_passes_the_configured_timeout() -> None:
    runner = _FakeMmdc()
    renderer = SubprocessMmdcRenderer(runner=runner, timeout=12.5)

    await renderer.render("graph TD; A-->B")

    assert runner.seen_timeout == 12.5


async def test_render_raises_when_mmdc_is_not_installed() -> None:
    runner = _FakeMmdc(raises=FileNotFoundError("mmdc"))
    renderer = SubprocessMmdcRenderer(runner=runner)

    with pytest.raises(DiagramRenderError):
        await renderer.render("graph TD; A-->B")


async def test_render_raises_when_mmdc_exits_non_zero() -> None:
    runner = _FakeMmdc(returncode=1)
    renderer = SubprocessMmdcRenderer(runner=runner)

    with pytest.raises(DiagramRenderError):
        await renderer.render("not-valid-mermaid")


async def test_render_raises_when_output_png_is_missing() -> None:
    # A runner that "succeeds" but produces no PNG must still raise, never return b"".
    async def _no_output(argv: list[str], *, timeout: float) -> int:
        return 0

    renderer = SubprocessMmdcRenderer(runner=_no_output)

    with pytest.raises(DiagramRenderError):
        await renderer.render("graph TD; A-->B")


async def test_render_cleans_up_the_temp_dir() -> None:
    captured: dict[str, Path] = {}

    async def _capture(argv: list[str], *, timeout: float) -> int:
        in_path = Path(argv[argv.index("-i") + 1])
        captured["dir"] = in_path.parent
        Path(argv[argv.index("-o") + 1]).write_bytes(_PNG)
        return 0

    renderer = SubprocessMmdcRenderer(runner=_capture)

    await renderer.render("graph TD; A-->B")

    assert not captured["dir"].exists()


async def test_render_rejects_empty_source() -> None:
    renderer = SubprocessMmdcRenderer(runner=_FakeMmdc())

    with pytest.raises(DiagramRenderError):
        await renderer.render("   ")


def test_construction_rejects_a_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="timeout"):
        SubprocessMmdcRenderer(runner=_FakeMmdc(), timeout=0)


def test_construction_rejects_a_non_positive_scale() -> None:
    # BOB-037 B input edge: the deviceScaleFactor must be a positive integer.
    with pytest.raises(ValueError, match="scale"):
        SubprocessMmdcRenderer(runner=_FakeMmdc(), scale=0)
