# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Capability seam — the registry GUPPI uses to advertise and execute skills."""

from __future__ import annotations

from bob.application.capabilities.recall_memory import make_recall_memory_capability
from bob.application.capabilities.registry import (
    CapabilityRegistry,
    UnknownCapabilityError,
)
from bob.application.capabilities.search_memory import make_search_memory_capability
from bob.application.capabilities.tool_loop import ToolLoop

__all__ = [
    "CapabilityRegistry",
    "ToolLoop",
    "UnknownCapabilityError",
    "make_recall_memory_capability",
    "make_search_memory_capability",
]
