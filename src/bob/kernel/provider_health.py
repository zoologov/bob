# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Здоровье LLM-провайдера — состояние и переходы по исходам вызовов (BOB-116).

ОДНА ответственность: по исходу очередного вызова провайдера (успех / отказ с классом),
времени ``now`` и политике вернуть новое состояние и переход, а для зонда — сказать,
пора ли пробовать снова. Ничего не логирует, не шлёт и не смотрит на часы: время
приносит вызывающий слой (монитор ``application/router/health_monitor.py``), и он же
решает, что делать с переходом (сигнал владельцу, строка в логе, эпизод автобиографии).

Правила:

* **DEGRADED** — когда отказов подряд ``≥ failures_threshold`` **или** с первого отказа
  серии прошло ``≥ duration_threshold_s`` (что наступит раньше). Переход отдаётся один
  раз; повторные отказы в DEGRADED его не повторяют.
* **REMINDER** — отказ в DEGRADED, когда с прошлого сигнала прошло
  ``≥ reminders_s[min(alerts_sent - 1, len - 1)]``: расписание идёт по шагам, потолок —
  последний шаг.
* **RECOVERED** — только первый успех из DEGRADED. 🔴 Успех после допороговых отказов —
  тихий сброс без перехода: одиночный 5xx не будит владельца.
* **Зонд.** В HEALTHY вызов разрешён всегда. В DEGRADED — не раньше
  ``probe_s[min(failed_probes, len - 1)]`` от последней попытки; каждый отказ в DEGRADED
  считается проваленной попыткой, поэтому интервал растёт до потолка.

Ограничение, названное честно: ядро не различает зонд и обычный вызов. Отказ ответа
человеку в DEGRADED тоже сдвигает расписание зонда — для провайдера это такая же попытка.

🔴 Логика — в функциях модульного уровня, а не в методах dataclass: mutmut не мутирует
тела декорированных классов (MUTATION.md «Порог и честность»), и гейт иначе был бы
фантомным.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "HealthPolicy",
    "HealthState",
    "ProviderHealth",
    "Transition",
    "next_probe_interval",
    "on_failure",
    "on_success",
    "outage_duration",
    "probe_due",
]


