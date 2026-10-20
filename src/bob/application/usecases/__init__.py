# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Application use-cases — GUPPI's orchestration of domain logic over ports.

Use-cases depend on the domain (through ports) but never on infrastructure
directly; ``bob.app`` wires concrete adapters. They keep I/O at the edges and
delegate all rules to the pure domain.
"""

from __future__ import annotations

from bob.application.usecases.handle_message import HandleMessage
from bob.application.usecases.heartbeat import (
    InnerMonologueTick,
    MoodDriftTick,
    ReflectTick,
)
from bob.personality.usecases.apply_reflection import (
    ApplyReflection,
    ReflectionOutcome,
    ReflectionParser,
    ReflectionSignal,
)
from bob.personality.usecases.reflection_parser import HeuristicReflectionParser
from bob.personality.usecases.update_mood_from_text import (
    TextSignals,
    UpdateMoodFromText,
)

__all__ = [
    "ApplyReflection",
    "HandleMessage",
    "HeuristicReflectionParser",
    "InnerMonologueTick",
    "MoodDriftTick",
    "ReflectTick",
    "ReflectionOutcome",
    "ReflectionParser",
    "ReflectionSignal",
    "TextSignals",
    "UpdateMoodFromText",
]
