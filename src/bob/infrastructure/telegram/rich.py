# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""MarkdownToRichMessage — pure markdown to an aiogram ``RichMessage`` tree.

Bob replies in a small, predictable subset of Markdown. This module turns that
markdown into the **typed** aiogram rich-message representation (a tree of
``RichBlock`` and ``RichText`` nodes) that the gateway then renders as a native
Telegram rich message. The conversion is **pure and deterministic** — no I/O, no
network, no clock — so it is fully unit-testable in isolation.

Block grammar (line-oriented):

* ``# .. ######`` heading       → :class:`RichBlockSectionHeading` (``size`` 1..6)
* ```` ```lang ... ``` ````      → :class:`RichBlockPreformatted` (verbatim body)
* ``> ..``  blockquote           → :class:`RichBlockBlockQuotation`
* ``- ..`` / ``1. ..`` list      → :class:`RichBlockList` of ``RichBlockListItem``
* ``---`` / ``***`` rule         → :class:`RichBlockDivider`
* blank-line-separated text      → :class:`RichBlockParagraph`

Inline spans inside non-code text become typed ``RichText`` runs:

* ``**bold**``                   → :class:`RichTextBold`
* ``*italic*``                   → :class:`RichTextItalic`
* ``` `code` ```                 → :class:`RichTextCode` (body is verbatim)
* ``~~strike~~``                 → :class:`RichTextStrikethrough`
* ``||spoiler||``                → :class:`RichTextSpoiler`
* ``$math$``                     → :class:`RichTextMathematicalExpression`

