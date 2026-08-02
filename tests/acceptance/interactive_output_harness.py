# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Boundary harness for the interactive-terminal OUTPUT scenarios (BOB-085 S1/S2/S4).

Drives the real coding live-stream boundary — :class:`_DmLiveStreamer` over
:func:`render_stream_event` + :func:`chunk_for_telegram` — with a fake notifier that
captures exactly what is SENT to Telegram. The scenarios assert only observable output
(the messages the owner would receive), never private render state:

* S1 — an interactive-DM stream sends a long claude answer IN FULL (chunked in order, the
  concatenation reconstructs the whole answer), not the concise 200-char stub;
* S2 — claude's markdown structure survives to the notifier (rich passthrough), not
  flattened prose;
* S4 — the one-way group ``dev_dm`` stream stays concise/capped, byte-identical to the
  pre-BOB-085 behaviour (``verbose=False``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bob.coding.adapters.live_stream import _DmLiveStreamer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

TELEGRAM_LIMIT = 4096


@dataclass
class _FakeNotifier:
    """The outgoing boundary — records every message actually sent to the owner's DM."""

    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


def _assistant_text(text: str) -> dict[str, object]:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


@dataclass
class OutputObservations:
    """What the fake notifier captured for one streamed run."""

    sent: list[str] = field(default_factory=list)

    @property
    def joined(self) -> str:
        """Ordered chunks rejoined on newlines — the reconstructed full message."""
        return "\n".join(self.sent)


def _run(events: list[dict[str, object]], *, verbose: bool) -> OutputObservations:
    notifier = _FakeNotifier()
    streamer = _DmLiveStreamer(notifier=notifier, verbose=verbose)

    async def _events() -> AsyncIterator[Mapping[str, object]]:
        for event in events:
            yield event

    async def _drive() -> None:
        await streamer.stream(_events(), is_cancelled=lambda: False)

    asyncio.run(_drive())
    return OutputObservations(sent=list(notifier.sent))


# --- Fixed claude answers (deterministic acceptance inputs) --------------------

# Priority labels are pure-Cyrillic (kept out of any literal mixed with Latin/digits so the
# ambiguous-character lint stays quiet); numbers are stringified separately.
_PRIORITY_LABELS = ("ноль", "один", "два")
LONG_BUG_LIST = "\n".join(
    "пункт номер "
    + str(i)
    + ", приоритет "
    + _PRIORITY_LABELS[i % 3]
    + ": длинное человекочитаемое описание проблемы и её причины"
    for i in range(60)
)

RICH_MARKDOWN = (
    "## Найденные баги\n\n"
    "- **P0** — падение парсера\n"
    "- **P1** — утечка в `handler`\n\n"
    "Фикс:\n\n"
    "```python\ndef fix() -> None:\n    return None\n```\n\n"
    "Готово."
)


def stream_long_answer_interactive() -> OutputObservations:
    """S1: a long claude answer streamed on the interactive-DM (verbose) path."""
    return _run([_assistant_text(LONG_BUG_LIST)], verbose=True)


def stream_rich_answer_interactive() -> OutputObservations:
    """S2: a rich-markdown claude answer streamed on the interactive-DM path."""
    return _run([_assistant_text(RICH_MARKDOWN)], verbose=True)


def stream_long_answer_group() -> OutputObservations:
    """S4: the same long answer streamed on the one-way group (concise) path."""
    return _run([_assistant_text(LONG_BUG_LIST)], verbose=False)
