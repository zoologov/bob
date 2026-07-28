# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Состояния permission-request — чистый StrEnum жизненного цикла (BOB-052 .1).

``PermissionState`` — строковый ``Enum`` (значение совпадает с тем, что кладётся в
SQLite TEXT-колонку, так round-trip тривиален). Не-авторизованный участник просит
привилегированное → Боб заводит ``PENDING`` и спрашивает owner; решение owner двигает
запрос в ``APPROVED`` (исполнить) или ``DENIED`` (мягкий отказ); ``EXPIRED`` —
протух / отменён новым запросом.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["PermissionState"]


class PermissionState(StrEnum):
    """Состояние permission-request — гейтед под owner-решением.

    ``PENDING`` (ждёт решения owner) → ``APPROVED`` (owner разрешил → исполнить) /
    ``DENIED`` (owner отказал → мягкий отказ). ``EXPIRED`` — протух или вытеснен
    новым запросом того же просящего.
    """

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
