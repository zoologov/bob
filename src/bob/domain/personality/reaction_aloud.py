# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality

"""Being-received acknowledgment hint — "вижу, тебе зашло про…" (BOB-050 .3).

One pure helper, :func:`acknowledgment_hint`. When someone reacted warmly to one of
Bob's recent messages (a :class:`~bob.domain.personality.reaction_effect.NotableReaction`
the perceiving use-case recorded), Bob may — rarely, when it fits — acknowledge it in
his next reply. This turns that record into ONE light compose-context HINT the reply
tier can fold in naturally: who reacted, with what emoji, on what Bob had said. It is a
HINT, never a scripted phrase Bob must utter — the "if it fits / not obligatory" wording
keeps it a suggestion, so Bob weaves it in himself or lets it pass (not needy).

Pure and deterministic: it only formats the record. The RARE decision (a low-frequency
seeded roll) and the per-person containment live in the application layer; here there is
no I/O and no policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.domain.personality.reaction_effect import NotableReaction


def acknowledgment_hint(note: NotableReaction) -> str:
    """Return ONE light HINT line about ``note`` — a warm reaction Bob may acknowledge.

    The line names the reactor, the emoji, and a short excerpt of what Bob had said,
    then frames the mention as OPTIONAL ("если к месту", "не обязательно") so the reply
    tier folds it in naturally or lets it pass — never a forced, scripted phrase. Pure;
    no I/O.
    """
    return (
        f"Замечено: {note.reactor_name} недавно тепло отреагировал ({note.emoji}) "
        f"на твоё «{note.bob_excerpt}» — можешь естественно отметить это, "
        f"если к месту (не обязательно)."
    )
