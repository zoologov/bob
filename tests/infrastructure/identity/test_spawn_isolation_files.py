# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты материализации изоляции окружения спавна — НАСТОЯЩАЯ файловая система (BOB-089.C).

Проверяется ровно то, о чём фейк соврал бы: какие файлы появляются, с какими правами, что
исчезает и где НЕ остаётся токена. Решения (какие переменные и какие пары конфига) живут в
чистом ядре и проверяются отдельно (``tests/domain/identity/test_spawn_isolation.py``).
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from bob.identity.adapters.spawn_isolation_files import SpawnIsolationFiles
from bob.identity.ports import IdentityConfigError
from bob.identity.spawn_isolation import controlled_ssh_command

_FORK = "https://github.com/bobiverse-dev/bob.git"
_TOKEN = "ghs_fake_installation_token"  # noqa: S105 — фиктивный «токен» для проверки утечек


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_root_is_created_private_to_the_user(tmp_path: Path) -> None:
    root = tmp_path / "spawn-env"

    isolation = SpawnIsolationFiles(root).materialize()

    assert root.is_dir()
    # 0700: в этом каталоге лежит стор кредов Боба — чужим тут делать нечего.
    assert _mode(root) == 0o700
    assert isolation.config_global.startswith(str(root))


def test_the_controlled_global_config_resets_the_helper_list_in_the_file_too(
    tmp_path: Path,
) -> None:
    isolation = SpawnIsolationFiles(tmp_path).materialize()

    content = (tmp_path / "gitconfig").read_text(encoding="utf-8")
    # Второй слой, независимый от env-пар: даже если блок ``GIT_CONFIG_*`` снимут изнутри,
    # подменный global-конфиг всё равно сбрасывает список хелперов.
    assert "[credential]" in content
    assert "helper =" in content
    assert isolation.config_global == str(tmp_path / "gitconfig")


def test_without_a_token_the_spawn_gets_no_credential_store_at_all(tmp_path: Path) -> None:
    isolation = SpawnIsolationFiles(tmp_path).materialize()

    assert isolation.credential_store == ""
    assert not (tmp_path / "credentials").exists()


def test_a_stale_credential_store_from_a_previous_run_is_removed(tmp_path: Path) -> None:
    # 🔴 Иначе токен прошлой сессии остался бы на диске и достался бы спавну, который
    # кредов получать не должен.
    stale = tmp_path / "credentials"
    stale.write_text("https://x-access-token:OLD@github.com\n", encoding="utf-8")

    isolation = SpawnIsolationFiles(tmp_path).materialize()

    assert isolation.credential_store == ""
    assert not stale.exists()


def test_with_a_token_the_store_is_written_readable_only_by_the_user(tmp_path: Path) -> None:
    isolation = SpawnIsolationFiles(tmp_path).materialize(fork_url=_FORK, token=_TOKEN)

    store = tmp_path / "credentials"
    assert isolation.credential_store == str(store)
    assert _mode(store) == 0o600
    assert store.read_text(encoding="utf-8") == f"https://x-access-token:{_TOKEN}@github.com\n"


def test_a_world_readable_store_is_tightened_before_the_token_lands(tmp_path: Path) -> None:
    # Файл мог остаться с прошлого прогона ослабленным; токен обязан попасть в файл,
    # который УЖЕ 0600, а не быть затянутым следом.
    store = tmp_path / "credentials"
    store.write_text("old\n", encoding="utf-8")
    store.chmod(0o644)

    SpawnIsolationFiles(tmp_path).materialize(fork_url=_FORK, token=_TOKEN)

    assert _mode(store) == 0o600


def test_a_fresh_token_replaces_the_previous_one_rather_than_appending(tmp_path: Path) -> None:
    files = SpawnIsolationFiles(tmp_path)
    files.materialize(fork_url=_FORK, token="ghs_first")  # noqa: S106 — фиктивный токен
    files.materialize(fork_url=_FORK, token="ghs_second")  # noqa: S106 — фиктивный токен

    content = (tmp_path / "credentials").read_text(encoding="utf-8")
    assert content.count("\n") == 1
    assert "ghs_first" not in content


def test_the_token_never_leaves_the_store_file(tmp_path: Path) -> None:
    isolation = SpawnIsolationFiles(tmp_path).materialize(fork_url=_FORK, token=_TOKEN)

    # Ни в возвращаемом значении (его ``repr`` уезжает в лог и traceback), ни в остальных
    # файлах контролируемого каталога.
    assert _TOKEN not in repr(isolation)
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.name != "credentials":
            assert _TOKEN not in path.read_text(encoding="utf-8", errors="replace")


