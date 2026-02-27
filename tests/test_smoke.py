# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Smoke test: project imports correctly."""

import bob


def test_bob_package_is_importable() -> None:
    assert bob is not None
