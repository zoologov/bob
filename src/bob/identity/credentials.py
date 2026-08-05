# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=identity
# beadloom:layer=domain

"""Чем принципал аутентифицируется — чистое ядро реквизитов (BOB-089, срез B).

ОДНА ответственность: собрать из секции конфига ``github`` реквизиты ОДНОГО принципала и
громко отказать, если конфиг неполон или имеет негодную форму. Ничего не читается с диска
и никуда не отправляется: файл ключа тут только назван путём.

Три поля на принципала (``<принципал>_app_id`` / ``_app_key`` / ``_repo``):

* ``app_id`` — числовой идентификатор GitHub App, уезжает в claim ``iss`` App-JWT;
* ``app_key`` — ПУТЬ к приватному ключу (``.secrets/*.pem``, 0600). 🔴 Именно путь:
  содержимое ключа в argv было бы видно в ``ps`` любому процессу пользователя, поэтому
  PEM, случайно вставленный в конфиг вместо пути, отвергается — а секрет при этом не
  попадает в текст отказа;
* ``repo`` — ``owner/repo``, по которому находится УСТАНОВКА этого принципала
  (``GET /repos/{repo}/installation``). Токен GitHub скоупится на одну установку, поэтому
  «какой репозиторий обслуживает принципал» — часть его реквизитов, а не деталь
  транспорта. Слаг едет в ПУТЬ запроса, значит его форма проверяется до сети.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.identity.ports import IdentityConfigError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.identity.principals import Principal

__all__ = ["AppCredentials", "credentials_for"]

#: ``owner/repo`` из символов, которые GitHub разрешает в именах: буквы, цифры, ``.-_``.
_REPO_SLUG = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

#: Признак того, что в поле пути лежит САМО содержимое ключа, а не путь к нему.
_PEM_MARKER = "PRIVATE KEY"


@dataclass(frozen=True)
class AppCredentials:
    """Реквизиты одного принципала: чем подписываемся и где живёт его установка."""

    #: Числовой app_id GitHub App (claim ``iss`` в App-JWT).
    app_id: str
    #: Путь к приватному ключу приложения (содержимое НЕ хранится и не логируется).
    private_key_path: str
    #: ``owner/repo``, по которому находится установка этого принципала.
    repository: str


def credentials_for(section: Mapping[str, object], principal: Principal) -> AppCredentials:
    """Собрать реквизиты ``principal`` из секции конфига ``github``.

    Отказ приходит ДО любой сети и до любого чтения ключа: неполный или кривой конфиг —
    это состояние, в котором Боб не должен даже пытаться выступать своей идентичностью.
    В тексте отказа — ИМЯ ключа конфига, а не его значение.
    """
    prefix = principal.value
    app_id = _required(section, f"{prefix}_app_id")
    if not app_id.isdigit():
        raise IdentityConfigError(
            f"config github.{prefix}_app_id must be the numeric GitHub App id"
        )
    key_path = _required(section, f"{prefix}_app_key")
    if _PEM_MARKER in key_path or "\n" in key_path:
        raise IdentityConfigError(
            f"config github.{prefix}_app_key must be a PATH to the private key file, "
            "not the key material itself (argv is visible in `ps`)"
        )
    repository = _required(section, f"{prefix}_repo")
    if _REPO_SLUG.match(repository) is None:
        raise IdentityConfigError(
            f"config github.{prefix}_repo must be an owner/repo slug"
        )
    return AppCredentials(app_id=app_id, private_key_path=key_path, repository=repository)


def _required(section: Mapping[str, object], key: str) -> str:
    """Вернуть непустое строковое значение ``key`` или отказать с именем этого ключа."""
    value = section.get(key)
    if not isinstance(value, str):
        raise IdentityConfigError(f"config github.{key} must be a non-empty string")
    stripped = value.strip()
    if not stripped:
        raise IdentityConfigError(f"config github.{key} is not configured")
    return stripped
