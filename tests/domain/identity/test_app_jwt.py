# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit-тесты чистого ядра App-JWT (RS256) — claims и сборка (BOB-089, срез B).

Ядро собирает то, что подписывается, и склеивает подписанное; сама подпись — работа
адаптера (``openssl``), и она проверяется НАСТОЯЩИМ openssl отдельно
(``tests/infrastructure/identity/test_openssl_signer_real_openssl.py``) — фейк доказал бы
контракт фейка.

Здесь измеряется сила решений: какие claims уезжают GitHub'у, как выдерживается его
ограничение «не дальше 10 минут», и почему ``iat`` намеренно сдвинут назад.
"""

from __future__ import annotations

import base64
import json

import pytest

from bob.identity.app_jwt import (
    CLOCK_DRIFT_SECONDS,
    MAX_JWT_SPAN_SECONDS,
    assemble_jwt,
    b64url,
    jwt_claims,
    signing_input,
)
from bob.identity.ports import IdentityConfigError, SigningError

_NOW = 1_770_000_000


def _decode_segment(segment: str) -> dict[str, object]:
    padded = segment + "=" * (-len(segment) % 4)
    decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    parsed = json.loads(decoded)
    assert isinstance(parsed, dict)
    return parsed


# --------------------------------------------------------------------------- #
# jwt_claims — что именно подписывается
# --------------------------------------------------------------------------- #


def test_the_issuer_is_the_app_id() -> None:
    # GitHub опознаёт App по ``iss``: не тот app_id — не тот принципал.
    claims = jwt_claims(app_id="4491954", now=_NOW, lifetime_seconds=480)
    assert claims["iss"] == "4491954"


def test_issued_at_is_backdated_against_clock_drift() -> None:
    # 🔴 Часы нашей машины и GitHub'а расходятся на секунды, и «iat в будущем» он
    # отвергает целиком. Поэтому ``iat`` сдвинут назад НАМЕРЕННО.
    claims = jwt_claims(app_id="1", now=_NOW, lifetime_seconds=480)
    assert claims["iat"] == _NOW - CLOCK_DRIFT_SECONDS


def test_expiry_is_the_requested_lifetime_ahead() -> None:
    claims = jwt_claims(app_id="1", now=_NOW, lifetime_seconds=480)
    assert claims["exp"] == _NOW + 480


def test_the_signed_span_stays_within_the_github_ceiling() -> None:
    # GitHub мерит по своим часам ``exp - iat``; вместе со сдвигом назад это и есть
    # величина, которую нельзя перерасти.
    longest = MAX_JWT_SPAN_SECONDS - CLOCK_DRIFT_SECONDS
    claims = jwt_claims(app_id="1", now=_NOW, lifetime_seconds=longest)
    assert int(claims["exp"]) - int(claims["iat"]) == MAX_JWT_SPAN_SECONDS


def test_a_lifetime_that_would_break_the_ceiling_is_refused() -> None:
    # Ронять на сборке дешевле, чем получить 401 от GitHub'а и гадать, почему.
    too_long = MAX_JWT_SPAN_SECONDS - CLOCK_DRIFT_SECONDS + 1
    with pytest.raises(IdentityConfigError, match="lifetime"):
        jwt_claims(app_id="1", now=_NOW, lifetime_seconds=too_long)


@pytest.mark.parametrize("lifetime", [0, -1])
def test_a_non_positive_lifetime_is_refused(lifetime: int) -> None:
    with pytest.raises(IdentityConfigError, match="lifetime"):
        jwt_claims(app_id="1", now=_NOW, lifetime_seconds=lifetime)


def test_the_smallest_positive_lifetime_is_accepted() -> None:
    # Граница ровно там, где заявлено: «положительное» значит положительное, а не
    # «больше единицы». Абсурдно короткий, но валидный JWT — не повод отказывать.
    assert jwt_claims(app_id="1", now=_NOW, lifetime_seconds=1)["exp"] == _NOW + 1


def test_an_empty_app_id_is_refused() -> None:
    with pytest.raises(IdentityConfigError, match="app_id"):
        jwt_claims(app_id="", now=_NOW, lifetime_seconds=480)


def test_claims_carry_exactly_the_three_registered_fields() -> None:
    # Ничего лишнего: App-JWT — это ровно iss/iat/exp, а любой лишний claim у GitHub'а
    # либо игнорируется, либо ломает разбор.
    claims = jwt_claims(app_id="1", now=_NOW, lifetime_seconds=480)
    assert set(claims) == {"iss", "iat", "exp"}


# --------------------------------------------------------------------------- #
# b64url / signing_input / assemble_jwt — как это упаковано
# --------------------------------------------------------------------------- #


def test_b64url_uses_the_url_alphabet_without_padding() -> None:
    # JWT — это base64url БЕЗ '='; лишнее '+' / '/' / '=' сделали бы токен невалидным.
    encoded = b64url(b"\xfb\xff\xfe")
    assert "=" not in encoded
    assert "+" not in encoded
    assert "/" not in encoded
    assert encoded == "-__-"


@pytest.mark.parametrize(("raw", "expected"), [(b"\x01", "AQ"), (b"\x01\x02", "AQI")])
def test_b64url_strips_the_padding_that_base64_would_add(raw: bytes, expected: str) -> None:
    # Ровно тот случай, ради которого срезается '=': на длине, не кратной трём, base64
    # ДОБАВЛЯЕТ выравнивание, и оставленное '=' сделало бы JWT невалидным. Без такого
    # входа проверка «нет padding'а» была бы вакуумной (трёхбайтовый вход padding'а и не
    # даёт).
    assert b64url(raw) == expected


def test_b64url_strips_only_the_padding_and_nothing_else() -> None:
    # Срезается ИМЕННО '=': значащий последний символ токена (здесь 'X') обязан остаться.
    assert b64url(b"\x00\x00\x17") == "AAAX"


def test_signing_input_is_header_dot_payload() -> None:
    payload = signing_input(jwt_claims(app_id="42", now=_NOW, lifetime_seconds=480))
    header_segment, _, claims_segment = payload.decode("ascii").partition(".")
    assert _decode_segment(header_segment) == {"alg": "RS256", "typ": "JWT"}
    assert _decode_segment(claims_segment)["iss"] == "42"


def test_signing_input_is_deterministic_for_the_same_claims() -> None:
    # Порядок ключей фиксирован сортировкой: иначе одна и та же подпись собиралась бы
    # над разными байтами, а такой баг ловится только вживую.
    claims = jwt_claims(app_id="42", now=_NOW, lifetime_seconds=480)
    assert signing_input(claims) == signing_input(dict(reversed(list(claims.items()))))


def test_signing_input_encodes_compact_json_without_whitespace() -> None:
    # 🔴 Проверять «нет пробела» в САМИХ байтах бесполезно: они base64, пробел там не
    # виден ни при каком форматировании (вакуумный ассерт, найденный мутацией). Смотрим
    # на РАСКОДИРОВАННЫЙ JSON: компактные разделители, как их делают библиотеки JWT.
    payload = signing_input(jwt_claims(app_id="42", now=_NOW, lifetime_seconds=480))
    for segment in payload.decode("ascii").split("."):
        padded = segment + "=" * (-len(segment) % 4)
        text = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        assert " " not in text
        assert ", " not in text
        assert ": " not in text


def test_assemble_appends_the_signature_as_a_third_segment() -> None:
    token = assemble_jwt(b"aGVhZGVy.cGF5bG9hZA", b"\x01\x02\x03")
    assert token == "aGVhZGVy.cGF5bG9hZA." + b64url(b"\x01\x02\x03")
    assert token.count(".") == 2


def test_assemble_refuses_an_empty_signature() -> None:
    # Пустая подпись — признак того, что подписывающий шаг молча провалился; такой
    # «токен» уехал бы в сеть и вернулся невнятным 401.
    with pytest.raises(SigningError, match="signature"):
        assemble_jwt(b"aGVhZGVy.cGF5bG9hZA", b"")
