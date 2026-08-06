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
``.git`` (срез A) и у токена Боба НЕТ права записи в апстрим (срез B).

🔴 ИСПРАВЛЕНО ПО ФАКТУ (bob-a6b.10; ошибка оставлена видимой, а не переписана задним
числом). Абзац выше заканчивался утверждением «именно поэтому обход изоляции ничего не
даёт: креды, до которых можно дотянуться, апстрим не пускают». Это было НЕВЕРНО, и вот
чем: изоляция не касалась ssh ВОВСЕ. Из ровно прод-окружения спавна
``ssh -T git@github.com`` отвечал ``Hi <owner>! You've successfully authenticated``, а
``git ls-remote`` апстрима по ssh проходил (rc=0) — то есть рядом с изолированным https
жила полноправная дорога к апстриму ключом owner'а из ``~/.ssh``, мимо всех мер с
credential-хелперами. Права тут ни при чём: по ssh Боб предъявлял не свой installation-
токен, а ключ owner'а.

Что закрыто теперь: GIT-дорога по ssh. ``GIT_SSH_COMMAND`` (и тем же значением
``core.sshCommand`` в подменном global-конфиге — второй слой, живой после
``env -u GIT_SSH_COMMAND``) заставляет git ходить командой из
:func:`controlled_ssh_command`, у которой явно назван несуществующий ``IdentityFile``:
``git ls-remote`` апстрима по ssh отвечает ``Permission denied (publickey)``.

🔴 Что НЕ закрыто и закрыто быть не может окружением: ПРЯМОЙ вызов ``ssh``/``scp`` из
спавна. Ключ owner'а лежит на диске под тем же UID, а ``~`` OpenSSH раскрывает по записи
в passwd, а НЕ по ``HOME`` (проверено: ``HOME=<пустой каталог> ssh -T git@github.com``
по-прежнему здоровается как owner) — подменить домашний каталог ssh нечем. Значит модель,
которая ЗАХОЧЕТ дотянуться до апстрима, дотянется: ``ssh``, а не ``git``. Это НАЗВАННОЕ
ограничение, а не забытое: оно зафиксировано исполняемо
(``tests/infrastructure/identity/test_ssh_road_live_smoke.py``, честная рамка) и
закрывается только раздельным UID — беада BOB-093, тот же вывод, что у локального
файлового пути в PRD.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from bob.identity.ports import IdentityConfigError

__all__ = [
    "OWNER_CREDENTIAL_VARS",
    "SpawnIsolation",
    "controlled_ssh_command",
    "credential_store_line",
    "isolation_config_pairs",
    "isolation_env",
]

#: Имя пользователя, под которым installation-токен GitHub работает как пароль https.
_STORE_USERNAME = "x-access-token"

#: ``https://<authority>[/…]`` — единственная форма, в которой токен вообще работает.
_HTTPS_AUTHORITY = re.compile(r"^https://(?P<authority>[^/]+)")

#: Управляющие символы (C0 + DEL) — то, чему в полях строки стора места нет НИ В ОДНОМ.
#: Перевод строки дописывает в стор ВТОРУЮ запись (уже для чужого хоста), а остальные
#: управляют терминалом, в котором owner этот файл посмотрит.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

#: Клиент ssh берётся из ``PATH`` — тем же, каким его нашёл бы и сам git.
_SSH_BIN = "ssh"

#: Опции ssh, которыми закрывается АМБИЕНТНАЯ ssh-дорога к апстриму. Смысл каждой — в
#: докстроке :func:`controlled_ssh_command`; ни одна не выбрана «по аналогии», все проверены
#: на настоящем ssh (mutation модульные константы не мутирует — поэтому на каждую свой юнит).
_SSH_ISOLATION_OPTIONS: tuple[str, ...] = (
    "-F",
    "none",
    "-o",
    "IdentitiesOnly=yes",
    "-o",
    "IdentityAgent=none",
    "-o",
    "BatchMode=yes",
)

