# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""ProviderHealthMonitor — исходы вызовов → состояние, сигнал владельцу, лог, эпизод (BOB-116 D3).

Наблюдается через границу монитора: что пришло в фейковый ``OwnerAlertSink``, какие строки
легли в лог, что показал ``snapshot()``/``is_degraded``/``probe_due`` и с чем был вызван
колбэк восстановления. Часы — фейковые, поэтому пороги по времени проверяются точно.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest

from bob.application.router.health_monitor import (
    TIER0_EFFECTIVE,
    TIER0_PRIMARY,
    TIER0_UNDERSTUDY,
    TIER1,
    NoopHealthObserver,
    ProviderHealthMonitor,
)
from bob.kernel.ports import HealthObserver, HealthReader, HealthView
from bob.kernel.provider_health import HealthPolicy, HealthState

_START = datetime(2026, 10, 1, 6, 10, 42, tzinfo=UTC)
_LOGGER = "bob.application.router.health_monitor"


class _Clock:
    def __init__(self) -> None:
        self.current = _START

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class _Sink:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.texts: list[str] = []
        self._error = error

    async def notify_owner(self, text: str) -> None:
        if self._error is not None:
            raise self._error
        self.texts.append(text)


class _Recovered:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, datetime, datetime, str | None]] = []
        self._error = error

    async def __call__(
        self, provider_id: str, since: datetime, until: datetime, failure_class: str | None
    ) -> None:
        self.calls.append((provider_id, since, until, failure_class))
        if self._error is not None:
            raise self._error


def _monitor(
    *,
    has_understudy: bool = False,
    sink: _Sink | None = None,
    recovered: _Recovered | None = None,
    owner_address: str | None = None,
) -> tuple[ProviderHealthMonitor, _Clock, _Sink, _Recovered]:
    clock = _Clock()
    sink = sink if sink is not None else _Sink()
    recovered = recovered if recovered is not None else _Recovered()
    monitor = ProviderHealthMonitor(
        clock=clock,
        policy=HealthPolicy(),
        sink=sink,
        on_recovered=recovered,
        has_understudy=has_understudy,
        owner_address=owner_address,
    )
    return monitor, clock, sink, recovered


async def _fail(
    monitor: ProviderHealthMonitor,
    clock: _Clock,
    provider_id: str,
    times: int,
    *,
    failure_class: str = "auth",
    step: float = 1.0,
) -> None:
    for _ in range(times):
        await monitor.record_failure(provider_id, failure_class)
        clock.advance(step)


def _health_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER]


def _local_since(moment: datetime, *, with_date: bool = False) -> str:
    """Ожидаемое «since …» в поясе процесса со смещением — посчитано мимо модуля, через ``%z``."""
    local = moment.astimezone()
    offset = local.strftime("%z")
    clock = local.strftime("%Y-%m-%d %H:%M:%S" if with_date else "%H:%M:%S")
    return f"since {clock} {offset[:3]}:{offset[3:]}"


def _machine_offset_plus(delta: timedelta) -> timezone:
    """Пояс, сдвинутый от пояса машины на ``delta``: пропуск перевода краснеет на любой машине."""
    machine = _START.astimezone().utcoffset()
    assert machine is not None
    return timezone(machine + delta)


# --- порты -------------------------------------------------------------------------


def test_monitor_is_both_an_observer_and_a_reader() -> None:
    monitor, *_ = _monitor()
    assert isinstance(monitor, HealthObserver)
    assert isinstance(monitor, HealthReader)


async def test_noop_observer_accepts_every_outcome_and_does_nothing() -> None:
    noop = NoopHealthObserver()
    assert isinstance(noop, HealthObserver)
    await noop.record_success(TIER1)
    await noop.record_failure(TIER1, "auth")


# --- снимок ------------------------------------------------------------------------


def test_snapshot_names_every_wired_provider_from_the_start() -> None:
    monitor, *_ = _monitor(has_understudy=True)
    snapshot = monitor.snapshot()
    assert set(snapshot) == {TIER0_PRIMARY, TIER0_UNDERSTUDY, TIER1}
    assert all(view == HealthView(state=HealthState.HEALTHY) for view in snapshot.values())


