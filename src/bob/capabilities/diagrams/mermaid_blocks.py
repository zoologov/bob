# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Pure mermaid fenced-block extraction / stripping / normalisation (BOB-037).

The model unreliably calls the ``render_diagram`` tool — usually it just writes the
mermaid as a fenced ```mermaid block IN its text reply, so no image is sent. The
reliability fix scans the composed reply for those blocks, renders each, and removes
the fence from the visible text (the image takes its place). These are the PURE
string helpers behind that:

* :func:`extract_mermaid_blocks` — the mermaid sources of every ```mermaid fence,
  in order (tolerant of ``` mermaid with a space and of a case-different tag);
* :func:`strip_mermaid_blocks` — the reply text with those fences removed, leaving
  the surrounding prose tidy (no dangling blank run where a block stood alone);
* :func:`normalize_mermaid` — a canonical key for one source so an inline block can
  be deduped against the SAME diagram the tool already rendered this turn.

No I/O, no rendering — the application layer composes these with a
:class:`~bob.capabilities.ports.DiagramRenderer`.
"""

from __future__ import annotations

import re

__all__ = [
    "extract_mermaid_blocks",
    "normalize_mermaid",
    "strip_mermaid_blocks",
]

# A fenced ```mermaid block: an opening fence whose info-string is ``mermaid``
# (case-insensitive, an optional space after the backticks tolerated — the model
# emits both ```mermaid and ``` mermaid), the source up to the closing ``` fence on
# its own line. ``DOTALL`` lets the body span lines; the body is captured non-greedy
# so two adjacent blocks do not merge. Anchored to line starts so a fence mid-line is
# not mistaken for a block.
_MERMAID_BLOCK = re.compile(
    r"^[ \t]*```[ \t]*mermaid[ \t]*\r?\n(?P<source>.*?)\r?\n[ \t]*```[ \t]*$",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)

# Collapse a run of 3+ newlines (left where a stripped block stood alone between
# blank lines) back to a single paragraph break, so the visible reply stays tidy.
_BLANK_RUN = re.compile(r"\n{3,}")


def extract_mermaid_blocks(text: str) -> list[str]:
    """Return the mermaid source of every ```mermaid fence in ``text`` (in order).

    Each returned string is the block's inner source with surrounding whitespace
    trimmed. A plain (non-mermaid) code fence is ignored; no fence yields ``[]``.
    """
    return [match.group("source").strip() for match in _MERMAID_BLOCK.finditer(text)]


def strip_mermaid_blocks(text: str, *, only: set[str] | None = None) -> str:
    """Return ``text`` with ```mermaid fences removed (prose preserved).

    The rendered image replaces the fence, so the fenced block is dropped from the
    visible reply while the surrounding prose stays. When ``only`` is given, just the
    blocks whose :func:`normalize_mermaid` source is in that set are removed — so a
    block that could NOT be rendered (mmdc missing) is LEFT as text; ``None`` removes
    every block. A block that stood alone between blank lines would otherwise leave a
    big run of blanks behind; that run is collapsed to a single paragraph break, and
    leading/trailing whitespace is trimmed, so the reply reads cleanly. No matching
    mermaid → the text is returned unchanged.
    """
    if not _MERMAID_BLOCK.search(text):
        return text

    def _replace(match: re.Match[str]) -> str:
        if only is not None and normalize_mermaid(match.group("source")) not in only:
            return match.group(0)
        return ""

    without_blocks = _MERMAID_BLOCK.sub(_replace, text)
    if without_blocks == text:
        return text
    return _BLANK_RUN.sub("\n\n", without_blocks).strip()


def normalize_mermaid(source: str) -> str:
    """Return a canonical key for ``source`` for the inline/tool dedup.

    Two mermaid sources that differ only in surrounding whitespace or trailing
    spaces on each line are the SAME diagram; this normalises them to one key so an
    inline ```mermaid block is not re-rendered when the ``render_diagram`` tool
    already rendered the same source this turn.
    """
    lines = [line.rstrip() for line in source.strip().splitlines()]
    return "\n".join(lines)
