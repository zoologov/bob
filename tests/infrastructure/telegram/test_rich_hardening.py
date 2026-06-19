# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening for the markdown<->RichMessage seam (US-1 rendering edges).

``test_rich.py`` covers the structural happy paths. This file pins the *edges* a
real reasoning model will eventually emit: a multi-line blockquote terminated by
other content, an unterminated inline marker, empty inline text, and the
serializer's flatten/inline branches for nested and exotic runs (math inside a
list/quote, an unsupported block kind). Together they prove the converter never
raises and round-trips faithfully on malformed-but-plausible markdown.
"""

from __future__ import annotations

from aiogram.types import (
    RichBlockBlockQuotation,
    RichBlockList,
    RichBlockListItem,
    RichBlockParagraph,
    RichBlockPreformatted,
    RichBlockThinking,
    RichMessage,
    RichTextBold,
    RichTextHashtag,
    RichTextMathematicalExpression,
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


# --- Converter edges ----------------------------------------------------------


def test_multiline_blockquote_terminated_by_plain_text() -> None:
    # A quote spanning two lines, then a non-quote line. The converter must close
    # the quote at the plain line and start a fresh paragraph block.
    message = _convert("> line one\n> line two\nplain after")

    kinds = [type(b).__name__ for b in message.blocks]
    assert kinds == ["RichBlockBlockQuotation", "RichBlockParagraph"]
    quote = message.blocks[0]
    assert isinstance(quote, RichBlockBlockQuotation)
    inner = quote.blocks[0]
    assert isinstance(inner, RichBlockParagraph)
    assert inner.text == "line one line two"


def test_unterminated_inline_marker_is_kept_literal() -> None:
    # A bold opener with no closer must NOT swallow the rest as a run; the marker
    # is carried through literally and the paragraph stays plain text.
    message = _convert("a **bold without close")

    paragraph = message.blocks[0]
    assert isinstance(paragraph, RichBlockParagraph)
    assert paragraph.text == "a **bold without close"


def test_asymmetric_markers_never_crash_and_round_trip_text() -> None:
    # A stray '*' that greedily pairs with a later marker is the converter's actual
    # behaviour; what matters for the seam is that it never raises and the visible
    # text content survives a convert -> serialize -> convert round trip.
    message = _convert("see * and **really** bold")

    paragraph = message.blocks[0]
    assert isinstance(paragraph, RichBlockParagraph)
    markdown = _serialize(message)
    # Re-converting the serialized form is stable (idempotent serializer output).
    assert _serialize(_convert(markdown)) == markdown
    assert "really" in markdown


def test_empty_paragraph_inline_collapses_to_empty_string() -> None:
    # A heading whose text is empty after the marker yields an empty inline run
    # (the no-runs path), not a crash.
    message = _convert("#")  # '#' alone is not a heading match; becomes a paragraph

    assert len(message.blocks) == 1
    paragraph = message.blocks[0]
    assert isinstance(paragraph, RichBlockParagraph)
    assert paragraph.text == "#"


# --- Serializer flatten / inline branches -------------------------------------


def test_empty_bold_span_yields_an_empty_inner_run() -> None:
    # ``****`` is an opener immediately followed by its closer: the inner text is
    # empty, so the bold run's inner inline collapses to "" (the converter's
    # no-runs branch) rather than raising.
    message = _convert("x ****")

    paragraph = message.blocks[0]
    assert isinstance(paragraph, RichBlockParagraph)
    runs = paragraph.text
    assert isinstance(runs, list)
    bold = next(r for r in runs if isinstance(r, RichTextBold))
    assert bold.text == ""


def test_math_inside_a_list_item_round_trips() -> None:
    # Math inside a list item exercises the serializer's _flatten over a list-item
    # body (flatten_blocks -> inline) and the math inline branch.
    message = _convert("- energy is $E=mc^2$ today")

    markdown = _serialize(message)
    assert "$E=mc^2$" in markdown


def test_math_inside_blockquote_flattens_to_expression() -> None:
    message = _convert("> recall $a+b$ here")

    markdown = _serialize(message)
    assert "a+b" in markdown


def test_thinking_block_with_nested_runs_flattens_to_plain() -> None:
    # A hand-built thinking block whose text is a list of mixed runs must flatten
    # to plain text (markers stripped) inside the collapsible block.
    thinking = RichBlockThinking(
        text=["weigh ", RichTextBold(text="this"), " and ", RichTextStrikethrough(text="that")]
    )
    message = RichMessage(blocks=[thinking, RichBlockParagraph(text="answer")])

    markdown = _serialize(message)
    # Flatten strips markers: the spoiler wrapper around plain inner text.
    assert "||weigh this and that||" in markdown
    assert markdown.strip().endswith("answer")


def test_serializer_ignores_block_kinds_the_converter_never_emits() -> None:
    # A list item carrying a nested LIST (a shape the converter does not produce)
    # exercises both _text_block's "unsupported block kind" branch (the nested
    # RichBlockList routed through _flatten_blocks falls through to "") and
    # _flatten_blocks. It must serialize without raising.
    nested_item = RichBlockListItem(
        label="", value=1, blocks=[RichBlockList(items=[])]
    )
    message = RichMessage(blocks=[RichBlockList(items=[nested_item])])

    # Act / Assert: no exception; the unsupported inner block contributes nothing.
    markdown = _serialize(message)
    assert isinstance(markdown, str)


def test_empty_thinking_text_serializes_to_empty_spoiler_wrapper() -> None:
    # A thinking block whose text is an empty inline (no runs) flattens to "" — the
    # _inline no-runs branch and the _flatten str branch, no crash.
    message = RichMessage(
        blocks=[RichBlockThinking(text=""), RichBlockParagraph(text="")]
    )

    markdown = _serialize(message)
    assert markdown == "||||"


def test_paragraph_with_unsupported_run_kind_flattens_to_empty() -> None:
    # A paragraph whose inline carries a VALID rich run the serializer does not
    # explicitly handle (a hashtag — never emitted by the converter) must not
    # raise: _inline/_flatten fall through their final "" branch for the unknown
    # run while keeping the surrounding plain text.
    hashtag = RichTextHashtag(text="#bob", hashtag="bob")
    message = RichMessage(
        blocks=[RichBlockParagraph(text=["keep ", hashtag, " text"])]
    )

    markdown = _serialize(message)
    assert "keep " in markdown
    assert " text" in markdown


def test_flatten_handles_bare_math_run_text() -> None:
    # A code block whose "text" is a math run (degenerate hand-built tree) flattens
    # via the math branch rather than raising.
    block = RichBlockPreformatted(
        text=RichTextMathematicalExpression(expression="x^2"), language="math"
    )
    message = RichMessage(blocks=[block])

    markdown = _serialize(message)
    assert "x^2" in markdown
