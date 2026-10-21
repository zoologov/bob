# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``health_gated`` — a heartbeat lane that respects provider health (BOB-116 D5).

The reader is a fake standing in for the provider-health monitor: the tick plays the
monitor's part by recording a failure (or a success) on it, exactly as the router does
before the exception reaches the lane.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime import heartbeat
from bob.application.runtime.heartbeat import health_gated, periodic
from bob.kernel.ports import HealthReader, HealthView
from bob.kernel.provider_health import HealthState

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping

_PROVIDER = "tier0-primary"
_LOGGER = heartbeat.__name__


class FakeHealthReader:
    """In-memory provider health with a monitor-like write side for the tick to drive."""

    def __init__(self, *, degraded: bool, probe_due: bool = True) -> None:
        self._views: dict[str, HealthView] = {}
        self.due = probe_due
        if degraded:
            self._views[_PROVIDER] = HealthView(
                state=HealthState.DEGRADED, consecutive_failures=5, failure_class="auth"
            )

    def snapshot(self) -> Mapping[str, HealthView]:
        return dict(self._views)

    def is_degraded(self, provider_id: str) -> bool:
        view = self._views.get(provider_id)
        return view is not None and view.state is HealthState.DEGRADED

    def probe_due(self, provider_id: str) -> bool:
        return self.due if self.is_degraded(provider_id) else True

    def fail(self, failure_class: str = "auth") -> None:
        """What the monitor does when the router reports a failed call."""
        view = self._views.get(_PROVIDER, HealthView(state=HealthState.HEALTHY))
        self._views[_PROVIDER] = HealthView(
            state=view.state,
            consecutive_failures=view.consecutive_failures + 1,
            failure_class=failure_class,
        )
        self.due = False

    def succeed(self) -> None:
        """What the monitor does when the router reports a successful call."""
        self._views[_PROVIDER] = HealthView(state=HealthState.HEALTHY)


class Tick:
    """A one-shot heartbeat tick that counts calls and runs a scripted body."""

    def __init__(self, body: object = None) -> None:
        self.calls = 0
        self._body = body

    async def __call__(self) -> None:
        self.calls += 1
        if callable(self._body):
            self._body()


def test_fake_reader_satisfies_the_health_reader_port() -> None:
    reader: HealthReader = FakeHealthReader(degraded=False)
    assert isinstance(reader, HealthReader)


# --- HEALTHY: transparent ------------------------------------------------------------


async def test_healthy_provider_runs_the_tick() -> None:
    tick = Tick()
    gated = health_gated(tick, reader=FakeHealthReader(degraded=False), provider_id=_PROVIDER)

    await gated()

    assert tick.calls == 1


async def test_healthy_provider_lets_a_tick_failure_through_unchanged() -> None:
    boom = RuntimeError("boom")

    def raise_boom() -> None:
        raise boom

    reader = FakeHealthReader(degraded=False)
    gated = health_gated(Tick(raise_boom), reader=reader, provider_id=_PROVIDER, probe=True)

    with pytest.raises(RuntimeError) as caught:
        await gated()

    assert caught.value is boom


# --- DEGRADED, lane without a probe: skipped without a trace ---------------------------


async def test_degraded_lane_without_probe_skips_the_tick_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tick = Tick()
    reader = FakeHealthReader(degraded=True, probe_due=True)
    gated = health_gated(tick, reader=reader, provider_id=_PROVIDER, probe=False)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        await gated()

    assert tick.calls == 0
    assert caplog.records == []


async def test_probe_is_off_by_default() -> None:
    tick = Tick()
    gated = health_gated(tick, reader=FakeHealthReader(degraded=True), provider_id=_PROVIDER)

    await gated()

    assert tick.calls == 0


async def test_gate_reads_only_its_own_provider() -> None:
    tick = Tick()
    reader = FakeHealthReader(degraded=True)
    gated = health_gated(tick, reader=reader, provider_id="tier1", probe=False)

    await gated()

    assert tick.calls == 1


# --- DEGRADED, probe lane ------------------------------------------------------------


