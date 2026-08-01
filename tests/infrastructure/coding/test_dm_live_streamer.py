# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты _DmLiveStreamer — адаптер лайв-стрима сырых событий в личку owner'а (BOB-082.3).

Реализует порт use-case ``LiveRunStreamer``: рендерит каждое сырое stream-json событие
через :func:`~bob.coding.stream_render.render_stream_event` и льёт БЕЗ капа в DM-нотификатор
(отдельные сообщения) + прогрессивно катит «терминальную» панель. Шум (None-рендер)
пропускается. ``is_cancelled`` обрывает поток (kill-switch). Best-effort: сбой панели не
валит стрим.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters.live_stream import _DmLiveStreamer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


@dataclass
class _SpyNotifier:
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


@dataclass
class _SpyPanel:
    opened: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)

    async def open(self, text: str) -> None:
        self.opened.append(text)

    async def update(self, text: str) -> None:
        self.updated.append(text)


async def _events(
    items: Sequence[Mapping[str, object]],
) -> AsyncIterator[Mapping[str, object]]:
    for item in items:
        yield item


def _edit(path: str) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": path}}]
        },
    }


def _never_cancelled() -> bool:
    return False


@pytest.mark.asyncio
async def test_each_rendered_event_is_sent_to_the_dm_notifier() -> None:
    notifier = _SpyNotifier()
    streamer = _DmLiveStreamer(notifier=notifier)

    await streamer.stream(
        _events([_edit("a.py"), _edit("b.py")]), is_cancelled=_never_cancelled
    )

    assert notifier.sent == ["правлю `a.py`", "правлю `b.py`"]


@pytest.mark.asyncio
async def test_stream_is_uncapped_far_beyond_the_group_cap() -> None:
    # The group narration caps at _MAX_NARRATION (12); the private DM firehose does NOT —
    # every one of many edits reaches the owner's dev-channel.
    notifier = _SpyNotifier()
    streamer = _DmLiveStreamer(notifier=notifier)

    events = [_edit(f"f{i}.py") for i in range(50)]
    await streamer.stream(_events(events), is_cancelled=_never_cancelled)

    assert len(notifier.sent) == 50


@pytest.mark.asyncio
async def test_noise_events_are_skipped() -> None:
    notifier = _SpyNotifier()
    streamer = _DmLiveStreamer(notifier=notifier)

    await streamer.stream(
        _events([{"type": "system", "subtype": "init"}, _edit("a.py")]),
        is_cancelled=_never_cancelled,
    )

    assert notifier.sent == ["правлю `a.py`"]


@pytest.mark.asyncio
async def test_cancellation_breaks_the_stream() -> None:
    notifier = _SpyNotifier()
    streamer = _DmLiveStreamer(notifier=notifier)
    stop = {"hit": False}

    def _cancelled() -> bool:
        return stop["hit"]

    async def _events_then_stop() -> AsyncIterator[Mapping[str, object]]:
        yield _edit("a.py")
        stop["hit"] = True  # a concurrent /code stop landed
        yield _edit("b.py")  # must NOT be streamed

    await streamer.stream(_events_then_stop(), is_cancelled=_cancelled)

    assert notifier.sent == ["правлю `a.py`"]


@pytest.mark.asyncio
async def test_rolling_panel_opens_then_updates_with_the_terminal_window() -> None:
    notifier = _SpyNotifier()
    panel = _SpyPanel()
    streamer = _DmLiveStreamer(notifier=notifier, panel=panel)

    await streamer.stream(
        _events([_edit("a.py"), _edit("b.py")]), is_cancelled=_never_cancelled
    )

    # One open (first line) then edits — a single rolling "terminal" message, not spam.
    assert panel.opened == ["правлю `a.py`"]
    assert panel.updated[-1].endswith("правлю `b.py`")
    assert "правлю `a.py`" in panel.updated[-1]


@pytest.mark.asyncio
async def test_panel_failure_never_breaks_the_stream() -> None:
    notifier = _SpyNotifier()

    class _BrokenPanel:
        async def open(self, text: str) -> None:
            raise RuntimeError("edit boom")

        async def update(self, text: str) -> None:
            raise RuntimeError("edit boom")

    streamer = _DmLiveStreamer(notifier=notifier, panel=_BrokenPanel())

    await streamer.stream(_events([_edit("a.py")]), is_cancelled=_never_cancelled)

    # The firehose still reached the DM even though the rolling panel raised.
    assert notifier.sent == ["правлю `a.py`"]
