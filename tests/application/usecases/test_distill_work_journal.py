# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Tier-0 work-journal distiller — BOB-087.B1.

``parse_work_episodes`` is the mutation core: it turns the model's multi-line answer into
1-3 first-person :class:`WorkEpisode`s (bullets/numbering stripped, blanks dropped, capped),
and any malformed/empty answer degrades to an empty tuple. ``Tier0WorkJournalDistiller``
mirrors ``ClassifyCodingIntent``: a single cheap Tier-0 call, parsed conservatively, and a
flaky model degrades to no episodes (best-effort — never raises into the session).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.coding.usecases.distill_work_journal import (
    _MAX_EPISODES,
    Tier0WorkJournalDistiller,
    parse_work_episodes,
)
from bob.coding.work_facts import SessionKeyFacts, WorkOutcome

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class _FakeProvider:
    """Tier-0 provider returning a fixed answer (or raising)."""

    def __init__(self, answer: str, *, raises: bool = False) -> None:
        self._answer = answer
        self._raises = raises
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.calls += 1
        if self._raises:
            raise RuntimeError("local model down")
        return self._answer


def _distiller(answer: str, *, raises: bool = False) -> Tier0WorkJournalDistiller:
    provider = _FakeProvider(answer, raises=raises)
    router = LLMRouter(providers={0: provider})
    return Tier0WorkJournalDistiller(router=router)


_FACTS = SessionKeyFacts(
    files=("interactive_runner.py",), tests_failed=True, errors=("over 64KB",)
)


# --- parse_work_episodes (pure mutation core) ---------------------------------


def test_parses_lines_into_episodes() -> None:
    text = "я попросил GUPPI починить краш\nтесты падали на >64 КБ\nподняли лимит — позеленело"
    episodes = parse_work_episodes(text)
    assert [e.content for e in episodes] == [
        "я попросил GUPPI починить краш",
        "тесты падали на >64 КБ",
        "подняли лимит — позеленело",
    ]


def test_strips_bullets_and_numbering() -> None:
    text = "- я правил runner\n* GUPPI гонял тесты\n1. позеленело\n2) открыл PR"
    contents = [e.content for e in parse_work_episodes(text)]
    assert contents == ["я правил runner", "GUPPI гонял тесты", "позеленело"]  # capped at 3


def test_drops_blank_lines() -> None:
    text = "я доделал X\n\n   \nя открыл PR"
    contents = [e.content for e in parse_work_episodes(text)]
    assert contents == ["я доделал X", "я открыл PR"]


def test_caps_at_max_episodes() -> None:
    text = "\n".join(f"эпизод {i}" for i in range(_MAX_EPISODES + 4))
    assert len(parse_work_episodes(text)) == _MAX_EPISODES


def test_empty_answer_yields_no_episodes() -> None:
    assert parse_work_episodes("") == ()
    assert parse_work_episodes("   \n\n  ") == ()


# --- Tier0WorkJournalDistiller (adapter) --------------------------------------


async def test_distills_via_tier0_call() -> None:
    distiller = _distiller("я починил стрим в runner — позеленело")
    episodes = await distiller.distill("почини стрим", _FACTS, WorkOutcome.FINISHED)
    assert [e.content for e in episodes] == ["я починил стрим в runner — позеленело"]


async def test_flaky_model_degrades_to_no_episodes() -> None:
    distiller = _distiller("...", raises=True)
    assert await distiller.distill("почини стрим", _FACTS, WorkOutcome.FINISHED) == ()


async def test_routes_on_local_work_journal_task() -> None:
    provider = _FakeProvider("я доделал X")
    router = LLMRouter(providers={0: provider})
    distiller = Tier0WorkJournalDistiller(router=router)

    await distiller.distill("задача", _FACTS, WorkOutcome.FINISHED)

    assert provider.calls == 1
    assert TaskType.WORK_JOURNAL.value == "work_journal"
