# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=identity
# beadloom:layer=infrastructure

"""SpawnIsolationFiles — материализовать контролируемое git-окружение спавна (BOB-089.C).

Одна ответственность: положить на диск то, на что показывают переменные изоляции, и
убрать то, чего там быть не должно. Решения (какие переменные, какие пары конфига, как
выглядит строка стора) живут в чистом ядре :mod:`bob.identity.spawn_isolation`; здесь —
только файлы и права.

Что появляется в контролируемом каталоге (сам каталог — 0700):

* ``gitconfig`` — подменный global-конфиг вместо ``~/.gitconfig`` owner'а. Он не пустой:
  внутри тот же сброс списка credential-хелперов, что и в env-парах, — ВТОРОЙ слой, живой
  даже если блок ``GIT_CONFIG_*`` кто-то снимет изнутри;
* ``gh/`` — пустой каталог конфигурации ``gh``: с ним ``gh`` не аутентифицирован ни на
  одном хосте, а токен owner'а из ``~/.config/gh/hosts.yml`` до спавна не доезжает;
* ``credentials`` (0600) — ТОЛЬКО когда Бобу выдан installation-токен. Без токена файл не
  создаётся, а оставшийся с прошлого раза УДАЛЯЕТСЯ: иначе спавн, которому кредов не
  давали, получил бы их из вчерашнего файла;
* ``askpass-disabled`` — путь, которого НЕТ (и который здесь же удаляется, если появился):
  ``GIT_ASKPASS`` в никуда, и git падает с самообъясняющим ``cannot exec``.

🔴 Токен живёт в ФАЙЛЕ, а не в argv и не в URL remote'а: командная строка видна в ``ps``
любому процессу пользователя, а ``git remote -v`` — любому, кто заглянет в клон.
"""

from __future__ import annotations

from pathlib import Path

from bob.identity.spawn_isolation import (
    SpawnIsolation,
    controlled_ssh_command,
    credential_store_line,
)

__all__ = ["SpawnIsolationFiles"]

#: Права каталога и файла: только владелец. Стор кредов Боба — секрет, пусть и
#: короткоживущий, и лежать он должен как секрет.
_DIR_MODE = 0o700
_FILE_MODE = 0o600

#: Шаблон подменного global-конфига: сброс списка хелперов, контролируемый ssh + записка
#: человеку, который однажды найдёт этот файл и захочет понять, откуда он взялся.
_GLOBAL_CONFIG = """\
# Подменный global-конфиг git для спавна claude (bob, BOB-089).
# Создаётся автоматически; правки будут перезаписаны.
# Пустое значение helper СБРАСЫВАЕТ список credential-хелперов, накопленный из
# системного и глобального конфигов, — у спавна не остаётся кредов owner'а.
[credential]
\thelper =
# И ssh — не ключом owner'а из ~/.ssh: у команды ниже явно назван IdentityFile,
# которого нет. Тот же слой, что переменная GIT_SSH_COMMAND, но ФАЙЛОМ — он живой,
# даже если переменную снимут изнутри (проверено: core.sshCommand сильнее GIT_SSH).
[core]
\tsshCommand = {ssh_command}
"""


def _config_value(raw: str) -> str:
    """Обернуть значение в кавычки для git-конфига (в них ``#`` и ``;`` — не комментарий).

    Значение приезжает из ``coder.clone_root``, то есть из конфига owner'а: путь с решёткой
    без кавычек обрезал бы строку комментарием, и в конфиге осталась бы команда ssh БЕЗ
    ``IdentityFile`` — то есть дефолтные ключи owner'а, молча и в виде исправного файла.
    """
    escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class SpawnIsolationFiles:
    """Завести (и подчистить) файлы контролируемого git-окружения спавна."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def materialize(self, *, fork_url: str = "", token: str = "") -> SpawnIsolation:
        """Разложить файлы окружения и вернуть описание изоляции (идемпотентно).

        Токен передаётся ЗНАЧЕНИЕМ и уезжает ровно в один файл (0600); в возвращаемом
        описании его нет — только путь. Без токена стор не создаётся вовсе: прод-дефолт —
        спавн без кредов, потому что пуш ветки в форк делает процесс самого Боба.

        Форма строки стора проверяется чистым ядром, и его отказ НЕ глотается: токен без
        адреса — это конфигурационная ошибка, на которой правильно падать громко, а не
        писать секрет по неизвестному адресу.
        """
        line = credential_store_line(fork_url=fork_url, token=token) if token else ""
        self._root.mkdir(parents=True, exist_ok=True)
        self._root.chmod(_DIR_MODE)
        # Ключа у спавна нет — и путь, которым он «назван», обязан остаться пустым местом:
        # настоящий ключ, оказавшийся здесь, ssh взял бы в дело.
        ssh_identity = self._root / "ssh-identity-disabled"
        ssh_identity.unlink(missing_ok=True)
        ssh_command = controlled_ssh_command(identity=str(ssh_identity))
        config_global = self._root / "gitconfig"
        config_global.write_text(
            _GLOBAL_CONFIG.format(ssh_command=_config_value(ssh_command)), encoding="utf-8"
        )
        gh_config_dir = self._root / "gh"
        gh_config_dir.mkdir(exist_ok=True)
        gh_config_dir.chmod(_DIR_MODE)
        askpass = self._root / "askpass-disabled"
        askpass.unlink(missing_ok=True)
        store = self._root / "credentials"
        if not line:
            # Ни просроченного, ни живого токена прошлой сессии на диске не остаётся.
            store.unlink(missing_ok=True)
            return SpawnIsolation(
                config_global=str(config_global),
                askpass=str(askpass),
                ssh_identity=str(ssh_identity),
                gh_config_dir=str(gh_config_dir),
            )
        # 🔴 Права СНАЧАЛА, содержимое потом: иначе между записью и ``chmod`` существует
        # окно, в котором токен лежит в файле с правами по умолчанию (0644 при обычном
        # umask). ``touch`` не трогает права уже существующего файла — поэтому ещё и
        # ``chmod``, чтобы ослабленный кем-то файл затянулся ДО появления в нём токена.
        store.touch(mode=_FILE_MODE, exist_ok=True)
        store.chmod(_FILE_MODE)
        store.write_text(line, encoding="utf-8")
        return SpawnIsolation(
            config_global=str(config_global),
            askpass=str(askpass),
            ssh_identity=str(ssh_identity),
            gh_config_dir=str(gh_config_dir),
            credential_store=str(store),
        )
