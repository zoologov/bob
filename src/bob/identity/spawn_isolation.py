# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=identity
# beadloom:layer=domain

"""Чем аутентифицируется процесс спавна — чистое ядро изоляции окружения (BOB-089, срез C).

ОДНА ответственность: решить, каким git-окружением работает спавненный ``claude`` — чей
конфиг он читает, какие креды ему доступны и каких переменных owner'а в нём не остаётся.
Ни файла, ни процесса: здесь только решения (материализует их
:class:`bob.identity.adapters.spawn_isolation_files.SpawnIsolationFiles`, а склеивает с
окружением спавна :func:`bob.coding.push_guard.guarded_spawn_env` — 🔴 ВТОРОГО механизма
изоляции не заводится, расширяется существующий).

🔴 ЧТО ИМЕННО ВЫЯСНИЛОСЬ НА НАСТОЯЩЕМ GIT 2.49 (иначе изоляция была бы мнимой):

* ``GIT_CONFIG_GLOBAL`` САМ ПО СЕБЕ кредов owner'а НЕ убирает. На машине owner'а
  ``credential.helper = osxkeychain`` приезжает из СИСТЕМНОГО конфига
  (``/opt/homebrew/etc/gitconfig``), а ``GIT_CONFIG_GLOBAL`` замещает только
  ``~/.gitconfig`` / XDG. Поэтому системный конфиг отключается отдельно
  (``GIT_CONFIG_NOSYSTEM``), а поверх ещё и сбрасывается сам список хелперов.
* ПУСТОЕ значение ``credential.helper`` СБРАСЫВАЕТ накопленный список хелперов, и
  env-конфиг читается git'ом ПОСЛЕДНИМ — значит сброс из окружения гасит и системный
  helper, и helper owner'а, и локальный. Проверено: после сброса
  ``git credential fill`` для ``https://github.com`` отвечает
  ``could not read Username … terminal prompts disabled`` вместо пароля owner'а.
* Пара «сброс, затем ``store --file=<стор Боба>``» отдаёт УЖЕ токен Боба — то есть
  порядок пар и есть смысл механизма, а не деталь оформления.

🔴 ЧЕСТНО О СИЛЕ МЕРЫ (та же рамка, что у :mod:`bob.coding.push_guard`). Окружение — НЕ
граница: процесс работает под тем же UID и владеет своим окружением, поэтому
``env -u GIT_CONFIG_NOSYSTEM``/``GIT_CONFIG_COUNT=0`` снимает изоляцию изнутри, а
``~/.ssh`` и логин-keychain остаются читаемыми для того же пользователя. Изоляция убирает
АМБИЕНТНУЮ дорогу к кредам owner'а — ту, по которой пойдут и нечаянный ``git push``, и
модель, «доделавшая задачу». Структурными остаются ровно два свойства: у клона свой
``.git`` (срез A) и у токена Боба НЕТ права записи в апстрим (срез B) — именно поэтому
обход изоляции ничего не даёт: креды, до которых можно дотянуться, апстрим не пускают.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bob.identity.ports import IdentityConfigError

__all__ = [
    "OWNER_CREDENTIAL_VARS",
    "SpawnIsolation",
    "credential_store_line",
    "isolation_config_pairs",
    "isolation_env",
]

#: Имя пользователя, под которым installation-токен GitHub работает как пароль https.
_STORE_USERNAME = "x-access-token"

#: ``https://<authority>[/…]`` — единственная форма, в которой токен вообще работает.
_HTTPS_AUTHORITY = re.compile(r"^https://(?P<authority>[^/]+)")

#: Переменные окружения owner'а, которые НЕ имеют права доехать до спавна: каждая — своя
#: дорога к записи в апстрим мимо git-конфига (``gh``-токен в окружении, ssh-агент с
#: ключом owner'а). Ни одна из них не устанавливается изоляцией — иначе она сняла бы свою
#: же настройку (утверждено тестом).
OWNER_CREDENTIAL_VARS: tuple[str, ...] = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "SSH_AUTH_SOCK",
)


@dataclass(frozen=True)
class SpawnIsolation:
    """Контролируемое окружение git для спавна: что подменено и чем спавн платит.

    Значения — ПУТИ, материализованные адаптером; ни одно из них не несёт секрета, кроме
    файла :attr:`credential_store` (0600), содержимое которого в argv не попадает никогда.
    """

    #: Путь к подменному global-конфигу git (вместо ``~/.gitconfig`` owner'а).
    config_global: str
    #: Путь «в никуда» для ``GIT_ASKPASS``/``SSH_ASKPASS``: файла нет, значит спросить
    #: пароль не у кого — git падает с самообъясняющим ``cannot exec``.
    askpass: str
    #: Контролируемый каталог конфигурации ``gh`` (пусто → не подменяем).
    gh_config_dir: str = ""
    #: Путь к стору кредов БОБА (пусто → у спавна нет кредов вовсе — прод-дефолт).
    credential_store: str = ""


def isolation_env(isolation: SpawnIsolation) -> dict[str, str]:
    """Собрать переменные окружения изоляции: чей конфиг и куда НЕ уходить за паролем.

    Пустой :attr:`SpawnIsolation.config_global` или :attr:`SpawnIsolation.askpass` —
    отказ, а не «частичная изоляция»: без подменного global-конфига спавн читал бы
    конфигурацию owner'а, а без askpass-заглушки git ушёл бы спрашивать пароль. Тихо
    отдать половину меры хуже, чем упасть на сборке.
    """
    if not isolation.config_global.strip():
        raise IdentityConfigError(
            "spawn isolation needs a controlled global git config: without it the spawn "
            "reads the owner's configuration (and his credential helper)"
        )
    if not isolation.askpass.strip():
        raise IdentityConfigError(
            "spawn isolation needs an askpass target that leads nowhere: without it git "
            "may go and ask for a password"
        )
    env = {
        # Вместо ``~/.gitconfig`` owner'а — наш файл.
        "GIT_CONFIG_GLOBAL": isolation.config_global,
        # 🔴 И вместо системного: именно там на этой машине живёт osxkeychain.
        "GIT_CONFIG_NOSYSTEM": "1",
        # Неинтерактивный спавн: git обязан упасть честно, а не ждать ввода.
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": isolation.askpass,
        "SSH_ASKPASS": isolation.askpass,
    }
    if isolation.gh_config_dir:
        # ``gh`` держит свой токен в ``<config-dir>/hosts.yml``; с токеном owner'а
        # ``gh pr merge`` дотянулся бы до ствола мимо любого git-конфига.
        env["GH_CONFIG_DIR"] = isolation.gh_config_dir
    return env


def isolation_config_pairs(isolation: SpawnIsolation) -> tuple[tuple[str, str], ...]:
    """Собрать пары git-конфига изоляции: сброс списка хелперов, затем (опц.) свой.

    🔴 ПОРЯДОК — ЭТО И ЕСТЬ МЕХАНИЗМ. Первая пара с ПУСТЫМ значением сбрасывает список
    хелперов, накопленный из системного, глобального и локального конфигов; всё, что
    стоит после неё, начинает список заново. Поменяй порядок — и helper owner'а останется
    первым в списке, то есть креды owner'а снова будут отвечать на запрос git.

    Стор не задан (прод-дефолт) → у спавна нет кредов ВОВСЕ, и это осознанно: пуш ветки в
    форк делает процесс самого Боба, а не спавн.
    """
    pairs = [("credential.helper", "")]
    if isolation.credential_store:
        pairs.append(("credential.helper", f"store --file={isolation.credential_store}"))
    return tuple(pairs)


def credential_store_line(*, fork_url: str, token: str) -> str:
    """Собрать строку стора кредов git для хоста форка: ``https://x-access-token:<токен>@host``.

    🔴 Токен попадает в ФАЙЛ (0600), а не в argv и не в URL remote'а: командная строка
    видна в ``ps`` любому процессу пользователя. Ни один отказ этой функции не несёт
    значения токена — отказы уезжают в лог и в traceback.

    Отвергается: пустой токен (git записал бы пустой пароль и получил невнятный 401),
    токен с переводом строки (дописал бы в стор ВТОРУЮ запись — уже для чужого хоста),
    не-``https`` адрес (по ssh installation-токен не работает) и адрес, в котором креды
    уже вклеены.
    """
    if not token.strip():
        raise IdentityConfigError(
            "refusing to write an empty installation token to the credential store"
        )
    if "\n" in token or "\r" in token:
        raise IdentityConfigError(
            "refusing an installation token containing a line break: it would add a "
            "second entry (another host) to the credential store"
        )
    match = _HTTPS_AUTHORITY.match(fork_url)
    if match is None:
        raise IdentityConfigError(
            "the fork must be addressed by an https URL for token authentication to work"
        )
    authority = match.group("authority")
    if "@" in authority:
        raise IdentityConfigError(
            "the fork URL already carries credentials; the token belongs to the "
            "credential store, never to a URL"
        )
    return f"https://{_STORE_USERNAME}:{token}@{authority}\n"
