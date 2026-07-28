# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты PermissionState — StrEnum жизненного цикла permission-request (BOB-052 .1).

Значение каждого состояния — стабильная строка (round-trip с TEXT-колонкой SQLite);
проверяем сами литералы и членство.
"""

from __future__ import annotations

from bob.social.permission.state import PermissionState


def test_state_string_values() -> None:
    assert PermissionState.PENDING.value == "pending"
    assert PermissionState.APPROVED.value == "approved"
    assert PermissionState.DENIED.value == "denied"
    assert PermissionState.EXPIRED.value == "expired"


def test_state_round_trips_through_string() -> None:
    for state in PermissionState:
        assert PermissionState(state.value) is state
