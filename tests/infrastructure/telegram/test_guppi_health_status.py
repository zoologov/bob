# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Снимок здоровья LLM в GUPPI ``/status`` (BOB-116 D6).

Две стороны:

* :func:`render_health_status` — снимок ``HealthReader.snapshot()`` превращается в блок
  человеческих строк по-русски: по строке на провайдера, дата начала отказа, класс отказа
  словами, а не кодом;
* :class:`GuppiHandler` — без ``health`` ``/status`` отвечает прежним текстом байт-в-байт,
  с ``health`` — прежний текст и блок снимка, прочитанный в момент команды.

Фейковый reader — структурный ``HealthReader``: ни сети, ни монитора.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.telegram.guppi import GuppiHandler
from bob.infrastructure.telegram.health_status import render_health_status
from bob.kernel.ports import HealthReader, HealthView
from bob.kernel.provider_health import HealthState

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from aiogram.types import InputRichMessage

    from bob.infrastructure.telegram.gateway import UpdateLike

_CHAT_ID = -1004372947307
_OWNER_ID = 27468732

# Прежний ответ ``/status`` — литералом, а не константой модуля: тест держит текст,
# который видит владелец, а не имя, которое можно поменять вместе с текстом.
_PREVIOUS_STATUS = (
    "GUPPI на связи — привратник Боба. Команды: /authorize, /deauthorize, /status."
)

_SINCE_UTC = datetime(2026, 10, 1, 6, 10, tzinfo=UTC)
_MSK = timezone(timedelta(hours=3))


def _healthy() -> HealthView:
    return HealthView(state=HealthState.HEALTHY)


def _degraded(
    failure_class: str | None = "auth",
    failures: int = 5,
    since: datetime | None = _SINCE_UTC,
) -> HealthView:
    return HealthView(
        state=HealthState.DEGRADED,
        consecutive_failures=failures,
        failure_class=failure_class,
        failing_since=since,
    )


# --- render_health_status -----------------------------------------------------


def test_all_healthy_renders_one_line_per_provider_in_fixed_order() -> None:
    snapshot = {
        "tier1": _healthy(),
        "tier0-understudy": _healthy(),
        "tier0-primary": _healthy(),
    }

    assert render_health_status(snapshot, tz=UTC) == (
        "LLM:\ntier0 облако — ок\nдублёр — ок\ntier1 — ок"
    )


def test_degraded_primary_names_start_time_reason_and_count() -> None:
    snapshot = {"tier0-primary": _degraded(), "tier1": _healthy()}

    lines = render_health_status(snapshot, tz=UTC).splitlines()

    assert lines[1] == (
        "tier0 облако — деградирован с 2026-10-01 06:10 +00:00 "
        "(не пускало по ключу/квоте, 5 подряд)"
    )


# Три пояса с разными смещениями: локальный пояс машины совпадает максимум с одним из них,
# поэтому реализация, которая игнорирует ``tz`` и печатает локальное время, краснеет на
# любой машине (на машине с поясом +03:00 одиночный тест с МСК был бы вакуумным).
@pytest.mark.parametrize(
    ("tz", "expected"),
    [
        (UTC, "2026-10-01 06:10 +00:00"),
        (timezone(timedelta(hours=5, minutes=45)), "2026-10-01 11:55 +05:45"),
        (timezone(-timedelta(hours=9, minutes=30)), "2026-09-30 20:40 -09:30"),
    ],
)
def test_start_time_is_rendered_in_the_requested_timezone(tz: tzinfo, expected: str) -> None:
    snapshot = {"tier0-primary": _degraded()}

    assert f"деградирован с {expected} " in render_health_status(snapshot, tz=tz)


def test_default_timezone_is_the_process_local_one() -> None:
    snapshot = {"tier0-primary": _degraded()}
    local = _SINCE_UTC.astimezone()
    zone = local.strftime("%z")  # «+0300» — пояс процесса, посчитанный мимо модуля

    assert f"деградирован с {local:%Y-%m-%d %H:%M} {zone[:3]}:{zone[3:]} " in (
        render_health_status(snapshot)
    )


