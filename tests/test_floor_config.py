# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``addressivity.floor.*`` config builders (BOB-025 .2).

``_build_floor_enabled`` and ``_build_floor_config`` are the composition-root seams
that turn the optional ``addressivity.floor`` section into the BOB-025 conversation
floor wiring: the kill-switch (whether a floor store is wired at all) and the
:class:`FloorConfig` (timeout + silent-reset) injected into HandleMessage. Covered
here because the dev wave exercised the resolve/advance integration on fakes, but
never the config-parsing seam itself.
"""

from __future__ import annotations

import pytest

from bob.app import _build_floor_config, _build_floor_enabled
from bob.conversation.conversation_floor import FloorConfig


def test_floor_enabled_defaults_true_when_section_absent() -> None:
    # The floor is the BOB-025 mechanism: on by default, even with no config section.
    assert _build_floor_enabled({}) is True


def test_floor_enabled_explicit_false_disables() -> None:
    # The kill-switch: enabled=false → no floor store is wired (BOB-023 behaviour).
    config = {"addressivity": {"floor": {"enabled": False}}}

    assert _build_floor_enabled(config) is False


def test_floor_enabled_env_string_false_disables() -> None:
    # Tolerates an env-style string boolean.
    config = {"addressivity": {"floor": {"enabled": "false"}}}

    assert _build_floor_enabled(config) is False


def test_floor_config_absent_section_yields_conservative_defaults() -> None:
    # No floor section → the dataclass defaults (timeout 300s, reset after 2 silent).
    assert _build_floor_config({}) == FloorConfig()


def test_floor_config_overrides_timeout_and_reset() -> None:
    # Both knobs flow through verbatim.
    config = {
        "addressivity": {"floor": {"timeout_seconds": 120, "reset_after_silent": 3}}
    }

    cfg = _build_floor_config(config)

    assert cfg.timeout_seconds == 120
    assert cfg.reset_after_silent == 3


def test_floor_config_partial_section_keeps_defaults_for_missing_keys() -> None:
    # Only the timeout is set; the reset key falls back to the conservative default.
    config = {"addressivity": {"floor": {"timeout_seconds": 600}}}

    cfg = _build_floor_config(config)

    assert cfg.timeout_seconds == 600
    assert cfg.reset_after_silent == FloorConfig().reset_after_silent


def test_floor_config_invalid_values_fall_back_to_defaults() -> None:
    # Garbage types (a non-numeric string, a bool) → conservative defaults, never a crash.
    config = {
        "addressivity": {"floor": {"timeout_seconds": "soon", "reset_after_silent": True}}
    }

    assert _build_floor_config(config) == FloorConfig()


def test_floor_config_non_positive_timeout_is_rejected() -> None:
    # A non-positive timeout violates the domain invariant — surfaced, never wired.
    config = {"addressivity": {"floor": {"timeout_seconds": 0}}}

    with pytest.raises(ValueError, match="timeout_seconds"):
        _build_floor_config(config)
