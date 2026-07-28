# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``repeat.*`` config builder (BOB-026 .3).

``_build_repeat_thresholds`` is the composition-root seam that turns the optional
``repeat`` config section into the conservative :class:`RepeatThresholds` injected
into both the reply guard (BOB-026 .1) and the reflect-tick dedup (BOB-026 .2).
Covered here because the dev waves exercised the thresholds object and its two
consumers, but never the config-parsing seam itself.
"""

from __future__ import annotations

import pytest

from bob.app import _build_repeat_thresholds
from bob.conversation.conversation import RepeatThresholds


def test_repeat_config_absent_section_yields_conservative_defaults() -> None:
    # Arrange: config without a ``repeat`` section at all.
    config: dict[str, object] = {}

    # Act
    thresholds = _build_repeat_thresholds(config)

    # Assert: falls back to the dataclass defaults (window=5, threshold=0.9).
    assert thresholds == RepeatThresholds()


def test_repeat_config_overrides_window_and_threshold() -> None:
    # Arrange: both knobs supplied.
    config = {"repeat": {"window": 8, "similarity_threshold": 0.75}}

    # Act
    thresholds = _build_repeat_thresholds(config)

    # Assert: both flow through verbatim.
    assert thresholds.window == 8
    assert thresholds.similarity_threshold == 0.75


def test_repeat_config_partial_section_keeps_defaults_for_missing_keys() -> None:
    # Arrange: only the window is set; the threshold key is absent.
    config = {"repeat": {"window": 3}}

    # Act
    thresholds = _build_repeat_thresholds(config)

    # Assert: window overridden, threshold falls back to the conservative default.
    assert thresholds.window == 3
    assert thresholds.similarity_threshold == RepeatThresholds().similarity_threshold


def test_repeat_config_invalid_values_fall_back_to_defaults() -> None:
    # Arrange: garbage types for both knobs (a non-numeric string, a bool).
    config = {"repeat": {"window": "lots", "similarity_threshold": True}}

    # Act
    thresholds = _build_repeat_thresholds(config)

    # Assert: invalid -> conservative defaults (never a crash, never a bool threshold).
    assert thresholds == RepeatThresholds()


def test_repeat_config_string_window_digits_are_parsed() -> None:
    # Arrange: env-style string ints are accepted by the int reader.
    config = {"repeat": {"window": "4"}}

    # Act
    thresholds = _build_repeat_thresholds(config)

    # Assert
    assert thresholds.window == 4


def test_repeat_config_out_of_range_threshold_is_rejected() -> None:
    # Arrange: a similarity threshold above 1.0 is invalid for the dataclass invariant.
    config = {"repeat": {"similarity_threshold": 1.5}}

    # Act / Assert: the builder surfaces the dataclass guard rather than silently
    # wiring an impossible threshold.
    with pytest.raises(ValueError, match="similarity_threshold"):
        _build_repeat_thresholds(config)


def test_repeat_config_tic_knobs_default_when_absent() -> None:
    # BOB-036 .1: with no tic.* keys, the phrase-tic knobs fall back to the defaults.
    thresholds = _build_repeat_thresholds({})

    assert thresholds.tic_min_words == RepeatThresholds().tic_min_words
    assert thresholds.tic_min_occurrences == RepeatThresholds().tic_min_occurrences


def test_repeat_config_overrides_tic_knobs() -> None:
    # BOB-036 .1: both tic knobs flow through verbatim.
    config = {"repeat": {"tic_min_words": 4, "tic_min_occurrences": 3}}

    thresholds = _build_repeat_thresholds(config)

    assert thresholds.tic_min_words == 4
    assert thresholds.tic_min_occurrences == 3


def test_repeat_config_tic_lookback_defaults_when_absent() -> None:
    # BOB-043: with no ``tic_lookback`` key, the wide-lookback window falls back to
    # the conservative dataclass default.
    thresholds = _build_repeat_thresholds({})

    assert thresholds.tic_lookback == RepeatThresholds().tic_lookback


def test_repeat_config_overrides_tic_lookback() -> None:
    # BOB-043: the wide closer-lookback window is tunable via ``repeat.tic_lookback``.
    config = {"repeat": {"tic_lookback": 30}}

    thresholds = _build_repeat_thresholds(config)

    assert thresholds.tic_lookback == 30
