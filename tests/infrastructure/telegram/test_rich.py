# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``MarkdownToRichMessage`` — the pure markdown to RichMessage tree.

The converter is deterministic and side-effect free: given Bob's markdown reply it
returns an aiogram :class:`RichMessage` (a tree of typed ``RichBlock`` / ``RichText``
nodes). These tests assert the block structure (headings, lists, code, blockquote,
divider, paragraphs) and the inline styling (bold, italic, code, strikethrough,
spoiler, math), plus the optional ``thinking`` prepend rendered as a collapsible
``RichBlockThinking`` block.
"""

from __future__ import annotations

from aiogram.types import (
    RichBlockBlockQuotation,
    RichBlockDivider,
    RichBlockList,
    RichBlockParagraph,
    RichBlockPreformatted,
    RichBlockSectionHeading,
    RichBlockTable,
    RichBlockThinking,
    RichMessage,
    RichTextBold,
    RichTextCode,
    RichTextItalic,
    RichTextMathematicalExpression,
    RichTextSpoiler,
    RichTextStrikethrough,
)

from bob.infrastructure.telegram.rich import (
    MarkdownToRichMessage,
    RichMessageSerializer,
)


def _convert(markdown: str, *, thinking: str | None = None) -> RichMessage:
    return MarkdownToRichMessage().convert(markdown, thinking=thinking)


def _serialize(message: RichMessage) -> str:
    return RichMessageSerializer().to_markdown(message)


# --- Block structure ----------------------------------------------------------


def test_plain_text_becomes_a_single_paragraph() -> None:
    message = _convert("hello bob")

    assert len(message.blocks) == 1
    block = message.blocks[0]
    assert isinstance(block, RichBlockParagraph)
    assert block.text == "hello bob"


def test_blank_lines_split_paragraphs() -> None:
    message = _convert("first para\n\nsecond para")

    assert [type(b) for b in message.blocks] == [
        RichBlockParagraph,
        RichBlockParagraph,
    ]
    assert isinstance(message.blocks[0], RichBlockParagraph)
    assert message.blocks[0].text == "first para"
    assert isinstance(message.blocks[1], RichBlockParagraph)
    assert message.blocks[1].text == "second para"


def test_headings_map_to_section_heading_with_size() -> None:
    message = _convert("# Title\n\n### Sub")

    assert isinstance(message.blocks[0], RichBlockSectionHeading)
    assert message.blocks[0].text == "Title"
    assert message.blocks[0].size == 1
    assert isinstance(message.blocks[1], RichBlockSectionHeading)
    assert message.blocks[1].text == "Sub"
    assert message.blocks[1].size == 3


def test_fenced_code_becomes_preformatted_with_language() -> None:
    message = _convert("```python\nprint(1)\nprint(2)\n```")

    block = message.blocks[0]
    assert isinstance(block, RichBlockPreformatted)
    assert block.text == "print(1)\nprint(2)"
    assert block.language == "python"


def test_fenced_code_without_language_has_no_language() -> None:
    message = _convert("```\nraw\n```")

    block = message.blocks[0]
    assert isinstance(block, RichBlockPreformatted)
    assert block.text == "raw"
    assert block.language is None


def test_fenced_code_preserves_markdown_specials_verbatim() -> None:
    message = _convert("```\n# not a heading\n- not a list\n```")

    block = message.blocks[0]
    assert isinstance(block, RichBlockPreformatted)
    assert block.text == "# not a heading\n- not a list"


def test_blockquote_becomes_block_quotation() -> None:
    message = _convert("> quoted line\n> still quoted")

    block = message.blocks[0]
    assert isinstance(block, RichBlockBlockQuotation)
    assert len(block.blocks) == 1
    inner = block.blocks[0]
    assert isinstance(inner, RichBlockParagraph)
    assert inner.text == "quoted line still quoted"


def test_unordered_list_becomes_list_block() -> None:
    message = _convert("- one\n- two")

    block = message.blocks[0]
    assert isinstance(block, RichBlockList)
    assert len(block.items) == 2
    first = block.items[0]
    assert len(first.blocks) == 1
    inner = first.blocks[0]
    assert isinstance(inner, RichBlockParagraph)
    assert inner.text == "one"


def test_ordered_list_becomes_list_with_values() -> None:
    message = _convert("1. alpha\n2. beta")

    block = message.blocks[0]
    assert isinstance(block, RichBlockList)
    assert [item.value for item in block.items] == [1, 2]


def test_divider_rule_becomes_divider() -> None:
    message = _convert("above\n\n---\n\nbelow")

    assert [type(b) for b in message.blocks] == [
        RichBlockParagraph,
        RichBlockDivider,
        RichBlockParagraph,
    ]
    assert isinstance(message.blocks[1], RichBlockDivider)


# --- Inline styling -----------------------------------------------------------


def test_bold_span() -> None:
    message = _convert("a **bold** b")

    block = message.blocks[0]
    assert isinstance(block, RichBlockParagraph)
    runs = block.text
    assert isinstance(runs, list)
    assert runs[0] == "a "
    assert isinstance(runs[1], RichTextBold)
    assert runs[1].text == "bold"
    assert runs[2] == " b"


def test_italic_span() -> None:
    message = _convert("an *italic* word")

    block = message.blocks[0]
    assert isinstance(block, RichBlockParagraph)
    runs = block.text
    assert isinstance(runs, list)
    assert isinstance(runs[1], RichTextItalic)
    assert runs[1].text == "italic"


def test_inline_code_span() -> None:
    message = _convert("call `func()` now")

    block = message.blocks[0]
    assert isinstance(block, RichBlockParagraph)
    runs = block.text
    assert isinstance(runs, list)
    assert isinstance(runs[1], RichTextCode)
    assert runs[1].text == "func()"


def test_strikethrough_span() -> None:
    message = _convert("~~gone~~ now")

    block = message.blocks[0]
    assert isinstance(block, RichBlockParagraph)
    runs = block.text
    assert isinstance(runs, list)
    assert isinstance(runs[0], RichTextStrikethrough)
    assert runs[0].text == "gone"


def test_spoiler_span() -> None:
    message = _convert("a ||secret|| b")

    block = message.blocks[0]
    assert isinstance(block, RichBlockParagraph)
    runs = block.text
    assert isinstance(runs, list)
    assert isinstance(runs[1], RichTextSpoiler)
    assert runs[1].text == "secret"


def test_math_span() -> None:
    message = _convert("euler $e^{i\\pi}+1=0$ done")

    block = message.blocks[0]
    assert isinstance(block, RichBlockParagraph)
    runs = block.text
    assert isinstance(runs, list)
    expr = runs[1]
    assert isinstance(expr, RichTextMathematicalExpression)
    assert expr.expression == "e^{i\\pi}+1=0"


def test_inline_code_is_not_styled_inside() -> None:
    # Markdown specials inside inline code are literal, not re-parsed.
    message = _convert("`**not bold**`")

    block = message.blocks[0]
    assert isinstance(block, RichBlockParagraph)
    runs = block.text
    assert isinstance(runs, RichTextCode)
    assert runs.text == "**not bold**"


# --- Thinking -----------------------------------------------------------------


def test_thinking_prepends_collapsible_block() -> None:
    message = _convert("the answer", thinking="i should be brief")

    assert isinstance(message.blocks[0], RichBlockThinking)
    assert message.blocks[0].text == "i should be brief"
    # The answer blocks follow the thinking block.
    assert isinstance(message.blocks[1], RichBlockParagraph)
    assert message.blocks[1].text == "the answer"


def test_no_thinking_block_when_absent() -> None:
    message = _convert("plain answer")

    assert not any(isinstance(b, RichBlockThinking) for b in message.blocks)


def test_blank_thinking_is_ignored() -> None:
    message = _convert("answer", thinking="   ")

    assert not any(isinstance(b, RichBlockThinking) for b in message.blocks)


# --- Empty / whitespace -------------------------------------------------------


def test_empty_markdown_yields_no_blocks() -> None:
    message = _convert("   \n\n  ")

    assert message.blocks == []


def test_empty_markdown_with_thinking_yields_only_thinking() -> None:
    message = _convert("", thinking="just a thought")

    assert len(message.blocks) == 1
    assert isinstance(message.blocks[0], RichBlockThinking)


# --- Serializer: RichMessage tree -> Telegram rich-message markdown -----------


def test_serialize_paragraph_with_inline_styles() -> None:
    out = _serialize(_convert("a **bold** and *italic* and `code`"))

    assert out == "a **bold** and *italic* and `code`"


def test_serialize_heading() -> None:
    out = _serialize(_convert("## Section"))

    assert out == "## Section"


def test_serialize_code_block_with_language() -> None:
    out = _serialize(_convert("```python\nx = 1\n```"))

    assert out == "```python\nx = 1\n```"


def test_serialize_list_and_blockquote() -> None:
    out = _serialize(_convert("- one\n- two\n\n> quoted"))

    assert out == "- one\n- two\n\n> quoted"


def test_serialize_divider() -> None:
    out = _serialize(_convert("above\n\n---\n\nbelow"))

    assert out == "above\n\n---\n\nbelow"


def test_serialize_thinking_block() -> None:
    out = _serialize(_convert("answer", thinking="a thought"))

    # Thinking renders as a collapsible spoiler-style note ahead of the answer.
    assert "a thought" in out
    assert out.strip().endswith("answer")


def test_serialize_strikethrough_spoiler_math() -> None:
    out = _serialize(_convert("~~x~~ ||y|| $z$"))

    assert out == "~~x~~ ||y|| $z$"


# --- GFM tables ---------------------------------------------------------------


def test_gfm_table_becomes_table_with_header_and_data_cells() -> None:
    message = _convert("| H1 | H2 |\n|----|----|\n| a | b |")

    block = message.blocks[0]
    assert isinstance(block, RichBlockTable)
    assert len(block.cells) == 2  # header row + one data row
    header = block.cells[0]
    assert all(cell.is_header for cell in header)
    assert [cell.text for cell in header] == ["H1", "H2"]
    data = block.cells[1]
    assert not any(cell.is_header for cell in data)
    assert [cell.text for cell in data] == ["a", "b"]


def test_gfm_table_column_alignment_from_separator() -> None:
    message = _convert("| L | C | R |\n|:---|:--:|---:|\n| a | b | c |")

    block = message.blocks[0]
    assert isinstance(block, RichBlockTable)
    assert [cell.align for cell in block.cells[0]] == ["left", "center", "right"]
    # Alignment applies to the data row too.
    assert [cell.align for cell in block.cells[1]] == ["left", "center", "right"]


def test_gfm_table_default_alignment_is_left() -> None:
    message = _convert("| H |\n|---|\n| x |")

    block = message.blocks[0]
    assert isinstance(block, RichBlockTable)
    assert block.cells[0][0].align == "left"


def test_gfm_table_cell_valign_is_middle() -> None:
    message = _convert("| H |\n|---|\n| x |")

    block = message.blocks[0]
    assert isinstance(block, RichBlockTable)
    assert block.cells[0][0].valign == "middle"


def test_gfm_table_cell_preserves_inline_formatting() -> None:
    message = _convert("| Name | Note |\n|---|---|\n| **bob** | `code` |")

    block = message.blocks[0]
    assert isinstance(block, RichBlockTable)
    bold_cell = block.cells[1][0]
    assert isinstance(bold_cell.text, RichTextBold)
    assert bold_cell.text.text == "bob"
    code_cell = block.cells[1][1]
    assert isinstance(code_cell.text, RichTextCode)
    assert code_cell.text.text == "code"


def test_gfm_table_header_only_no_data_rows_is_valid() -> None:
    message = _convert("| H1 | H2 |\n|---|---|")

    block = message.blocks[0]
    assert isinstance(block, RichBlockTable)
    assert len(block.cells) == 1  # just the header row


def test_gfm_table_after_paragraph_text_is_recognized() -> None:
    message = _convert("intro line\n| H1 | H2 |\n|---|---|\n| a | b |")

    assert isinstance(message.blocks[0], RichBlockParagraph)
    assert message.blocks[0].text == "intro line"
    assert isinstance(message.blocks[1], RichBlockTable)


# --- GFM tables: graceful degradation -----------------------------------------


def test_malformed_table_missing_separator_degrades_to_paragraph() -> None:
    blocks = _convert("| H1 | H2 |\n| a | b |").blocks

    assert not any(isinstance(b, RichBlockTable) for b in blocks)
    assert all(isinstance(b, RichBlockParagraph) for b in blocks)


def test_ragged_table_columns_degrade_to_paragraph() -> None:
    blocks = _convert("| H1 | H2 |\n|---|---|\n| only-one |").blocks

    assert not any(isinstance(b, RichBlockTable) for b in blocks)


def test_lone_pipe_line_degrades_and_does_not_crash() -> None:
    blocks = _convert("|").blocks

    assert not any(isinstance(b, RichBlockTable) for b in blocks)
    assert isinstance(blocks[0], RichBlockParagraph)


def test_spoiler_line_is_not_mistaken_for_a_table() -> None:
    # ``||spoiler||`` contains pipes but is not a GFM table.
    message = _convert("a ||secret|| b")

    block = message.blocks[0]
    assert isinstance(block, RichBlockParagraph)
    assert not isinstance(block, RichBlockTable)


# --- GFM tables: serialization round-trip -------------------------------------


def test_serialize_gfm_table_round_trips() -> None:
    out = _serialize(_convert("| H1 | H2 |\n|:---|---:|\n| a | b |"))

    assert out == "| H1 | H2 |\n| :--- | ---: |\n| a | b |"


def test_serialize_gfm_table_center_alignment() -> None:
    out = _serialize(_convert("| H |\n|:--:|\n| x |"))

    assert out == "| H |\n| :--: |\n| x |"


# --- Regression: existing subset unchanged by table support -------------------


def test_existing_subset_round_trips_byte_identical() -> None:
    # Every pre-table block/inline kind must survive convert->serialize unchanged.
    doc = (
        "# Title\n\n"
        "para with **bold** and *italic* and `code`\n\n"
        "- one\n"
        "- two\n\n"
        "> quoted\n\n"
        "```python\n"
        "x = 1\n"
        "```\n\n"
        "---\n\n"
        "~~x~~ ||y|| $z$"
    )

    assert _serialize(_convert(doc)) == doc