def test_gh_gets_an_empty_config_dir_of_its_own(tmp_path: Path) -> None:
    isolation = SpawnIsolationFiles(tmp_path).materialize()

    gh_dir = tmp_path / "gh"
    assert isolation.gh_config_dir == str(gh_dir)
    assert gh_dir.is_dir()
    # Пустой каталог = ``gh`` не аутентифицирован ни на одном хосте.
    assert list(gh_dir.iterdir()) == []


def test_the_askpass_target_deliberately_does_not_exist(tmp_path: Path) -> None:
    isolation = SpawnIsolationFiles(tmp_path).materialize()

    assert isolation.askpass == str(tmp_path / "askpass-disabled")
    assert not Path(isolation.askpass).exists()


def test_a_planted_askpass_helper_is_removed(tmp_path: Path) -> None:
    # Если кто-то (в т.ч. прошлый прогон) положил туда исполняемый файл, он стал бы
    # каналом выдачи пароля — «в никуда» обязано остаться никуда.
    planted = tmp_path / "askpass-disabled"
    planted.write_text("#!/bin/sh\necho OWNERSECRET\n", encoding="utf-8")

    isolation = SpawnIsolationFiles(tmp_path).materialize()

    assert not planted.exists()
    assert isolation.askpass == str(planted)


def test_the_ssh_identity_target_deliberately_does_not_exist(tmp_path: Path) -> None:
    # 🔴 bob-a6b.10: ЯВНО названный ``IdentityFile`` — единственное, что отменяет дефолтные
    # ключи owner'а из ``~/.ssh``; а раз ключа у спавна нет, файла быть и не должно.
    isolation = SpawnIsolationFiles(tmp_path).materialize()

    assert isolation.ssh_identity == str(tmp_path / "ssh-identity-disabled")
    assert not Path(isolation.ssh_identity).exists()


def test_a_planted_ssh_key_is_removed(tmp_path: Path) -> None:
    # Настоящий ключ по этому пути превратил бы «изоляцию» в выдачу ключа: ssh взял бы его.
    planted = tmp_path / "ssh-identity-disabled"
    planted.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")

    isolation = SpawnIsolationFiles(tmp_path).materialize()

    assert not planted.exists()
    assert isolation.ssh_identity == str(planted)


def test_the_controlled_global_config_carries_the_same_ssh_command(tmp_path: Path) -> None:
    # Второй слой ssh-дороги, независимый от блока ``GIT_CONFIG_*`` и от переменной
    # ``GIT_SSH_COMMAND``: снимут их изнутри — останется ``core.sshCommand`` в файле.
    isolation = SpawnIsolationFiles(tmp_path).materialize()

    content = (tmp_path / "gitconfig").read_text(encoding="utf-8")
    assert "[core]" in content
    assert controlled_ssh_command(identity=isolation.ssh_identity) in content


def test_the_ssh_command_in_the_config_is_quoted_so_a_hash_cannot_comment_it_out(
    tmp_path: Path,
) -> None:
    # 🔴 ``coder.clone_root`` — значение из конфига owner'а, а в git-конфиге ``#`` и ``;``
    # начинают КОММЕНТАРИЙ: без кавычек путь с решёткой обрезал бы строку, и второй слой
    # молча превратился бы в «sshCommand = ssh -F none …» без ключа, то есть в дефолтные
    # ключи owner'а. Что настоящий git читает значение целиком — проверено на нём же.
    root = tmp_path / "clones#1" / ".spawn-env"

    SpawnIsolationFiles(root).materialize()

    line = next(
        text
        for text in (root / "gitconfig").read_text(encoding="utf-8").splitlines()
        if "sshCommand =" in text
    )
    value = line.split("=", 1)[1].strip()
    assert value.startswith('"')
    assert value.endswith('"')
    assert "clones#1" in value


def test_materialising_twice_is_idempotent(tmp_path: Path) -> None:
    files = SpawnIsolationFiles(tmp_path)

    assert files.materialize() == files.materialize()


def test_a_token_without_a_fork_url_is_refused_loudly(tmp_path: Path) -> None:
    # Токен есть, а хоста нет: записать его «куда-нибудь» значило бы отдать секрет
    # неизвестному адресу. Отказ чистого ядра адаптер не глотает.
    with pytest.raises(IdentityConfigError):
        SpawnIsolationFiles(tmp_path).materialize(fork_url="", token=_TOKEN)


def test_a_refused_token_is_not_left_on_disk(tmp_path: Path) -> None:
    with pytest.raises(IdentityConfigError):
        SpawnIsolationFiles(tmp_path).materialize(fork_url="git@github.com:o/r", token=_TOKEN)

    assert not (tmp_path / "credentials").exists()
