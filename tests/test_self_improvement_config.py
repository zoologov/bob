# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``self_improvement.*`` config placeholders (BOB-028 .2).

The detector (.2) ships the config SECTION; the master switch ``enabled`` defaults
OFF (full app-wiring is .3). These assert the defaults dict carries the knob set so
.3 can wire it without re-introducing the keys, and that OFF is the conservative
default (behaviour exactly as before BOB-028).
"""

from __future__ import annotations

from bob.infrastructure.config.loader import ConfigLoader


def _config() -> dict[str, object]:
    return ConfigLoader(yaml_path=None, env={}).load()


def test_self_improvement_master_switch_defaults_off() -> None:
    section = _config()["self_improvement"]
    assert isinstance(section, dict)
    assert section["enabled"] is False


def test_self_improvement_carries_detector_knobs() -> None:
    section = _config()["self_improvement"]
    assert isinstance(section, dict)
    assert section["detect_cadence"] == 20
    assert section["detector_tier"] == 1
    assert section["max_active_rules"] == 5
    assert section["max_magnitude"] == 0.3