async def test_degraded_probe_lane_skips_silently_until_the_probe_is_due(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tick = Tick()
    reader = FakeHealthReader(degraded=True, probe_due=False)
    gated = health_gated(tick, reader=reader, provider_id=_PROVIDER, probe=True)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        await gated()

    assert tick.calls == 0
    assert caplog.records == []


async def test_degraded_probe_lane_runs_the_tick_when_the_probe_is_due() -> None:
    tick = Tick()
    reader = FakeHealthReader(degraded=True, probe_due=True)
    gated = health_gated(tick, reader=reader, provider_id=_PROVIDER, probe=True)

    await gated()

    assert tick.calls == 1


async def test_failed_probe_is_one_info_line_without_a_stack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeHealthReader(degraded=True, probe_due=True)

    def provider_refuses() -> None:
        reader.fail("auth")
        raise RuntimeError("403 Forbidden")

    gated = health_gated(
        Tick(provider_refuses), reader=reader, provider_id=_PROVIDER, probe=True
    )

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        await gated()

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.INFO
    assert record.exc_info is None
    message = record.getMessage()
    assert "\n" not in message
    assert _PROVIDER in message
    assert "auth" in message


async def test_failed_probe_through_periodic_logs_no_stack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = FakeHealthReader(degraded=True, probe_due=True)
    tick = Tick(lambda: _fail_as_provider(reader))
    loop = periodic(
        health_gated(tick, reader=reader, provider_id=_PROVIDER, probe=True),
        interval_seconds=0.0,
        sleep=_yield,
    )

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        await _run_until(loop, lambda: tick.calls >= 1)

    assert [r.levelno for r in caplog.records] == [logging.INFO]
    assert all(r.exc_info is None for r in caplog.records)


async def test_db_error_while_degraded_reaches_periodic_and_is_logged_with_a_stack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # RFC risk row: the gate must not hide a non-LLM failure of the tick.
    reader = FakeHealthReader(degraded=True, probe_due=True)

    def db_breaks() -> None:
        raise OSError("database is locked")

    tick = Tick(db_breaks)
    loop = periodic(
        health_gated(tick, reader=reader, provider_id=_PROVIDER, probe=True),
        interval_seconds=0.0,
        sleep=_yield,
    )

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        await _run_until(loop, lambda: tick.calls >= 1)

    stacked = [r for r in caplog.records if r.exc_info is not None]
    assert len(stacked) == 1
    assert stacked[0].levelno == logging.ERROR
    exc_info = stacked[0].exc_info
    assert exc_info is not None
    assert isinstance(exc_info[1], OSError)


async def test_db_error_while_degraded_is_raised_from_the_gated_tick() -> None:
    reader = FakeHealthReader(degraded=True, probe_due=True)
    broken = OSError("database is locked")

    def db_breaks() -> None:
        raise broken

    gated = health_gated(Tick(db_breaks), reader=reader, provider_id=_PROVIDER, probe=True)

    with pytest.raises(OSError, match="database is locked") as caught:
        await gated()

    assert caught.value is broken


async def test_error_after_a_recovered_probe_is_raised() -> None:
    # The model answered (monitor: recovered), then the tick failed elsewhere.
    reader = FakeHealthReader(degraded=True, probe_due=True)

    def recover_then_break() -> None:
        reader.succeed()
        raise OSError("disk full")

    gated = health_gated(
        Tick(recover_then_break), reader=reader, provider_id=_PROVIDER, probe=True
    )

    with pytest.raises(OSError, match="disk full"):
        await gated()


async def test_cancellation_during_a_probe_propagates() -> None:
    reader = FakeHealthReader(degraded=True, probe_due=True)

    def cancelled() -> None:
        reader.fail()
        raise asyncio.CancelledError

    gated = health_gated(Tick(cancelled), reader=reader, provider_id=_PROVIDER, probe=True)

    with pytest.raises(asyncio.CancelledError):
        await gated()


async def test_successful_probe_restores_the_ordinary_rhythm() -> None:
    reader = FakeHealthReader(degraded=True, probe_due=True)
    probe_tick = Tick(reader.succeed)
    quiet_tick = Tick()
    probe_lane = health_gated(probe_tick, reader=reader, provider_id=_PROVIDER, probe=True)
    quiet_lane = health_gated(quiet_tick, reader=reader, provider_id=_PROVIDER, probe=False)

    await quiet_lane()  # degraded: skipped
    await probe_lane()  # the probe goes and the provider answers
    for _ in range(3):
        await probe_lane()
        await quiet_lane()

    assert probe_tick.calls == 4
    assert quiet_tick.calls == 3


async def test_failed_probe_waits_for_the_next_due_probe() -> None:
    reader = FakeHealthReader(degraded=True, probe_due=True)
    tick = Tick(lambda: _fail_as_provider(reader))
    gated = health_gated(tick, reader=reader, provider_id=_PROVIDER, probe=True)

    await gated()  # probe fails, the monitor pushes the next probe out
    await gated()
    await gated()

    assert tick.calls == 1


# --- gate_id: the lane closes on a composite, the probe goes to the provider -----------
# BOB-116 F2 (review M2): a Tier-0 lane is closed only when Tier-0 as a whole cannot think
# (the cloud is down and the understudy cannot hold), while the probe, its schedule, its
# failure count and its log line stay the cloud's — the wrapper tries the cloud first.

_GATE = "tier0"


class CompositeReader(FakeHealthReader):
    """A reader that also answers a composite gate id, as the monitor does for Tier-0."""

    def __init__(self, *, provider_degraded: bool, gate_degraded: bool, probe_due: bool) -> None:
        super().__init__(degraded=provider_degraded, probe_due=probe_due)
        self.gate_degraded = gate_degraded

    def is_degraded(self, provider_id: str) -> bool:
        if provider_id == _GATE:
            return self.gate_degraded
        return super().is_degraded(provider_id)

    def probe_due(self, provider_id: str) -> bool:
        assert provider_id != _GATE, "the probe is asked of the provider, not of the gate"
        return super().probe_due(provider_id)


def _composite_lane(tick: Tick, reader: CompositeReader, *, probe: bool) -> heartbeat.Tick:
    return health_gated(tick, reader=reader, provider_id=_PROVIDER, probe=probe, gate_id=_GATE)


async def test_open_gate_runs_a_quiet_lane_while_its_provider_is_degraded() -> None:
    tick = Tick()
    reader = CompositeReader(provider_degraded=True, gate_degraded=False, probe_due=False)

    for _ in range(3):
        await _composite_lane(tick, reader, probe=False)()

    assert tick.calls == 3


async def test_open_gate_runs_the_probe_lane_every_time_not_on_the_probe_schedule() -> None:
    tick = Tick()
    reader = CompositeReader(provider_degraded=True, gate_degraded=False, probe_due=False)

    for _ in range(3):
        await _composite_lane(tick, reader, probe=True)()

    assert tick.calls == 3


async def test_open_gate_lets_a_tick_failure_through_unchanged() -> None:
    reader = CompositeReader(provider_degraded=True, gate_degraded=False, probe_due=True)
    gated = _composite_lane(Tick(lambda: _fail_as_provider(reader)), reader, probe=True)

    with pytest.raises(RuntimeError, match="502 Bad Gateway"):
        await gated()


async def test_closed_gate_silences_a_quiet_lane(caplog: pytest.LogCaptureFixture) -> None:
    tick = Tick()
    reader = CompositeReader(provider_degraded=True, gate_degraded=True, probe_due=True)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        await _composite_lane(tick, reader, probe=False)()

    assert tick.calls == 0
    assert caplog.records == []


async def test_closed_gate_probes_on_the_providers_schedule() -> None:
    reader = CompositeReader(provider_degraded=True, gate_degraded=True, probe_due=True)
    tick = Tick(lambda: _fail_as_provider(reader))
    gated = _composite_lane(tick, reader, probe=True)

    await gated()  # the probe is due: it goes and the provider fails it
    await gated()  # the provider pushed its next probe out
    reader.due = True
    await gated()  # due again

    assert tick.calls == 2


async def test_closed_gate_failed_probe_is_one_info_line_naming_the_provider(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reader = CompositeReader(provider_degraded=True, gate_degraded=True, probe_due=True)
    gated = _composite_lane(Tick(lambda: _fail_as_provider(reader)), reader, probe=True)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        await gated()

    assert [r.levelno for r in caplog.records] == [logging.INFO]
    message = caplog.records[0].getMessage()
    assert f"heartbeat probe of {_PROVIDER} failed (server, RuntimeError)" in message


async def test_closed_gate_db_error_before_the_call_is_raised() -> None:
    reader = CompositeReader(provider_degraded=True, gate_degraded=True, probe_due=True)

    def db_breaks() -> None:
        raise OSError("database is locked")

    with pytest.raises(OSError, match="database is locked"):
        await _composite_lane(Tick(db_breaks), reader, probe=True)()


# --- helpers ---------------------------------------------------------------------------


def _fail_as_provider(reader: FakeHealthReader) -> None:
    reader.fail("server")
    raise RuntimeError("502 Bad Gateway")


async def _yield(_seconds: float) -> None:
    await asyncio.sleep(0)


async def _run_until(
    loop: Callable[[], Coroutine[object, object, None]],
    done: Callable[[], bool],
) -> None:
    task = asyncio.create_task(loop())
    for _ in range(1000):
        if done():
            break
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