class HealthState(Enum):
    """Состояние провайдера: отвечает или признан неработающим."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"


class Transition(Enum):
    """Что произошло на этом исходе — то, на что реагирует монитор."""

    NONE = "none"
    DEGRADED = "degraded"
    REMINDER = "reminder"
    RECOVERED = "recovered"


@dataclass(frozen=True, slots=True)
class HealthPolicy:
    """Пороги деградации, расписание напоминаний и зонда (секунды).

    Дефолты — блок ``llm.health`` из CONTEXT BOB-116. Негодная политика отвергается
    при создании (:func:`_check_policy`): порог числа отказов ``< 2`` сделал бы
    одиночный отказ диагнозом, как в ``outage_state`` (BOB-094).
    """

    failures_threshold: int = 5
    duration_threshold_s: float = 180.0
    reminders_s: tuple[float, ...] = (600.0, 3600.0, 21600.0, 86400.0)
    probe_s: tuple[float, ...] = (60.0, 120.0, 300.0)

    def __post_init__(self) -> None:
        _check_policy(self)


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """Снимок здоровья одного провайдера; по умолчанию — здоров и без истории.

    ``failing_since`` — время первого отказа текущей серии; ``last_probe_at`` — время
    последней попытки (любой исход); ``failed_probes`` — сколько попыток провалилось
    после перехода в DEGRADED (индекс расписания зонда).
    """

    state: HealthState = HealthState.HEALTHY
    consecutive_failures: int = 0
    failing_since: float | None = None
    failure_class: str | None = None
    alerts_sent: int = 0
    last_alert_at: float | None = None
    last_probe_at: float | None = None
    failed_probes: int = 0


def _check_policy(policy: HealthPolicy) -> None:
    """Отвергнуть политику, на которой ядро вело бы себя бессмысленно."""
    min_failures_threshold = 2
    if policy.failures_threshold < min_failures_threshold:
        msg = (
            f"failures_threshold must be >= 2 (a single failure is not an outage), "
            f"got {policy.failures_threshold}"
        )
        raise ValueError(msg)
    if policy.duration_threshold_s <= 0:
        msg = f"duration_threshold_s must be positive, got {policy.duration_threshold_s}"
        raise ValueError(msg)
    _check_schedule("reminders_s", policy.reminders_s)
    _check_schedule("probe_s", policy.probe_s)


def _check_schedule(name: str, schedule: tuple[float, ...]) -> None:
    """Расписание непустое и из положительных шагов — иначе нет ни интервала, ни потолка."""
    if not schedule:
        msg = f"{name} must not be empty"
        raise ValueError(msg)
    if any(step <= 0 for step in schedule):
        msg = f"{name} steps must be positive, got {schedule}"
        raise ValueError(msg)


def on_failure(
    h: ProviderHealth,
    *,
    now: float,
    failure_class: str,
    policy: HealthPolicy,
) -> tuple[ProviderHealth, Transition]:
    """Учесть отказ: копить серию, перейти в DEGRADED по порогу или напомнить."""
    if h.state is HealthState.DEGRADED:
        return _fail_while_degraded(h, now=now, failure_class=failure_class, policy=policy)
    failures = h.consecutive_failures + 1
    since = now if h.failing_since is None else h.failing_since
    if failures >= policy.failures_threshold or now - since >= policy.duration_threshold_s:
        degraded = ProviderHealth(
            state=HealthState.DEGRADED,
            consecutive_failures=failures,
            failing_since=since,
            failure_class=failure_class,
            alerts_sent=1,
            last_alert_at=now,
            last_probe_at=now,
        )
        return degraded, Transition.DEGRADED
    accumulating = ProviderHealth(
        consecutive_failures=failures,
        failing_since=since,
        failure_class=failure_class,
        last_probe_at=now,
    )
    return accumulating, Transition.NONE


def _fail_while_degraded(
    h: ProviderHealth,
    *,
    now: float,
    failure_class: str,
    policy: HealthPolicy,
) -> tuple[ProviderHealth, Transition]:
    """Отказ в DEGRADED: проваленная попытка и, если пора, напоминание."""
    probed = dataclasses.replace(
        h,
        consecutive_failures=h.consecutive_failures + 1,
        failure_class=failure_class,
        last_probe_at=now,
        failed_probes=h.failed_probes + 1,
    )
    if not _reminder_due(h, now=now, policy=policy):
        return probed, Transition.NONE
    reminded = dataclasses.replace(probed, alerts_sent=h.alerts_sent + 1, last_alert_at=now)
    return reminded, Transition.REMINDER


def _reminder_due(h: ProviderHealth, *, now: float, policy: HealthPolicy) -> bool:
    """Прошёл ли шаг расписания напоминаний с прошлого сигнала (потолок — последний)."""
    if h.last_alert_at is None:
        return True
    step = min(h.alerts_sent - 1, len(policy.reminders_s) - 1)
    return now - h.last_alert_at >= policy.reminders_s[step]


def on_success(h: ProviderHealth, *, now: float) -> tuple[ProviderHealth, Transition]:
    """Учесть успех: полный сброс; RECOVERED — только если провайдер был в DEGRADED."""
    healthy = ProviderHealth(last_probe_at=now)
    if h.state is HealthState.DEGRADED:
        return healthy, Transition.RECOVERED
    return healthy, Transition.NONE


def probe_due(h: ProviderHealth, *, now: float, policy: HealthPolicy) -> bool:
    """Пора ли пробовать провайдера: в HEALTHY — всегда, в DEGRADED — по расписанию."""
    if h.state is HealthState.HEALTHY or h.last_probe_at is None:
        return True
    return now - h.last_probe_at >= next_probe_interval(h, policy)


def next_probe_interval(h: ProviderHealth, policy: HealthPolicy) -> float:
    """Интервал до следующего зонда: шаг по числу проваленных попыток, потолок — последний."""
    step = min(h.failed_probes, len(policy.probe_s) - 1)
    return policy.probe_s[step]


def outage_duration(h: ProviderHealth, *, now: float) -> float:
    """Сколько длится серия отказов к ``now``; без отказов и при часах назад — ноль."""
    if h.failing_since is None:
        return 0.0
    return max(0.0, now - h.failing_since)
