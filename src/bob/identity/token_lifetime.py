# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=identity
# beadloom:layer=domain

"""Годность installation-токена — чистое ядро решения «пора обновить» (BOB-089, срез B).

ОДНА ответственность: сказать, можно ли ещё пользоваться имеющимся токеном или надо идти
за новым. Плюс держатель токена, у которого секрет НЕ печатается.

🔴 ОБНОВЛЯТЬ ЗАРАНЕЕ, А НЕ ПО ФАКТУ ``401``. Installation-токен живёт час, а сессия кодера
бывает длиннее. Дожидаться отказа означало бы ронять работу в середине: часть уже сделана,
ветка не запушена, а вызывающему приходит невнятная ошибка прав. Поэтому за
``margin_seconds`` до конца токен считается уже негодным — лишний минт стоит одного
запроса, потерянная сессия стоит несравнимо дороже.

🔴 СЛОМАННЫЙ СРОК ВСПЛЫВАЕТ, А НЕ УГАДЫВАЕТСЯ (урок BOB-087.E1: контрактный сбой нельзя
маскировать). Токен, срок которого неизвестен, невозможно обновить заранее — значит и
пользоваться им молча нельзя: :func:`parse_expiry` роняет
:class:`~bob.identity.ports.TokenMintError`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from bob.identity.ports import TokenMintError

__all__ = ["Freshness", "InstallationToken", "parse_expiry", "token_freshness"]


class Freshness(Enum):
    """Что делать с имеющимся installation-токеном."""

    #: Времени достаточно — пользоваться как есть.
    USABLE = "usable"
    #: Токена нет, он просрочен или доживает последние секунды — взять новый.
    RENEW = "renew"


@dataclass(frozen=True)
class InstallationToken:
    """Installation-токен со сроком жизни; значение НЕ попадает в ``repr``.

    🔴 ``repr`` уезжает в traceback и в отладочный лог, где секрет осел бы навсегда,
    поэтому у держателя своё представление: срок виден, значение — нет.
    """

    #: Само значение токена (``ghs_…``) — читается только тем, кто идёт с ним в сеть.
    value: str = field(repr=False)
    #: Момент истечения в секундах эпохи.
    expires_at: int

    def __post_init__(self) -> None:
        if not self.value:
            raise TokenMintError("GitHub returned an empty installation token value")

    def __repr__(self) -> str:
        """Диагностическое представление: срок жизни без значения токена."""
        return f"InstallationToken(expires_at={self.expires_at}, value=<redacted>)"


def token_freshness(*, expires_at: int | None, now: int, margin_seconds: int) -> Freshness:
    """Решить, годен ли токен с истечением ``expires_at`` в момент ``now``.

    ``expires_at=None`` — токена ещё нет (первый вызов): это не ошибка, а повод сходить за
    ним. Отрицательный запас — не настройка, а опечатка («пользуйся просроченным»), поэтому
    он отвергается.
    """
    if margin_seconds < 0:
        raise ValueError(f"renew margin must not be negative, got {margin_seconds}s")
    if expires_at is None:
        return Freshness.RENEW
    if expires_at - now <= margin_seconds:
        return Freshness.RENEW
    return Freshness.USABLE


def parse_expiry(raw: str) -> int:
    """Разобрать ``expires_at`` ответа GitHub (ISO-8601 с зоной) в секунды эпохи.

    Наивное время (без зоны) отвергается наравне с мусором: «какой это час» в таком случае
    неизвестно, а ошибка на несколько часов превратила бы обновление заранее в фикцию.
    """
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise TokenMintError(
            "GitHub response field expires_at is not an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise TokenMintError(
            "GitHub response field expires_at carries no timezone — refusing to guess it"
        )
    return int(parsed.timestamp())
