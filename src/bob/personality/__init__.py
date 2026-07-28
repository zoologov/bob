# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=domain

"""Personality module («кто Боб есть») — Bob's character vertical.

The full "who Bob is" bounded context in one module-vertical (BOB-062.6a): the pure
value objects and domain services of his Higher Mind — mood / taste / disposition /
fascination / phantoms, language & profanity, expression (incl. the verbosity /
engagement vocabulary), voice, the reaction family (aloud / effect / meaning /
judgment), negotiation (stance & conviction), reflection and absence; the port
protocols (:mod:`~bob.personality.ports`); the ``usecases`` half (mood update,
reflection apply / reappraise / parse, fascination & phantom evolution, reaction
perception); and the ``adapters`` half (the Tier-0 reaction judge + the SQLite / kv
fascination & notable-reaction stores).

The package facade re-exports only the stable *ports* — the personality contract the
outer layers (and ``bob.conversation``) depend on. ``bob.domain.ports`` re-exports
these same names for backward compatibility (a thin shim).
"""

from __future__ import annotations

from bob.personality.ports import (
    FascinationStore,
    MessageReactor,
    NotableReactionStore,
    ReflectionReader,
)

__all__ = [
    "FascinationStore",
    "MessageReactor",
    "NotableReactionStore",
    "ReflectionReader",
]
