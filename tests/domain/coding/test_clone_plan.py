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
    fetch_argv,
    identity_argv,
    is_credential_free_url,
    origin_argv,
    workspace_verdict,
)

#: 🔴 Закалённые пары (bob-a6b.14) выписаны здесь ДОСЛОВНО, а не взяты из продового
#: :func:`bob.coding.untrusted_repo.hardened_git_argv`: иначе тест утверждал бы сам себя, а
#: снятие пары в проде осталось бы зелёным. Что каждая закрывает и чем это доказано — в
#: докстроке того модуля и в паре контроль/защита на настоящем git
#: (``tests/infrastructure/coding/test_untrusted_repo_real_git.py``).
_PINS = [
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "commit.gpgSign=false",
]


def _hardened(git_bin: str, *rest: str) -> list[str]:
    """Ожидаемая форма: бинарь, пары, потом всё остальное (включая ``-C <путь>``)."""
    return [git_bin, *_PINS, *rest]


# --------------------------------------------------------------------------- #
# clone_argv — как именно заводится клон
# --------------------------------------------------------------------------- #


def test_clone_goes_through_the_file_transport_of_an_absolute_source() -> None:
    # 🔴 ``file://`` намеренно: локальная оптимизация git (hardlink объектов основного
    # репозитория) отменяется, и у клона появляется СВОЙ объектный склад. Иначе файлы
    # объектов остались бы общими inode'ами с репозиторием owner'а.
    assert clone_argv("git", source="/Users/o/bob", dest="/Users/o/bob/.clones/task") == (
        _hardened("git", "clone", "file:///Users/o/bob", "/Users/o/bob/.clones/task")
    )


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
    assert checkout_argv("git", dest="/clone", branch="bob/task", on_origin=False) == (
        _hardened("git", "-C", "/clone", "switch", "-c", "bob/task")
    )


def test_a_branch_known_to_origin_starts_from_it_instead_of_being_recreated() -> None:
    # 🔴 Урок BOB-087.D5b: пересоздание ветки поверх HEAD теряет НАКОПЛЕННУЮ работу
    # долгоживущего места. Если ветка уже есть у источника — стартуем с неё.
    assert checkout_argv("git", dest="/clone", branch="bob/epic-bob-089", on_origin=True) == (
        _hardened(
            "git",
            "-C",
            "/clone",
            "switch",
            "-c",
            "bob/epic-bob-089",
            "origin/bob/epic-bob-089",
        )
    )


# --------------------------------------------------------------------------- #
# origin_argv — куда клон вообще может пушить
# --------------------------------------------------------------------------- #


def test_origin_is_repointed_to_the_fork() -> None:
    assert origin_argv("git", dest="/clone", fork_url="git@github.com:org/bob.git") == (
        _hardened(
            "git", "-C", "/clone", "remote", "set-url", "origin", "git@github.com:org/bob.git"
        )
    )


def test_without_a_fork_the_remote_is_removed_entirely() -> None:
    # 🔴 Ключевое: после клонирования ``origin`` указывает на рабочую копию OWNER'А.
    # Если форк не настроен, remote'а не остаётся ВООБЩЕ — нечего пушить и нечего
    # перепутать; оставить путь owner'а как origin было бы худшим из вариантов.
    assert origin_argv("git", dest="/clone", fork_url="") == (
        _hardened("git", "-C", "/clone", "remote", "remove", "origin")
    )


# --------------------------------------------------------------------------- #
# fetch_argv — у КОГО спрашивают про накопленную ветку (ревью bob-a6b.6, MAJOR-2)
# --------------------------------------------------------------------------- #


def test_the_fork_is_asked_about_its_branches_by_a_pruning_fetch() -> None:
    # 🔴 ``--prune`` — не украшение. Сразу после клонирования refs ``origin/*`` описывают
    # ветки РЕПОЗИТОРИЯ ВЛАДЕЛЬЦА; после переадресации remote'а на форк они остаются
    # лежать как есть. Без прунинга ветка, которая есть ТОЛЬКО у владельца, читалась бы
    # как «накопленная работа в форке», и клон встал бы на чужое состояние.
    assert fetch_argv("git", dest="/clone") == (
        _hardened("git", "-C", "/clone", "fetch", "--prune", "origin")
    )


def test_fetch_runs_the_injected_git_binary() -> None:
    assert fetch_argv("my-git", dest="/clone")[0] == "my-git"


def test_fetch_never_names_a_remote_other_than_origin() -> None:
    # У клона remote РОВНО один и он — форк (или его нет вовсе): спрашивать больше некого.
    assert fetch_argv("git", dest="/clone")[-1] == "origin"


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


