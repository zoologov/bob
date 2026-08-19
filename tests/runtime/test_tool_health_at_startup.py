# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""BOB-111: muteness is VISIBLE at startup, not discovered by being asked.

Issues #62. The requirements are collected from the SAME config keys the wiring reads,
so the check and the real call can never disagree about which binary is meant — a check
that watched a different setting would be the "guard reading the source" trap all over
again (§0.3 п.12).

Asserted through observable behaviour: what the log says, and what an assembled
requirement list contains — never private state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.runtime.wiring.tool_health import collect_requirements, report_tool_health

if TYPE_CHECKING:
    import pytest

_LAPTOP_PATH = "/Users/someone/.nvm/versions/node/v18.20.8/bin/mmdc"


def _config(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "capabilities": {"introspection": {"architecture_tools": True, "dev_tools": True}},
        "introspection": {},
        "diagrams": {},
        "coder": {"enabled": False},
    }
    base.update(overrides)
    return base


def test_enabled_capabilities_declare_their_binaries() -> None:
    # Act
    tools = [r.tool for r in collect_requirements(_config())]

    # Assert: the four that a live Bob depends on with these flags.
    assert set(tools) == {"beadloom", "bd", "git", "mmdc"}


def test_a_disabled_capability_is_not_reported() -> None:
    """A report people learn to ignore is worth less than no report at all."""
    # Arrange: the coder is off — a missing `claude` is then not a defect.
    tools = [r.tool for r in collect_requirements(_config())]
    assert "claude" not in tools

    # Act: switching it on makes the dependency real, and it appears.
    with_coder = [r.tool for r in collect_requirements(_config(coder={"enabled": True}))]
    assert "claude" in with_coder


def test_a_path_from_another_machine_is_named_in_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: the exact setting that silenced the renderer in production.
    config = _config(diagrams={"mmdc_bin": _LAPTOP_PATH})

    # Act
    with caplog.at_level(logging.WARNING):
        report_tool_health(config)

    # Assert: the operator can act on this line — it names WHAT stopped working and
    # WHY, instead of leaving them to notice a year later in a group chat.
    text = caplog.text
    assert "картинка из mermaid" in text
    assert _LAPTOP_PATH in text


def test_all_tools_present_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange: binaries that certainly exist on any host running these tests.
    config = _config(
        capabilities={"introspection": {"architecture_tools": False, "dev_tools": False}},
        diagrams={"mmdc_bin": "sh"},
    )

    # Act
    with caplog.at_level(logging.WARNING):
        verdicts = report_tool_health(config)

    # Assert: silence here is honest — something WAS checked and found present.
    assert [v.available for v in verdicts] == [True]
    assert "НЕДОСТУПНЫ" not in caplog.text


def test_a_missing_tool_does_not_raise() -> None:
    """🔴 Reports, never refuses — a mute renderer must not stop Bob from living."""
    report_tool_health(_config(diagrams={"mmdc_bin": _LAPTOP_PATH}))


def test_a_broken_probe_does_not_kill_the_boot(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """🔴 «Reports, never refuses» must hold even when the PROBE itself breaks.

    Found by reviewing this bead against its own promise: a check that can raise is a
    worse failure than the muteness it reveals — Bob dead because we asked whether he
    could draw. The startup path calls this before anything else, so an exception here
    would take the whole process with it.
    """
    # Arrange: the resolver blows up the way a hostile filesystem might.
    def _explode(_configured: str) -> str | None:
        msg = "filesystem said no"
        raise OSError(msg)

    monkeypatch.setattr(
        "bob.runtime.wiring.tool_health.resolve_tool", _explode
    )

    # Act: must not raise.
    with caplog.at_level(logging.ERROR):
        verdicts = report_tool_health(_config())

    # Assert: nothing claimed, and the fault is visible rather than swallowed silently.
    assert verdicts == ()
    assert "проверка внешних инструментов сорвалась" in caplog.text
