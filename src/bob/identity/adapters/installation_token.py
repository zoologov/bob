# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=identity
# beadloom:layer=infrastructure

"""GitHubInstallationTokens — короткоживущий токен, обновляемый ЗАРАНЕЕ (BOB-089, срез B).

Реализует :class:`bob.identity.ports.InstallationTokenSource`. Одна ответственность:
держать по одному годному installation-токену на принципала и вовремя брать новый. Решения
берутся из чистых ядер (:func:`~bob.identity.principals.principal_for`,
:func:`~bob.identity.credentials.credentials_for`, :mod:`bob.identity.app_jwt`,
:func:`~bob.identity.token_lifetime.token_freshness`), а здесь — только их исполнение:
подписать, сходить, положить в кэш.

🔴 ОБНОВЛЕНИЕ ЗАРАНЕЕ, А НЕ ПО ФАКТУ ``401``. Installation-токен живёт час, сессия кодера
бывает длиннее. Дожидаться отказа значило бы ронять работу в середине: часть сделана, ветка
не запушена, а вызывающему приходит невнятная ошибка прав. Поэтому за
``renew_margin_seconds`` до конца токен считается негодным заранее — лишний минт стоит
одного запроса, потерянная сессия несравнимо дороже.

Два принципала — два независимых кэша и две независимые установки: ``work`` пушит в форк,
``propose`` читает апстрим, и права у них РАЗНЫЕ (см. :mod:`bob.identity.principals`).
Реквизиты разбираются ЛЕНИВО, по первому обращению: ненастроенный ``propose`` не должен
лишать Боба его рабочего принципала.

🔴 СЕКРЕТЫ НЕ ЛОГИРУЮТСЯ НИКОГДА. В отладочный лог идут принципал, ``app_id`` и срок
жизни — по ним видно, кто ходил за токеном и когда пойдёт снова; ни JWT, ни само значение
токена там не появляются (утверждено тестом, а не обещанием).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from bob.identity.adapters.github_api import AiohttpGitHubAppApi
from bob.identity.adapters.openssl_signer import OpensslRs256Signer
from bob.identity.app_jwt import assemble_jwt, jwt_claims, signing_input
from bob.identity.credentials import AppCredentials, credentials_for
from bob.identity.principals import Principal, Purpose, principal_for
from bob.identity.token_lifetime import (
    Freshness,
    InstallationToken,
    parse_expiry,
    token_freshness,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from bob.identity.ports import GitHubAppApi, Rs256Signer
    from bob.kernel.ports import Clock

__all__ = ["GitHubInstallationTokens", "build_installation_tokens"]

logger = logging.getLogger(__name__)

#: Запас, за который до конца токен считается негодным (секунды). Пять минут — заметно
#: больше самой долгой операции git, которую Боб делает под этим токеном.
DEFAULT_RENEW_MARGIN_SECONDS = 300

#: Время жизни App-JWT: с запасом внутри десятиминутного предела GitHub (секунды).
DEFAULT_JWT_LIFETIME_SECONDS = 480


class GitHubInstallationTokens:
    """Кэш installation-токенов двух принципалов с обновлением заранее."""

    def __init__(
        self,
        section: Mapping[str, object],
        *,
        signer: Rs256Signer,
        api: GitHubAppApi,
        clock: Clock,
        root: Path,
        renew_margin_seconds: int = DEFAULT_RENEW_MARGIN_SECONDS,
        jwt_lifetime_seconds: int = DEFAULT_JWT_LIFETIME_SECONDS,
    ) -> None:
        self._section = section
        self._root = root
        self._signer = signer
        self._api = api
        self._clock = clock
        self._margin = renew_margin_seconds
        self._jwt_lifetime = jwt_lifetime_seconds
        self._credentials: dict[Principal, AppCredentials] = {}
        self._installations: dict[Principal, int] = {}
        self._tokens: dict[Principal, InstallationToken] = {}
        self._locks: dict[Principal, asyncio.Lock] = {
            principal: asyncio.Lock() for principal in Principal
        }

    async def token(self, purpose: Purpose) -> str:
        """Вернуть годный токен принципала, обслуживающего ``purpose``.

        Годность решает чистое ядро; при негодности токен минтится под замком принципала —
        одновременные запросы (кодер и его окружение спрашивают независимо) дают ОДИН минт,
        а не два лишних отзываемых токена.
        """
        principal = principal_for(purpose)
        cached = self._usable(principal)
        if cached is not None:
            return cached
        async with self._locks[principal]:
            # Под замком проверяем ещё раз: пока мы его ждали, сосед мог уже сминтить.
            cached = self._usable(principal)
            if cached is not None:
                return cached
            return await self._mint(principal)

    def _usable(self, principal: Principal) -> str | None:
        """Вернуть закэшированный токен, если он ещё годен по вердикту ядра."""
        held = self._tokens.get(principal)
        expires_at = held.expires_at if held is not None else None
        freshness = token_freshness(
            expires_at=expires_at, now=self._now(), margin_seconds=self._margin
        )
        if freshness is Freshness.USABLE and held is not None:
            return held.value
        return None

    async def _mint(self, principal: Principal) -> str:
        """Взять новый installation-токен принципала и положить его в кэш."""
        credentials = self._credentials_of(principal)
        app_jwt = await self._app_jwt(credentials)
        installation = await self._installation_of(principal, credentials, app_jwt)
        raw_token, raw_expiry = await self._api.create_installation_token(
            installation_id=installation, app_jwt=app_jwt
        )
        token = InstallationToken(value=raw_token, expires_at=parse_expiry(raw_expiry))
        self._tokens[principal] = token
        logger.debug(
            "installation token minted for principal %s (app_id %s), expires_at %s",
            principal.value,
            credentials.app_id,
            token.expires_at,
        )
        return token.value

    async def _app_jwt(self, credentials: AppCredentials) -> str:
        """Собрать и подписать App-JWT принципала (ключ участвует путём, не содержимым)."""
        claims = jwt_claims(
            app_id=credentials.app_id, now=self._now(), lifetime_seconds=self._jwt_lifetime
        )
        payload = signing_input(claims)
        signature = await self._signer.sign(
            payload, private_key_path=credentials.private_key_path
        )
        return assemble_jwt(payload, signature)

    async def _installation_of(
        self, principal: Principal, credentials: AppCredentials, app_jwt: str
    ) -> int:
        """Вернуть id установки принципала, найдя его один раз за жизнь провайдера."""
        known = self._installations.get(principal)
        if known is not None:
            return known
        installation = await self._api.installation_id(
            repository=credentials.repository, app_jwt=app_jwt
        )
        self._installations[principal] = installation
        return installation

    def _credentials_of(self, principal: Principal) -> AppCredentials:
        """Разобрать реквизиты принципала (лениво, по первому обращению)."""
        known = self._credentials.get(principal)
        if known is not None:
            return known
        credentials = credentials_for(self._section, principal, root=self._root)
        self._credentials[principal] = credentials
        return credentials

    def _now(self) -> int:
        """Текущее время в секундах эпохи (через инжектированные часы, не ``datetime.now``)."""
        return int(self._clock.now().timestamp())


def build_installation_tokens(
    section: Mapping[str, object], *, clock: Clock, root: Path
) -> GitHubInstallationTokens:
    """Собрать провайдер токенов из секции конфига ``github`` (настоящие openssl + aiohttp).

    Реквизиты принципалов НЕ разбираются здесь: сборка провайдера должна быть возможна и на
    ненастроенном Бобе (флаг выключен, ключей нет) — отказ придёт тогда, когда токен реально
    понадобится, и назовёт недостающий ключ конфига.

    ``root`` — корень проекта, от которого читается ОТНОСИТЕЛЬНЫЙ путь к ключу принципала
    (абсолютный и домашний уважаются как есть). Он едет сюда с композиции, чтобы путь не
    зависел от того, из какого каталога запущен процесс (bob-a6b.15).
    """
    return GitHubInstallationTokens(
        section,
        root=root,
        signer=OpensslRs256Signer(
            openssl_bin=_text(section, "openssl_bin", "openssl"),
            timeout_seconds=_number(section, "timeout_seconds", 30.0),
        ),
        api=AiohttpGitHubAppApi(
            base_url=_text(section, "api_base_url", "https://api.github.com"),
            timeout_seconds=_number(section, "timeout_seconds", 30.0),
        ),
        clock=clock,
        renew_margin_seconds=int(
            _number(section, "token_margin_seconds", DEFAULT_RENEW_MARGIN_SECONDS)
        ),
        jwt_lifetime_seconds=int(
            _number(section, "jwt_lifetime_seconds", DEFAULT_JWT_LIFETIME_SECONDS)
        ),
    )


def _text(section: Mapping[str, object], key: str, default: str) -> str:
    """Прочитать строковый параметр секции, не роняя сборку на пустом значении."""
    value = section.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _number(section: Mapping[str, object], key: str, default: float) -> float:
    """Прочитать числовой параметр секции (env отдаёт строки — они тоже принимаются)."""
    value = section.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default
