# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``build_roster_config`` — the ``social.roster.*`` config accessor (BOB-080).

The roster ships inert behind the bare ``social.roster`` flag (образец
``presence.stream_read``): off (the default) → disabled, so no roster is ever built.
The thresholds ``social.roster.newcomer_days`` (time-window for "new") and
``social.roster.limit`` (cap) fall back to conservative defaults. This accessor only
READS config into a :class:`RosterConfig`; bead .2 consumes it in the usecase.
"""

from __future__ import annotations

from bob.runtime.wiring.roster import RosterConfig, build_roster_config


def test_flag_off_by_default() -> None:
    cfg = build_roster_config({})

    assert cfg.enabled is False
    assert cfg.newcomer_days == 7.0
    assert cfg.limit == 6


def test_flag_explicit_false_stays_off() -> None:
    assert build_roster_config({"social": {"roster": False}}).enabled is False


def test_flag_on_enables() -> None:
    assert build_roster_config({"social": {"roster": True}}).enabled is True


def test_flag_env_string_true_enables() -> None:
    assert build_roster_config({"social": {"roster": "true"}}).enabled is True


def test_thresholds_override() -> None:
    config = {
        "social": {
            "roster": True,
            "roster_newcomer_days": 3.5,
            "roster_limit": 10,
        }
    }

    cfg = build_roster_config(config)

    assert cfg.newcomer_days == 3.5
    assert cfg.limit == 10


def test_invalid_thresholds_fall_back_to_defaults() -> None:
    config = {"social": {"roster_newcomer_days": "soon", "roster_limit": "lots"}}

    cfg = build_roster_config(config)

    assert cfg == RosterConfig(enabled=False, newcomer_days=7.0, limit=6)