def test_naive_start_time_is_rendered_as_is() -> None:
    naive = datetime(2026, 10, 2, 23, 5)  # noqa: DTZ001 - наивное время — сам предмет теста
    snapshot = {"tier0-primary": _degraded(since=naive)}

    assert "деградирован с 2026-10-02 23:05 (" in render_health_status(snapshot, tz=_MSK)


# Причина — безличная фраза из общей таблицы bob.kernel.ru_text (ревью M3, bob-i83.20): та же
# причина, что в сообщении владельцу и в эпизоде «я молчал», в регистре строки /status.
@pytest.mark.parametrize(
    ("failure_class", "phrase"),
    [
        ("auth", "не пускало по ключу/квоте"),
        ("rate", "просило подождать"),
        ("server", "падало на своей стороне"),
        ("timeout", "не отвечало"),
        ("connection", "до него было не достучаться"),
        ("shape", "обрывало ответ на полуслове"),
        ("contract", "отвергало запрос"),
    ],
)
def test_failure_class_is_said_in_words(failure_class: str, phrase: str) -> None:
    snapshot = {"tier1": _degraded(failure_class=failure_class, failures=3)}

    assert f"tier1 — деградирован с 2026-10-01 06:10 +00:00 ({phrase}, 3 подряд)" in (
        render_health_status(snapshot, tz=UTC)
    )


def test_unknown_failure_class_is_shown_verbatim() -> None:
    snapshot = {"tier1": _degraded(failure_class="teapot", failures=2)}

    assert "(не работало (teapot), 2 подряд)" in render_health_status(snapshot, tz=UTC)


def test_degraded_without_class_or_start_keeps_the_count() -> None:
    snapshot = {"tier0-primary": _degraded(failure_class=None, since=None)}

    assert "tier0 облако — деградирован (5 подряд)" in render_health_status(snapshot, tz=UTC)


def test_sub_threshold_failures_are_not_hidden_behind_ok() -> None:
    view = HealthView(
        state=HealthState.HEALTHY,
        consecutive_failures=2,
        failure_class="rate",
        failing_since=_SINCE_UTC,
    )

    assert "tier0 облако — ок, сбоев подряд: 2 (просило подождать)" in (
        render_health_status({"tier0-primary": view}, tz=UTC)
    )


def test_absent_understudy_reads_as_none_and_other_absent_ids_as_no_data() -> None:
    assert render_health_status({}, tz=UTC) == (
        "LLM:\ntier0 облако — нет данных\nдублёр — нет\ntier1 — нет данных"
    )


def test_understudy_stood_down_at_startup_names_the_reason_and_the_restart() -> None:
    # bob-i83.15: дублёр включён в конфигурации, но при старте не готов — сборка его сняла,
    # и /status говорит это, а не «нет» (нет — это «не настроен»).
    stood_down = HealthView(
        state=HealthState.DEGRADED,
        stood_down_reason="модели qwen3:8b нет на http://127.0.0.1:11434/v1",
    )
    lines = render_health_status(
        {"tier0-primary": _healthy(), "tier0-understudy": stood_down}, tz=UTC
    ).splitlines()

    assert lines[2] == (
        "дублёр — выключен при старте: модели qwen3:8b нет на http://127.0.0.1:11434/v1 "
        "(до перезапуска)"
    )


def test_unexpected_provider_ids_are_listed_after_the_known_ones() -> None:
    snapshot = {"zeta": _healthy(), "tier1": _healthy(), "alpha": _healthy()}

    lines = render_health_status(snapshot, tz=UTC).splitlines()

    assert lines[-2:] == ["alpha — ок", "zeta — ок"]


