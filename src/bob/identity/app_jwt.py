# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=identity
# beadloom:layer=domain

"""App-JWT (RS256) — чистое ядро claims и сборки токена (BOB-089, срез B).

ОДНА ответственность: что именно подписывается приватным ключом приложения и как
подписанное склеивается в JWT. Сама подпись — работа адаптера
(:mod:`bob.identity.adapters.openssl_signer`), потому что это ввод-вывод; здесь нет ни
файлов, ни процессов, ни сети.

App-JWT — первый из двух шагов аутентификации GitHub App: им приложение доказывает, что
оно — это оно, и просит installation-токен. Форма фиксирована GitHub'ом:

* заголовок ``{"alg":"RS256","typ":"JWT"}``;
* claims ровно три — ``iss`` (app_id), ``iat``, ``exp``;
* подпись RS256 над ``base64url(header) + "." + base64url(claims)``;
* base64url БЕЗ выравнивающих ``=``.

🔴 ДВА ОГРАНИЧЕНИЯ, КОТОРЫЕ ЛЕЧАТСЯ ТОЛЬКО ЗДЕСЬ. GitHub мерит время ПО СВОИМ ЧАСАМ:
``exp`` дальше десяти минут он отвергает целиком, а ``iat`` в будущем (наши часы чуть
впереди) — тоже. Поэтому ``iat`` сдвинут назад на :data:`CLOCK_DRIFT_SECONDS`, а сумма
сдвига и запрошенного времени жизни проверяется против :data:`MAX_JWT_SPAN_SECONDS` —
ронять на сборке дешевле, чем ловить невнятный ``401`` из сети.

Никакого секрета этот модуль не видит: он собирает БАЙТЫ ДЛЯ подписи и приклеивает уже
готовую подпись.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

from bob.identity.ports import IdentityConfigError, SigningError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CLOCK_DRIFT_SECONDS",
    "MAX_JWT_SPAN_SECONDS",
    "assemble_jwt",
    "b64url",
    "jwt_claims",
    "signing_input",
]

#: Насколько ``iat`` сдвигается НАЗАД против расхождения часов с GitHub (секунды).
CLOCK_DRIFT_SECONDS = 60

#: Предел GitHub на ``exp - iat`` App-JWT: десять минут, дальше — отказ (секунды).
MAX_JWT_SPAN_SECONDS = 600

#: Заголовок фиксирован: единственный алгоритм подписи GitHub App — RS256.
_HEADER: Mapping[str, str] = {"alg": "RS256", "typ": "JWT"}


def jwt_claims(*, app_id: str, now: int, lifetime_seconds: int) -> dict[str, int | str]:
    """Собрать claims App-JWT для ``app_id`` на ``lifetime_seconds`` вперёд от ``now``.

    ``iat`` намеренно сдвинут назад на :data:`CLOCK_DRIFT_SECONDS`; ``exp`` — ровно
    ``now + lifetime_seconds``. Негодное время жизни (неположительное или такое, что вместе
    со сдвигом перерастает предел GitHub) отвергается здесь, а не в сети.
    """
    if not app_id:
        raise IdentityConfigError("app_id is required to issue an App JWT")
    if lifetime_seconds <= 0:
        raise IdentityConfigError(
            f"App JWT lifetime must be positive, got {lifetime_seconds}s"
        )
    if lifetime_seconds + CLOCK_DRIFT_SECONDS > MAX_JWT_SPAN_SECONDS:
        raise IdentityConfigError(
            f"App JWT lifetime {lifetime_seconds}s exceeds the GitHub ceiling "
            f"({MAX_JWT_SPAN_SECONDS}s including the {CLOCK_DRIFT_SECONDS}s clock-drift "
            "backdate)"
        )
    return {"iss": app_id, "iat": now - CLOCK_DRIFT_SECONDS, "exp": now + lifetime_seconds}


def signing_input(claims: Mapping[str, int | str]) -> bytes:
    """Вернуть байты ``base64url(header).base64url(claims)``, которые надо подписать.

    JSON компактный и с отсортированными ключами — те же claims дают те же байты, иначе
    подпись собиралась бы над разным содержимым при одном и том же смысле.
    """
    return b".".join((_segment(_HEADER), _segment(claims)))


def assemble_jwt(payload: bytes, signature: bytes) -> str:
    """Склеить готовый JWT из подписанных байтов ``payload`` и подписи ``signature``.

    Пустая подпись означает, что подписывающий шаг молча провалился; такой «токен» уехал бы
    в сеть и вернулся невнятным ``401``, поэтому он отвергается здесь.
    """
    if not signature:
        raise SigningError("refusing to assemble an App JWT with an empty signature")
    return f"{payload.decode('ascii')}.{b64url(signature)}"


def b64url(raw: bytes) -> str:
    """Закодировать ``raw`` в base64url без выравнивающих ``=`` (форма JWT)."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _segment(payload: Mapping[str, int | str] | Mapping[str, str]) -> bytes:
    """Закодировать одну часть JWT: компактный детерминированный JSON в base64url."""
    encoded = json.dumps(dict(payload), separators=(",", ":"), sort_keys=True)
    return b64url(encoded.encode("utf-8")).encode("ascii")
