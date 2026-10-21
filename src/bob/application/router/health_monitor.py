# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=router

"""ProviderHealthMonitor — здоровье LLM-провайдеров Боба по исходам каждого вызова (BOB-116).

ОДНА ответственность: держать состояние здоровья каждого провайдера и действовать на его
ПЕРЕХОДАХ. Исходы приносят роутер (``tier1`` и «голый» Tier-0) и дублёр-обёртка
(``tier0-primary`` и ``tier0-understudy`` по отдельности) через порт
:class:`~bob.kernel.ports.HealthObserver`; правила переходов — чистое ядро
:mod:`bob.kernel.provider_health`; слова — :mod:`bob.application.router.health_messages`.
На переход монитор делает три вещи и только их:

* **одна строка лога** (``LLM health tier0-primary: healthy → degraded (auth, 5 failures,
  since 09:10:42 +03:00)``) — без стека: стек отказа уже сказал всё, что мог, первый раз;
  время в ней — в поясе процесса с явным смещением, как в текстах человеку
  (:mod:`bob.kernel.local_time`, BOB-116 D12), а не в поясе часов без подписи;
* **сообщение владельцу** через :class:`~bob.kernel.ports.OwnerAlertSink` — ошибка
  доставки глотается с предупреждением, доклад исхода никогда не валит сам вызов;
* на **восстановлении** — колбэк ``on_recovered(provider_id, since, until, failure_class)``,
  через который сборка пишет эпизод «я молчал» в автобиографию. Колбэк — ``Callable``, а не
  порт ``memory``: ``application`` в ``memory`` не ходит.

🔴 Эпизод «я молчал» — только когда Бобу ДЕЙСТВИТЕЛЬНО было нечем думать (решение
координатора, CONTEXT BOB-116): лежал ``tier0-primary`` и дублёра нет или он тоже лежал,
либо лежал ``tier1`` (голос). Облако мертво при живом дублёре — владельцу сигнал есть,
эпизода нет: ложная память хуже дыры. Когда лежали оба этажа Tier-0, молчание началось с
падения ПОЗДНЕГО из них, и эпизод пишет тот, кто первым вернулся, — ровно один раз.

🔴 Порядок важен для гейта дорожек heartbeat (D5): состояние обновляется ДО любого
``await`` — к моменту, когда исключение доходит до вызывающего, ``snapshot()`` уже видит
этот отказ, даже если сообщение владельцу ещё в пути.

Дублёр, включённый в конфигурации, но не готовый при старте, сборка снимает до перезапуска
(:meth:`ProviderHealthMonitor.stand_down_understudy`, BOB-116 D11): с этой минуты монитор
считает, что дублёра нет, — облако легло, значит думать нечем, — а снимок несёт причину,
чтобы ``/status`` сказал «выключен при старте: …», а не «нет».

Ядро считает в секундах ``float``; часы (:class:`~bob.kernel.ports.Clock`) дают
``datetime`` — монитор переводит туда и обратно в поясе часов.
"""

from __future__ import annotations

import logging
from datetime import datetime, tzinfo
from typing import TYPE_CHECKING

