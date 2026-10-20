# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Thread projection — turn the persisted conversation thread into turn signals.

Pure, no-I/O projections of the already-replayed per-person / shared thread (the
episodes ``EpisodeReader`` replays, each stored as ``"<name>: <text>\\nbob:
<reply>"``) into the small signals a single turn reads:

* :func:`_render_thread` — the judge's recent-thread snippet (BOB-049).
* :func:`_reaction_marker` — Bob's persisted half for a REACT turn (BOB-049).
* :func:`_last_seen_at` — the freshest prior-turn timestamp for the absence hint
  (BOB-045 .3).
* :func:`_recent_bob_replies` — Bob's recent replies for the anti-repeat window
  (BOB-026 .1).
* :func:`_strip_recalled_closer` — excise a recurring closer motif from a recalled
  exemplar so it is not fed back as few-shot (BOB-061 .2).
* :func:`_author_key` / :func:`_history_for_author` — attribute the now-shared thread
  to the current author by robust ``sender_id`` (BOB-058 .3).
* :func:`_user_turns` — the owner's own turns for repeat detection (BOB-022).
* :func:`_thread_without_work_journal` — drop Bob's distilled ``work`` journal entries: the
  thread is conversation, his work comes back through register-aware recall (BOB-087.C8).

These were lifted verbatim out of ``HandleMessage`` (BOB-062.6b Wave 0): the use-case
orchestrates, the projection lives here in the conversation domain.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from bob.conversation.conversation import strip_recurring_closer
from bob.kernel.episode_types import WORK_EVENT_TYPE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.kernel.episode_types import Recalled
    from bob.social.interlocutor import Interlocutor


def _reaction_marker(emoji: str) -> str:
    """Bob's persisted half for a REACT turn: the meaning-chosen emoji (BOB-049)."""
    return f"(реакция: {emoji})"


def _thread_without_work_journal(
    history: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    """Drop Bob's distilled ``work`` journal entries from the replayed thread (BOB-087.C8).

    The recent thread is CONVERSATION — what was actually said in the room. A ``work``
    episode (:data:`~bob.kernel.episode_types.WORK_EVENT_TYPE`) is not a turn anybody spoke:
    it is the first-person operator journal Bob writes to himself when a coding session
    ends, sharing the same episodic log. Replayed as history it would enter EVERY chat's
    compose prompt with no relevance gate, no register and no provenance framing — the
    widest of the casual-pollution doors. His work belongs in RECALL instead, where the
    register decides whether it surfaces and the provenance directive rides with it.

    Pure and order-preserving; ONLY the known work marker is dropped (a defensive default —
    a digest / self_action / unlabeled row replays untouched), so while the work journal is
    off there is no such row and the thread is byte-identical.
    """
    return tuple(item for item in history if not _is_work_journal(item))


def _is_work_journal(item: Mapping[str, object]) -> bool:
    """True when a replayed episode is one of Bob's distilled ``work`` journal entries."""
    kind = item.get("event_type")
    return isinstance(kind, str) and kind.casefold() == WORK_EVENT_TYPE


def _render_thread(history: Sequence[Mapping[str, object]]) -> str:
    """Render the shared recent thread into the judge's recent-thread snippet (BOB-049).

    Joins each replayed episode's ``content`` (stored as ``"<name>: <text>\\nbob:
    <reply>"``) oldest-first; an empty history yields ``""`` (the judge reads it as a
    fresh thread). No I/O — a pure projection of the already-replayed history (BOB-058 .1:
    the shared group thread, author-labeled).
    """
    return "\n".join(
        str(item.get("content", "")) for item in history if item.get("content")
    )


def _last_seen_at(history: Sequence[Mapping[str, object]]) -> datetime | None:
    """Return the timestamp of the person's MOST RECENT prior turn, or ``None`` (BOB-045 .3).

    The replayed per-person ``history`` is oldest-first, so the freshest prior turn is
    the last one carrying a parseable ``ts`` (the ISO-8601 string the episode store
    persists, or a ``datetime`` if already typed). Scans back to front and returns the
    first such timestamp; an empty history (first contact) or rows with no/garbled ``ts``
    yield ``None``, so the absence hint simply does not fire — never a crash. No I/O.
    """
    for item in reversed(list(history)):
        ts = item.get("ts")
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts)
            except ValueError:
                continue
    return None


# Marker prefixing Bob's turn inside a persisted episode's ``content`` (see
# :meth:`HandleMessage._persist`, which writes "<sender>: <text>\nbob: <reply>").
_BOB_TURN_MARKER = "\nbob: "


def _recent_bob_replies(
    history: Sequence[Mapping[str, object]], *, limit: int
) -> tuple[str, ...]:
    """Return Bob's last ``limit`` reply texts (freshest first) from history (BOB-026 .1).

    Episodes are stored as ``"<sender>: <text>\\nbob: <reply>"`` (see
    :meth:`HandleMessage._persist`); this scans the most-recent episodes back to
    front and recovers the ``bob:`` half of each so the anti-repeat guard can compare
    the fresh reply against a WINDOW of Bob's own recent replies — not just the last —
    catching a repeat "через ход". No Bob turn on record yields an empty tuple.
    """
    replies: list[str] = []
    for item in reversed(list(history)):
        if len(replies) >= limit:
            break
        content = item.get("content")
        if not isinstance(content, str):
            continue
        marker = content.rfind(_BOB_TURN_MARKER)
        if marker != -1:
            replies.append(content[marker + len(_BOB_TURN_MARKER) :])
    return tuple(replies)


def _strip_recalled_closer(item: Recalled, closer: str) -> Recalled:
    """Return ``item`` with the recurring ``closer`` stripped off its content (BOB-061 .2).

    On a detected closer-tic, the recalled exemplar's whole-turn content (
    ``"<sender>: <text>\\nbob: <reply>"``) may END with the tic motif — feeding it back as
    few-shot would reinforce the very ending the nudge is trying to break. This excises the
    trailing motif sentence via :func:`strip_recurring_closer` (the SAME deterministic strip
    the anti-repeat guard uses) and returns a shallow copy carrying the tidied content. When
    the content does not end with the motif (nothing to strip) or is not a string, the
    original ``item`` is returned untouched — the fact body is always preserved.
    """
    content = item.get("content")
    if not isinstance(content, str):
        return item
    stripped = strip_recurring_closer(content, closer)
    if stripped == content:
        return item
    updated = dict(item)
    updated["content"] = stripped
    return updated


# Separator between a turn's sender label and the user's message text inside a
# persisted episode's ``content`` ("<sender>: <text>\nbob: <reply>"); the user half
# is what sits between this and ``_BOB_TURN_MARKER`` (see :meth:`HandleMessage._persist`).
_SENDER_TEXT_SEPARATOR = ": "


def _author_key(interlocutor: Interlocutor | None) -> int | None:
    """The CURRENT author's ``sender_id`` signal key, or ``None`` when unresolved (BOB-058 .3).

    Per-person signals (absence, anti-repeat) over the SHARED thread key on the ROBUST
    ``sender_id`` — the same identity the per-person stores (relationship BOB-014,
    first-impression BOB-019) already use — NOT the parsed ``"<name>:"`` label. The label
    is brittle as a signal key: homonymous members cross-attribute, a display name with a
    ``": "`` or a rename between turns silently drops the signal. ``None`` — no perception
    seam, no interlocutor, or an unresolved ``sender_id`` — means "do not filter": the
    signal falls back to the whole window, exactly as before perception was wired.
    """
    return interlocutor.sender_id if interlocutor is not None else None


def _history_for_author(
    history: Sequence[Mapping[str, object]], sender_id: int | None
) -> list[Mapping[str, object]]:
    """Filter the shared thread to the episodes authored by ``sender_id`` (BOB-058 .3).

    Keeps ordering (oldest-first) so the per-person signals — absence last-seen,
    anti-repeat turns — see only the CURRENT author's own turns even though ``history``
    now interleaves the whole group. Episodes are attributed by their persisted
    ``sender_id`` (robust to homonyms / renames / a ``": "`` in the display name — the
    human-readable ``"<name>:"`` label is only for rendering the thread, never the signal
    key). ``sender_id is None`` (unresolved identity) means "do not filter" → the full
    window is returned (the pre-BOB-058 degraded behaviour).
    """
    if sender_id is None:
        return list(history)
    return [item for item in history if item.get("sender_id") == sender_id]


def _user_turns(
    history: Sequence[Mapping[str, object]], sender_id: int | None = None
) -> list[str]:
    """Recover the USER half of each replayed episode (BOB-022 repeat detection).

    Episodes are stored as ``"<name>: <text>\\nbob: <reply>"`` (see
    :meth:`HandleMessage._persist`); this extracts the ``<text>`` between the first
    ``"<name>: "`` and the ``"\\nbob: "`` marker for each episode so the user-repeat
    predicate compares the current message ONLY against prior USER turns — never against
    Bob's own replies. 🔴 BOB-058 .3: over the now-SHARED thread, ``sender_id`` (when given)
    restricts the turns to the CURRENT author's episodes BY ID, so a DIFFERENT member's
    similar line is not mistaken for this person repeating themselves. Episodes without
    the expected shape are skipped.
    """
    turns: list[str] = []
    for item in _history_for_author(history, sender_id):
        content = item.get("content")
        if not isinstance(content, str):
            continue
        marker = content.find(_BOB_TURN_MARKER)
        head = content[:marker] if marker != -1 else content
        sep = head.find(_SENDER_TEXT_SEPARATOR)
        if sep == -1:
            continue
        user_text = head[sep + len(_SENDER_TEXT_SEPARATOR) :]
        if user_text:
            turns.append(user_text)
    return turns