# --- GuppiHandler /status -----------------------------------------------------


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _FakeBot:
    """Records GUPPI's plain sends; the other BotLike calls are never made here."""

    texts: list[str] = field(default_factory=list)

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[UpdateLike]:  # pragma: no cover - GuppiHandler never polls
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,  # noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _FakeMessage:
        self.texts.append(text)
        return _FakeMessage(message_id=0, text=text)

    async def set_message_reaction(
        self, *, chat_id: int, message_id: int, reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover - GuppiHandler never reacts
        return True

    async def send_chat_action(
        self, *, chat_id: int, action: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover - GuppiHandler never types
        return True

    async def send_rich_message(
        self, *, chat_id: int, rich_message: InputRichMessage,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _FakeMessage:  # pragma: no cover - GuppiHandler sends plain only
        return _FakeMessage(message_id=0, text="")

    async def send_photo(
        self, *, chat_id: int, photo: object, caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:  # pragma: no cover - never posts a photo
        raise NotImplementedError

    async def send_document(
        self, *, chat_id: int, document: object, caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:  # pragma: no cover - never posts a document
        raise NotImplementedError


@dataclass
class _OwnerOnly:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(
        self, *, user_id: int | None, chat_id: int  # noqa: ARG002
    ) -> bool:  # pragma: no cover - not used by /status
        return True

    async def authorize(self, user_id: int) -> None:  # pragma: no cover
        raise NotImplementedError

    async def deauthorize(self, user_id: int) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass
class _FakeHealthReader:
    """Structural ``HealthReader``: a snapshot the test sets, and how often it was read."""

    views: dict[str, HealthView] = field(default_factory=dict)
    reads: int = 0

    def snapshot(self) -> Mapping[str, HealthView]:
        self.reads += 1
        return dict(self.views)

    def is_degraded(self, provider_id: str) -> bool:  # pragma: no cover - not /status
        return self.views[provider_id].state is HealthState.DEGRADED

    def probe_due(self, provider_id: str) -> bool:  # noqa: ARG002  # pragma: no cover
        return True


def _handler(health: HealthReader | None) -> tuple[GuppiHandler, _FakeBot]:
    bot = _FakeBot()
    handler = GuppiHandler(
        bot=bot, authorizer=_OwnerOnly(), general_chat_id=_CHAT_ID, health=health
    )
    return handler, bot


async def _status(handler: GuppiHandler) -> bool:
    return await handler.handle_general_command(
        text="/status", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )


def test_fake_reader_satisfies_the_port() -> None:
    assert isinstance(_FakeHealthReader(), HealthReader)


@pytest.mark.asyncio
async def test_status_without_health_is_the_previous_text_byte_for_byte() -> None:
    handler, bot = _handler(None)

    assert await _status(handler) is True
    assert bot.texts == [_PREVIOUS_STATUS]


@pytest.mark.asyncio
async def test_status_with_healthy_reader_appends_the_snapshot_block() -> None:
    reader = _FakeHealthReader(
        views={"tier0-primary": _healthy(), "tier1": _healthy()}
    )
    handler, bot = _handler(reader)

    await _status(handler)

    assert bot.texts == [
        _PREVIOUS_STATUS + "\n\nLLM:\ntier0 облако — ок\nдублёр — нет\ntier1 — ок"
    ]


@pytest.mark.asyncio
async def test_status_with_degraded_reader_shows_since_when_and_why() -> None:
    reader = _FakeHealthReader(views={"tier0-primary": _degraded(), "tier1": _healthy()})
    handler, bot = _handler(reader)

    await _status(handler)

    (text,) = bot.texts
    assert text.startswith(_PREVIOUS_STATUS + "\n\nLLM:\n")
    local = _SINCE_UTC.astimezone()
    zone = local.strftime("%z")
    since = f"{local:%Y-%m-%d %H:%M} {zone[:3]}:{zone[3:]}"
    assert (
        f"tier0 облако — деградирован с {since} (не пускало по ключу/квоте, 5 подряд)"
        in text
    )


@pytest.mark.asyncio
async def test_status_reads_the_snapshot_at_command_time_not_at_construction() -> None:
    reader = _FakeHealthReader(views={"tier0-primary": _healthy()})
    handler, bot = _handler(reader)
    assert reader.reads == 0

    reader.views["tier0-primary"] = _degraded()
    await _status(handler)

    assert reader.reads == 1
    assert "tier0 облако — деградирован с " in bot.texts[0]
