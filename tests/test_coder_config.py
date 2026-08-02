# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``coder.*`` config section (BOB-039 .3, gated «Bob runs Claude Code»).

The master switch ``enabled`` defaults OFF (conservative — the most powerful capability
stays unwired until the owner switches it on). These assert the defaults dict carries the
knob set and that the gated coding capability is NEVER on the autonomous safe-allowlist.
"""

from __future__ import annotations

from bob.infrastructure.config.loader import ConfigLoader


def _config() -> dict[str, object]:
    return ConfigLoader(yaml_path=None, env={}).load()


def test_coder_master_switch_defaults_off() -> None:
    section = _config()["coder"]
    assert isinstance(section, dict)
    assert section["enabled"] is False


def test_coder_carries_runtime_knobs() -> None:
    section = _config()["coder"]
    assert isinstance(section, dict)
    assert section["claude_bin"] == "claude"
    assert section["gh_bin"] == "gh"
    assert section["worktree_root"] == ".worktrees"
    assert section["timeout"] == 600
    # The execute mode is an apply mode — never a bypass mode.
    assert section["permission_mode"] == "acceptEdits"


def test_coder_stream_via_guppi_defaults_off() -> None:
    # Firehose-via-GUPPI (BOB-087.A1) ships inert: default OFF → the coder stream stays on
    # Bob's bot exactly as before (byte-identical), Bob's voice always on Bob's bot.
    section = _config()["coder"]
    assert isinstance(section, dict)
    assert section["stream_via_guppi"] is False


def test_coding_capability_is_never_on_the_autonomous_safe_allowlist() -> None:
    # The gated coding session is owner-driven, never autonomous: it must NOT leak into
    # ``goals.safe_capabilities`` (the self-directed tick's allowlist).
    goals = _config()["goals"]
    assert isinstance(goals, dict)
    assert goals["safe_capabilities"] == []
