# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""provider_health — чистое ядро здоровья LLM-провайдера (BOB-116 D1).

Ядро детерминированное и без I/O: по исходу очередного вызова провайдера, времени
``now`` и политике отдаёт новое состояние и переход (``NONE`` / ``DEGRADED`` /
``REMINDER`` / ``RECOVERED``), а для зонда — «пора ли пробовать». Через границу
проверяем только возвращаемые значения: состояние, переход и булев вердикт.

🔴 Одиночный 5xx не будит владельца: допороговые отказы сбрасываются первым успехом
без перехода. 🔴 Политика с порогом < 2 отвергается — иначе первый же чих объявил бы
провайдера мёртвым (как ``outage_state``, BOB-094).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.kernel.ports import HealthObserver, HealthReader, HealthView, OwnerAlertSink
from bob.kernel.provider_health import (
    HealthPolicy,
    HealthState,
    ProviderHealth,
    Transition,
    next_probe_interval,
    on_failure,
    on_success,
    outage_duration,
    probe_due,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# Маленькая политика, чтобы границы были видны в тестах: 3 отказа / 100 с,
# напоминания 10/20/40 с, зонд 5/7/11 с (разные числа — подмена индекса видна).
_POLICY = HealthPolicy(
    failures_threshold=3,
    duration_threshold_s=100.0,
    reminders_s=(10.0, 20.0, 40.0),
    probe_s=(5.0, 7.0, 11.0),
)

_T0 = 1_000.0


def _fail(
    h: ProviderHealth, now: float, failure_class: str = "auth"
) -> tuple[ProviderHealth, Transition]:
    return on_failure(h, now=now, failure_class=failure_class, policy=_POLICY)


def _degraded(at: float = _T0) -> ProviderHealth:
    """Провайдер, переведённый в DEGRADED тремя отказами подряд, последний — в ``at``."""
    h = ProviderHealth()
    h, _ = _fail(h, at - 2.0)
    h, _ = _fail(h, at - 1.0)
    h, transition = _fail(h, at)
    assert transition is Transition.DEGRADED
    return h


# --- Политика ------------------------------------------------------------------


def test_default_policy_matches_the_approved_thresholds() -> None:
    """Дефолты CONTEXT: 5 отказов / 180 с, напоминания 600/3600/21600/86400, зонд 60/120/300."""
    policy = HealthPolicy()
    assert policy.failures_threshold == 5
    assert policy.duration_threshold_s == 180.0
    assert policy.reminders_s == (600.0, 3600.0, 21600.0, 86400.0)
    assert policy.probe_s == (60.0, 120.0, 300.0)


def test_policy_with_threshold_two_is_accepted() -> None:
    """Минимально допустимый порог — 2 (граница ≥ 2 включительно)."""
    assert HealthPolicy(failures_threshold=2).failures_threshold == 2


@pytest.mark.parametrize("threshold", [1, 0, -3])
def test_policy_with_threshold_below_two_is_rejected(threshold: int) -> None:
    """🔴 Порог < 2 сделал бы одиночный отказ диагнозом — программная ошибка."""
    with pytest.raises(ValueError, match=r"^failures_threshold "):
        HealthPolicy(failures_threshold=threshold)


@pytest.mark.parametrize("duration", [0.0, -1.0])
def test_policy_with_non_positive_duration_is_rejected(duration: float) -> None:
    """Порог длительности ≤ 0 объявил бы деградацию на первом же отказе."""
    with pytest.raises(ValueError, match=r"^duration_threshold_s "):
        HealthPolicy(duration_threshold_s=duration)


def test_policy_with_tiny_positive_duration_is_accepted() -> None:
    """Граница строгая: любое положительное значение годится."""
    assert HealthPolicy(duration_threshold_s=0.5).duration_threshold_s == 0.5


@pytest.mark.parametrize("field", ["reminders_s", "probe_s"])
def test_policy_with_empty_schedule_is_rejected(field: str) -> None:
    """Пустое расписание не даёт ни интервала, ни потолка."""
    with pytest.raises(ValueError, match=rf"^{field} "):
        HealthPolicy(**{field: ()})  # type: ignore[arg-type]  # поле выбирается параметром


@pytest.mark.parametrize("field", ["reminders_s", "probe_s"])
@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_policy_with_non_positive_interval_is_rejected(field: str, bad: float) -> None:
    """Интервал ≤ 0 в расписании означал бы напоминание/зонд на каждом вызове."""
    with pytest.raises(ValueError, match=rf"^{field} "):
        HealthPolicy(**{field: (10.0, bad)})  # type: ignore[arg-type]  # поле выбирается параметром


def test_policy_accepts_short_positive_schedule_steps() -> None:
    """Граница строгая (> 0): шаг меньше секунды — годный шаг, а не ошибка."""
    policy = HealthPolicy(reminders_s=(0.5,), probe_s=(0.5, 1.0))
    assert policy.reminders_s == (0.5,)
    assert policy.probe_s == (0.5, 1.0)


def test_policy_is_frozen() -> None:
    """Политика — значение: её нельзя переписать на ходу."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        _POLICY.failures_threshold = 9  # type: ignore[misc]  # проверяем именно запрет записи


# --- Начальное состояние --------------------------------------------------------


def test_fresh_provider_is_healthy_with_nothing_accumulated() -> None:
    """Новый провайдер здоров и без истории."""
    h = ProviderHealth()
    assert h.state is HealthState.HEALTHY
    assert h.consecutive_failures == 0
    assert h.failing_since is None
    assert h.failure_class is None
    assert h.alerts_sent == 0
    assert h.last_alert_at is None
    assert h.last_probe_at is None
    assert h.failed_probes == 0


# --- on_failure: допороговые отказы ----------------------------------------------


def test_first_failure_starts_the_outage_clock_without_a_transition() -> None:
    """Первый отказ: счётчик 1, время начала = now, класс записан, перехода нет."""
    h, transition = _fail(ProviderHealth(), _T0, "server")
    assert transition is Transition.NONE
    assert h.state is HealthState.HEALTHY
    assert h.consecutive_failures == 1
    assert h.failing_since == _T0
    assert h.failure_class == "server"
    assert h.last_probe_at == _T0
    assert h.alerts_sent == 0
    assert h.last_alert_at is None


def test_later_failures_keep_the_original_start_time() -> None:
    """Начало простоя — время ПЕРВОГО отказа серии, а не последнего."""
    h, _ = _fail(ProviderHealth(), _T0)
    h, transition = _fail(h, _T0 + 5.0, "timeout")
    assert transition is Transition.NONE
    assert h.consecutive_failures == 2
    assert h.failing_since == _T0
    assert h.failure_class == "timeout"
    assert h.last_probe_at == _T0 + 5.0


# --- on_failure: порог по числу и по длительности ---------------------------------


def test_reaching_the_count_threshold_degrades_once() -> None:
    """Ровно порог отказов (граница ≥) → DEGRADED, первый сигнал записан."""
    h, t1 = _fail(ProviderHealth(), _T0)
    h, t2 = _fail(h, _T0 + 1.0)
    assert (t1, t2) == (Transition.NONE, Transition.NONE)
    h, t3 = _fail(h, _T0 + 2.0, "rate")
    assert t3 is Transition.DEGRADED
    assert h.state is HealthState.DEGRADED
    assert h.consecutive_failures == 3
    assert h.failing_since == _T0
    assert h.failure_class == "rate"
    assert h.alerts_sent == 1
    assert h.last_alert_at == _T0 + 2.0
    assert h.last_probe_at == _T0 + 2.0
    assert h.failed_probes == 0


def test_reaching_the_duration_threshold_degrades_before_the_count() -> None:
    """Два отказа, но между ними ровно порог длительности (граница ≥) → DEGRADED."""
    h, _ = _fail(ProviderHealth(), _T0)
    h, transition = _fail(h, _T0 + 100.0)
    assert transition is Transition.DEGRADED
    assert h.state is HealthState.DEGRADED
    assert h.consecutive_failures == 2
    assert h.alerts_sent == 1
    assert h.last_alert_at == _T0 + 100.0


def test_just_under_the_duration_threshold_stays_healthy() -> None:
    """На волосок раньше порога длительности и ниже порога числа — ещё не деградация."""
    h, _ = _fail(ProviderHealth(), _T0)
    h, transition = _fail(h, _T0 + 99.0)
    assert transition is Transition.NONE
    assert h.state is HealthState.HEALTHY


def test_count_alone_degrades_even_when_the_duration_is_short() -> None:
    """Порог по числу работает без порога по длительности («что раньше»)."""
    h, _ = _fail(ProviderHealth(), _T0)
    h, _ = _fail(h, _T0)
    h, transition = _fail(h, _T0)
    assert transition is Transition.DEGRADED


def test_count_one_below_the_threshold_stays_healthy() -> None:
    """Порог − 1 отказов в одно мгновение — не деградация."""
    h, _ = _fail(ProviderHealth(), _T0)
    h, transition = _fail(h, _T0)
    assert transition is Transition.NONE
    assert h.state is HealthState.HEALTHY


# --- on_failure: в DEGRADED ------------------------------------------------------


def test_failure_while_degraded_before_reminder_is_silent() -> None:
    """DEGRADED не повторяется: отказ до срока напоминания — переход NONE."""
    h = _degraded()
    h2, transition = _fail(h, _T0 + 9.0, "timeout")
    assert transition is Transition.NONE
    assert h2.state is HealthState.DEGRADED
    assert h2.consecutive_failures == 4
    assert h2.failing_since == h.failing_since
    assert h2.failure_class == "timeout"
    assert h2.alerts_sent == 1
    assert h2.last_alert_at == _T0
    assert h2.last_probe_at == _T0 + 9.0
    assert h2.failed_probes == 1


def test_first_reminder_fires_at_the_first_interval() -> None:
    """Ровно reminders_s[0] после первого сигнала (граница ≥) → REMINDER."""
    h, transition = _fail(_degraded(), _T0 + 10.0)
    assert transition is Transition.REMINDER
    assert h.state is HealthState.DEGRADED
    assert h.alerts_sent == 2
    assert h.last_alert_at == _T0 + 10.0


def test_reminders_follow_the_schedule_and_stick_to_the_last_interval() -> None:
    """Напоминания: 10, затем 20, затем 40, затем снова 40 (потолок — последний)."""
    h = _degraded()
    expected_gaps = [10.0, 20.0, 40.0, 40.0, 40.0]
    now = _T0
    for alerts_before, gap in enumerate(expected_gaps, start=1):
        early, t_early = _fail(h, now + gap - 1.0)
        assert t_early is Transition.NONE, f"напоминание №{alerts_before} пришло раньше {gap} с"
        assert early.alerts_sent == alerts_before
        now += gap
        h, transition = _fail(h, now)
        assert transition is Transition.REMINDER, f"нет напоминания через {gap} с"
        assert h.alerts_sent == alerts_before + 1
        assert h.last_alert_at == now


def test_degraded_without_a_recorded_alert_reminds_on_the_next_failure() -> None:
    """DEGRADED без записанного сигнала (собрано вручную) — сигнал не теряется."""
    h = ProviderHealth(state=HealthState.DEGRADED, consecutive_failures=3, alerts_sent=1)
    h2, transition = _fail(h, _T0)
    assert transition is Transition.REMINDER
    assert h2.alerts_sent == 2
    assert h2.last_alert_at == _T0


def test_degraded_failures_count_failed_probes() -> None:
    """Каждый отказ в DEGRADED — проваленная попытка: счётчик растёт на единицу."""
    h = _degraded()
    h, _ = _fail(h, _T0 + 1.0)
    h, _ = _fail(h, _T0 + 2.0)
    assert h.failed_probes == 2
    assert h.consecutive_failures == 5


# --- on_success ------------------------------------------------------------------


def test_success_from_degraded_recovers_and_resets() -> None:
    """Первый успех из DEGRADED → RECOVERED и полностью здоровое состояние."""
    h, transition = on_success(_degraded(), now=_T0 + 50.0)
    assert transition is Transition.RECOVERED
    assert h == ProviderHealth(last_probe_at=_T0 + 50.0)


def test_success_with_sub_threshold_failures_resets_silently() -> None:
    """🔴 Одиночный 5xx не будит: допороговые отказы сбрасываются без перехода."""
    h, _ = _fail(ProviderHealth(), _T0, "server")
    h, _ = _fail(h, _T0 + 1.0, "server")
    h, transition = on_success(h, now=_T0 + 2.0)
    assert transition is Transition.NONE
    assert h == ProviderHealth(last_probe_at=_T0 + 2.0)


def test_success_on_a_clean_provider_is_a_no_op() -> None:
    """Успех здорового провайдера — без перехода, только время последней попытки."""
    h, transition = on_success(ProviderHealth(), now=_T0)
    assert transition is Transition.NONE
    assert h == ProviderHealth(last_probe_at=_T0)


def test_after_recovery_degradation_needs_the_full_threshold_again() -> None:
    """После RECOVERED счёт начинается заново: один отказ — снова не диагноз."""
    h, _ = on_success(_degraded(), now=_T0 + 50.0)
    h, transition = _fail(h, _T0 + 51.0)
    assert transition is Transition.NONE
    assert h.state is HealthState.HEALTHY
    assert h.failing_since == _T0 + 51.0


# --- probe_due и next_probe_interval ----------------------------------------------


def test_healthy_provider_is_always_due_for_a_call() -> None:
    """HEALTHY → вызов разрешён всегда, даже сразу после попытки."""
    h, _ = _fail(ProviderHealth(), _T0)
    assert probe_due(h, now=_T0, policy=_POLICY) is True
    assert probe_due(ProviderHealth(), now=_T0, policy=_POLICY) is True


def test_degraded_probe_waits_for_the_first_interval() -> None:
    """Сразу после деградации зонд ждёт probe_s[0]; ровно на границе — пора."""
    h = _degraded()
    assert probe_due(h, now=_T0 + 4.0, policy=_POLICY) is False
    assert probe_due(h, now=_T0 + 5.0, policy=_POLICY) is True


def test_degraded_probe_interval_grows_with_failed_probes_and_caps() -> None:
    """Интервал зонда: 5, 7, 11, затем 11 (потолок — последний)."""
    h = _degraded()
    now = _T0
    for gap in (5.0, 7.0, 11.0, 11.0, 11.0):
        assert next_probe_interval(h, _POLICY) == gap
        assert probe_due(h, now=now + gap - 1.0, policy=_POLICY) is False
        assert probe_due(h, now=now + gap, policy=_POLICY) is True
        now += gap
        h, _ = _fail(h, now)


def test_next_probe_interval_on_a_fresh_provider_is_the_first_step() -> None:
    """Без проваленных зондов интервал — первый шаг расписания."""
    assert next_probe_interval(ProviderHealth(), _POLICY) == 5.0


def test_degraded_without_a_recorded_attempt_is_due() -> None:
    """Состояние без времени попытки (собрано вручную) — зонд разрешён, а не завис."""
    h = ProviderHealth(state=HealthState.DEGRADED, consecutive_failures=3)
    assert probe_due(h, now=_T0, policy=_POLICY) is True


# --- outage_duration ----------------------------------------------------------------


def test_outage_duration_is_zero_without_failures() -> None:
    """Нет отказов — нет простоя."""
    assert outage_duration(ProviderHealth(), now=_T0) == 0.0


def test_outage_duration_counts_from_the_first_failure() -> None:
    """Длительность — от первого отказа серии до ``now``."""
    h = _degraded(at=_T0)
    assert outage_duration(h, now=_T0 + 40.0) == 42.0


def test_outage_duration_never_goes_negative() -> None:
    """Часы, ушедшие назад, не дают отрицательного простоя."""
    h, _ = _fail(ProviderHealth(), _T0)
    assert outage_duration(h, now=_T0 - 30.0) == 0.0


# --- Значения перечислений ------------------------------------------------------------


def test_state_and_transition_values_are_stable_strings() -> None:
    """Значения идут в лог «healthy → degraded» и в снимок — их меняют осознанно."""
    assert [s.value for s in HealthState] == ["healthy", "degraded"]
    assert [t.value for t in Transition] == ["none", "degraded", "reminder", "recovered"]


# --- Порты kernel/ports.py: наблюдатель, читатель, сигнал владельцу, снимок -------------


class _Observer:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str | None]] = []

    async def record_success(self, provider_id: str) -> None:
        self.seen.append((provider_id, None))

    async def record_failure(self, provider_id: str, failure_class: str) -> None:
        self.seen.append((provider_id, failure_class))


class _Reader:
    def snapshot(self) -> Mapping[str, HealthView]:
        return {"tier1": HealthView(state=HealthState.HEALTHY)}

    def is_degraded(self, provider_id: str) -> bool:
        return provider_id == "tier0-primary"

    def probe_due(self, provider_id: str) -> bool:
        return provider_id != "tier0-primary"


class _Sink:
    async def notify_owner(self, text: str) -> None:
        del text


def test_structural_fakes_satisfy_the_health_ports() -> None:
    """Порты структурные: монитор и адаптер выполняют их без наследования."""
    assert isinstance(_Observer(), HealthObserver)
    assert isinstance(_Reader(), HealthReader)
    assert isinstance(_Sink(), OwnerAlertSink)
    assert not isinstance(_Sink(), HealthObserver)
    assert not isinstance(_Observer(), HealthReader)


def test_health_view_defaults_to_a_clean_healthy_snapshot() -> None:
    """Снимок без истории: здоров, отказов нет, класса и начала простоя нет."""
    view = HealthView(state=HealthState.HEALTHY)
    assert view.consecutive_failures == 0
    assert view.failure_class is None
    assert view.failing_since is None


def test_health_view_is_frozen() -> None:
    """Снимок — значение: читатель не может переписать состояние монитора."""
    view = HealthView(
        state=HealthState.DEGRADED,
        consecutive_failures=5,
        failure_class="auth",
        failing_since=datetime(2026, 10, 1, 6, 10, tzinfo=UTC),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.consecutive_failures = 0  # type: ignore[misc]  # проверяем именно запрет записи
