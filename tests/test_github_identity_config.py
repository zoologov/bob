# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты секции конфига ``github.*`` — идентичность Боба на GitHub (BOB-089, срез B).

Секция объявлена ЯВНО, хотя env-механизм и так положил бы ``BOB_GITHUB__WORK_APP_ID`` по
этому пути: объявленная форма — это документация ключей и гарантия, что «пусто» означает
«Боб не настроен», а не «ключа нет в словаре».

🔴 Все реквизиты по умолчанию ПУСТЫЕ, и в дефолтах нет ни одного секрета: ключи приезжают из
``.env`` (пути к ``.secrets/*.pem``, 0600), а не из репозитория.
"""

from __future__ import annotations

import pytest

from bob.identity.credentials import credentials_for
from bob.identity.ports import IdentityConfigError
from bob.identity.principals import Principal
from bob.infrastructure.config.loader import ConfigLoader


def _github_section(env: dict[str, str] | None = None) -> dict[str, object]:
    section = ConfigLoader(yaml_path=None, env=env or {}).load()["github"]
    assert isinstance(section, dict)
    return section


def test_both_principals_ship_unconfigured() -> None:
    section = _github_section()
    for key in (
        "work_app_id",
        "work_app_key",
        "work_repo",
        "propose_app_id",
        "propose_app_key",
        "propose_repo",
    ):
        assert section[key] == "", key


def test_an_unconfigured_bob_is_refused_by_key_name_not_silently() -> None:
    # Пустая секция — не повод «как-нибудь» пойти в сеть: отказ приходит с именем ключа.
    with pytest.raises(IdentityConfigError, match="work_app_id"):
        credentials_for(_github_section(), Principal.WORK)


def test_the_lifetime_knobs_have_conservative_defaults() -> None:
    section = _github_section()
    # 🔴 Обновление ЗАРАНЕЕ: пять минут запаса заметно больше самой долгой git-операции.
    assert section["token_margin_seconds"] == 300
    # App-JWT с запасом внутри десятиминутного предела GitHub.
    assert section["jwt_lifetime_seconds"] == 480
    assert section["api_base_url"] == "https://api.github.com"
    assert section["openssl_bin"] == "openssl"


def test_the_env_variables_the_owner_already_set_land_in_this_section() -> None:
    # Ровно те имена, что лежат в .env owner'а: ключи едут ПУТЯМИ, а не содержимым.
    section = _github_section(
        {
            "BOB_GITHUB__WORK_APP_ID": "4491954",
            "BOB_GITHUB__WORK_APP_KEY": "/repo/.secrets/bob-ai-work.private-key.pem",
            "BOB_GITHUB__PROPOSE_APP_ID": "4491957",
            "BOB_GITHUB__PROPOSE_APP_KEY": "/repo/.secrets/bob-ai-propose.private-key.pem",
        }
    )
    assert section["work_app_id"] == "4491954"
    assert section["work_app_key"] == "/repo/.secrets/bob-ai-work.private-key.pem"
    assert section["propose_app_id"] == "4491957"
    assert section["propose_app_key"] == "/repo/.secrets/bob-ai-propose.private-key.pem"


def test_a_fully_configured_principal_parses_end_to_end() -> None:
    section = _github_section(
        {
            "BOB_GITHUB__WORK_APP_ID": "4491954",
            "BOB_GITHUB__WORK_APP_KEY": "/repo/.secrets/bob-ai-work.private-key.pem",
            "BOB_GITHUB__WORK_REPO": "bobiverse-dev/bob",
        }
    )
    credentials = credentials_for(section, Principal.WORK)
    assert credentials.app_id == "4491954"
    assert credentials.repository == "bobiverse-dev/bob"


def test_no_default_value_looks_like_a_secret() -> None:
    # Дефолты живут в репозитории — значит в них не должно быть ни ключа, ни токена.
    for key, value in _github_section().items():
        if not isinstance(value, str):
            continue
        assert "PRIVATE KEY" not in value, key
        assert not value.startswith("ghs_"), key
