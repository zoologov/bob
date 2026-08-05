# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit-тесты решения «токен ещё годен / пора обновить» (BOB-089, срез B).

🔴 Смысл ядра — обновлять ЗАРАНЕЕ, а не по факту 401. Installation-токен живёт час, сессия
кодера бывает длиннее, и падение посреди работы обошлось бы дороже, чем лишний минт: за
``margin`` секунд до конца токен считается уже негодным.

Тут же живёт держатель токена, у которого секрет НЕ печатается: значение не попадает ни в
``repr``, ни в ``str`` — то есть ни в traceback, ни в отладочный лог, где оно осело бы
навсегда.
"""

from __future__ import annotations

import pytest

from bob.identity.ports import TokenMintError
from bob.identity.token_lifetime import (
    Freshness,
    InstallationToken,
    parse_expiry,
    token_freshness,
)

_NOW = 1_770_000_000
_MARGIN = 300


def test_a_token_with_plenty_of_time_left_is_used_as_is() -> None:
    assert (
        token_freshness(expires_at=_NOW + 3600, now=_NOW, margin_seconds=_MARGIN)
        is Freshness.USABLE
    )


def test_a_token_inside_the_margin_is_renewed_before_it_dies() -> None:
    # 🔴 Ровно та причина, по которой ядро существует: токен ЕЩЁ валиден (жить ему больше
    # четырёх минут), но начинать им длинную операцию — значит рисковать обрывом.
    assert (
        token_freshness(expires_at=_NOW + 299, now=_NOW, margin_seconds=_MARGIN)
        is Freshness.RENEW
    )


def test_the_margin_boundary_itself_counts_as_time_to_renew() -> None:
    # На самой границе выбираем консервативно: обновить.
    assert (
        token_freshness(expires_at=_NOW + _MARGIN, now=_NOW, margin_seconds=_MARGIN)
        is Freshness.RENEW
    )


def test_one_second_past_the_margin_is_still_usable() -> None:
    # Граница именно там, где заявлено, а не «примерно там».
    assert (
        token_freshness(expires_at=_NOW + _MARGIN + 1, now=_NOW, margin_seconds=_MARGIN)
        is Freshness.USABLE
    )


def test_an_expired_token_is_renewed() -> None:
    assert (
        token_freshness(expires_at=_NOW - 1, now=_NOW, margin_seconds=_MARGIN)
        is Freshness.RENEW
    )


def test_no_token_at_all_means_renew() -> None:
    # Первый вызов: токена нет, и это не ошибка — это повод сходить за ним.
    assert token_freshness(expires_at=None, now=_NOW, margin_seconds=_MARGIN) is Freshness.RENEW


def test_a_zero_margin_still_renews_an_already_dead_token() -> None:
    # Запас можно свести к нулю конфигом, но «просроченный годен» не должно получиться
    # ни при каком значении.
    assert token_freshness(expires_at=_NOW, now=_NOW, margin_seconds=0) is Freshness.RENEW


def test_a_negative_margin_is_refused_rather_than_silently_used() -> None:
    # Отрицательный запас означал бы «пользуйся уже просроченным» — это не настройка, это
    # опечатка, и молчать о ней нельзя.
    with pytest.raises(ValueError, match="margin"):
        token_freshness(expires_at=_NOW + 10, now=_NOW, margin_seconds=-1)


# --------------------------------------------------------------------------- #
# parse_expiry — срок жизни, как его сообщает GitHub
# --------------------------------------------------------------------------- #


def test_the_github_expiry_shape_is_parsed_to_epoch_seconds() -> None:
    # GitHub отдаёт ISO-8601 с 'Z'; всё внутреннее решение живёт в секундах эпохи.
    assert parse_expiry("2026-08-06T12:00:00Z") == 1_786_017_600


def test_an_explicit_offset_is_honoured_not_ignored() -> None:
    # +03:00 — это на три часа РАНЬШЕ того же настенного времени в UTC; проигнорировать
    # смещение значило бы считать токен живее, чем он есть.
    assert parse_expiry("2026-08-06T15:00:00+03:00") == parse_expiry("2026-08-06T12:00:00Z")


def test_the_two_broken_shapes_are_diagnosed_differently() -> None:
    # Диагностика по ТИПУ сбоя: «это вообще не дата» и «дата без зоны» — разные поломки, и
    # различить их в отказе важнее, чем сообщить «что-то не так с expires_at».
    with pytest.raises(TokenMintError, match="ISO-8601"):
        parse_expiry("not-a-date")
    with pytest.raises(TokenMintError, match="timezone"):
        parse_expiry("2026-08-06T12:00:00")


@pytest.mark.parametrize("raw", ["", "  ", "2026-08-06", "not-a-date", "2026-08-06T12:00:00"])
def test_a_broken_expiry_surfaces_instead_of_being_guessed(raw: str) -> None:
    # 🔴 Урок BOB-087.E1: контрактный сбой обязан всплыть, а не быть замаскированным.
    # Токен с неизвестным сроком нельзя обновлять заранее — значит нельзя и пользоваться
    # им молча (наивное время без зоны сюда же: «какой это час» — неизвестно).
    with pytest.raises(TokenMintError, match="expires_at"):
        parse_expiry(raw)


# --------------------------------------------------------------------------- #
# InstallationToken — держатель, который не печатает секрет
# --------------------------------------------------------------------------- #


def test_the_token_value_never_leaks_through_repr() -> None:
    # 🔴 repr уезжает в traceback и в отладочный лог; секрет там осел бы навсегда.
    token = InstallationToken(value="ghs_SUPERSECRET", expires_at=_NOW + 3600)
    assert "ghs_SUPERSECRET" not in repr(token)
    assert "SUPERSECRET" not in str(token)


def test_the_redacted_repr_still_says_when_the_token_dies() -> None:
    # Диагностика по факту, а не по значению: срок виден, секрет — нет.
    token = InstallationToken(value="ghs_x", expires_at=_NOW + 3600)
    assert str(_NOW + 3600) in repr(token)


def test_the_token_value_is_still_readable_by_the_code_that_needs_it() -> None:
    token = InstallationToken(value="ghs_x", expires_at=_NOW + 3600)
    assert token.value == "ghs_x"


def test_an_empty_token_value_is_refused() -> None:
    # Пустое значение — признак сломанного ответа; уехав дальше, оно превратилось бы в
    # невнятный 401 в середине работы.
    with pytest.raises(TokenMintError, match="token"):
        InstallationToken(value="", expires_at=_NOW + 3600)
