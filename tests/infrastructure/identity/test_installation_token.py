# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Провайдер installation-токенов: обновление ЗАРАНЕЕ и два принципала (BOB-089, срез B).

🔴 Главное, что здесь доказывается: токен обновляется ДО того, как умрёт, а не по факту
``401``. Installation-токен живёт час, сессия кодера бывает длиннее, и обрыв посреди работы
обошёлся бы дороже лишнего запроса.

Второе: назначение операции выбирает принципала, и реквизиты между принципалами не
съезжают — ``work`` (пуш в форк) и ``propose`` (чтение апстрима) ходят своими ключами, к
своим установкам, со своими кэшами.

Третье: секреты не текут. Ни JWT, ни токен не появляются в логах и в текстах отказов —
проверяется ассертами, а не обещанием.

Подпись здесь фейковая НАМЕРЕННО (тут измеряется политика обновления, а не криптография);
настоящая подпись проверяется настоящим ``openssl`` в
``test_openssl_signer_real_openssl.py`` — фейк доказал бы контракт фейка.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from bob.identity.adapters.installation_token import GitHubInstallationTokens
from bob.identity.ports import IdentityConfigError, TokenMintError
from bob.identity.principals import Purpose

if TYPE_CHECKING:
    from collections.abc import Mapping

_SECTION = {
    "work_app_id": "4491954",
    "work_app_key": "/repo/.secrets/work.pem",
    "work_repo": "bobiverse-dev/bob",
    "propose_app_id": "4491957",
    "propose_app_key": "/repo/.secrets/propose.pem",
    "propose_repo": "zoologov/bob",
}

_HOUR = 3600


class _FrozenClock:
    """Управляемые часы: тест сам решает, сколько прошло времени."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class _FakeSigner:
    """Фейковая подпись: запоминает, каким ключом и что подписывали.

    🔴 ``sleep(0)`` не украшение: настоящая подпись — это подпроцесс, а настоящий запрос —
    сокет, и оба ОТДАЮТ управление циклу. Фейк без точки приостановки исполнялся бы
    «атомарно», и тест на гонку проверял бы контракт фейка, а не наш замок (поймано
    проверкой на кусачесть: снятие замка тест НЕ ронял).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str]] = []

    async def sign(self, payload: bytes, *, private_key_path: str) -> bytes:
        await asyncio.sleep(0)
        self.calls.append((payload, private_key_path))
        return b"signature-bytes"


class _FakeApi:
    """Фейковый GitHub App API: считает вызовы и выдаёт токены по порядку."""

    def __init__(self, *, expires_in: int = _HOUR, clock: _FrozenClock | None = None) -> None:
        self._clock = clock or _FrozenClock()
        self._expires_in = expires_in
        self.lookup_calls: list[tuple[str, str]] = []
        self.mint_calls: list[tuple[int, str]] = []
        self.installations = {"bobiverse-dev/bob": 71000001, "zoologov/bob": 71000002}
        self.minted: list[str] = []

    async def installation_id(self, *, repository: str, app_jwt: str) -> int:
        await asyncio.sleep(0)  # см. пояснение у _FakeSigner: настоящий транспорт уступает
        self.lookup_calls.append((repository, app_jwt))
        return self.installations[repository]

    async def create_installation_token(
        self, *, installation_id: int, app_jwt: str
    ) -> tuple[str, str]:
        await asyncio.sleep(0)  # см. пояснение у _FakeSigner: настоящий транспорт уступает
        self.mint_calls.append((installation_id, app_jwt))
        token = f"ghs_TOKEN{len(self.mint_calls)}"
        self.minted.append(token)
        expiry = self._clock.now() + timedelta(seconds=self._expires_in)
        return token, expiry.isoformat().replace("+00:00", "Z")


def _provider(
    *,
    clock: _FrozenClock,
    api: _FakeApi,
    signer: _FakeSigner | None = None,
    renew_margin_seconds: int = 300,
    section: Mapping[str, object] | None = None,
) -> GitHubInstallationTokens:
    return GitHubInstallationTokens(
        section if section is not None else dict(_SECTION),
        signer=signer or _FakeSigner(),
        api=api,
        clock=clock,
        renew_margin_seconds=renew_margin_seconds,
    )


# --------------------------------------------------------------------------- #
# Штатный путь: один минт, потом кэш
# --------------------------------------------------------------------------- #


