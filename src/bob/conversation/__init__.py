# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Conversation module («как ведётся ход») — Bob's turn-conduct vertical.

The full "how a turn is conducted" bounded context in one module-vertical
(BOB-062.6a): the pure decisions of a running exchange — addressivity, the
conversation floor & continuity, brevity & engagement (returning personality
expression VOs), the zone classifier, interim lines, response choice, and the
response / volatility judgments; the port protocols
(:mod:`~bob.conversation.ports`, incl. :class:`~bob.conversation.ports.ZoneClassifier`);
the ``usecases`` half (:mod:`~bob.conversation.usecases.decide_response`); and the
``adapters`` half (the Tier-0 response / volatility / interim judges + the SQLite
conversation-floor & closer-log stores).

This vertical depends on :mod:`bob.personality` one-directionally (a turn asks the
character *how* to speak); personality never imports conversation. The package facade
re-exports only the stable *ports*.
"""

from __future__ import annotations

from bob.conversation.ports import (
    CloserLog,
    ConversationFloorStore,
    ZoneClassifier,
)

__all__ = [
    "CloserLog",
    "ConversationFloorStore",
    "ZoneClassifier",
]
