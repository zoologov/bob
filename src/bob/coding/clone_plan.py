# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""План рабочего места-КЛОНА — чистое ядро (BOB-089, срезы A + D).

ОДНА ответственность: решить, КАК заводится и переиспользуется рабочее место Боба, когда
оно перестаёт быть linked worktree и становится отдельным клоном. Решения, ни одного
побочного эффекта:

* :func:`clone_argv` / :func:`checkout_argv` / :func:`origin_argv` — фиксированные,
  shell-free формы git-команд заведения клона;
* :func:`identity_argv` — чем подписана работа в этом клоне (``bob[ai]``, 🔴 ЛОКАЛЬНО);
* :func:`workspace_verdict` — клонировать / переиспользовать / отказать для
  долгоживущего места;
* :func:`is_credential_free_url` — какой URL вообще допустим в argv.

🔴 ЗАЧЕМ КЛОН, А НЕ WORKTREE (проверено на настоящем git, волна bob-5ao). Linked worktree
делит ``.git`` с основным репозиторием: те же объекты, те же **refs**, те же remotes и те
же credentials. Поэтому ``git update-ref refs/heads/main <sha>`` двигает main owner'а
ЛОКАЛЬНО — без сети, без кредов, мимо любого push-барьера
(:mod:`bob.coding.push_guard` этот класс не закрывает и не может). У клона свой ``.git``,
и ref'ов основного репозитория в нём просто нет.

🔴 ПОЧЕМУ ``file://``, А НЕ ГОЛЫЙ ПУТЬ (замерено, BOB-089.A). Для локального пути git
включает оптимизацию: файлы объектов не копируются, а **хардлинкуются** — у клона и у
репозитория owner'а остаются ОБЩИЕ inode'ы, то есть общее хранилище объектов. Это дешевле
по месту, но ровно то, от чего мы уходим. ``file://`` переводит клонирование на обычный
транспорт (по-прежнему без сети): у клона появляется собственный, свежесобранный pack.
Цена на этом репозитории: 3.8 с и 142 МБ против 2.2 с и ~45 МБ у хардлинкованного
варианта (и 642 МБ у ``--no-hardlinks``, который копирует полтерабайта… точнее 510 МиБ
рыхлых объектов как есть). ``--depth 1`` (1.3 с, 63 МБ) отвергнут: без истории Боб не
может ни ``git log``, ни ``blame``, а это его рабочий инструмент. ``--shared`` /
``--reference`` отвергнуты по той же причине, что и хардлинки, и хуже: клон начинает
ЗАВИСЕТЬ от объектов owner'а, и ``git gc --prune`` в основном репозитории способен его
сломать.

