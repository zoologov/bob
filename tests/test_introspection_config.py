# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``introspection.*`` config defaults (BOB-017 Phase A .2).

The three read-only self-introspection capabilities ship behind one config
section. Unlike the conservative-OFF autonomy/self-improvement switches, this one
defaults ON (read-only, owner-only chat). These assert the defaults dict carries
the whole knob set so the composition root reads it without re-introducing keys.
"""

from __future__ import annotations

from bob.infrastructure.config.loader import ConfigLoader
from bob.runtime.wiring.parameters import (
    _build_architecture_tools_enabled,
    _build_dev_tools_enabled,
)


def _config() -> dict[str, object]:
    return ConfigLoader(yaml_path=None, env={}).load()


def test_introspection_enabled_defaults_on() -> None:
    section = _config()["introspection"]
    assert isinstance(section, dict)
    assert section["enabled"] is True


def test_introspection_carries_the_capability_knobs() -> None:
    section = _config()["introspection"]
    assert isinstance(section, dict)
    assert section["max_output_chars"] == 20000
    assert section["read_max_lines"] == 200
    assert section["beadloom_bin"] == "beadloom"
    assert section["bd_bin"] == "bd"


def test_dev_tools_sub_flag_defaults_off() -> None:
    # BOB-081: the read-only dev-introspection tools (git history + tracker reads) are
    # gated by a SUB-flag that defaults OFF — they ship as one gated piece.
    section = _config()["introspection"]
    assert isinstance(section, dict)
    assert section["dev_tools"] is False


# --- 🔴 the registration gate helper (defense-in-depth, BOB-081.3) ------------


def test_dev_tools_gate_off_by_default_and_on_config() -> None:
    # The exact predicate the wiring uses to gate registering the 4 dev tools. OFF for
    # a missing section, an empty section, or an explicit false; ON only for true —
    # so a stray/absent flag can never accidentally expose the tools.
    assert _build_dev_tools_enabled({}) is False
    assert _build_dev_tools_enabled({"introspection": {}}) is False
    assert _build_dev_tools_enabled({"introspection": {"dev_tools": False}}) is False
    assert _build_dev_tools_enabled({"introspection": {"dev_tools": True}}) is True


# --- BOB-091.1: the architecture tools ride their own sub-flag ------------------


def test_architecture_tools_sub_flag_defaults_off() -> None:
    # The diagram + impact skills ship as one gated piece, OFF until the live smoke.
    section = _config()["introspection"]
    assert isinstance(section, dict)
    assert section["architecture_tools"] is False


def test_architecture_tools_gate_off_by_default_and_on_config() -> None:
    # The exact predicate the wiring uses: OFF for a missing section, an empty section,
    # or an explicit false; ON only for true — a stray flag never exposes the tools.
    assert _build_architecture_tools_enabled({}) is False
    assert _build_architecture_tools_enabled({"introspection": {}}) is False
    assert (
        _build_architecture_tools_enabled(
            {"introspection": {"architecture_tools": False}}
        )
        is False
    )
    assert (
        _build_architecture_tools_enabled(
            {"introspection": {"architecture_tools": True}}
        )
        is True
    )


def test_architecture_tools_is_independent_of_dev_tools() -> None:
    # Two separate sub-flags: switching the tracker/git tools on must not advertise the
    # architecture ones (and vice versa).
    config = {"introspection": {"dev_tools": True}}
    assert _build_dev_tools_enabled(config) is True
    assert _build_architecture_tools_enabled(config) is False