def test_snapshot_without_understudy_does_not_invent_one() -> None:
    monitor, *_ = _monitor(has_understudy=False)
    assert set(monitor.snapshot()) == {TIER0_PRIMARY, TIER1}


# --- дублёр снят при старте (BOB-116 D11, bob-i83.15) --------------------------------
# Дублёр включён в конфигурации, но при старте не готов: сборка снимает его до перезапуска.
# Монитор с этой минуты считает, что дублёра нет (облако легло → думать нечем), а /status
# видит причину в снимке — не «нет» (это «не настроен»), а «выключен при старте: …».

_STOOD_DOWN_REASON = "модели qwen3:8b нет на http://127.0.0.1:11434/v1"


def test_stood_down_understudy_is_in_the_snapshot_with_its_reason() -> None:
    monitor, *_ = _monitor(has_understudy=True)
    monitor.stand_down_understudy(_STOOD_DOWN_REASON)
    snapshot = monitor.snapshot()
    assert set(snapshot) == {TIER0_PRIMARY, TIER0_UNDERSTUDY, TIER1}
    assert snapshot[TIER0_UNDERSTUDY] == HealthView(
        state=HealthState.DEGRADED, stood_down_reason=_STOOD_DOWN_REASON
    )
    assert monitor.is_degraded(TIER0_UNDERSTUDY)
    assert not monitor.probe_due(TIER0_UNDERSTUDY)


async def test_cloud_down_after_the_stand_down_is_muteness_not_the_understudy_holding() -> None:
    monitor, clock, sink, recovered = _monitor(has_understudy=True)
    monitor.stand_down_understudy(_STOOD_DOWN_REASON)
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    assert sink.texts[0].startswith("Я не могу думать")
    assert "Дублёра на этой машине нет" in sink.texts[0]
    assert "держусь на дублёре" not in sink.texts[0]
    await monitor.record_success(TIER0_PRIMARY)
    assert [call[0] for call in recovered.calls] == [TIER0_PRIMARY]


def test_monitor_without_a_stand_down_has_no_reason_in_its_snapshot() -> None:
    monitor, *_ = _monitor(has_understudy=True)
    assert monitor.snapshot()[TIER0_UNDERSTUDY].stood_down_reason is None
    assert not monitor.is_degraded(TIER0_UNDERSTUDY)


async def test_failures_below_the_threshold_show_in_the_snapshot_without_a_signal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monitor, clock, sink, _ = _monitor()
    await _fail(monitor, clock, TIER0_PRIMARY, 4, failure_class="server")
    view = monitor.snapshot()[TIER0_PRIMARY]
    assert view == HealthView(
        state=HealthState.HEALTHY,
        consecutive_failures=4,
        failure_class="server",
        failing_since=_START,
    )
    assert sink.texts == []
    assert _health_lines(caplog) == []


def test_unknown_provider_reads_as_healthy() -> None:
    monitor, *_ = _monitor()
    assert not monitor.is_degraded("tier9")
    assert monitor.probe_due("tier9")


# --- деградация --------------------------------------------------------------------


async def test_reaching_the_threshold_signals_once_and_logs_one_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monitor, clock, sink, _ = _monitor(owner_address="Вова")
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    assert monitor.is_degraded(TIER0_PRIMARY)
    assert len(sink.texts) == 1
    assert sink.texts[0].startswith("Вова, я не могу думать: облако отказывает мне в доступе")
    assert "Дублёра на этой машине нет" in sink.texts[0]
    assert _health_lines(caplog) == [
        f"LLM health tier0-primary: healthy → degraded (auth, 5 failures, {_local_since(_START)})"
    ]
    record = next(r for r in caplog.records if r.name == _LOGGER)
    assert record.levelno == logging.WARNING
    assert record.exc_info is None


async def test_further_failures_before_the_reminder_are_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monitor, clock, sink, _ = _monitor()
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    await _fail(monitor, clock, TIER0_PRIMARY, 20, step=10.0)
    assert len(sink.texts) == 1
    assert len(_health_lines(caplog)) == 1
    assert monitor.snapshot()[TIER0_PRIMARY].consecutive_failures == 25


