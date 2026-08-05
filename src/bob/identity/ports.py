# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=identity
# beadloom:layer=domain

"""Порты и типы отказов модуля identity (BOB-089, срез B).

Контракты, через которые остальной код получает право говорить с GitHub от имени Боба, и
ничего сверх них: реализации живут в ``adapters/``, а решения — в чистых ядрах
(:mod:`bob.identity.principals`, :mod:`bob.identity.credentials`,
:mod:`bob.identity.app_jwt`, :mod:`bob.identity.token_lifetime`).

🔴 ДИАГНОСТИКА ПО ТИПУ, А НЕ ПО ЗНАЧЕНИЮ. Семейство отказов разделено намеренно:
:class:`IdentityConfigError` — Боб настроен неполно или неверно (ронять на сборке, до
сети); :class:`SigningError` — подписать App-JWT не удалось; :class:`TokenMintError` —
GitHub не выдал installation-токен или ответил не тем, чем обещал. Ни один из них не имеет
права нести значение секрета: ни приватный ключ, ни JWT, ни токен. Ровно поэтому у отказов
нет поля «а вот что мы отправляли» — по типу и по ``app_id`` диагноз ставится, а по
секрету он не нужен.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.identity.principals import Purpose

__all__ = [
    "GitHubAppApi",
    "IdentityConfigError",
    "IdentityError",
    "InstallationTokenSource",
    "Rs256Signer",
    "SigningError",
    "TokenMintError",
]


class IdentityError(Exception):
    """Боб не может выступить своей github-идентичностью (общий корень отказов)."""


class IdentityConfigError(IdentityError):
    """Реквизиты принципала отсутствуют или имеют негодную форму (сбой конфигурации)."""


class SigningError(IdentityError):
    """Подписать App-JWT приватным ключом не удалось."""


class TokenMintError(IdentityError):
    """GitHub не выдал installation-токен либо ответил не обещанной формой."""


@runtime_checkable
class Rs256Signer(Protocol):
    """Подписыватель RS256: подписать байты ключом, лежащим по пути ``private_key_path``.

    🔴 Ключ передаётся ПУТЁМ, а не содержимым: содержимое в argv было бы видно в ``ps``
    любому процессу пользователя.
    """

    async def sign(self, payload: bytes, *, private_key_path: str) -> bytes:
        """Вернуть RS256-подпись ``payload`` (сырые байты, не base64)."""
        ...


@runtime_checkable
class GitHubAppApi(Protocol):
    """Две ручки GitHub App API, которые нужны для минта installation-токена.

    Транспорт, и только он: где стоит приложение и какой токен оно получило. Решение «пора
    ли обновлять» здесь не живёт — оно в чистом ядре
    (:func:`bob.identity.token_lifetime.token_freshness`).
    """

    async def installation_id(self, *, repository: str, app_jwt: str) -> int:
        """Вернуть id установки приложения на репозитории ``repository``."""
        ...

    async def create_installation_token(
        self, *, installation_id: int, app_jwt: str
    ) -> tuple[str, str]:
        """Вернуть ``(токен, срок как его сообщил GitHub)`` для установки."""
        ...


@runtime_checkable
class InstallationTokenSource(Protocol):
    """Источник installation-токена под назначение операции.

    Единственный шов, через который остальной код получает креды Боба. Токен
    короткоживущий и обновляется ЗАРАНЕЕ — вызывающему достаточно попросить его перед
    операцией и не думать о сроках.
    """

    async def token(self, purpose: Purpose) -> str:
        """Вернуть годный токен принципала, обслуживающего ``purpose``."""
        ...