A single plain run collapses to a bare ``str`` (aiogram's ``RichTextUnion`` leaf);
mixed runs become a ``list``. An optional ``thinking`` note is rendered as a
leading collapsible :class:`RichBlockThinking` block before the answer blocks.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from aiogram.types import (
    RichBlockBlockQuotation,
    RichBlockDivider,
    RichBlockList,
    RichBlockListItem,
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

if TYPE_CHECKING:
    from aiogram.types.rich_block_union import RichBlockUnion
    from aiogram.types.rich_text_union import RichTextUnion

__all__ = ["MarkdownToRichMessage", "RichMessageSerializer"]

_MAX_HEADING_SIZE = 6
_FENCE = "```"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_UNORDERED_RE = re.compile(r"^[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\d+)\.\s+(.*)$")
_DIVIDER_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")

# Inline span markers, longest/most-specific first so e.g. ``**`` wins over ``*``.
# Each entry: (compiled pattern, run builder). The first group is the inner text.
_INLINE_SPECIALS = re.compile(r"\*\*|\*|`|~~|\|\||\$")

# Symmetric inline markers, keyed by the rich-text run type, for serialization.
_INLINE_MARKERS: dict[type, str] = {
    RichTextBold: "**",
    RichTextItalic: "*",
    RichTextStrikethrough: "~~",
    RichTextSpoiler: "||",
}

# Runs that wrap inner ``text`` with a symmetric marker (used by ``_inline``).
_MARKED_RUNS = (
    RichTextBold,
    RichTextItalic,
    RichTextStrikethrough,
    RichTextSpoiler,
)
# Runs whose inner ``text`` is recursed into when flattening to plain text.
_WRAPPED_RUNS = (*_MARKED_RUNS, RichTextCode)


class MarkdownToRichMessage:
    """Convert Bob's markdown reply into an aiogram ``RichMessage`` tree."""

    def convert(self, markdown: str, *, thinking: str | None = None) -> RichMessage:
        """Return the typed rich-message tree for ``markdown``.

        When ``thinking`` is a non-blank string it is rendered as a leading
        collapsible :class:`RichBlockThinking` block, followed by the answer
        blocks parsed from ``markdown``.
        """
        blocks: list[RichBlockUnion] = []
        if thinking is not None and thinking.strip():
            blocks.append(RichBlockThinking(text=thinking.strip()))
        blocks.extend(self._parse_blocks(markdown))
        return RichMessage(blocks=blocks)

    # --- Block parsing --------------------------------------------------------

    def _parse_blocks(self, markdown: str) -> list[RichBlockUnion]:
        lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        blocks: list[RichBlockUnion] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if not stripped:
                index += 1
                continue
            block: RichBlockUnion
            if stripped.startswith(_FENCE):
                block, index = self._take_code(lines, index)
                blocks.append(block)
                continue
            if _DIVIDER_RE.match(stripped):
                blocks.append(RichBlockDivider())
                index += 1
                continue
            heading = _HEADING_RE.match(stripped)
            if heading is not None:
                blocks.append(self._heading(heading))
                index += 1
                continue
            if _QUOTE_RE.match(stripped):
                block, index = self._take_quote(lines, index)
                blocks.append(block)
                continue
            if _UNORDERED_RE.match(stripped) or _ORDERED_RE.match(stripped):
                block, index = self._take_list(lines, index)
                blocks.append(block)
                continue
            block, index = self._take_paragraph(lines, index)
            blocks.append(block)
        return blocks

    def _heading(self, match: re.Match[str]) -> RichBlockSectionHeading:
        size = min(len(match.group(1)), _MAX_HEADING_SIZE)
        return RichBlockSectionHeading(text=self._inline(match.group(2)), size=size)

    def _take_code(
        self, lines: list[str], start: int
    ) -> tuple[RichBlockPreformatted, int]:
        opener = lines[start].strip()
        language = opener[len(_FENCE) :].strip() or None
        body: list[str] = []
        index = start + 1
        while index < len(lines) and lines[index].strip() != _FENCE:
            body.append(lines[index])
            index += 1
        if index < len(lines):  # consume the closing fence
            index += 1
        return RichBlockPreformatted(text="\n".join(body), language=language), index

    def _take_quote(
        self, lines: list[str], start: int
    ) -> tuple[RichBlockBlockQuotation, int]:
        parts: list[str] = []
        index = start
        while index < len(lines):
            match = _QUOTE_RE.match(lines[index].strip())
            if match is None:
                break
            parts.append(match.group(1))
            index += 1
        inner = RichBlockParagraph(text=self._inline(" ".join(parts)))
        return RichBlockBlockQuotation(blocks=[inner]), index

    def _take_list(
        self, lines: list[str], start: int
    ) -> tuple[RichBlockList, int]:
        items: list[RichBlockListItem] = []
        index = start
        while index < len(lines):
            stripped = lines[index].strip()
            ordered = _ORDERED_RE.match(stripped)
            unordered = _UNORDERED_RE.match(stripped)
            if ordered is not None:
                items.append(self._list_item(ordered.group(2), int(ordered.group(1))))
            elif unordered is not None:
                items.append(self._list_item(unordered.group(1), None))
            else:
                break
            index += 1
        return RichBlockList(items=items), index

    def _list_item(self, text: str, value: int | None) -> RichBlockListItem:
        inner = RichBlockParagraph(text=self._inline(text))
        return RichBlockListItem(label="", blocks=[inner], value=value)

    def _take_paragraph(
        self, lines: list[str], start: int
    ) -> tuple[RichBlockParagraph, int]:
        parts: list[str] = []
        index = start
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped or self._is_block_start(stripped):
                break
            parts.append(stripped)
            index += 1
        return RichBlockParagraph(text=self._inline(" ".join(parts))), index

    @staticmethod
    def _is_block_start(stripped: str) -> bool:
        return bool(
            stripped.startswith(_FENCE)
            or _DIVIDER_RE.match(stripped)
            or _HEADING_RE.match(stripped)
            or _QUOTE_RE.match(stripped)
            or _UNORDERED_RE.match(stripped)
            or _ORDERED_RE.match(stripped)
        )

    # --- Inline parsing -------------------------------------------------------

    def _inline(self, text: str) -> RichTextUnion:
        runs = self._inline_runs(text)
        if not runs:
            return ""
        if len(runs) == 1:
            return runs[0]
        return runs

    def _inline_runs(self, text: str) -> list[RichTextUnion]:
        runs: list[RichTextUnion] = []
        buffer = ""
        position = 0
        while position < len(text):
            match = _INLINE_SPECIALS.search(text, position)
            if match is None:
                buffer += text[position:]
                break
            marker = match.group(0)
            start = match.start()
            closer = self._closer(marker)
            close_at = text.find(closer, start + len(marker))
            if close_at == -1:
                buffer += text[position : start + len(marker)]
                position = start + len(marker)
                continue
            buffer += text[position:start]
            if buffer:
                runs.append(buffer)
                buffer = ""
            inner = text[start + len(marker) : close_at]
            runs.append(self._styled_run(marker, inner))
            position = close_at + len(closer)
        if buffer:
            runs.append(buffer)
        return runs

    @staticmethod
    def _closer(marker: str) -> str:
        return marker

    def _styled_run(self, marker: str, inner: str) -> RichTextUnion:
        if marker == "`":  # code body is verbatim — no nested re-parsing
            return RichTextCode(text=inner)
        if marker == "$":
            return RichTextMathematicalExpression(expression=inner)
        nested = self._inline(inner)
        if marker == "**":
            return RichTextBold(text=nested)
        if marker == "*":
            return RichTextItalic(text=nested)
        if marker == "~~":
            return RichTextStrikethrough(text=nested)
        return RichTextSpoiler(text=nested)


class RichMessageSerializer:
    """Render an aiogram ``RichMessage`` tree back to rich-message markdown.

    aiogram's ``InputRichMessage`` accepts Telegram's rich-message **markdown**
    dialect (``InputRichMessage(markdown=...)``); it does not take a block tree on
    the send side. The gateway therefore builds the typed tree (which carries the
    optional thinking block and drives length splitting) and serializes it here
    into that markdown for the wire. Serialization is pure and deterministic.
    """

    def to_markdown(self, message: RichMessage) -> str:
        """Return the rich-message markdown for ``message``."""
        rendered = [self._block(block) for block in message.blocks]
        return "\n\n".join(part for part in rendered if part)

    def _block(self, block: RichBlockUnion) -> str:
        if isinstance(block, RichBlockDivider):
            return "---"
        if isinstance(block, RichBlockSectionHeading | RichBlockPreformatted):
            return self._heading_or_code(block)
        if isinstance(block, RichBlockBlockQuotation):
            return self._quote(block)
        if isinstance(block, RichBlockList):
            return self._list(block)
        return self._text_block(block)

    def _text_block(self, block: RichBlockUnion) -> str:
        """Render the leaf-text blocks (thinking, paragraph) the converter emits."""
        if isinstance(block, RichBlockThinking):
            return f"||{self._flatten(block.text)}||"
        if isinstance(block, RichBlockParagraph):
            return self._inline(block.text)
        return ""  # other rich-block kinds are not produced by the converter

    def _list(self, block: RichBlockList) -> str:
        return "\n".join(self._list_item(item) for item in block.items)

    def _heading_or_code(
        self, block: RichBlockSectionHeading | RichBlockPreformatted
    ) -> str:
        if isinstance(block, RichBlockSectionHeading):
            return f"{'#' * block.size} {self._inline(block.text)}"
        language = block.language or ""
        return f"{_FENCE}{language}\n{self._flatten(block.text)}\n{_FENCE}"

    def _quote(self, block: RichBlockBlockQuotation) -> str:
        inner = self._flatten_blocks(block.blocks)
        return "\n".join(f"> {line}" for line in inner.split("\n"))

    def _list_item(self, item: RichBlockListItem) -> str:
        body = self._flatten_blocks(item.blocks)
        marker = f"{item.value}." if item.value is not None else "-"
        return f"{marker} {body}"

    def _flatten_blocks(self, blocks: list[RichBlockUnion]) -> str:
        return " ".join(self._block(block) for block in blocks)

    def _flatten(self, text: RichTextUnion) -> str:
        """Plain-text flattening (no markers) for code/thinking bodies."""
        if isinstance(text, str):
            return text
        if isinstance(text, list):
            return "".join(self._flatten(part) for part in text)
        if isinstance(text, RichTextMathematicalExpression):
            return text.expression
        if isinstance(text, _WRAPPED_RUNS):
            return self._flatten(text.text)
        return ""

    def _inline(self, text: RichTextUnion) -> str:
        if isinstance(text, str):
            return text
        if isinstance(text, list):
            return "".join(self._inline(part) for part in text)
        if isinstance(text, RichTextCode):  # body is verbatim, not re-styled
            return f"`{self._flatten(text.text)}`"
        if isinstance(text, RichTextMathematicalExpression):
            return f"${text.expression}$"
        if isinstance(text, _MARKED_RUNS):
            marker = _INLINE_MARKERS[type(text)]
            return f"{marker}{self._inline(text.text)}{marker}"
        return self._flatten(text)
