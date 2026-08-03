# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure work-episode value + its episodic mapping — BOB-087.B1.

A distilled work episode is Bob's first-person operator recollection of a dev session.
:func:`work_episode_event` turns it into an :class:`EpisodicEvent` on a DISTINCT
``event_type`` (``work``, not ``self_action`` — so the existing self-action voice/recall
is untouched, and slice C's register-aware recall has a clean seam). It is tagged
``work``/``dev`` + a provenance marker (the deed is Bob's own operator recollection) and
carries the caller's visibility.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bob.kernel import episode_types as kernel_episode_types
from bob.memory import work_journal
from bob.memory.work_journal import (
    WORK_EVENT_TYPE,
    WorkEpisode,
    work_episode_event,
)
from bob.social.disclosure import VISIBILITY_OWNER_PRIVATE

_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def test_work_event_type_is_distinct_from_self_action() -> None:
    assert WORK_EVENT_TYPE == "work"


def test_work_event_type_is_the_shared_kernel_term_re_exported() -> None:
    """Memory re-exports the KERNEL term — one shared word, no second copy (bob-abk.32).

    The term is shared with ``conversation``/``personality``, so it lives in the kernel;
    ``bob.memory.work_journal`` keeps it on its public surface for existing importers.
    Should the two ever drift apart, this equality is what breaks.
    """
    assert work_journal.WORK_EVENT_TYPE == kernel_episode_types.WORK_EVENT_TYPE
    assert "WORK_EVENT_TYPE" in work_journal.__all__


def test_episode_maps_to_work_event_first_person_content() -> None:
    episode = WorkEpisode(content="я попросил GUPPI починить краш стрима — позеленело")
    event = work_episode_event(
        episode, ts=_NOW, sender_id=42, visibility=VISIBILITY_OWNER_PRIVATE
    )
    assert event.event_type == "work"
    assert event.content == episode.content
    assert event.ts == _NOW
    assert event.sender_id == 42


def test_episode_is_tagged_work_dev_and_provenance() -> None:
    event = work_episode_event(
        WorkEpisode(content="я доделал X"), ts=_NOW, sender_id=None, visibility=None
    )
    assert "work" in event.tags
    assert "dev" in event.tags
    # Provenance marker: the episode is Bob's OWN operator recollection (actor bob).
    assert any(tag.startswith("actor:") for tag in event.tags)


def test_visibility_is_carried_through() -> None:
    event = work_episode_event(
        WorkEpisode(content="я доделал X"),
        ts=_NOW,
        sender_id=None,
        visibility=VISIBILITY_OWNER_PRIVATE,
    )
    assert event.visibility == VISIBILITY_OWNER_PRIVATE
