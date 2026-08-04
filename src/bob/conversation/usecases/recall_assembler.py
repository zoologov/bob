# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=application

"""RecallAssembler — replay the recent thread + texture a turn's context (BOB-044/045/050).

The turn's «what recent conversation + light social texture grounds the reply» concern in
one cohesive collaborator (extracted from ``HandleMessage`` in BOB-062.6b, wave 2,
behavior-preserving):

* :meth:`replay_recent_thread` replays the SHARED recent thread of the whole topic
  (BOB-058 .1) — the last ``recent_turns`` episodes across ALL participants, author-labeled;
* :meth:`absence_for` folds a light long-gap "haven't seen you in a while" hint for the
  CURRENT person (per-person over the shared thread, BOB-045 .3); and
* :meth:`acknowledgment_for` OCCASIONALLY folds a per-person "being received"
  acknowledgment when someone reacted warmly to one of Bob's messages (BOB-050 .3).

🔴 :meth:`acknowledgment_for` reads the notable-reaction marker BEFORE the seeded roll, so
an unlucky turn spends no draw and LEAVES the marker for later; a lucky turn CLEARS it
(consume-once). It shares the SAME injected ``Random`` as every other turn collaborator, so
the per-turn draw order (plan → engagement → verbosity → addressivity → surface/**ack**) is
unchanged. Every read is turn-local through arguments — nothing per-turn is held on this
shared-singleton collaborator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.conversation.thread import (
    _author_key,
    _history_for_author,
    _last_seen_at,
    _thread_without_work_journal,
)
from bob.personality.absence import absence_hint
from bob.personality.reaction_aloud import acknowledgment_hint

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from random import Random

    from bob.application.usecases.handle_message import EpisodeReader
    from bob.kernel.ports import Clock
    from bob.personality.ports import NotableReactionStore
    from bob.social.interlocutor import Interlocutor


class RecallAssembler:
    """Replay the recent thread + add absence / acknowledgment texture (BOB-044/045/050)."""

    def __init__(
        self,
        *,
        episodes: EpisodeReader,
        recent_turns: int,
        absence_hint_hours: float,
        notable_reaction: NotableReactionStore | None,
        acknowledge_reaction_freq: float,
        clock: Clock,
        rng: Random,
    ) -> None:
        self._episodes = episodes
        self._recent_turns = recent_turns
        self._absence_hint_hours = absence_hint_hours
        self._notable_reaction = notable_reaction
        self._acknowledge_reaction_freq = acknowledge_reaction_freq
        self._clock = clock
        self._rng = rng

    async def replay_recent_thread(
        self, interlocutor: Interlocutor | None
    ) -> Sequence[Mapping[str, object]]:
        """Replay the SHARED recent thread of the whole topic (BOB-058 .1).

        The conversation context for judgment + reply is the group's recent thread —
        the last ``recent_turns`` episodes across ALL participants (``recent_episodes``),
        already author-labeled ``"<name>: …\\nbob: …"``. So Bob hears the whole room and
        holds the multi-party thread: when Vladimir asks Bob to answer Lyosha, Alexey's
        film message is right there in the context (US-1/2/3) instead of hidden behind a
        per-person replay. Memory is unified for the closed group (BOB-051), so the shared
        read is safe — it is ordinary topic traffic, not owner-private material.

        Scope hook (BOB-058 .1): a PUBLIC group reads the shared thread. A future
        PRIVATE/DM scope would read the CURRENT interlocutor's per-person slice
        (``recent_episodes_for(interlocutor.sender_id, …)``) instead — only the public
        group exists today, so the per-person branch is intentionally NOT wired here. The
        ``interlocutor`` argument is retained as the seam that a private scope would key on.

        🔴 The thread is CONVERSATION (BOB-087.C8): Bob's distilled ``work`` journal entries
        share the episodic log but are not turns anybody spoke, so they are left out of the
        replay — otherwise they would enter every chat's compose prompt with no relevance
        gate, no register and no provenance. His work returns through register-aware RECALL.
        With the work journal off there is no such row and the replay is byte-identical.
        """
        del interlocutor  # public group → shared thread (see the scope hook above)
        return _thread_without_work_journal(
            await self._episodes.recent_episodes(self._recent_turns)
        )

    def absence_for(
        self,
        history: Sequence[Mapping[str, object]],
        interlocutor: Interlocutor | None,
    ) -> str | None:
        """A light long-gap absence hint for the CURRENT person, or ``None`` (BOB-045 .3).

        🔴 Per-person over the SHARED thread (BOB-058 .3): ``history`` is now the whole
        group's recent thread, so the last-seen must be filtered to the CURRENT author's
        own turns (by ``sender_id``, robust to homonyms / renames — the ``"<name>:"`` label
        stays only for rendering) before reading the freshest timestamp — a DIFFERENT member
        speaking recently must never reset THIS person's gap. Via the pure :func:`absence_hint`
        domain helper the
        gap to ``self._clock.now()`` becomes a SHORT neutral note Bob can fold in to notice
        the pause humanly. Returns ``None`` — add no line, unchanged behaviour — when the
        current author has no turn in the shared window (graceful, exactly like an empty
        history today), on an unparseable timestamp, a gap under the configured threshold,
        or the hint disabled (``absence_hint_hours == 0``). Deterministic given the clock.
        """
        mine = _history_for_author(history, _author_key(interlocutor))
        last_seen = _last_seen_at(mine)
        if last_seen is None:
            return None
        return absence_hint(
            last_seen, self._clock.now(), threshold_hours=self._absence_hint_hours
        )

    async def acknowledgment_for(self, interlocutor: Interlocutor | None) -> str:
        """A RARE being-received acknowledgment hint for THIS person, or "" (BOB-050 .3).

        When someone reacted warmly to one of Bob's recent messages, Bob may — at the
        small seeded ``acknowledge_reaction_freq`` — fold ONE light HINT into the compose
        context so he can naturally mention being received (he weaves it himself; never a
        scripted phrase). Returns ``""`` — add no line, behave as before — unless ALL hold:
        a store is wired, a notable reaction is on record, its reactor is THIS interlocutor
        (per-person / BOB-019 authz: a guest's reaction never surfaces to the owner and
        vice-versa; an anonymous reaction has no person to acknowledge), and the seeded roll
        lands inside the low frequency. The marker is read BEFORE the roll, so an unlucky
        turn spends no draw and LEAVES the marker for a later turn; on a lucky turn it is
        CLEARED (consumed) so Bob acknowledges the moment at most once — never needy. The
        whole call is wrapped by ``_safe_addon`` at the call site, so a store failure is
        dropped silently (decorative, never an outage notice).
        """
        if self._notable_reaction is None or interlocutor is None:
            return ""
        note = await self._notable_reaction.latest()
        if note is None or note.sender_id is None:
            return ""
        if note.sender_id != interlocutor.sender_id:
            return ""
        if self._rng.random() >= self._acknowledge_reaction_freq:
            return ""
        await self._notable_reaction.clear()
        return acknowledgment_hint(note)