async def test_reminder_follows_the_schedule(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monitor, clock, sink, _ = _monitor()
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    clock.advance(600)
    await monitor.record_failure(TIER0_PRIMARY, "auth")
    assert len(sink.texts) == 2
    assert sink.texts[1].startswith("Я всё ещё не могу думать")
    assert "Напомню через час" in sink.texts[1]
    assert _health_lines(caplog)[-1].startswith(
        f"LLM health tier0-primary: still degraded (auth, 6 failures, {_local_since(_START)})"
    )


async def test_since_names_the_date_when_the_outage_crossed_midnight(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monitor, clock, _, _ = _monitor()
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    clock.advance(86400)
    await monitor.record_failure(TIER0_PRIMARY, "auth")
    assert f"{_local_since(_START, with_date=True)})" in _health_lines(caplog)[-1]


@pytest.mark.parametrize(
    "clock_zone",
    [
        pytest.param(_machine_offset_plus(timedelta(hours=5, minutes=45)), id="machine+05:45"),
        pytest.param(_machine_offset_plus(-timedelta(hours=9, minutes=30)), id="machine-09:30"),
    ],
)
async def test_log_lines_name_the_process_zone_and_its_offset_whatever_the_clock_zone(
    caplog: pytest.LogCaptureFixture, clock_zone: timezone
) -> None:
    """Лог — в поясе процесса со смещением, как тексты человеку (D12), не в поясе часов."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monitor, clock, _, _ = _monitor()
    clock.current = _START.astimezone(clock_zone)
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    clock.advance(600)
    await monitor.record_failure(TIER0_PRIMARY, "auth")
    await monitor.record_success(TIER0_PRIMARY)
    since = _local_since(_START)
    assert _health_lines(caplog) == [
        f"LLM health tier0-primary: healthy → degraded (auth, 5 failures, {since})",
        f"LLM health tier0-primary: still degraded (auth, 6 failures, {since})",
        f"LLM health tier0-primary: degraded → healthy (auth, down {since})",
    ]


async def test_same_day_is_decided_in_the_process_zone_not_in_the_clock_zone(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """В поясе часов серия перешла полночь, в поясе процесса — нет: даты в строке нет."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monitor, clock, _, _ = _monitor()
    clock_zone = _machine_offset_plus(timedelta(hours=5, minutes=45))
    start = datetime(2026, 10, 1, 23, 59, 58, tzinfo=clock_zone)
    clock.current = start
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    assert _health_lines(caplog) == [
        f"LLM health tier0-primary: healthy → degraded (auth, 5 failures, {_local_since(start)})"
    ]


async def test_degradation_by_duration_reports_the_real_count() -> None:
    monitor, clock, sink, _ = _monitor()
    await _fail(monitor, clock, TIER1, 2, failure_class="timeout", step=180.0)
    assert monitor.is_degraded(TIER1)
    assert sink.texts[0].startswith("Основная модель не отвечает вовремя")
    assert "2 запроса подряд" in sink.texts[0]


# --- зонд --------------------------------------------------------------------------


async def test_probe_waits_for_the_schedule_once_degraded() -> None:
    monitor, clock, _, _ = _monitor()
    assert monitor.probe_due(TIER0_PRIMARY)
    await _fail(monitor, clock, TIER0_PRIMARY, 5, step=0.0)
    assert not monitor.probe_due(TIER0_PRIMARY)
    clock.advance(59)
    assert not monitor.probe_due(TIER0_PRIMARY)
    clock.advance(1)
    assert monitor.probe_due(TIER0_PRIMARY)


# --- восстановление ----------------------------------------------------------------


async def test_recovery_from_muteness_signals_logs_and_writes_the_episode(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monitor, clock, sink, recovered = _monitor()
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    clock.advance(3600)
    until = clock.now()
    await monitor.record_success(TIER0_PRIMARY)
    assert not monitor.is_degraded(TIER0_PRIMARY)
    assert sink.texts[-1].startswith("Я вернулся: облако ответило. Молчал час")
    assert recovered.calls == [(TIER0_PRIMARY, _START, until, "auth")]
    assert _health_lines(caplog)[-1] == (
        f"LLM health tier0-primary: degraded → healthy (auth, down {_local_since(_START)})"
    )
    assert monitor.snapshot()[TIER0_PRIMARY] == HealthView(state=HealthState.HEALTHY)


async def test_success_without_degradation_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monitor, clock, sink, recovered = _monitor()
    await _fail(monitor, clock, TIER0_PRIMARY, 4)
    await monitor.record_success(TIER0_PRIMARY)
    assert sink.texts == []
    assert recovered.calls == []
    assert _health_lines(caplog) == []


async def test_cloud_dead_while_understudy_holds_is_signalled_but_not_remembered_as_silence() -> (
    None
):
    monitor, clock, sink, recovered = _monitor(has_understudy=True)
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    assert "держусь на дублёре" in sink.texts[0]
    await monitor.record_success(TIER0_PRIMARY)
    assert "держал дублёр" in sink.texts[-1]
    assert recovered.calls == []


async def test_both_tier0_down_then_cloud_returns_writes_one_episode_from_the_later_fall() -> None:
    monitor, clock, sink, recovered = _monitor(has_understudy=True)
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    understudy_fell = clock.now()
    await _fail(monitor, clock, TIER0_UNDERSTUDY, 5, failure_class="connection")
    assert "облако тоже лежит" in sink.texts[-1]
    until = clock.now()
    await monitor.record_success(TIER0_PRIMARY)
    assert recovered.calls == [(TIER0_PRIMARY, understudy_fell, until, "auth")]
    assert sink.texts[-1].startswith("Я вернулся: облако ответило.")
    await monitor.record_success(TIER0_UNDERSTUDY)
    assert len(recovered.calls) == 1
    assert sink.texts[-1].startswith("Дублёр снова отвечает.")


async def test_understudy_returning_first_ends_the_silence_and_the_cloud_does_not_repeat_it() -> (
    None
):
    monitor, clock, _, recovered = _monitor(has_understudy=True)
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    await _fail(monitor, clock, TIER0_UNDERSTUDY, 5, failure_class="connection")
    await monitor.record_success(TIER0_UNDERSTUDY)
    assert [call[0] for call in recovered.calls] == [TIER0_UNDERSTUDY]
    assert recovered.calls[0][3] == "connection"
    await monitor.record_success(TIER0_PRIMARY)
    assert len(recovered.calls) == 1


async def test_understudy_down_alone_is_signalled_without_an_episode() -> None:
    monitor, clock, sink, recovered = _monitor(has_understudy=True)
    await _fail(monitor, clock, TIER0_UNDERSTUDY, 5, failure_class="timeout")
    assert "подстраховать будет некому" in sink.texts[0]
    await monitor.record_success(TIER0_UNDERSTUDY)
    assert recovered.calls == []


async def test_voice_tier_recovery_writes_the_episode() -> None:
    monitor, clock, sink, recovered = _monitor()
    await _fail(monitor, clock, TIER1, 5, failure_class="rate")
    await monitor.record_success(TIER1)
    assert [call[0] for call in recovered.calls] == [TIER1]
    assert sink.texts[-1].startswith("Основная модель снова отвечает.")


async def test_unknown_provider_recovers_without_an_episode() -> None:
    monitor, clock, sink, recovered = _monitor()
    await _fail(monitor, clock, "tier9", 5)
    await monitor.record_success("tier9")
    assert sink.texts[-1].startswith("Провайдер tier9 снова отвечает.")
    assert recovered.calls == []


async def test_monitor_without_a_recovery_callback_still_signals() -> None:
    sink = _Sink()
    monitor = ProviderHealthMonitor(clock=_Clock(), policy=HealthPolicy(), sink=sink)
    for _ in range(5):
        await monitor.record_failure(TIER0_PRIMARY, "auth")
    await monitor.record_success(TIER0_PRIMARY)
    assert len(sink.texts) == 2


# --- отказ доставки не валит доклад ------------------------------------------------


async def test_sink_failure_is_a_warning_and_the_state_still_moves(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monitor, clock, _, _ = _monitor(sink=_Sink(error=RuntimeError("telegram down")))
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    assert monitor.is_degraded(TIER0_PRIMARY)
    lines = _health_lines(caplog)
    assert lines[-1] == "Owner alert about tier0-primary failed (RuntimeError: telegram down)"
    assert all(r.exc_info is None for r in caplog.records if r.name == _LOGGER)


async def test_recovery_callback_failure_is_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monitor, clock, sink, _ = _monitor(recovered=_Recovered(error=OSError("db locked")))
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    await monitor.record_success(TIER0_PRIMARY)
    assert sink.texts[-1].startswith("Я вернулся")
    assert _health_lines(caplog)[-1] == (
        "Outage episode for tier0-primary was not recorded (OSError: db locked)"
    )


async def test_the_record_is_visible_before_the_owner_is_messaged() -> None:
    """Контракт D5: гейт heartbeat читает snapshot сразу после исхода — запись не ждёт sink."""
    seen: list[int] = []
    monitor: ProviderHealthMonitor

    class _PeekingSink:
        async def notify_owner(self, _text: str) -> None:
            seen.append(monitor.snapshot()[TIER0_PRIMARY].consecutive_failures)

    monitor = ProviderHealthMonitor(clock=_Clock(), policy=HealthPolicy(), sink=_PeekingSink())
    for _ in range(5):
        await monitor.record_failure(TIER0_PRIMARY, "auth")
    assert seen == [5]


# --- Tier-0 целиком: «думать есть чем?» (BOB-116 F2, ревью M2) --------------------------
# Дорожки heartbeat спрашивают не «лежит ли облако», а «лежит ли Tier-0 целиком»: облако
# лежит И дублёра нет, он снят при старте или лежит тоже. Это то же правило, что ситуация MUTE
# в сообщении владельцу и эпизод «я молчал», — одна реализация на троих.


async def test_tier0_is_up_while_the_understudy_holds_a_dead_cloud() -> None:
    monitor, clock, sink, _ = _monitor(has_understudy=True)
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    assert monitor.is_degraded(TIER0_PRIMARY)
    assert not monitor.is_degraded(TIER0_EFFECTIVE)
    assert "держусь на дублёре" in sink.texts[0]


async def test_tier0_is_down_when_both_floors_are_down() -> None:
    monitor, clock, sink, _ = _monitor(has_understudy=True)
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    await _fail(monitor, clock, TIER0_UNDERSTUDY, 5)
    assert monitor.is_degraded(TIER0_EFFECTIVE)
    assert sink.texts[-1].startswith("Я не могу думать")


async def test_tier0_is_down_with_a_dead_cloud_and_no_understudy() -> None:
    monitor, clock, *_ = _monitor(has_understudy=False)
    assert not monitor.is_degraded(TIER0_EFFECTIVE)
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    assert monitor.is_degraded(TIER0_EFFECTIVE)


async def test_tier0_is_down_with_a_dead_cloud_after_the_understudy_was_stood_down() -> None:
    monitor, clock, sink, _ = _monitor(has_understudy=True)
    monitor.stand_down_understudy(_STOOD_DOWN_REASON)
    assert not monitor.is_degraded(TIER0_EFFECTIVE)
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    assert monitor.is_degraded(TIER0_EFFECTIVE)
    assert sink.texts[0].startswith("Я не могу думать")


async def test_a_dead_understudy_alone_leaves_tier0_up() -> None:
    monitor, clock, *_ = _monitor(has_understudy=True)
    await _fail(monitor, clock, TIER0_UNDERSTUDY, 5)
    assert monitor.is_degraded(TIER0_UNDERSTUDY)
    assert not monitor.is_degraded(TIER0_EFFECTIVE)


async def test_tier0_comes_back_with_whichever_floor_returns_first() -> None:
    monitor, clock, *_ = _monitor(has_understudy=True)
    await _fail(monitor, clock, TIER0_PRIMARY, 5)
    await _fail(monitor, clock, TIER0_UNDERSTUDY, 5)
    await monitor.record_success(TIER0_UNDERSTUDY)
    assert not monitor.is_degraded(TIER0_EFFECTIVE)


def test_the_whole_tier0_view_is_not_a_provider_in_the_snapshot() -> None:
    """/status перечисляет провайдеров; «Tier-0 целиком» — вопрос гейта, а не строка статуса."""
    monitor, *_ = _monitor(has_understudy=True)
    assert TIER0_EFFECTIVE not in monitor.snapshot()
    assert TIER0_EFFECTIVE not in {TIER0_PRIMARY, TIER0_UNDERSTUDY, TIER1}