async def test_the_first_request_mints_a_token_through_the_app_jwt() -> None:
    clock = _FrozenClock()
    api = _FakeApi(clock=clock)
    signer = _FakeSigner()
    token = await _provider(clock=clock, api=api, signer=signer).token(Purpose.PUSH_TO_FORK)
    assert token == api.minted[0]
    # Подписывался именно ключ принципала work, и подписывались байты «header.payload».
    payload, key_path = signer.calls[0]
    assert key_path == "/repo/.secrets/work.pem"
    assert payload.count(b".") == 1
    # …а в сеть уехал собранный JWT из трёх частей.
    assert api.mint_calls[0][1].count(".") == 2


async def test_a_second_request_reuses_the_cached_token_without_a_new_mint() -> None:
    # Минт стоит двух запросов к GitHub; на каждый пуш ходить за новым токеном незачем.
    clock = _FrozenClock()
    api = _FakeApi(clock=clock)
    provider = _provider(clock=clock, api=api)
    first = await provider.token(Purpose.PUSH_TO_FORK)
    clock.advance(60)
    second = await provider.token(Purpose.PUSH_TO_FORK)
    assert first == second
    assert len(api.mint_calls) == 1


# --------------------------------------------------------------------------- #
# 🔴 Обновление ЗАРАНЕЕ
# --------------------------------------------------------------------------- #


async def test_the_token_is_renewed_before_it_expires_not_after_a_401() -> None:
    # Токен ещё формально жив (осталось 4 минуты при запасе 5), но начинать им длинную
    # операцию — значит рисковать обрывом. Провайдер обновляет ЗАРАНЕЕ.
    clock = _FrozenClock()
    api = _FakeApi(clock=clock, expires_in=_HOUR)
    provider = _provider(clock=clock, api=api, renew_margin_seconds=300)
    first = await provider.token(Purpose.PUSH_TO_FORK)
    clock.advance(_HOUR - 240)
    second = await provider.token(Purpose.PUSH_TO_FORK)
    assert second != first
    assert len(api.mint_calls) == 2


async def test_a_long_session_keeps_getting_a_live_token() -> None:
    # Сессия кодера длиннее часа — ровно случай из PRD: токен обязан оставаться живым, а
    # не умереть в середине работы.
    clock = _FrozenClock()
    api = _FakeApi(clock=clock, expires_in=_HOUR)
    provider = _provider(clock=clock, api=api)
    seen = set()
    for _ in range(4):
        seen.add(await provider.token(Purpose.PUSH_TO_FORK))
        clock.advance(_HOUR - 60)
    assert len(seen) == 4
    assert len(api.mint_calls) == 4


async def test_the_installation_is_looked_up_once_and_reused_across_renewals() -> None:
    # Установка не переезжает, поэтому её поиск — один запрос на принципала, а не на
    # каждый минт.
    clock = _FrozenClock()
    api = _FakeApi(clock=clock)
    provider = _provider(clock=clock, api=api)
    await provider.token(Purpose.PUSH_TO_FORK)
    clock.advance(_HOUR)
    await provider.token(Purpose.PUSH_TO_FORK)
    assert len(api.mint_calls) == 2
    assert len(api.lookup_calls) == 1


# --------------------------------------------------------------------------- #
# Два принципала: реквизиты не съезжают
# --------------------------------------------------------------------------- #


async def test_each_purpose_uses_its_own_principal_credentials_and_installation() -> None:
    clock = _FrozenClock()
    api = _FakeApi(clock=clock)
    signer = _FakeSigner()
    provider = _provider(clock=clock, api=api, signer=signer)
    await provider.token(Purpose.PUSH_TO_FORK)
    await provider.token(Purpose.READ_UPSTREAM)
    assert [key for _, key in signer.calls] == [
        "/repo/.secrets/work.pem",
        "/repo/.secrets/propose.pem",
    ]
    assert [repo for repo, _ in api.lookup_calls] == ["bobiverse-dev/bob", "zoologov/bob"]
    assert [installation for installation, _ in api.mint_calls] == [71000001, 71000002]


async def test_the_two_principals_keep_separate_token_caches() -> None:
    # Один кэш на двоих означал бы работу чужим токеном — то есть либо мёртвый отказ по
    # правам, либо запись не тем принципалом.
    clock = _FrozenClock()
    api = _FakeApi(clock=clock)
    provider = _provider(clock=clock, api=api)
    work = await provider.token(Purpose.PUSH_TO_FORK)
    propose = await provider.token(Purpose.READ_UPSTREAM)
    assert work != propose
    assert await provider.token(Purpose.PUSH_TO_FORK) == work
    assert len(api.mint_calls) == 2


