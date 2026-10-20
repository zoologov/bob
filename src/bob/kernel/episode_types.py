# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Shared episodic event-type vocabulary — the terms several modules agree on.

An episode is stored with an ``event_type`` discriminator (see
:class:`~bob.memory.entities.EpisodicEvent`). Most of those terms are private to the
module that mints them; a few are a genuine SHARED language — written by one context
and read by others:

* :data:`WORK_EVENT_TYPE` — Bob's distilled first-person *operator* recollection of a
  dev session. ``memory`` mints it (:func:`~bob.memory.work_journal.work_episode_event`)
  and keys register-aware recall on it, ``conversation`` filters it out of the spoken
  thread (BOB-087.C8), ``personality`` voices its provenance directive.

The term lives HERE, in the shared kernel, precisely because it is shared: parking it
in ``memory`` forced ``conversation`` into a peer domain→domain import and closed the
cycle ``conversation → memory → runtime-app → conversation`` (bob-abk.32). The kernel is
the neutral surface every module may import, so the shared word costs no edge. Values
are PERSISTED in the episodic log — changing one rewrites history, so they are stable.

* :data:`Recalled` — the shape of one recalled memory item. ``memory`` returns it from
  recall, ``conversation`` and ``personality`` read it — both BELOW ``memory`` in the
  runtime order, so the type lives here rather than in ``memory`` (BOB-113).
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = ["WORK_EVENT_TYPE", "Recalled"]

# A single recalled memory item (content + relevance score), returned by recall.
type Recalled = Mapping[str, object]

# The episodic ``event_type`` of a distilled work episode — DISTINCT from ``self_action``
# so the existing self-action voice/recall stays byte-identical and register-aware recall
# keys on this domain marker (BOB-087.B1).
WORK_EVENT_TYPE = "work"