#: Разумный верхний предел длины токена: installation-токен GitHub — десятки байт, и
#: значение на три порядка больше означает, что на вход приехал не токен.
_MAX_TOKEN_CHARS = 4096

#: Переменные окружения owner'а, которые НЕ имеют права доехать до спавна: каждая — своя
#: дорога к записи в апстрим мимо git-конфига (``gh``-токен в окружении, ssh-агент с
#: ключом owner'а, унаследованный блок git-конфига). Ни одна из них не устанавливается
#: изоляцией — иначе она сняла бы свою же настройку (утверждено тестом).
#:
#: 🔴 ``GIT_CONFIG_PARAMETERS`` здесь не для симметрии: git читает его ПОСЛЕ пар
#: ``GIT_CONFIG_KEY_i``, поэтому унаследованная переменная встаёт ПОСЛЕ нашего сброса
#: хелперов и ВОЗВРАЩАЕТ credential.helper owner'а (проверено на git 2.49 —
#: ``git credential fill`` снова отдавал его пароль). Её не «снимают изнутри», её
#: НАСЛЕДУЮТ: git экспортирует её дочерним процессам, когда сам запущен как ``git -c …``,
#: git-алиас или хук — то есть ровно тот класс амбиентной дороги, от которого мера и
#: заведена (ревью bob-a6b.6, MAJOR-1).
OWNER_CREDENTIAL_VARS: tuple[str, ...] = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "SSH_AUTH_SOCK",
    "GIT_CONFIG_PARAMETERS",
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
    #: Путь «в никуда» для ``IdentityFile`` ssh: файла нет, значит ключа у спавна нет —
    #: и, что важнее, ЯВНО названный IdentityFile отменяет дефолтные ``~/.ssh/id_*``
    #: owner'а. Без значения по умолчанию СОЗНАТЕЛЬНО: изоляция без закрытой ssh-дороги
    #: невыразима (bob-a6b.10 нашла её открытой ровно потому, что поля не было).
    ssh_identity: str
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
        # 🔴 И ssh — своим: без этого git ходил бы по ``git@host:`` ключом owner'а из
        # ``~/.ssh`` (bob-a6b.10). Переменная сильнее ``GIT_SSH`` owner'а, если тот
        # унаследован (проверено на git 2.49), поэтому вычищать её не нужно — она
        # перекрывается значением.
        "GIT_SSH_COMMAND": controlled_ssh_command(identity=isolation.ssh_identity),
    }
    if isolation.gh_config_dir:
        # ``gh`` держит свой токен в ``<config-dir>/hosts.yml``; с токеном owner'а
        # ``gh pr merge`` дотянулся бы до ствола мимо любого git-конфига.
        env["GH_CONFIG_DIR"] = isolation.gh_config_dir
    return env