async def test_a_principal_configured_with_a_blank_key_is_refused_by_name() -> None:
    # Ненастроенный принципал — это отказ ДО сети, с именем ключа конфига.
    clock = _FrozenClock()
    api = _FakeApi(clock=clock)
    section = {**_SECTION, "work_app_key": ""}
    provider = _provider(clock=clock, api=api, section=section)
    with pytest.raises(IdentityConfigError, match="work_app_key"):
        await provider.token(Purpose.PUSH_TO_FORK)
    assert api.mint_calls == []


async def test_one_unconfigured_principal_does_not_disable_the_other() -> None:
    # propose может быть не настроен (он нужен только для чтения апстрима) — это не повод
    # лишать Боба его рабочего принципала.
    clock = _FrozenClock()
    api = _FakeApi(clock=clock)
    section = {**_SECTION, "propose_app_id": ""}
    provider = _provider(clock=clock, api=api, section=section)
    assert await provider.token(Purpose.PUSH_TO_FORK)
    with pytest.raises(IdentityConfigError, match="propose_app_id"):
        await provider.token(Purpose.READ_UPSTREAM)


# --------------------------------------------------------------------------- #
# Одновременные запросы
# --------------------------------------------------------------------------- #


async def test_two_concurrent_requests_mint_the_token_once() -> None:
    # Кодер и его окружение спрашивают токен независимо; два минта на один принципал —
    # это лишний запрос и лишний отзываемый токен.
    clock = _FrozenClock()
    api = _FakeApi(clock=clock)
    provider = _provider(clock=clock, api=api)
    first, second = await asyncio.gather(
        provider.token(Purpose.PUSH_TO_FORK), provider.token(Purpose.PUSH_TO_FORK)
    )
    assert first == second
    assert len(api.mint_calls) == 1


# --------------------------------------------------------------------------- #
# 🔴 Секреты не текут
# --------------------------------------------------------------------------- #


async def test_no_secret_reaches_the_debug_log(caplog: pytest.LogCaptureFixture) -> None:
    clock = _FrozenClock()
    api = _FakeApi(clock=clock)
    provider = _provider(clock=clock, api=api)
    with caplog.at_level(logging.DEBUG, logger="bob.identity"):
        token = await provider.token(Purpose.PUSH_TO_FORK)
    logged = caplog.text
    assert token not in logged
    assert api.mint_calls[0][1] not in logged  # сам JWT
    # Диагностика при этом есть: по принципалу и app_id видно, кто ходил за токеном.
    assert "4491954" in logged


async def test_a_failed_mint_reports_the_principal_but_not_the_secret() -> None:
    clock = _FrozenClock()

    class _RefusingApi(_FakeApi):
        async def create_installation_token(
            self, *, installation_id: int, app_jwt: str
        ) -> tuple[str, str]:
            raise TokenMintError("GitHub refused the token request (HTTP 403)")

    api = _RefusingApi(clock=clock)
    provider = _provider(clock=clock, api=api)
    with pytest.raises(TokenMintError) as excinfo:
        await provider.token(Purpose.PUSH_TO_FORK)
    message = str(excinfo.value)
    assert "403" in message
    assert "signature-bytes" not in message
    assert "-----BEGIN" not in message


async def test_a_failed_mint_leaves_no_half_token_behind() -> None:
    # Сорванный минт не должен оставить в кэше «что-то» — следующий вызов обязан честно
    # сходить за токеном снова.
    clock = _FrozenClock()
    calls = {"n": 0}

    class _FlakyApi(_FakeApi):
        async def create_installation_token(
            self, *, installation_id: int, app_jwt: str
        ) -> tuple[str, str]:
            calls["n"] += 1
            if calls["n"] == 1:
                raise TokenMintError("transient failure")
            return await super().create_installation_token(
                installation_id=installation_id, app_jwt=app_jwt
            )

    api = _FlakyApi(clock=clock)
    provider = _provider(clock=clock, api=api)
    with pytest.raises(TokenMintError):
        await provider.token(Purpose.PUSH_TO_FORK)
    assert await provider.token(Purpose.PUSH_TO_FORK)