from bob.application.router.health_messages import (
    HealthNotice,
    Situation,
    degraded_text,
    recovered_text,
    reminder_text,
)
from bob.kernel.local_time import in_local_zone, utc_offset_label
from bob.kernel.ports import HealthView
from bob.kernel.provider_health import (
    HealthState,
    ProviderHealth,
    Transition,
    next_probe_interval,
    on_failure,
    on_success,
    probe_due,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from bob.kernel.ports import Clock, OwnerAlertSink
    from bob.kernel.provider_health import HealthPolicy

__all__ = [
    "TIER0_PRIMARY",
    "TIER0_UNDERSTUDY",
    "TIER1",
    "NoopHealthObserver",
    "OutageRecovered",
    "ProviderHealthMonitor",
]

logger = logging.getLogger(__name__)

# Идентификаторы провайдеров — одни на роутер, обёртку и монитор (RFC BOB-116).
TIER0_PRIMARY = "tier0-primary"
TIER0_UNDERSTUDY = "tier0-understudy"
TIER1 = "tier1"

# Восстановление после молчания: (provider_id, since, until, failure_class).
type OutageRecovered = Callable[[str, datetime, datetime, str | None], Awaitable[None]]

_SILENT_SITUATIONS = frozenset({Situation.MUTE, Situation.VOICE_DOWN})


class NoopHealthObserver:
    """Наблюдатель-заглушка: исходы никому не нужны (тесты, сборка без монитора)."""

    async def record_success(self, provider_id: str) -> None:
        """Ничего."""

    async def record_failure(self, provider_id: str, failure_class: str) -> None:
        """Ничего."""


class ProviderHealthMonitor:
    """Состояние здоровья провайдеров + реакция на переходы; реализует observer и reader."""

    def __init__(
        self,
        *,
        clock: Clock,
        policy: HealthPolicy,
        sink: OwnerAlertSink,
        on_recovered: OutageRecovered | None = None,
        has_understudy: bool = False,
        owner_name: str | None = None,
    ) -> None:
        self._clock = clock
        self._policy = policy
        self._sink = sink
        self._on_recovered = on_recovered
        self._has_understudy = has_understudy
        self._owner_name = owner_name
        # Известные провайдеры видны в снимке с первой секунды — /status не гадает, есть ли
        # дублёр: его нет в снимке ровно тогда, когда он не подключён.
        wired: tuple[str, ...] = (TIER0_PRIMARY, TIER1)
        if has_understudy:
            wired = (TIER0_PRIMARY, TIER0_UNDERSTUDY, TIER1)
        self._health: dict[str, ProviderHealth] = {pid: ProviderHealth() for pid in wired}
        # Снятые при старте провайдеры и почему (сейчас — только дублёр). Вызовов к ним нет
        # до перезапуска, поэтому в ядре состояния их нет: это факт сборки, не исход вызова.
        self._stood_down: dict[str, str] = {}

    def stand_down_understudy(self, reason: str) -> None:
        """Дублёр снят при старте: дальше Tier-0 — одно облако, до перезапуска процесса.

        Сборка зовёт это в тот же момент, когда роутер переходит на «голое» облако, — и до
        первого вызова провайдера. ``reason`` — человеческая причина из проверки при старте.
        """
        self._has_understudy = False
        self._health.pop(TIER0_UNDERSTUDY, None)
        self._stood_down[TIER0_UNDERSTUDY] = reason

    # --- HealthObserver ------------------------------------------------------------

    async def record_success(self, provider_id: str) -> None:
        """Провайдер ответил: сброс серии; из DEGRADED — «вернулся» и, если молчал, эпизод."""
        moment = self._clock.now()
        before = self._get(provider_id)
        situation = self._situation(provider_id)
        after, transition = on_success(before, now=moment.timestamp())
        self._health[provider_id] = after
        if transition is Transition.RECOVERED:
            await self._recovered(provider_id, before, situation, moment)

    async def record_failure(self, provider_id: str, failure_class: str) -> None:
        """Провайдер отказал: копим серию; на пороге — сигнал, по расписанию — напоминание."""
        moment = self._clock.now()
        after, transition = on_failure(
            self._get(provider_id),
            now=moment.timestamp(),
            failure_class=failure_class,
            policy=self._policy,
        )
        self._health[provider_id] = after
        if transition is Transition.DEGRADED:
            self._log_streak(provider_id, after, moment, "healthy → degraded")
            notice = self._notice(provider_id, after, moment)
            await self._tell_owner(provider_id, degraded_text(notice))
        elif transition is Transition.REMINDER:
            self._log_streak(provider_id, after, moment, "still degraded")
            notice = self._notice(provider_id, after, moment)
            await self._tell_owner(provider_id, reminder_text(notice))

    # --- HealthReader --------------------------------------------------------------

    def snapshot(self) -> Mapping[str, HealthView]:
        """Здоровье каждого известного провайдера по его id."""
        tz = self._clock.now().tzinfo
        views = {pid: self._view(h, tz) for pid, h in self._health.items()}
        for pid, reason in self._stood_down.items():
            views[pid] = HealthView(state=HealthState.DEGRADED, stood_down_reason=reason)
        return views

    def is_degraded(self, provider_id: str) -> bool:
        """Признан ли провайдер неработающим (снятый при старте — тоже); незнакомый — здоров."""
        if provider_id in self._stood_down:
            return True
        return self._get(provider_id).state is HealthState.DEGRADED

    def probe_due(self, provider_id: str) -> bool:
        """Можно ли идти к провайдеру сейчас: здоровому — всегда, лежащему — по расписанию.

        Снятому при старте — никогда: он вернётся только с перезапуском.
        """
        if provider_id in self._stood_down:
            return False
        return probe_due(
            self._get(provider_id), now=self._clock.now().timestamp(), policy=self._policy
        )

    # --- внутреннее ----------------------------------------------------------------

    def _get(self, provider_id: str) -> ProviderHealth:
        return self._health.get(provider_id, ProviderHealth())

    def _situation(self, provider_id: str) -> Situation:
        """Что значит деградация ``provider_id`` при текущем состоянии ДРУГИХ провайдеров."""
        if provider_id == TIER1:
            return Situation.VOICE_DOWN
        if provider_id == TIER0_PRIMARY:
            if not self._has_understudy or self.is_degraded(TIER0_UNDERSTUDY):
                return Situation.MUTE
            return Situation.UNDERSTUDY_HOLDS
        if provider_id == TIER0_UNDERSTUDY:
            if self.is_degraded(TIER0_PRIMARY):
                return Situation.MUTE
            return Situation.UNDERSTUDY_DOWN
        return Situation.OTHER

    async def _recovered(
        self,
        provider_id: str,
        before: ProviderHealth,
        situation: Situation,
        moment: datetime,
    ) -> None:
        """Лог, «вернулся» владельцу и — только после настоящего молчания — эпизод."""
        logger.info(
            "LLM health %s: degraded → healthy (%s, down since %s)",
            provider_id,
            before.failure_class,
            _since_label(self._at(before.failing_since, moment), moment),
        )
        since = self._silence_start(provider_id, before, situation, moment)
        notice = self._notice(provider_id, before, moment, situation=situation, since=since)
        await self._tell_owner(provider_id, recovered_text(notice))
        if situation in _SILENT_SITUATIONS and self._on_recovered is not None:
            try:
                await self._on_recovered(provider_id, since, moment, before.failure_class)
            except Exception as error:  # эпизод — не повод валить вызов, который ответил
                logger.warning(
                    "Outage episode for %s was not recorded (%s: %s)",
                    provider_id,
                    type(error).__name__,
                    error,
                )

    def _silence_start(
        self,
        provider_id: str,
        before: ProviderHealth,
        situation: Situation,
        moment: datetime,
    ) -> datetime:
        """С какого момента Боб молчал: при двух лежащих этажах Tier-0 — с падения позднего."""
        starts = [before.failing_since]
        if situation is Situation.MUTE and self._has_understudy:
            other = TIER0_UNDERSTUDY if provider_id == TIER0_PRIMARY else TIER0_PRIMARY
            starts.append(self._get(other).failing_since)
        known = [start for start in starts if start is not None]
        return self._at(max(known) if known else None, moment)

    def _notice(
        self,
        provider_id: str,
        health: ProviderHealth,
        moment: datetime,
        *,
        situation: Situation | None = None,
        since: datetime | None = None,
    ) -> HealthNotice:
        reminders = self._policy.reminders_s
        step = min(max(health.alerts_sent - 1, 0), len(reminders) - 1)
        return HealthNotice(
            provider_id=provider_id,
            situation=situation if situation is not None else self._situation(provider_id),
            failure_class=health.failure_class,
            failures=health.consecutive_failures,
            since=since if since is not None else self._at(health.failing_since, moment),
            now=moment,
            next_reminder_s=reminders[step],
            probe_s=next_probe_interval(health, self._policy),
            has_understudy=self._has_understudy,
            owner_name=self._owner_name,
        )

    def _log_streak(
        self, provider_id: str, health: ProviderHealth, moment: datetime, change: str
    ) -> None:
        logger.warning(
            "LLM health %s: %s (%s, %d failures, since %s)",
            provider_id,
            change,
            health.failure_class,
            health.consecutive_failures,
            _since_label(self._at(health.failing_since, moment), moment),
        )

    async def _tell_owner(self, provider_id: str, text: str) -> None:
        try:
            await self._sink.notify_owner(text)
        except Exception as error:  # доставка — не повод валить доклад исхода
            logger.warning(
                "Owner alert about %s failed (%s: %s)", provider_id, type(error).__name__, error
            )

    @staticmethod
    def _at(timestamp: float | None, moment: datetime) -> datetime:
        """Время ядра → ``datetime`` в поясе часов; без отметки — сам момент."""
        if timestamp is None:
            return moment
        return datetime.fromtimestamp(timestamp, tz=moment.tzinfo)

    @staticmethod
    def _view(health: ProviderHealth, tz: tzinfo | None) -> HealthView:
        since = (
            None
            if health.failing_since is None
            else datetime.fromtimestamp(health.failing_since, tz=tz)
        )
        return HealthView(
            state=health.state,
            consecutive_failures=health.consecutive_failures,
            failure_class=health.failure_class,
            failing_since=since,
        )


def _since_label(since: datetime, moment: datetime) -> str:
    """«09:10:42 +03:00» в тот же день, иначе с датой — строка лога не врёт про сутки назад.

    Оба момента — в поясе процесса: «тот же день» решается там же, где читается.
    """
    local_since = in_local_zone(since)
    same_day = local_since.date() == in_local_zone(moment).date()
    clock = local_since.strftime("%H:%M:%S" if same_day else "%Y-%m-%d %H:%M:%S")
    offset = utc_offset_label(local_since)
    return f"{clock} {offset}" if offset else clock