def controlled_ssh_command(*, identity: str) -> str:
    """Собрать команду ssh для git: свой (несуществующий) ключ и ничей больше.

    🔴 КАЖДАЯ опция здесь проверена на НАСТОЯЩЕМ ssh 10.2 против настоящего GitHub, потому
    что «похоже на изоляцию» тут ничего не стоит:

    * ``-o IdentityFile=<путь, которого нет>`` — ЕДИНСТВЕННОЕ, что реально отключает
      дефолтные ключи owner'а. Явно названный ``IdentityFile`` замещает список по
      умолчанию (``~/.ssh/id_ed25519``, ``id_rsa``, …), и ssh отвечает
      ``Permission denied (publickey)`` вместо ``Hi <owner>!``;
    * ``-o IdentitiesOnly=yes`` САМ ПО СЕБЕ НЕ ДОСТАТОЧЕН и без предыдущей опции не даёт
      ничего: «configured identity» у ssh включает и ДЕФОЛТНЫЕ файлы, поэтому с одним этим
      флагом ssh по-прежнему здоровался как owner. Он нужен для другой дороги — чтобы
      личности, предложенные АГЕНТОМ, не пошли в дело (проверено с агентом, в который
      добавлен настоящий ключ owner'а: без флага — ``Hi <owner>!``, с флагом — отказ);
    * ``-o IdentityAgent=none`` закрывает ту же агентскую дорогу вторым, независимым
      способом (проверено отдельно) — сокет агента вычищается из окружения, но назвать его
      мог бы и конфиг, которого мы не писали;
    * ``-F none`` — не читать ``~/.ssh/config`` owner'а: оттуда вернулись бы и
      ``IdentityFile``, и ``IdentityAgent``, и ``ProxyCommand``. На машине owner'а сегодня
      стансы для github нет, то есть НА ЭТОЙ конфигурации опция не несущая — она про то,
      чтобы гарантия не зависела от чужого файла;
    * ``-o BatchMode=yes`` — тот же смысл, что у ``GIT_TERMINAL_PROMPT=0``.

    Путь квотируется: ``GIT_SSH_COMMAND`` git исполняет ЧЕРЕЗ ШЕЛЛ, а ``coder.clone_root``
    приезжает из конфига owner'а и может содержать пробел.

    🔴 ЧЕГО ЭТА КОМАНДА НЕ ДЕЛАЕТ (и почему HOME не подменяется): ``~`` ssh раскрывает по
    ЗАПИСИ В passwd, а НЕ по ``HOME`` — проверено, ``HOME=<пустой каталог> ssh -T
    git@github.com`` по-прежнему здоровается как owner. Значит ключ owner'а остаётся
    доступен ПРЯМОМУ вызову ``ssh`` из спавна, и закрыть это может только раздельный UID
    (беада BOB-093), а не окружение. Здесь закрыта ровно git-дорога по ssh.
    """
    identity = identity.strip()
    if not identity:
        raise IdentityConfigError(
            "spawn isolation needs an ssh identity path that leads nowhere: an empty "
            "IdentityFile is no option at all for ssh, so the owner's default keys in "
            "~/.ssh would answer again"
        )
    return shlex.join([_SSH_BIN, *_SSH_ISOLATION_OPTIONS, "-o", f"IdentityFile={identity}"])


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
    перевод строки или иной управляющий символ в ЛЮБОМ поле (дописал бы в стор ВТОРУЮ
    запись — уже для чужого хоста), ``@`` в токене (git берёт ПЕРВЫЙ ``@``, поэтому токен
    молча обрезался бы и уехал не тому хосту), абсурдная длина токена, не-``https`` адрес
    (по ssh installation-токен не работает) и адрес, в котором креды уже вклеены.

    🔴 Проверка ОБОИХ полей, а не одного (ревью bob-a6b.6, MAJOR-4). Первая редакция
    запрещала перевод строки только токену — а адрес доезжал до стора как есть, и в файле
    получалось ДВЕ строки: инвариант «одна запись» держался на одном из двух аргументов.
    Записывается ровно то, что проверено (``token.strip()``, не сырое значение).
    """
    token = token.strip()
    if not token:
        raise IdentityConfigError(
            "refusing to write an empty installation token to the credential store"
        )
    if _CONTROL_CHARS.search(token):
        raise IdentityConfigError(
            "refusing an installation token containing a line break or control character: "
            "it would add a second entry (another host) to the credential store"
        )
    if len(token) > _MAX_TOKEN_CHARS:
        raise IdentityConfigError(
            f"refusing an installation token longer than {_MAX_TOKEN_CHARS} characters: "
            "that is not the shape of a GitHub installation token"
        )
    if "@" in token:
        raise IdentityConfigError(
            "refusing an installation token containing '@': git reads the FIRST '@' as the "
            "end of the credentials, so the token would be truncated and stored for the "
            "wrong host"
        )
    if _CONTROL_CHARS.search(fork_url):
        raise IdentityConfigError(
            "refusing a fork URL containing a line break or control character: it would "
            "add a second entry (another host) to the credential store"
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
