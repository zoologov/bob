# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Снимок здоровья LLM-провайдеров словами для GUPPI ``/status`` (BOB-116 D6).

ОДНА ответственность: снимок :meth:`~bob.kernel.ports.HealthReader.snapshot` превратить в
блок строк по-русски, по строке на провайдера, — так, чтобы владелец прочёл его без
словаря кодов::

    LLM:
    tier0 облако — деградирован с 2026-10-01 06:10 +03:00 (не пускало по ключу/квоте, 5 подряд)
    дублёр — нет
    tier1 — ок

Правила вывода:

* порядок — ``tier0-primary``, ``tier0-understudy``, ``tier1``; id, которых в этом списке
  нет, идут следом по алфавиту под своим id — данные снимка не прячутся;
* id из списка, которого нет в снимке, — «нет данных», а отсутствующий дублёр — «нет»
  (дублёр не настроен — монитор о нём не знает);
* класс отказа говорится безличной фразой из :func:`bob.kernel.ru_text.failure_report` — та
  же таблица причин, что в сообщении владельцу и в эпизоде «я молчал» (ревью M3,
  bob-i83.20); незнакомый класс называется как есть в скобках;
* ``HEALTHY`` с допороговыми отказами не прячется за «ок»: «ок, сбоев подряд: N (…)»;
* провайдер, снятый при старте (``stood_down_reason``: дублёр включён, но не готов), —
  «выключен при старте: <причина> (до перезапуска)»: сам он не вернётся.

🔴 Часовой пояс. Время начала отказа (``failing_since``, у монитора — aware) печатается
как ``YYYY-MM-DD HH:MM +03:00`` в поясе ``tz``; по умолчанию (``tz=None``) — в **поясе
процесса**, то есть в том, что настроен на машине Боба: у владельца на VPS это пояс сервера.
Смещение пишется явно — тот же пояс и та же подпись, что в сообщениях владельцу и в эпизоде
«я молчал» (:mod:`bob.kernel.local_time`, решение координатора bob-i83.15). Наивное время
печатается как есть и без смещения — пересчитывать его не из чего. Предлог перед ним всегда
«с»: время здесь начинается с года, а правило «со 2 октября» из :mod:`bob.kernel.ru_text`
относится ко дню месяца в русской дате.

Чистая функция: ни сети, ни часов, ни монитора — только снимок на входе и текст на выходе.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.kernel.local_time import in_local_zone, utc_offset_label
from bob.kernel.provider_health import TIER0_PRIMARY, TIER0_UNDERSTUDY, TIER1, HealthState
from bob.kernel.ru_text import failure_report

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime, tzinfo

    from bob.kernel.ports import HealthView

__all__ = ["render_health_status"]

_HEADER = "LLM:"
_TIME_FORMAT = "%Y-%m-%d %H:%M"

# Известные провайдеры в порядке показа и их человеческие имена.
_PROVIDER_LABELS: tuple[tuple[str, str], ...] = (
    (TIER0_PRIMARY, "tier0 облако"),
    (TIER0_UNDERSTUDY, "дублёр"),
    (TIER1, "tier1"),
)

_NO_DATA = "нет данных"
_STOOD_DOWN = "выключен при старте: {reason} (до перезапуска)"
_UNDERSTUDY_ABSENT = "нет"
_OK = "ок"


def render_health_status(
    snapshot: Mapping[str, HealthView], *, tz: tzinfo | None = None
) -> str:
    """Блок ``/status``: заголовок ``LLM:`` и по строке на провайдера.

    ``tz`` — пояс, в котором печатается время начала отказа; ``None`` — локальный пояс
    процесса (см. докстринг модуля).
    """
    known = {provider_id for provider_id, _ in _PROVIDER_LABELS}
    lines = [_HEADER]
    for provider_id, label in _PROVIDER_LABELS:
        view = snapshot.get(provider_id)
        lines.append(f"{label} — {_describe(provider_id, view, tz)}")
    for provider_id in sorted(set(snapshot) - known):
        lines.append(f"{provider_id} — {_describe(provider_id, snapshot[provider_id], tz)}")
    return "\n".join(lines)


def _describe(provider_id: str, view: HealthView | None, tz: tzinfo | None) -> str:
    """Состояние одного провайдера словами."""
    if view is None:
        return _UNDERSTUDY_ABSENT if provider_id == TIER0_UNDERSTUDY else _NO_DATA
    if view.stood_down_reason is not None:
        return _STOOD_DOWN.format(reason=view.stood_down_reason)
    if view.state is HealthState.DEGRADED:
        return _describe_degraded(view, tz)
    if view.consecutive_failures > 0:
        return (
            f"{_OK}, сбоев подряд: {view.consecutive_failures}"
            f"{_reason_suffix(view.failure_class)}"
        )
    return _OK


def _describe_degraded(view: HealthView, tz: tzinfo | None) -> str:
    """``деградирован с <время> (<причина>, N подряд)`` — без частей, которых нет."""
    since = (
        f" с {_format_time(view.failing_since, tz)}"
        if view.failing_since is not None
        else ""
    )
    details = [f"{view.consecutive_failures} подряд"]
    if view.failure_class is not None:
        details.insert(0, failure_report(view.failure_class))
    return f"деградирован{since} ({', '.join(details)})"


def _reason_suffix(failure_class: str | None) -> str:
    """`` (<причина>)`` или пусто, если класс не сообщён."""
    return "" if failure_class is None else f" ({failure_report(failure_class)})"


def _format_time(moment: datetime, tz: tzinfo | None) -> str:
    """``YYYY-MM-DD HH:MM +03:00`` в поясе ``tz`` (``None`` — процесса); наивное — без смещения."""
    local = in_local_zone(moment, tz)
    offset = utc_offset_label(local)
    text = local.strftime(_TIME_FORMAT)
    return f"{text} {offset}" if offset else text
