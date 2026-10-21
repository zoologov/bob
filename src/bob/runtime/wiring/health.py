# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root LLM-health wiring — монитор здоровья провайдеров из ``llm.health`` (BOB-116).

ОДНА ответственность: собрать из конфигурации то, чем Боб следит за своим модельным стеком, —
политику порогов, канал сигнала владельцу и сам
:class:`~bob.application.router.health_monitor.ProviderHealthMonitor`. Кому монитор отдаётся
(роутер, дублёр-обёртка, гейт дорожек heartbeat, GUPPI ``/status``), решает
``build_application``; здесь только «из чего он сделан».

Канал сигнала — бот Боба, личка ``telegram.owner_id``, шаблон без LLM (решение владельца Р2):
путь не должен зависеть от того, что сломалось. ``llm.health.owner_alert: false`` или
незаданный владелец — заглушка: строка лога остаётся, сообщение не уходит.

Эпизод «я молчал» монитор отдаёт колбэком ``on_recovered``; правило «только когда думать было
нечем» живёт в мониторе, сборка его не повторяет.

Дублёр, не готовый при старте, снимается до перезапуска (BOB-116 D11):
:func:`build_understudy_stand_down` — одно действие на роутер и монитор сразу, чтобы «Tier-0 —
одно облако» и «дублёра нет» стали правдой в один и тот же момент. Проверка асинхронная
(HTTP), а ``build_application`` синхронный, поэтому снимает дублёр ``startup`` — до первого
вызова провайдера, — а не сама сборка: синхронный HTTP в сборке встал бы колом, если бы её
звали из работающего цикла событий рядом с локальным эндпоинтом.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.application.router.health_monitor import ProviderHealthMonitor
from bob.infrastructure.llm.factory import understudy_endpoint
from bob.infrastructure.telegram.owner_alert import NoopOwnerAlert, OwnerAlert
from bob.kernel.provider_health import HealthPolicy
from bob.runtime.config import _flag, _float_or, _int, _section, _str
from bob.runtime.wiring.self_action import build_outage_episode_writer

if TYPE_CHECKING:
    from bob.application.router import LLMRouter
    from bob.infrastructure.llm.factory import UnderstudyEndpoint
    from bob.infrastructure.telegram.owner_alert import _PlainNotifyBot
    from bob.kernel.ports import Clock, OwnerAlertSink
    from bob.memory.ports import SelfActionRecorder

__all__ = [
    "LlmHealth",
    "UnderstudyStandDown",
    "build_health_policy",
    "build_llm_health",
    "build_owner_alert_sink",
    "build_understudy_stand_down",
    "configured_understudy",
    "health_owner_name",
]


# Снять дублёр Tier-0 до перезапуска; аргумент — человеческая причина из проверки при старте.
type UnderstudyStandDown = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class LlmHealth:
    """Собранное здоровье LLM: монитор (наблюдатель + читатель) и канал сигнала владельцу."""

    monitor: ProviderHealthMonitor
    sink: OwnerAlertSink


def build_llm_health(
    config: Mapping[str, object],
    *,
    clock: Clock,
    bot: _PlainNotifyBot,
    recorder: SelfActionRecorder,
) -> LlmHealth:
    """Монитор здоровья провайдеров по ``llm.health`` — до провайдеров, которым он нужен.

    ``recorder`` — автобиография (no-op без ``memory.autobiography``): в неё монитор пишет
    эпизод «я молчал» на восстановлении после настоящей немоты.
    """
    sink = build_owner_alert_sink(config, bot=bot)
    monitor = ProviderHealthMonitor(
        clock=clock,
        policy=build_health_policy(config),
        sink=sink,
        on_recovered=build_outage_episode_writer(recorder),
        has_understudy=configured_understudy(config) is not None,
        owner_name=health_owner_name(config),
    )
    return LlmHealth(monitor=monitor, sink=sink)


def build_understudy_stand_down(
    *, router: LLMRouter, monitor: ProviderHealthMonitor
) -> UnderstudyStandDown:
    """Дублёр не готов при старте → Tier-0 — одно облако, монитор знает, что дублёра нет.

    Роутер переходит на «голое» облако (его вызовы докладывает он сам), монитор перестаёт
    рассчитывать на дублёр — облако легло, значит думать нечем — и несёт причину в снимок
    для ``/status``. Оба шага синхронны и идут подряд: между ними нет ``await``, и ни один
    вызов провайдера не увидит половину. Вернуть дублёр может только перезапуск.
    """

    def stand_down(reason: str) -> None:
        router.stand_down_tier0_understudy()
        monitor.stand_down_understudy(reason)

    return stand_down


def build_health_policy(config: Mapping[str, object]) -> HealthPolicy:
    """Пороги деградации, расписание напоминаний и зонда из ``llm.health`` (дефолт — ядра).

    Негодная политика (``failures_threshold < 2``) останавливает старт ``ValueError`` из
    ядра: опечатка в пороге не должна молча превратить одиночный отказ в тревогу.
    """
    health = _health_section(config)
    default = HealthPolicy()
    return HealthPolicy(
        failures_threshold=_int(health, "failures_threshold", default.failures_threshold),
        duration_threshold_s=_float_or(
            health, "duration_threshold_seconds", default.duration_threshold_s
        ),
        reminders_s=_seconds(health, "reminders_seconds", default.reminders_s),
        probe_s=_seconds(health, "probe_seconds", default.probe_s),
    )


def build_owner_alert_sink(
    config: Mapping[str, object], *, bot: _PlainNotifyBot
) -> OwnerAlertSink:
    """Бот Боба в личку владельца; заглушка, если сигнал выключен или владельца нет."""
    owner_id = _int(_section(config, "telegram"), "owner_id", 0)
    if not _owner_alert_enabled(config) or owner_id <= 0:
        return NoopOwnerAlert()
    return OwnerAlert(bot, owner_id)


def configured_understudy(config: Mapping[str, object]) -> UnderstudyEndpoint | None:
    """Дублёр Tier-0 из конфигурации; без секции ``llm`` (сборка на фейках) — нет дублёра."""
    if not _section(config, "llm"):
        return None
    return understudy_endpoint(config)


def health_owner_name(config: Mapping[str, object]) -> str | None:
    """Как обращаться к владельцу в сигнале; пустое имя — без обращения."""
    return _str(_section(config, "telegram"), "owner_name", "") or None


def _health_section(config: Mapping[str, object]) -> Mapping[str, object]:
    return _section(_section(config, "llm"), "health")


def _owner_alert_enabled(config: Mapping[str, object]) -> bool:
    """``llm.health.owner_alert``; не задан — включён (дефолт CONTEXT BOB-116)."""
    health = _health_section(config)
    if "owner_alert" not in health:
        return True
    return _flag(health, "owner_alert")


def _seconds(
    section: Mapping[str, object], key: str, default: tuple[float, ...]
) -> tuple[float, ...]:
    """Список интервалов в секундах; пустой или с нечисловым элементом — дефолт ядра."""
    value = section.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return default
    numbers = [
        float(item)
        for item in value
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    ]
    if not numbers or len(numbers) != len(value):
        return default
    return tuple(numbers)
