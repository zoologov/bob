# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure mermaid fenced-block extraction/strip helpers (BOB-037).

These are pure, side-effect-free string functions — no I/O, no rendering — so they
are tested in isolation: extracting the mermaid source out of a fenced ```mermaid
block, stripping those blocks from the visible reply text, and normalising a source
for the dedup comparison. The auto-render reliability fix (BOB-037 A) composes them
with a renderer in the application layer. (ASCII prose labels are used in the
fixtures only to keep the ambiguous-Cyrillic lint quiet — the helpers are language
agnostic.)
"""

from __future__ import annotations

from bob.domain.diagrams.mermaid_blocks import (
    extract_mermaid_blocks,
    normalize_mermaid,
    strip_mermaid_blocks,
)


def test_extract_one_mermaid_block() -> None:
    text = "Diagram:\n```mermaid\ngraph TD; A-->B\n```\nDone."

    assert extract_mermaid_blocks(text) == ["graph TD; A-->B"]


def test_extract_returns_empty_when_no_mermaid() -> None:
    assert extract_mermaid_blocks("plain text with no diagram") == []


def test_extract_ignores_a_plain_code_fence() -> None:
    # A non-mermaid fenced block (e.g. python) is NOT a diagram.
    text = "```python\nprint('hi')\n```"

    assert extract_mermaid_blocks(text) == []


def test_extract_multiple_blocks_in_order() -> None:
    text = (
        "First:\n```mermaid\ngraph TD; A-->B\n```\n"
        "Second:\n```mermaid\nsequenceDiagram\n A->>B: hi\n```\n"
    )

    assert extract_mermaid_blocks(text) == [
        "graph TD; A-->B",
        "sequenceDiagram\n A->>B: hi",
    ]


def test_extract_handles_a_space_after_the_fence() -> None:
    # ``` mermaid (with a space) is a real-world variant the model emits.
    text = "``` mermaid\ngraph LR; X-->Y\n```"

    assert extract_mermaid_blocks(text) == ["graph LR; X-->Y"]


def test_extract_is_case_insensitive_on_the_language_tag() -> None:
    text = "```Mermaid\ngraph TD; A-->B\n```"

    assert extract_mermaid_blocks(text) == ["graph TD; A-->B"]


def test_strip_removes_the_block_but_keeps_surrounding_prose() -> None:
    text = "Diagram:\n```mermaid\ngraph TD; A-->B\n```\nDone."
    stripped = strip_mermaid_blocks(text)

    assert "```mermaid" not in stripped
    assert "graph TD" not in stripped
    assert "Diagram:" in stripped
    assert "Done." in stripped


def test_strip_no_mermaid_is_unchanged() -> None:
    text = "plain text"

    assert strip_mermaid_blocks(text) == text


def test_strip_multiple_blocks() -> None:
    text = (
        "A:\n```mermaid\ngraph TD; A-->B\n```\n"
        "B:\n``` mermaid\ngraph LR; X-->Y\n```\nEnd."
    )
    stripped = strip_mermaid_blocks(text)

    assert "mermaid" not in stripped
    assert "graph" not in stripped
    assert "A:" in stripped
    assert "B:" in stripped
    assert "End." in stripped


def test_strip_does_not_leave_a_dangling_blank_run() -> None:
    # Stripping a block that stood alone on its own lines must not leave a big
    # run of blank lines behind — the visible reply stays tidy.
    text = "Before\n\n```mermaid\ngraph TD; A-->B\n```\n\nAfter"
    stripped = strip_mermaid_blocks(text)

    assert "\n\n\n" not in stripped
    assert "Before" in stripped
    assert "After" in stripped


def test_strip_only_removes_selected_blocks() -> None:
    # ``only`` strips just the handled (rendered) sources, leaving an unrendered block.
    text = (
        "A:\n```mermaid\ngraph TD; A-->B\n```\n"
        "B:\n```mermaid\ngraph LR; X-->Y\n```\n"
    )
    stripped = strip_mermaid_blocks(text, only={normalize_mermaid("graph TD; A-->B")})

    assert "graph TD" not in stripped
    # The second block was NOT in ``only`` → it stays as text.
    assert "graph LR; X-->Y" in stripped


def test_strip_only_empty_set_keeps_all_blocks() -> None:
    text = "```mermaid\ngraph TD; A-->B\n```"

    assert strip_mermaid_blocks(text, only=set()) == text


def test_normalize_ignores_surrounding_whitespace() -> None:
    assert normalize_mermaid("  graph TD; A-->B \n") == normalize_mermaid(
        "graph TD; A-->B"
    )


def test_normalize_distinguishes_different_sources() -> None:
    assert normalize_mermaid("graph TD; A-->B") != normalize_mermaid(
        "graph LR; X-->Y"
    )
