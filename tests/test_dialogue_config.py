# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``dialogue.*`` config builder (BOB-044).

``_build_recent_turns`` is the composition-root seam that turns the optional
``dialogue.recent_turns`` config key into the recent-history replay window injected
into :class:`~bob.application.usecases.handle_message.HandleMessage`. The window is
how many recent conversation turns Bob replays into the reply context so he holds the
dialogue thread; widened from the old hardcoded 6 to a default of 14 (BOB-044). This
is the conversation-replay window only — independent of the anti-repeat ``repeat.*``
windows (BOB-026/036) and the wide tic-guard ``repeat.tic_lookback`` (BOB-043).
"""

from __future__ import annotations

import pytest

from bob.app import _DEFAULT_RECENT_TURNS, _build_recent_turns
from bob.infrastructure.config.loader import DEFAULT_CONFIG


def test_recent_turns_absent_section_yields_widened_default() -> None:
    # Arrange: config without a ``dialogue`` section at all.
    config: dict[str, object] = {}

    # Act
    recent_turns = _build_recent_turns(config)

    # Assert: falls back to the widened default (14), not the old hardcoded 6.
    assert recent_turns == _DEFAULT_RECENT_TURNS
    assert recent_turns == 14


def test_default_config_ships_the_widened_window() -> None:
    # The built-in defaults carry the widened conversation-replay window.
    assert DEFAULT_CONFIG["dialogue"]["recent_turns"] == 14
    assert _build_recent_turns(DEFAULT_CONFIG) == 14


def test_recent_turns_override_flows_through() -> None:
    # Arrange: an explicit, wider window for a persona holding longer arcs.
    config = {"dialogue": {"recent_turns": 20}}

    # Act / Assert
    assert _build_recent_turns(config) == 20


def test_recent_turns_string_digits_are_parsed() -> None:
    # Env-style string ints are accepted by the int reader.
    config = {"dialogue": {"recent_turns": "18"}}

    assert _build_recent_turns(config) == 18


def test_recent_turns_invalid_type_falls_back_to_default() -> None:
    # Arrange: a non-numeric value -> the conservative default (never a crash).
    config = {"dialogue": {"recent_turns": "lots"}}

    # Act / Assert
    assert _build_recent_turns(config) == _DEFAULT_RECENT_TURNS


def test_recent_turns_zero_is_rejected() -> None:
    # A window that replays nothing is a misconfiguration, not a silent no-op.
    config = {"dialogue": {"recent_turns": 0}}

    with pytest.raises(ValueError, match="recent_turns"):
        _build_recent_turns(config)


def test_recent_turns_negative_is_rejected() -> None:
    # A negative window is invalid.
    config = {"dialogue": {"recent_turns": -3}}

    with pytest.raises(ValueError, match="recent_turns"):
        _build_recent_turns(config)
