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
