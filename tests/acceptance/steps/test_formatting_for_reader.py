# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the formatting-for-the-reader acceptance scenarios (BOB-086.3).

Binds ``formatting_for_reader.feature`` to two REAL boundaries (never private state):

* S1 / S3 — the composed **system prompt** produced by the real ``VoiceComposer`` gate.
  On a substantive turn (NORMAL/EXPANSIVE) the formatting guidance is folded into the
  prompt the model would receive; on a TERSE (casual) turn it is withheld while the
  short-answer brevity instruction stays intact. We assert on the captured prompt text.
* S2 — the real ``MarkdownToRichMessage`` converter: a markdown GFM table becomes a
  native ``RichBlockTable`` (header row, data rows, per-column alignment) — the outcome
  a Telegram reader sees instead of a monospace wall.
"""

from __future__ import annotations

import asyncio

import pytest
from aiogram.types import RichBlockParagraph, RichBlockTable, RichMessage
from pytest_bdd import given, scenarios, then, when

from bob.infrastructure.telegram.rich import MarkdownToRichMessage
from bob.personality.expression import Verbosity
from bob.personality.voice import formatting_directive
from tests.acceptance.formatting_harness import composed_prompt

scenarios("../features/formatting_for_reader.feature")


class _FormattingContext:
    """Carries the turn's verbosity + captured prompt / rendered message across steps."""

    def __init__(self) -> None:
        self.verbosity: Verbosity = Verbosity.NORMAL
        self.prompt: str = ""
        self.markdown: str = ""
        self.message: RichMessage | None = None

    @property
    def table(self) -> RichBlockTable:
        assert self.message is not None
        tables = [b for b in self.message.blocks if isinstance(b, RichBlockTable)]
        assert len(tables) == 1, "expected exactly one native table block"
        return tables[0]


@pytest.fixture
def formatting_context() -> _FormattingContext:
    return _FormattingContext()


# --- S1: substantive turn carries the formatting directive --------------------


@given("субстантивный ход Боба (развёрнутый, не короткая реплика)")
def substantive_turn(formatting_context: _FormattingContext) -> None:
    formatting_context.verbosity = Verbosity.NORMAL


# --- S3: casual TERSE turn -----------------------------------------------------


@given("короткий casual-ход Боба (болтовня в одну фразу)")
def casual_terse_turn(formatting_context: _FormattingContext) -> None:
    formatting_context.verbosity = Verbosity.TERSE


@when("собран системный промпт для этого хода")
def compose_prompt(formatting_context: _FormattingContext) -> None:
    formatting_context.prompt = asyncio.run(
        composed_prompt(formatting_context.verbosity)
    )


@then("промпт содержит указание форматировать под читателя (списки/таблицы)")
def prompt_contains_formatting_guidance(formatting_context: _FormattingContext) -> None:
    # The WHOLE formatting directive is present verbatim in the composed prompt — Bob is
    # instructed to shape structural content, so he CAN format (we can't run the LLM).
    assert formatting_directive() in formatting_context.prompt
    folded = formatting_context.prompt.casefold()
    assert "под читателя" in folded
    assert "список" in folded or "списк" in folded


@then("промпт называет нативные markdown-таблицы как часть палитры")
def prompt_names_native_tables(formatting_context: _FormattingContext) -> None:
    assert "таблиц" in formatting_context.prompt.casefold()


@then("промпт НЕ содержит формат-директиву")
def prompt_lacks_formatting_directive(formatting_context: _FormattingContext) -> None:
    # On a TERSE turn the formatting directive is withheld — casual chat stays natural.
    assert formatting_directive() not in formatting_context.prompt


@then("указание отвечать коротко одной фразой сохранено")
def prompt_keeps_terse_brevity(formatting_context: _FormattingContext) -> None:
    # The strong short-answer brevity instruction survives untouched on TERSE.
    assert "очень коротко" in formatting_context.prompt.casefold()


# --- S2: markdown table → native RichBlockTable (converter boundary) ----------


@given('список багов markdown-таблицей с колонками «# Приоритет Описание»')
def bug_list_markdown_table(formatting_context: _FormattingContext) -> None:
    formatting_context.markdown = (
        "| # | Приоритет | Описание |\n"
        "|:--|:--------:|---------:|\n"
        "| 1 | P0 | падает импорт |\n"
        "| 2 | P1 | течёт токен |\n"
    )


@when("Боб отрисовывает ответ через конвертер rich-сообщения")
def render_through_converter(formatting_context: _FormattingContext) -> None:
    formatting_context.message = MarkdownToRichMessage().convert(
        formatting_context.markdown
    )


@then("читатель видит нативную таблицу, а не моноширинное полотно")
def reader_sees_native_table(formatting_context: _FormattingContext) -> None:
    assert formatting_context.message is not None
    # A native table block exists (not a prose/paragraph wall).
    assert any(
        isinstance(b, RichBlockTable) for b in formatting_context.message.blocks
    )
    assert not all(
        isinstance(b, RichBlockParagraph) for b in formatting_context.message.blocks
    )


@then("у таблицы есть строка-шапка и строки-данные с правильным выравниванием колонок")
def table_has_header_rows_and_alignment(formatting_context: _FormattingContext) -> None:
    table = formatting_context.table
    header, *data = table.cells
    # Header row is flagged; data rows are not.
    assert all(cell.is_header for cell in header)
    assert [cell.text for cell in header] == ["#", "Приоритет", "Описание"]
    assert len(data) == 2  # two bug rows
    assert not any(cell.is_header for cell in data[0])
    # Per-column alignment comes straight from the separator (:-- / :-: / --:).
    assert [cell.align for cell in header] == ["left", "center", "right"]
    assert [cell.align for cell in data[0]] == ["left", "center", "right"]
