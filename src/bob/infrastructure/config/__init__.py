# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Layered configuration loading (defaults -> YAML -> env)."""

from bob.infrastructure.config.loader import DEFAULT_CONFIG, ConfigLoader

__all__ = ["DEFAULT_CONFIG", "ConfigLoader"]
