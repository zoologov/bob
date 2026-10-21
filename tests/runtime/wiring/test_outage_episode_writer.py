# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Эпизод «я молчал» говорит о времени в поясе процесса со смещением (BOB-116 D11).

Монитор отдаёт время в поясе часов (на VPS — UTC); сборка переводит его в пояс процесса —
тот же, что у сообщения владельцу и у GUPPI ``/status`` (решение координатора, bob-i83.15).
Пояс входа выбирается заведомо ОТЛИЧНЫМ от пояса машины (её смещение плюс 5:45), поэтому
сборка, которая пропустит перевод, краснеет на любой машине, а не только на «чужой».
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from bob.memory.self_action import SelfAction, describe_self_action
from bob.runtime.wiring.self_action import build_outage_episode_writer

_SINCE_UTC = datetime(2026, 10, 1, 6, 10, tzinfo=UTC)


class _Recorder:
    def __init__(self) -> None:
        self.actions: list[tuple[SelfAction, int | None, str | None]] = []

    async def record(
        self,
        action: SelfAction,
        *,
        sender_id: int | None = None,
        visibility: str | None = None,
    ) -> None:
        self.actions.append((action, sender_id, visibility))


def _offset_text(moment: datetime) -> str:
    """«+03:00» — посчитано мимо ядра ``local_time``, через ``%z``."""
    zone = moment.strftime("%z")
    return f"{zone[:3]}:{zone[3:]}"


async def test_episode_period_is_in_the_process_zone_with_its_offset() -> None:
    local_offset = _SINCE_UTC.astimezone().utcoffset()
    assert local_offset is not None
    foreign = timezone(local_offset + timedelta(hours=5, minutes=45))
    recorder = _Recorder()
    write = build_outage_episode_writer(recorder)

    since = _SINCE_UTC.astimezone(foreign)
    until = (_SINCE_UTC + timedelta(minutes=32)).astimezone(foreign)
    await write("tier0-primary", since, until, "auth")

    (action, sender_id, visibility) = recorder.actions[0]
    content = describe_self_action(action).content
    local_since = _SINCE_UTC.astimezone()
    local_until = (_SINCE_UTC + timedelta(minutes=32)).astimezone()
    assert f"с {local_since:%H:%M} по {local_until:%H:%M} {_offset_text(local_until)} (" in (
        content
    )
    assert _offset_text(until) not in content
    assert sender_id is None
    assert visibility == "owner_private"
