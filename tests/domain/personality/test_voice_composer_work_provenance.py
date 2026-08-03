# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Voice-composer WORK-provenance directive wiring (BOB-087.C3).

Register-aware recall (slice C) can surface one of Bob's OWN ``work`` dev episodes in
a reply. When it does, a LIGHT anti-confabulation voice line MUST reach the model — the
mirror of the self_action ownership directive: speak of it in the first person as REAL
work with GUPPI, own a failure honestly, never invent details. These drive the REAL
:class:`~bob.personality.usecases.voice_composer.VoiceComposer` and assert on the
composed system prompt — the true send boundary, never private state. Empty / non-work
recall leaves the prompt byte-identical (the directive is folded ONLY when it fires).
"""

from __future__ import annotations

import asyncio

from bob.memory.work_journal import _WORK_TAGS as _MEMORY_WORK_TAGS
from bob.memory.work_journal import WORK_EVENT_TYPE
from bob.personality.expression import Verbosity
from bob.personality.voice import _WORK_CATEGORY, _WORK_TAGS, recalled_work_directive
from tests.acceptance.formatting_harness import composed_prompt


def test_work_marker_mirror_matches_memory_domain_source_of_truth() -> None:
    # DRIFT-GUARD: voice.py keeps a documented MIRROR of the work provenance markers to
    # avoid a personality→memory import. If the memory-domain source of truth ever changes,
    # the mirror must be updated in lockstep — otherwise the anti-confabulation directive
    # would silently stop firing on real work episodes. This test fails loudly on drift.
    assert _WORK_CATEGORY == WORK_EVENT_TYPE
    assert frozenset(_MEMORY_WORK_TAGS) == _WORK_TAGS


def test_work_directive_folded_when_a_work_episode_is_recalled() -> None:
    recalled = [
        {"content": "я попросил GUPPI поднять лимит — тесты позеленели", "category": "work"},
    ]
    prompt = asyncio.run(composed_prompt(Verbosity.NORMAL, recalled=recalled))

    assert recalled_work_directive() in prompt


def test_work_directive_folded_on_a_work_tag() -> None:
    recalled = [{"content": "я правил runner", "tags": ["dev", "actor:bob"]}]
    prompt = asyncio.run(composed_prompt(Verbosity.NORMAL, recalled=recalled))

    assert recalled_work_directive() in prompt


def test_no_work_directive_when_recall_has_no_work_episode() -> None:
    recalled = [{"content": "Ada любит чай", "category": "preference"}]
    prompt = asyncio.run(composed_prompt(Verbosity.NORMAL, recalled=recalled))

    assert recalled_work_directive() not in prompt


def test_no_work_directive_on_empty_recall() -> None:
    prompt = asyncio.run(composed_prompt(Verbosity.NORMAL))

    assert recalled_work_directive() not in prompt
