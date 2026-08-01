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
