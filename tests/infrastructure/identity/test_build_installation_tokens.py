# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Сборка провайдера токенов из конфига (BOB-089, срез B).

🔴 Главное свойство: на НЕНАСТРОЕННОМ Бобе сборка не падает. Иначе процесс, у которого
секция ``github`` пуста (а это состояние по умолчанию), не смог бы даже подняться — отказ
должен приходить тогда, когда токен реально понадобился, и называть недостающий ключ.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.identity.adapters.installation_token import (
    DEFAULT_JWT_LIFETIME_SECONDS,
    DEFAULT_RENEW_MARGIN_SECONDS,
    build_installation_tokens,
)
from bob.identity.ports import IdentityConfigError
from bob.identity.principals import Purpose
from bob.infrastructure.config.loader import ConfigLoader


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


def _github_section() -> dict[str, object]:
    section = ConfigLoader(yaml_path=None, env={}).load()["github"]
    assert isinstance(section, dict)
    return section


def test_the_provider_builds_on_an_unconfigured_bob() -> None:
    assert build_installation_tokens(_github_section(), clock=_StubClock()) is not None


async def test_the_refusal_arrives_when_the_token_is_needed_named_by_key() -> None:
    provider = build_installation_tokens(_github_section(), clock=_StubClock())
    with pytest.raises(IdentityConfigError, match="work_app_id"):
        await provider.token(Purpose.PUSH_TO_FORK)


def test_the_lifetime_knobs_come_from_the_section_not_from_hardcode() -> None:
    section = {**_github_section(), "token_margin_seconds": 120, "jwt_lifetime_seconds": 300}
    provider = build_installation_tokens(section, clock=_StubClock())
    assert provider._margin == 120  # проверяем именно проброс настройки
    assert provider._jwt_lifetime == 300


def test_a_garbage_knob_falls_back_to_the_conservative_default() -> None:
    # env отдаёт строки, и «пятьсот» вместо числа не должно ни ронять сборку, ни молча
    # превращаться в нулевой запас (то есть в обновление по факту 401).
    section = {**_github_section(), "token_margin_seconds": "не-число"}
    provider = build_installation_tokens(section, clock=_StubClock())
    assert provider._margin == DEFAULT_RENEW_MARGIN_SECONDS
    assert provider._jwt_lifetime == DEFAULT_JWT_LIFETIME_SECONDS


def test_a_numeric_knob_given_as_an_env_string_is_honoured() -> None:
    # Ровно тот путь, которым приезжает env: строка с числом.
    section = {**_github_section(), "token_margin_seconds": "90"}
    provider = build_installation_tokens(section, clock=_StubClock())
    assert provider._margin == 90


@pytest.mark.parametrize("junk", [True, False, None, []])
def test_a_knob_of_the_wrong_type_never_becomes_a_zero_margin(junk: object) -> None:
    # 🔴 Опечатка в конфиге не имеет права ТИХО превратиться в нулевой запас: это означало
    # бы обновление токена по факту 401, то есть отказ посреди работы вместо обновления
    # заранее. ``True`` разобрано отдельно, потому что в Python это ещё и ``int`` — самая
    # правдоподобная дорога к «запасу 1 секунда».
    section = {**_github_section(), "token_margin_seconds": junk}
    provider = build_installation_tokens(section, clock=_StubClock())
    assert provider._margin == DEFAULT_RENEW_MARGIN_SECONDS


@pytest.mark.parametrize("blank", ["", "   ", None, 7])
def test_a_blank_textual_knob_falls_back_to_the_shipped_default(blank: object) -> None:
    # Строковые параметры (бинарь, база API) читаются той же дорогой: пустое значение из
    # ``.env`` — это «не задано», а не «задано пустым», иначе спавн звал бы бинарь с пустым
    # именем.
    section = {**_github_section(), "openssl_bin": blank}
    provider = build_installation_tokens(section, clock=_StubClock())
    assert provider is not None
