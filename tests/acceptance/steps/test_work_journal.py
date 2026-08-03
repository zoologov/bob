# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the work-journal scenarios (BOB-087 Срез B).

Binds ``work_journal.feature`` to :mod:`tests.acceptance.work_journal_harness`, which folds a
real dev-session firehose into bounded facts, distils them (fake Tier-0 model) with the REAL
recorder into a REAL SQLite store as ``work`` episodes, then reads them back through the REAL
recall + disclosure gate. The scenarios assert Bob's OBSERVABLE take-away — what he recalls,
to whom, on which domain — never the store's internals. The operator-voice scenario asserts
the REAL voice directives that colour how Bob talks about his coding work.

The scenarios are synchronous (pytest-bdd), so the async write/read path runs via
``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from bob.coding import session_voice
from bob.coding.work_facts import WorkOutcome
from bob.personality.voice import operator_stance
from tests.acceptance.work_journal_harness import (
    WorkJournalOutcome,
    run_dev_session,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

scenarios("../features/work_journal.feature")

# The first-person answer the fake Tier-0 model returns for the recorded session — concrete
# files/tests/fix, operator framing, one memory per line (what a real local model would emit).
_MODEL_REPLY = (
    "я попросил GUPPI починить краш стрима в interactive_runner.py — буфер рвался на >64 КБ\n"
    "тесты в work_facts.py сперва падали, подняли лимит буфера — позеленело\n"
    "GUPPI прогнал весь набор, всё зелёное — довёл до конца"
)


def _firehose() -> list[Mapping[str, object]]:
    """A realistic raw stream-json firehose: many events, a few key facts inside."""
    return [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "смотрю"}]}},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/interactive_runner.py"}},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "tests/work_facts.py"}},
        {"type": "tool_use", "name": "Write", "input": {"file_path": "src/work_facts.py"}},
        {"type": "tool_result", "content": "1 failed, 3 passed", "is_error": True},
        {"type": "tool_result", "content": "buffer over 64KB", "is_error": True},
        {"type": "tool_result", "content": "=== 42 passed in 1.2s ==="},
    ]


@dataclass(slots=True)
class _JournalContext:
    """The slate the steps share: isolated store root, the flag, and the outcome."""

    tmp_path: Path
    journal_enabled: bool = True
    events: list[Mapping[str, object]] = field(default_factory=_firehose)
    outcome: WorkJournalOutcome = field(default_factory=WorkJournalOutcome)
    voice_operator: str = ""


@pytest.fixture
def journal_context(tmp_path: Path) -> _JournalContext:
    """A fresh, isolated SQLite store per scenario."""
    return _JournalContext(tmp_path=tmp_path)


# --- Given: the recorded session + the flag -------------------------------------


@given(
    "dev-сессия правила файлы interactive_runner.py и work_facts.py, "
    "тесты падали и позеленели"
)
def a_recorded_dev_session(journal_context: _JournalContext) -> None:
    # The default firehose already encodes exactly this; assert it carries the substance.
    assert journal_context.events, "нет событий сессии"


@given("флаг memory.work_journal включён")
def flag_on(journal_context: _JournalContext) -> None:
    journal_context.journal_enabled = True


@given("флаг memory.work_journal выключен")
def flag_off(journal_context: _JournalContext) -> None:
    journal_context.journal_enabled = False


# --- When: the owner asks / Bob tunes his voice ---------------------------------


@when("владелец спрашивает, что Боб делал с interactive_runner.py")
def owner_asks_about_the_file(journal_context: _JournalContext) -> None:
    journal_context.outcome = asyncio.run(
        run_dev_session(
            journal_context.tmp_path,
            journal_enabled=journal_context.journal_enabled,
            events=journal_context.events,
            task="почини краш стрима в interactive_runner.py",
            outcome=WorkOutcome.FINISHED,
            model_reply=_MODEL_REPLY,
            question="что ты делал с interactive_runner.py и тестами?",
        )
    )


