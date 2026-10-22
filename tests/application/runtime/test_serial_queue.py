# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""SerialQueue (BOB-126, review M1): submit never waits; one worker, arrival order.

The reaction use-case loads a relationship, awaits the judge and saves it: two reactions
handled at once would lose one update. The queue keeps the order and the one-at-a-time
handling the poll loop used to give for free, while the caller returns at once.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from bob.application.runtime import SerialQueue

if TYPE_CHECKING:
    import pytest

_WAIT_S = 5.0


class _Recorder:
    """A handler that logs start/end per item and can be held on a gate."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.gate = asyncio.Event()
        self.gate.set()
        self.started = asyncio.Event()

    async def handle(self, item: str) -> None:
        self.log.append(f"start {item}")
        self.started.set()
        await self.gate.wait()
        if item == "boom":
            raise RuntimeError("handler failed")
        self.log.append(f"end {item}")


async def test_submit_returns_while_the_handler_is_still_running() -> None:
    recorder = _Recorder()
    recorder.gate.clear()
    queue: SerialQueue[str] = SerialQueue(recorder.handle, name="t")

    queue.submit("a")  # synchronous: nothing to await, nothing to wait on
    await asyncio.wait_for(recorder.started.wait(), _WAIT_S)

    assert recorder.log == ["start a"]
    recorder.gate.set()
    await asyncio.wait_for(queue.wait_for_idle(), _WAIT_S)
    assert recorder.log == ["start a", "end a"]
    await queue.aclose()


async def test_items_are_handled_one_at_a_time_in_arrival_order() -> None:
    recorder = _Recorder()
    recorder.gate.clear()
    queue: SerialQueue[str] = SerialQueue(recorder.handle, name="t")

    for item in ("a", "b", "c"):
        queue.submit(item)
    await asyncio.wait_for(recorder.started.wait(), _WAIT_S)
    await asyncio.sleep(0)
    assert recorder.log == ["start a"]  # b waits for a, it does not run beside it

    recorder.gate.set()
    await asyncio.wait_for(queue.wait_for_idle(), _WAIT_S)
    assert recorder.log == ["start a", "end a", "start b", "end b", "start c", "end c"]
    await queue.aclose()


async def test_a_failing_handler_does_not_stop_the_next_item(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = _Recorder()
    queue: SerialQueue[str] = SerialQueue(recorder.handle, name="t")

    with caplog.at_level(logging.ERROR):
        queue.submit("boom")
        queue.submit("b")
        await asyncio.wait_for(queue.wait_for_idle(), _WAIT_S)

    assert recorder.log == ["start boom", "start b", "end b"]
    assert any("t: обработчик упал" in r.getMessage() for r in caplog.records)
    await queue.aclose()


async def test_close_does_not_wait_on_a_stuck_handler_and_drops_the_rest(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = _Recorder()
    recorder.gate.clear()  # the handler never finishes on its own
    queue: SerialQueue[str] = SerialQueue(recorder.handle, name="t")
    queue.submit("a")
    queue.submit("b")
    await asyncio.wait_for(recorder.started.wait(), _WAIT_S)

    with caplog.at_level(logging.INFO):
        await asyncio.wait_for(queue.aclose(), _WAIT_S)

    assert recorder.log == ["start a"]
    assert any("брошено необработанных: 2" in r.getMessage() for r in caplog.records)
    queue.submit("late")  # after close: dropped, no worker revived
    await asyncio.sleep(0)
    assert recorder.log == ["start a"]
    await asyncio.wait_for(queue.wait_for_idle(), _WAIT_S)
