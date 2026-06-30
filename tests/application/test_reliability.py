# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``call_with_retry`` — the bounded async retry primitive (BOB-049 .3).

The reliability helper behind «full Bob or an honest GUPPI notice»: an ESSENTIAL step
is attempted a bounded number of times with an INJECTED backoff sleep (so tests are
deterministic), and the last error is re-raised once every attempt fails.
"""

from __future__ import annotations

import pytest

from bob.application.reliability import call_with_retry


class _RecordingSleep:
    """A sleep seam double recording each backoff delay (no real delay)."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


async def test_returns_first_result_without_sleeping() -> None:
    # A successful operation returns immediately — no retry, no backoff sleep.
    sleep = _RecordingSleep()
    calls = 0

    async def op() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    result = await call_with_retry(op, attempts=3, backoff_seconds=0.5, sleep=sleep)

    assert result == "ok"
    assert calls == 1
    assert sleep.delays == []  # success on the first try → never slept


async def test_retries_then_succeeds() -> None:
    # Fails once, then succeeds: the result is returned and exactly one backoff slept.
    sleep = _RecordingSleep()
    calls = 0

    async def op() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("flaky")
        return "recovered"

    result = await call_with_retry(op, attempts=3, backoff_seconds=0.5, sleep=sleep)

    assert result == "recovered"
    assert calls == 2
    assert sleep.delays == [0.5]  # one backoff between the failed and the retried call


async def test_reraises_last_error_after_exhausting_attempts() -> None:
    # Every attempt fails → the LAST error is re-raised and backoff slept between tries.
    sleep = _RecordingSleep()
    calls = 0

    async def op() -> str:
        nonlocal calls
        calls += 1
        msg = f"down #{calls}"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="down #3"):
        await call_with_retry(op, attempts=3, backoff_seconds=0.5, sleep=sleep)

    assert calls == 3  # initial + 2 retries
    assert sleep.delays == [0.5, 0.5]  # a backoff between each attempt, none after the last


async def test_rejects_a_non_positive_attempt_count() -> None:
    sleep = _RecordingSleep()

    async def op() -> str:
        return "unused"

    with pytest.raises(ValueError, match="attempts must be >= 1"):
        await call_with_retry(op, attempts=0, backoff_seconds=0.5, sleep=sleep)