@when("Боб настраивает свой голос для работы с кодом")
def bob_tunes_coding_voice(journal_context: _JournalContext) -> None:
    journal_context.voice_operator = operator_stance()


# --- Then: Bob's observable take-away -------------------------------------------


@then(
    "всплывает детальное воспоминание Боба от первого лица про конкретные файлы и тесты"
)
def detailed_first_person_recall(journal_context: _JournalContext) -> None:
    surfaced = " | ".join(journal_context.outcome.owner_recall)
    assert surfaced, "работа не всплыла из памяти"
    assert "я " in surfaced, f"воспоминание не от первого лица: {surfaced!r}"
    assert "interactive_runner.py" in surfaced, (
        f"нет конкретики про файл: {surfaced!r}"
    )
    assert "тест" in surfaced.casefold(), f"нет конкретики про тесты: {surfaced!r}"
    # NOT a generic stub and NOT a raw firehose dump: no stream-json machinery leaked.
    assert "tool_use" not in surfaced
    assert "file_path" not in surfaced
    assert "is_error" not in surfaced


@then("в память легло 1-3 эпизода, а не построчный дамп всего потока событий")
def bounded_episode_count(journal_context: _JournalContext) -> None:
    outcome = journal_context.outcome
    count = len(outcome.stored_work)
    assert 1 <= count <= 3, f"ожидалось 1-3 эпизода, легло {count}"
    # The bound is real: many raw events collapsed into a handful of episodes.
    assert count < outcome.raw_event_count


@then("ничего не всплывает — работа не попала в память")
def nothing_recalled(journal_context: _JournalContext) -> None:
    assert journal_context.outcome.owner_recall == (), (
        f"работа всплыла при выключенном флаге: {journal_context.outcome.owner_recall!r}"
    )


@then("в память не легло НИ ОДНОГО work-эпизода")
def no_work_episode_stored(journal_context: _JournalContext) -> None:
    assert journal_context.outcome.stored_work == (), (
        "work-эпизод осел при выключенном флаге (память не байт-в-байт)"
    )


@then("work-эпизод несёт провенанс actor:bob и теги work/dev")
def episode_carries_provenance(journal_context: _JournalContext) -> None:
    stored = journal_context.outcome.stored_work
    assert stored, "не осело ни одного work-эпизода"
    for row in stored:
        tags = str(row.get("tags", ""))
        assert "actor:bob" in tags, f"нет провенанса actor:bob: {tags!r}"
        assert "work" in tags
        assert "dev" in tags


@then("владельцу он всплывает, а гостю — нет (owner-приватно)")
def owner_sees_guest_does_not(journal_context: _JournalContext) -> None:
    outcome = journal_context.outcome
    assert outcome.owner_recall, "владелец не увидел свою рабочую память"
    assert outcome.guest_recall == (), (
        f"гость увидел owner-приватную рабочую память: {outcome.guest_recall!r}"
    )


@then("всплывает он на домене work, не смешиваясь с личными эпизодами")
def surfaces_on_work_domain(journal_context: _JournalContext) -> None:
    categories = journal_context.outcome.recalled_categories
    assert categories, "не всплыло ни одного эпизода"
    assert all(cat == "work" for cat in categories), (
        f"work-память смешалась с другим доменом: {categories!r}"
    )


@then("он держит операторскую рамку — ставит задачу GUPPI и рулит им")
def voice_holds_operator_frame(journal_context: _JournalContext) -> None:
    stance = journal_context.voice_operator.casefold()
    assert "оператор" in stance
    assert "guppi" in stance
    # The PR milestone line speaks as director: GUPPI is the executor Bob refers to.
    assert "guppi" in session_voice.pr("https://x/pull/1").casefold()


@then(
    "он не пересказывает построчно каждую правку, а реагирует на вехи своими словами"
)
def voice_reacts_not_narrates(journal_context: _JournalContext) -> None:
    stance = journal_context.voice_operator.casefold()
    # The reinforced BOB-074 anti-narration stance: reactions, not a per-edit log.
    assert "построчно" in stance
    assert "лог" in stance
