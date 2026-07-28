# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=application

"""Personality use-cases — orchestration of Bob's character logic over ports.

Mood update from text, reflection apply / reappraise / parse, and fascination &
phantom evolution (+ their source trackers). They depend on the personality domain
(through ports) but never on infrastructure directly; ``bob.app`` wires the concrete
adapters. This package ``__init__`` is the module façade — sibling use-cases may
reference each other through it. (Being-received reaction perception — a cross-domain
use-case over mood + relationship — lives in
``bob.application.usecases.perceive_reaction``.)
"""

from __future__ import annotations

from bob.personality.usecases.apply_reflection import (
    ApplyReflection,
    ReflectionOutcome,
    ReflectionParser,
    ReflectionSignal,
)
from bob.personality.usecases.evolve_fascination import EvolveFascination
from bob.personality.usecases.evolve_phantoms import EvolvePhantoms
from bob.personality.usecases.fascination_sources import (
    RepoFascinationGrounding,
    StoreFascinationReader,
)
from bob.personality.usecases.reappraise_reflection import (
    ReappraisalOutcome,
    ReappraiseReflection,
)
from bob.personality.usecases.reflection_parser import HeuristicReflectionParser
from bob.personality.usecases.update_mood_from_text import (
    TextSignals,
    UpdateMoodFromText,
)

__all__ = [
    "ApplyReflection",
    "EvolveFascination",
    "EvolvePhantoms",
    "HeuristicReflectionParser",
    "ReappraisalOutcome",
    "ReappraiseReflection",
    "ReflectionOutcome",
    "ReflectionParser",
    "ReflectionSignal",
    "RepoFascinationGrounding",
    "StoreFascinationReader",
    "TextSignals",
    "UpdateMoodFromText",
]
