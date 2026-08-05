# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Транспорт GitHub App API: две ручки и ни одного секрета наружу (BOB-089, срез B).

Проверяется ровно то, за что отвечает адаптер: КУДА уходит запрос, ГДЕ едет секрет и что
происходит, когда ответ не тот, что обещан.

🔴 Секрет живёт ТОЛЬКО в заголовке ``Authorization``. Именно поэтому запрос делается
in-process через aiohttp, а не ``curl``: аргументы процесса видны в ``ps`` любому процессу
пользователя, а заголовок — нет. Тесты это и утверждают: ни JWT, ни выданный токен не
появляются ни в URL, ни в тексте отказа.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.identity.adapters.github_api import AiohttpGitHubAppApi
from bob.identity.ports import TokenMintError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType

_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiI0NDkxOTU0In0.SIGNATURE-SECRET"
_TOKEN = "ghs_TOKENSECRET"


class _FakeResponse:
    """Один ответ фейкового транспорта: статус + JSON-тело."""

    def __init__(self, status: int, body: object) -> None:
        self.status = status
        self._body = body

    async def json(self) -> object:
        return self._body


class _FakeCall:
    """Async-контекст одного вызова; запоминает, чем именно его позвали."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return None


class _FakeTransport:
    """Фейковый шов запросов: отдаёт заготовленные ответы и пишет журнал вызовов."""

    def __init__(self, *responses: _FakeResponse) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, Mapping[str, str]]] = []

    def __call__(self, method: str, url: str, headers: Mapping[str, str]) -> _FakeCall:
        self.calls.append((method, url, dict(headers)))
        return _FakeCall(self._responses.pop(0))


def _api(transport: _FakeTransport) -> AiohttpGitHubAppApi:
    return AiohttpGitHubAppApi(base_url="https://api.github.com", request=transport)


# --------------------------------------------------------------------------- #
# installation_id — где стоит приложение
# --------------------------------------------------------------------------- #


async def test_the_installation_is_looked_up_by_repository() -> None:
    # Токен GitHub скоупится на ОДНУ установку, поэтому установка ищется по тому
    # репозиторию, который принципал обслуживает, — без угадывания «первой из списка».
    transport = _FakeTransport(_FakeResponse(200, {"id": 71234567}))
    installation = await _api(transport).installation_id(
        repository="bobiverse-dev/bob", app_jwt=_JWT
    )
    assert installation == 71234567
    method, url, _ = transport.calls[0]
    assert method == "GET"
    assert url == "https://api.github.com/repos/bobiverse-dev/bob/installation"


async def test_the_app_jwt_travels_in_the_authorization_header_only() -> None:
    # 🔴 Ключевое свойство транспорта: секрет в заголовке, а не в argv и не в URL.
    transport = _FakeTransport(_FakeResponse(200, {"id": 1}))
    await _api(transport).installation_id(repository="bobiverse-dev/bob", app_jwt=_JWT)
    _, url, headers = transport.calls[0]
    assert headers["Authorization"] == f"Bearer {_JWT}"
    assert _JWT not in url


async def test_the_request_declares_the_api_version_and_json_shape() -> None:
    # GitHub меняет форму ответов между версиями API; версия фиксируется явно, иначе
    # «работало вчера» перестанет работать молча.
    transport = _FakeTransport(_FakeResponse(200, {"id": 1}))
    await _api(transport).installation_id(repository="bobiverse-dev/bob", app_jwt=_JWT)
    _, _, headers = transport.calls[0]
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"]


async def test_a_refused_lookup_surfaces_with_its_status_and_without_the_secret() -> None:
    transport = _FakeTransport(_FakeResponse(401, {"message": "Bad credentials"}))
    with pytest.raises(TokenMintError) as excinfo:
        await _api(transport).installation_id(repository="bobiverse-dev/bob", app_jwt=_JWT)
    message = str(excinfo.value)
    assert "401" in message
    assert "SIGNATURE-SECRET" not in message
    assert _JWT not in message


async def test_a_lookup_body_without_an_installation_id_is_a_contract_failure() -> None:
    # Урок BOB-087.E1: контрактный сбой всплывает, а не маскируется догадкой.
    transport = _FakeTransport(_FakeResponse(200, {"unexpected": "shape"}))
    with pytest.raises(TokenMintError, match="installation"):
        await _api(transport).installation_id(repository="bobiverse-dev/bob", app_jwt=_JWT)


async def test_a_non_object_lookup_body_is_a_contract_failure() -> None:
    transport = _FakeTransport(_FakeResponse(200, ["not", "an", "object"]))
    with pytest.raises(TokenMintError):
        await _api(transport).installation_id(repository="bobiverse-dev/bob", app_jwt=_JWT)


# --------------------------------------------------------------------------- #
# create_installation_token — сам токен
# --------------------------------------------------------------------------- #


async def test_the_token_is_minted_for_the_resolved_installation() -> None:
    transport = _FakeTransport(
        _FakeResponse(201, {"token": _TOKEN, "expires_at": "2026-08-06T12:00:00Z"})
    )
    token, expires_at = await _api(transport).create_installation_token(
        installation_id=71234567, app_jwt=_JWT
    )
    assert (token, expires_at) == (_TOKEN, "2026-08-06T12:00:00Z")
    method, url, headers = transport.calls[0]
    assert method == "POST"
    assert url == "https://api.github.com/app/installations/71234567/access_tokens"
    assert headers["Authorization"] == f"Bearer {_JWT}"


async def test_a_refused_mint_surfaces_without_leaking_the_jwt() -> None:
    transport = _FakeTransport(_FakeResponse(403, {"message": "Resource not accessible"}))
    with pytest.raises(TokenMintError) as excinfo:
        await _api(transport).create_installation_token(installation_id=1, app_jwt=_JWT)
    message = str(excinfo.value)
    assert "403" in message
    assert "SIGNATURE-SECRET" not in message


async def test_a_mint_body_without_a_token_is_a_contract_failure() -> None:
    transport = _FakeTransport(_FakeResponse(201, {"expires_at": "2026-08-06T12:00:00Z"}))
    with pytest.raises(TokenMintError, match="token"):
        await _api(transport).create_installation_token(installation_id=1, app_jwt=_JWT)


async def test_a_mint_body_without_an_expiry_is_a_contract_failure() -> None:
    # Без срока обновление ЗАРАНЕЕ невозможно, а значит и пользоваться таким токеном
    # нельзя: он оборвал бы работу в середине.
    transport = _FakeTransport(_FakeResponse(201, {"token": _TOKEN}))
    with pytest.raises(TokenMintError, match="expires_at"):
        await _api(transport).create_installation_token(installation_id=1, app_jwt=_JWT)


async def test_a_leaked_token_in_a_broken_body_never_reaches_the_error_text() -> None:
    # 🔴 Тело ответа несёт СЕКРЕТ, поэтому его нельзя вкладывать в диагностику — даже
    # когда ответ сломан и вложить очень хочется.
    transport = _FakeTransport(_FakeResponse(201, {"token": _TOKEN, "expires_at": 42}))
    with pytest.raises(TokenMintError) as excinfo:
        await _api(transport).create_installation_token(installation_id=1, app_jwt=_JWT)
    assert _TOKEN not in str(excinfo.value)