# --------------------------------------------------------------------------- #
# identity_argv — чем подписана работа Боба (BOB-089, срез D)
# --------------------------------------------------------------------------- #


def test_the_work_is_signed_bob_ai_locally_in_the_clone() -> None:
    # 🔴 ГЛАВНОЕ среза D: ``--local``. Глобальная настройка переподписала бы коммиты
    # owner'а в его собственном репозитории как ``bob[ai]`` — ровно та путаница
    # идентичностей, от которой уходим. Форма это ЗАПРЕЩАЕТ: и ``-C <клон>``, и
    # ``--local`` стоят в argv явно.
    assert identity_argv("git", dest="/clone", app_user_id="424242") == [
        _hardened("git", "-C", "/clone", "config", "--local", "user.name", "bob[ai]"),
        _hardened(
            "git",
            "-C",
            "/clone",
            "config",
            "--local",
            "user.email",
            "424242+bob-ai-work[bot]@users.noreply.github.com",
        ),
    ]


def test_neither_identity_command_can_write_the_global_config() -> None:
    for argv in identity_argv("git", dest="/clone", app_user_id="424242"):
        assert "--local" in argv
        assert "--global" not in argv
        assert "--system" not in argv
        # адресат — клон, не репозиторий owner'а (``-C`` стоит сразу после закалённых пар)
        assert argv[len(_PINS) + 1 : len(_PINS) + 3] == ["-C", "/clone"]


def test_without_an_app_user_id_the_name_is_still_set_with_an_id_less_email() -> None:
    # 🔴 Не ставить подпись вовсе было бы ХУЖЕ: git взял бы имя из конфигурации owner'а,
    # и работа Боба выглядела бы работой owner'а (та самая неразличимость в ``git log``,
    # против которой US-2). Поэтому имя ставится всегда, а числовой префикс — опционален
    # (без него адрес просто не сшивается GitHub'ом с ботом).
    assert identity_argv("git", dest="/clone", app_user_id="") == [
        _hardened("git", "-C", "/clone", "config", "--local", "user.name", "bob[ai]"),
        _hardened(
            "git",
            "-C",
            "/clone",
            "config",
            "--local",
            "user.email",
            "bob-ai-work[bot]@users.noreply.github.com",
        ),
    ]


def test_a_non_numeric_app_user_id_is_ignored_rather_than_pasted_into_the_address() -> None:
    # id приложения — число. Мусор в конфиге не превращается в правдоподобный адрес.
    assert identity_argv("git", dest="/clone", app_user_id="not-an-id")[1][-1] == (
        "bob-ai-work[bot]@users.noreply.github.com"
    )


def test_identity_runs_the_injected_git_binary() -> None:
    for argv in identity_argv("my-git", dest="/clone", app_user_id="1"):
        assert argv[0] == "my-git"


def test_the_email_stays_one_fixed_argv_slot() -> None:
    # Форма фиксированная и shell-free: адрес целиком — ОДИН элемент argv.
    name_argv, email_argv = identity_argv("git", dest="/a b/clone", app_user_id="7")

    assert name_argv[-1] == "bob[ai]"
    assert email_argv[-1] == "7+bob-ai-work[bot]@users.noreply.github.com"
    assert len(email_argv) == 7 + len(_PINS)


# --------------------------------------------------------------------------- #
# 🔴 Ни одна форма не остаётся «голой» (bob-a6b.14)
# --------------------------------------------------------------------------- #


def test_every_form_of_the_clone_plan_carries_the_hardening_pins() -> None:
    # Клон заводится и обслуживается из процесса САМОГО Боба, а с первого ``switch`` в его
    # каталоге лежит содержимое, за которое отвечает модель. Форма, забывшая пары, — это
    # исполнение её кода на нашей стороне; поэтому проверяется НАБОР форм, а не отдельная.
    forms = [
        clone_argv("git", source="/src", dest="/dst"),
        checkout_argv("git", dest="/dst", branch="bob/task", on_origin=False),
        checkout_argv("git", dest="/dst", branch="bob/task", on_origin=True),
        origin_argv("git", dest="/dst", fork_url="https://github.com/org/bob.git"),
        origin_argv("git", dest="/dst", fork_url=""),
        fetch_argv("git", dest="/dst"),
        *identity_argv("git", dest="/dst", app_user_id="42"),
    ]

    for argv in forms:
        assert argv[: len(_PINS) + 1] == ["git", *_PINS], argv
