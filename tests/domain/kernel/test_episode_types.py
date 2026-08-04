# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the shared episodic event-type vocabulary — BOB-087 (bob-abk.32).

``WORK_EVENT_TYPE`` is the discriminator PERSISTED in the episodic log and read by
three bounded contexts (memory mints it, conversation filters on it, personality
voices it). It is a shared *term*, not a memory implementation detail, so it lives
in the kernel — the neutral surface every module may import without a peer
domain→domain edge.
"""

from __future__ import annotations

from bob.kernel.episode_types import WORK_EVENT_TYPE


def test_work_event_type_is_the_persisted_work_term() -> None:
    """The term is ``work`` — stable, because episodic rows already carry it."""
    assert WORK_EVENT_TYPE == "work"


def test_work_event_type_is_distinct_from_the_self_action_term() -> None:
    """A work episode is NOT a ``self_action`` deed — the two vocabularies differ."""
    assert WORK_EVENT_TYPE != "self_action"
