# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=identity
# beadloom:layer=infrastructure

"""AiohttpGitHubAppApi — транспорт двух ручек GitHub App API (BOB-089, срез B).

Реализует :class:`bob.identity.ports.GitHubAppApi`. Одна ответственность: сходить в
``api.github.com`` и вернуть ровно то, что там сказали:

* ``GET /repos/{owner}/{repo}/installation`` — где стоит это приложение. Токен GitHub
  скоупится на ОДНУ установку, поэтому установка ищется по обслуживаемому репозиторию, а не
  берётся «первой из списка»;
* ``POST /app/installations/{id}/access_tokens`` — сам installation-токен и его срок.

🔴 СЕКРЕТ ЖИВЁТ ТОЛЬКО В ЗАГОЛОВКЕ. Запрос делается in-process через aiohttp именно поэтому:
``curl`` унёс бы ``Authorization: Bearer <JWT>`` в argv, а argv видно в ``ps`` любому
процессу пользователя. По той же причине ни JWT, ни выданный токен не попадают ни в URL, ни
в лог, ни в текст отказа — в диагностике остаются шаг, HTTP-статус и репозиторий.

🔴 СЛОМАННЫЙ ОТВЕТ ВСПЛЫВАЕТ (урок BOB-087.E1: контрактный сбой нельзя маскировать). Нет
``id``, нет ``token``, нет ``expires_at``, не тот тип — :class:`TokenMintError`, а не
догадка: токен с неизвестным сроком нельзя обновить заранее, а значит нельзя и пользоваться
им молча.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import aiohttp

from bob.identity.ports import TokenMintError

if TYPE_CHECKING:
    from types import TracebackType

__all__ = ["AiohttpGitHubAppApi"]

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.github.com"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_HTTP_OK = 200
_HTTP_CREATED = 201

#: Версия REST API фиксируется явно: иначе смена формы ответов сломала бы Боба молча.
_API_VERSION = "2022-11-28"
_ACCEPT = "application/vnd.github+json"
_USER_AGENT = "BobBot/0.1 (github-app-identity)"


@runtime_checkable
class _JsonResponse(Protocol):
    """Та часть HTTP-ответа, которая нужна: статус + разобранный JSON."""

    @property
    def status(self) -> int: ...

    async def json(self) -> object: ...


@runtime_checkable
class _ResponseCtx(Protocol):
    """Async-контекст одного открытого ответа."""

    async def __aenter__(self) -> _JsonResponse: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...


#: (метод, url, заголовки) -> открытый ответ. Прод оставляет ``None`` (настоящий aiohttp),
#: тесты подсовывают детерминированный фейк — живая сеть в юнитах не участвует.
type JsonRequest = Callable[[str, str, Mapping[str, str]], _ResponseCtx]


class AiohttpGitHubAppApi:
    """Транспорт GitHub App API поверх aiohttp (секрет — только в заголовке)."""

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        request: JsonRequest | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._request = request

    async def installation_id(self, *, repository: str, app_jwt: str) -> int:
        """Вернуть id установки приложения на ``repository`` (форма слага уже проверена)."""
        body = await self._call(
            "GET",
            f"{self._base_url}/repos/{repository}/installation",
            app_jwt=app_jwt,
            expected_status=_HTTP_OK,
            step=f"installation lookup for {repository}",
        )
        installation = body.get("id")
        if not isinstance(installation, int) or isinstance(installation, bool):
            raise TokenMintError(
                f"GitHub returned no numeric installation id for {repository}"
            )
        logger.debug("GitHub installation for %s resolved", repository)
        return installation

    async def create_installation_token(
        self, *, installation_id: int, app_jwt: str
    ) -> tuple[str, str]:
        """Вернуть ``(токен, expires_at как строку GitHub)`` для установки."""
        body = await self._call(
            "POST",
            f"{self._base_url}/app/installations/{installation_id}/access_tokens",
            app_jwt=app_jwt,
            expected_status=_HTTP_CREATED,
            step=f"token mint for installation {installation_id}",
        )
        token = body.get("token")
        if not isinstance(token, str) or not token:
            raise TokenMintError("GitHub response carries no installation token")
        expires_at = body.get("expires_at")
        if not isinstance(expires_at, str) or not expires_at:
            # 🔴 Значение токена в диагностику НЕ идёт, хотя оно тут же, в этом же теле.
            raise TokenMintError("GitHub response carries no expires_at for the token")
        return token, expires_at

    async def _call(
        self,
        method: str,
        url: str,
        *,
        app_jwt: str,
        expected_status: int,
        step: str,
    ) -> Mapping[str, object]:
        """Сделать один запрос и вернуть JSON-объект ответа (или отказать по статусу)."""
        headers = {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": _ACCEPT,
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": _USER_AGENT,
        }
        if self._request is not None:
            return await _read(self._request(method, url, headers), expected_status, step)
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            opened = session.request(method, url, headers=headers)
            return await _read(opened, expected_status, step)


async def _read(
    context: _ResponseCtx, expected_status: int, step: str
) -> Mapping[str, object]:
    """Прочитать ответ: правильный статус + JSON-объект, иначе громкий отказ по типу."""
    async with context as response:
        status = response.status
        if status != expected_status:
            # Тело отказа GitHub не вкладываем: там бывает эхо запроса, а значит и секрет.
            raise TokenMintError(f"GitHub refused the {step}: HTTP {status}")
        body = await response.json()
    if not isinstance(body, Mapping):
        raise TokenMintError(f"GitHub answered the {step} with a non-object body")
    return body
