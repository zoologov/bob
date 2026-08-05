# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit-тесты чистого ядра плана рабочего места-КЛОНА (BOB-089, срез A).

Ядро решает три вещи и ничего не исполняет: какими ФИКСИРОВАННЫМИ git-командами
заводится клон, когда уже существующее место переиспользуется, и какой URL вообще
допустим в argv. Здесь измеряется сила именно этих решений (mutation-цель); поведение
настоящего git проверяется отдельно, на настоящем git
(``tests/infrastructure/coding/test_git_clone_real_git.py``) — фейк доказал бы контракт
фейка.
"""

from __future__ import annotations

from bob.coding.clone_plan import (
    WorkspaceVerdict,
    checkout_argv,
    clone_argv,
    is_credential_free_url,
    origin_argv,
    workspace_verdict,
)

# --------------------------------------------------------------------------- #
# clone_argv — как именно заводится клон
# --------------------------------------------------------------------------- #


def test_clone_goes_through_the_file_transport_of_an_absolute_source() -> None:
    # 🔴 ``file://`` намеренно: локальная оптимизация git (hardlink объектов основного
    # репозитория) отменяется, и у клона появляется СВОЙ объектный склад. Иначе файлы
    # объектов остались бы общими inode'ами с репозиторием owner'а.
    assert clone_argv("git", source="/Users/o/bob", dest="/Users/o/bob/.clones/task") == [
        "git",
        "clone",
        "file:///Users/o/bob",
        "/Users/o/bob/.clones/task",
    ]


def test_clone_runs_the_injected_git_binary() -> None:
    argv = clone_argv("my-git", source="/src", dest="/dst")
    assert argv[0] == "my-git"


def test_clone_argv_keeps_source_and_dest_as_separate_fixed_slots() -> None:
    # Форма фиксированная и shell-free: путь с пробелом остаётся ОДНИМ элементом argv,
    # а не превращается в два аргумента.
    argv = clone_argv("git", source="/a b/repo", dest="/c d/clone")
    assert argv[-2:] == ["file:///a b/repo", "/c d/clone"]


# --------------------------------------------------------------------------- #
# checkout_argv — на какой ветке оказывается клон
# --------------------------------------------------------------------------- #


def test_a_new_branch_is_created_at_the_cloned_head() -> None:
    assert checkout_argv("git", dest="/clone", branch="bob/task", on_origin=False) == [
        "git",
        "-C",
        "/clone",
        "switch",
        "-c",
        "bob/task",
    ]


def test_a_branch_known_to_origin_starts_from_it_instead_of_being_recreated() -> None:
    # 🔴 Урок BOB-087.D5b: пересоздание ветки поверх HEAD теряет НАКОПЛЕННУЮ работу
    # долгоживущего места. Если ветка уже есть у источника — стартуем с неё.
    assert checkout_argv("git", dest="/clone", branch="bob/epic-bob-089", on_origin=True) == [
        "git",
        "-C",
        "/clone",
        "switch",
        "-c",
        "bob/epic-bob-089",
        "origin/bob/epic-bob-089",
    ]


# --------------------------------------------------------------------------- #
# origin_argv — куда клон вообще может пушить
# --------------------------------------------------------------------------- #


def test_origin_is_repointed_to_the_fork() -> None:
    assert origin_argv("git", dest="/clone", fork_url="git@github.com:org/bob.git") == [
        "git",
        "-C",
        "/clone",
        "remote",
        "set-url",
        "origin",
        "git@github.com:org/bob.git",
    ]


def test_without_a_fork_the_remote_is_removed_entirely() -> None:
    # 🔴 Ключевое: после клонирования ``origin`` указывает на рабочую копию OWNER'А.
    # Если форк не настроен, remote'а не остаётся ВООБЩЕ — нечего пушить и нечего
    # перепутать; оставить путь owner'а как origin было бы худшим из вариантов.
    assert origin_argv("git", dest="/clone", fork_url="") == [
        "git",
        "-C",
        "/clone",
        "remote",
        "remove",
        "origin",
    ]


# --------------------------------------------------------------------------- #
# workspace_verdict — когда место переиспользуется
# --------------------------------------------------------------------------- #


def test_a_missing_destination_is_cloned() -> None:
    assert workspace_verdict(dest_exists=False, is_repo=False) is WorkspaceVerdict.CLONE


def test_an_existing_clone_is_reused_so_work_accumulates() -> None:
    assert workspace_verdict(dest_exists=True, is_repo=True) is WorkspaceVerdict.REUSE


def test_an_existing_directory_that_is_not_a_repo_is_refused_loudly() -> None:
    # Ни клонировать поверх, ни удалять чужой каталог: громкий отказ.
    assert workspace_verdict(dest_exists=True, is_repo=False) is WorkspaceVerdict.REFUSE


def test_a_repo_that_is_not_on_disk_is_still_cloned() -> None:
    # Вырожденный вход (``is_repo`` без каталога) не должен читаться как «переиспользуй».
    assert workspace_verdict(dest_exists=False, is_repo=True) is WorkspaceVerdict.CLONE


# --------------------------------------------------------------------------- #
# is_credential_free_url — токен не попадает в argv (виден в ``ps``)
# --------------------------------------------------------------------------- #


def test_an_url_with_an_embedded_token_is_refused() -> None:
    # Ровно форма installation-токена GitHub App — она НИКОГДА не должна оказаться в
    # командной строке: argv виден в ``ps`` любому процессу пользователя.
    assert (
        is_credential_free_url("https://x-access-token:ghs_secret@github.com/org/bob.git") is False
    )


def test_an_url_with_a_bare_userinfo_is_refused_too() -> None:
    assert is_credential_free_url("ssh://user:pw@example.com/org/bob.git") is False


def test_a_plain_https_url_is_accepted() -> None:
    assert is_credential_free_url("https://github.com/org/bob.git") is True


def test_an_scp_style_url_is_accepted() -> None:
    # ``git@host:path`` — это ИМЯ пользователя ssh, а не секрет: в scp-форме пароля нет.
    assert is_credential_free_url("git@github.com:org/bob.git") is True


def test_a_local_path_is_accepted() -> None:
    assert is_credential_free_url("/srv/mirrors/bob.git") is True


def test_an_at_sign_in_the_path_is_not_mistaken_for_credentials() -> None:
    assert is_credential_free_url("https://github.com/org/bob.git?x=a@b") is True


def test_an_empty_url_is_accepted_as_credential_free() -> None:
    # Пустой URL — «форк не настроен»; отказ по кредам тут был бы ложным диагнозом.
    assert is_credential_free_url("") is True