Формы фиксированные: ни одна строка не собирается интерполяцией в шелл, все динамические
слоты (путь, ветка, URL) едут отдельными элементами argv.
"""

from __future__ import annotations

import re
from enum import Enum

__all__ = [
    "WorkspaceVerdict",
    "checkout_argv",
    "clone_argv",
    "identity_argv",
    "is_credential_free_url",
    "origin_argv",
    "workspace_verdict",
]

#: Имя remote, который git создаёт при клонировании (и которое мы переписываем на форк).
_ORIGIN = "origin"

#: Подпись Боба в истории — ровно она отличает его работу от работы owner'а (US-2).
_COMMIT_NAME = "bob[ai]"
#: Ботовский адрес GitHub App: ``<app-user-id>+<login>@users.noreply.github.com``.
#: Суффикс ``[bot]`` в логине неизменяем (решение owner'а №5), поэтому он здесь дословно.
_BOT_LOGIN = "bob-ai-work[bot]"
_NOREPLY_HOST = "users.noreply.github.com"
#: id пользователя приложения — ЧИСЛО. Мусор в конфиге не превращается в правдоподобный
#: адрес (``isdigit`` тут не годится: он принимает и не-ascii цифры).
_APP_USER_ID = re.compile(r"[0-9]+")

#: URL со схемой: ``<scheme>://<authority>[/…]``. Секрет может жить только в authority
#: (``user:token@host``), поэтому дальше первого слэша разбор не нужен.
_SCHEME_AUTHORITY = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://(?P<authority>[^/]*)")


class WorkspaceVerdict(Enum):
    """Что делать с каталогом долгоживущего рабочего места-клона."""

    #: Каталога нет — завести клон.
    CLONE = "clone"
    #: Каталог есть и это репозиторий — переиспользовать (работа НАКАПЛИВАЕТСЯ).
    REUSE = "reuse"
    #: Каталог есть, но это не репозиторий — отказать громко, ничего не удаляя.
    REFUSE = "refuse"


def clone_argv(git_bin: str, *, source: str, dest: str) -> list[str]:
    """Собрать ``git clone file://<source> <dest>`` — клон со СВОИМ складом объектов.

    ``source`` — абсолютный путь основного репозитория (клонируем локально, без сети);
    ``file://`` отключает hardlink-оптимизацию git, поэтому объекты у клона свои, а не
    общие inode'ы с репозиторием owner'а (см. модульную докстроку — там замеры цены).
    """
    return [git_bin, "clone", f"file://{source}", dest]


def checkout_argv(git_bin: str, *, dest: str, branch: str, on_origin: bool) -> list[str]:
    """Собрать переход клона на рабочую ветку ``branch``.

    ``on_origin=False`` — ветка новая, создаётся на HEAD клона (тот же базовый коммит,
    что дал бы ``git worktree add -b``: паритет с прежним поведением).
    ``on_origin=True`` — ветка уже известна источнику, и стартовой точкой берётся
    ``origin/<branch>``. 🔴 Урок BOB-087.D5b: пересоздать такую ветку поверх HEAD значит
    молча потерять НАКОПЛЕННУЮ в ней работу долгоживущего места.
    """
    argv = [git_bin, "-C", dest, "switch", "-c", branch]
    if on_origin:
        argv.append(f"{_ORIGIN}/{branch}")
    return argv


def origin_argv(git_bin: str, *, dest: str, fork_url: str) -> list[str]:
    """Собрать переназначение единственного remote клона: форк — или ничего.

    🔴 Сразу после клонирования ``origin`` указывает на рабочую копию OWNER'А, и оставить
    его так нельзя: это обратная дорога к репозиторию, от которого мы отделялись. Есть
    URL форка — remote переписывается на него; URL пустой (форк не настроен) — remote
    удаляется ЦЕЛИКОМ, и у клона не остаётся ни одного адреса для push. Апстрим не
    прописывается никогда и ни при каком значении.
    """
    if not fork_url:
        return [git_bin, "-C", dest, "remote", "remove", _ORIGIN]
    return [git_bin, "-C", dest, "remote", "set-url", _ORIGIN, fork_url]


def identity_argv(git_bin: str, *, dest: str, app_user_id: str) -> list[list[str]]:
    """Собрать ЛОКАЛЬНУЮ подпись работы Боба в клоне: имя и e-mail двумя командами.

    🔴 ``--local`` и ``-C <dest>`` стоят в форме ЯВНО, и это главное свойство среза D.
    Глобальная настройка переподписала бы коммиты owner'а в его собственном
    репозитории как ``bob[ai]`` — ровно та путаница идентичностей, от которой уходим;
    ни ``--global``, ни ``--system`` эта форма выразить не может.

    Имя — всегда :data:`_COMMIT_NAME`: не подписать вовсе было бы ХУЖЕ, чем подписать
    без числового префикса, потому что тогда git взял бы имя из конфигурации owner'а и
    работа Боба стала бы неотличима от его собственной (то самое, против чего US-2).
    ``app_user_id`` (числовой id пользователя приложения) — опциональный префикс
    ботовского noreply-адреса: с ним GitHub сшивает коммит с ботом, без него остаётся
    честный адрес без привязки. Не-числовое значение игнорируется, а не вклеивается в
    адрес.
    """
    email = f"{_BOT_LOGIN}@{_NOREPLY_HOST}"
    if _APP_USER_ID.fullmatch(app_user_id):
        email = f"{app_user_id}+{email}"
    return [
        [git_bin, "-C", dest, "config", "--local", "user.name", _COMMIT_NAME],
        [git_bin, "-C", dest, "config", "--local", "user.email", email],
    ]


def workspace_verdict(*, dest_exists: bool, is_repo: bool) -> WorkspaceVerdict:
    """Решить судьбу каталога долгоживущего места: клонировать / переиспользовать / отказать.

    Идемпотентность ``ensure`` держится на этом вердикте. Существующий клон
    ПЕРЕИСПОЛЬЗУЕТСЯ (в нём накапливается работа между сеансами), отсутствующий —
    заводится, а посторонний непустой каталог даёт :attr:`WorkspaceVerdict.REFUSE`:
    клонировать поверх git не даст, а удалять чужие данные молча — недопустимо.
    """
    if not dest_exists:
        return WorkspaceVerdict.CLONE
    if is_repo:
        return WorkspaceVerdict.REUSE
    return WorkspaceVerdict.REFUSE


def is_credential_free_url(url: str) -> bool:
    """Свободен ли ``url`` от встроенных кредов (``https://user:token@host/…``).

    🔴 Токен не имеет права попасть в argv: командная строка процесса видна в ``ps``
    любому процессу того же пользователя, и это утечка ровно того секрета, ради которого
    строится вся схема прав. Форк адресуется чистым URL, а креды приезжают отдельным
    механизмом (credential helper окружения спавна, срез C).

    Секрет выразим только в authority URL со схемой, поэтому проверяется именно она.
    scp-подобная форма (``git@host:path``) и локальный путь кредов не несут: в scp-форме
    поля пароля нет вообще, а ``git`` там — имя ssh-пользователя.
    """
    match = _SCHEME_AUTHORITY.match(url)
    if match is None:
        return True
    return "@" not in match.group("authority")
