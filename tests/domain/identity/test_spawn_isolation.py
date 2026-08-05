# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты чистого ядра изоляции окружения спавна (BOB-089, срез C).

Что здесь решается: КАКИМ git-окружением работает процесс ``claude`` — чей конфиг он
читает, какие креды ему доступны и каких переменных owner'а в нём не остаётся. Ядро
чистое: ни файла, ни процесса, ни сети (mutation-цель).

🔴 То, что изоляция РЕАЛЬНО убирает креды owner'а, этими тестами НЕ доказывается — это
контракт настоящего git, и он проверяется отдельно на настоящем git
(``tests/infrastructure/coding/test_spawn_isolation_real_git.py``) и вживую против
настоящего GitHub (``tests/infrastructure/coding/test_upstream_refusal_live_smoke.py``).
Здесь — только форма вердикта.
"""

from __future__ import annotations

import pytest

from bob.identity.ports import IdentityConfigError
from bob.identity.spawn_isolation import (
    OWNER_CREDENTIAL_VARS,
    SpawnIsolation,
    credential_store_line,
    isolation_config_pairs,
    isolation_env,
)

_ISOLATION = SpawnIsolation(
    config_global="/w/gitconfig",
    askpass="/w/askpass-disabled",
    gh_config_dir="/w/gh",
)

# --------------------------------------------------------------------------- #
# isolation_env: чей конфиг читает git и куда он НЕ уходит спрашивать пароль
# --------------------------------------------------------------------------- #


def test_global_config_is_repointed_at_the_controlled_file() -> None:
    assert isolation_env(_ISOLATION)["GIT_CONFIG_GLOBAL"] == "/w/gitconfig"


def test_the_system_config_is_disabled_too() -> None:
    # 🔴 Главный факт, найденный на настоящем git: ``credential.helper = osxkeychain``
    # приезжает из СИСТЕМНОГО конфига (/opt/homebrew/etc/gitconfig), которого
    # ``GIT_CONFIG_GLOBAL`` не замещает. Без этой переменной изоляция была бы мнимой.
    assert isolation_env(_ISOLATION)["GIT_CONFIG_NOSYSTEM"] == "1"


def test_terminal_prompts_are_disabled_so_git_fails_instead_of_asking() -> None:
    # Спавн неинтерактивен: без этого git повис бы на запросе пароля, а не упал честно.
    assert isolation_env(_ISOLATION)["GIT_TERMINAL_PROMPT"] == "0"


def test_askpass_points_nowhere_for_both_git_and_ssh() -> None:
    env = isolation_env(_ISOLATION)
    assert env["GIT_ASKPASS"] == "/w/askpass-disabled"
    assert env["SSH_ASKPASS"] == "/w/askpass-disabled"


def test_gh_gets_its_own_empty_config_dir() -> None:
    # gh хранит СВОЙ токен в ``~/.config/gh/hosts.yml``; с токеном owner'а там
    # ``gh pr merge`` дотянулся бы до ствола мимо всякого git-конфига.
    assert isolation_env(_ISOLATION)["GH_CONFIG_DIR"] == "/w/gh"


def test_an_unset_gh_config_dir_is_not_invented() -> None:
    env = isolation_env(SpawnIsolation(config_global="/w/c", askpass="/w/a"))
    assert "GH_CONFIG_DIR" not in env


def test_isolation_without_a_controlled_global_config_is_refused() -> None:
    # «Изоляция» без подменного global-конфига — это не изоляция, а её видимость.
    with pytest.raises(IdentityConfigError):
        isolation_env(SpawnIsolation(config_global="", askpass="/w/a"))


def test_isolation_without_an_askpass_target_is_refused() -> None:
    with pytest.raises(IdentityConfigError):
        isolation_env(SpawnIsolation(config_global="/w/c", askpass=""))


# --------------------------------------------------------------------------- #
# isolation_config_pairs: сброс списка хелперов, потом (и только потом) свой
# --------------------------------------------------------------------------- #


def test_the_helper_list_is_reset_first() -> None:
    # Пустое значение СБРАСЫВАЕТ накопленный список хелперов (проверено на git 2.49):
    # именно так умирают и osxkeychain из системного конфига, и helper owner'а.
    assert isolation_config_pairs(_ISOLATION)[0] == ("credential.helper", "")


def test_with_no_store_the_spawn_gets_no_credentials_at_all() -> None:
    # Прод-дефолт: пуш делает процесс САМОГО Боба, спавну креды не нужны вовсе.
    assert isolation_config_pairs(_ISOLATION) == (("credential.helper", ""),)


def test_bobs_store_is_added_after_the_reset_never_before() -> None:
    pairs = isolation_config_pairs(
        SpawnIsolation(config_global="/w/c", askpass="/w/a", credential_store="/w/creds")
    )
    assert pairs == (
        ("credential.helper", ""),
        ("credential.helper", "store --file=/w/creds"),
    )


def test_every_pair_configures_only_the_credential_helper() -> None:
    pairs = isolation_config_pairs(
        SpawnIsolation(config_global="/w/c", askpass="/w/a", credential_store="/w/creds")
    )
    assert {key for key, _ in pairs} == {"credential.helper"}


# --------------------------------------------------------------------------- #
# Переменные owner'а, которые не имеют права доехать до спавна
# --------------------------------------------------------------------------- #


def test_ambient_github_tokens_are_named_for_removal() -> None:
    # Токен owner'а в окружении — прямая дорога к апстриму через ``gh``/API.
    assert {"GITHUB_TOKEN", "GH_TOKEN"} <= set(OWNER_CREDENTIAL_VARS)


def test_the_ssh_agent_socket_is_named_for_removal() -> None:
    # Ключ owner'а в агенте пушит по ``git@github.com:`` без всякого хелпера.
    assert "SSH_AUTH_SOCK" in OWNER_CREDENTIAL_VARS


def test_removal_list_never_names_a_variable_the_isolation_itself_sets() -> None:
    # Иначе изоляция сняла бы свою же настройку — и это молча.
    assert not set(OWNER_CREDENTIAL_VARS) & set(isolation_env(_ISOLATION))


# --------------------------------------------------------------------------- #
# credential_store_line: как токен Боба попадает к git, НЕ попадая в argv
# --------------------------------------------------------------------------- #


def test_store_line_addresses_the_host_of_the_fork_as_x_access_token() -> None:
    line = credential_store_line(fork_url="https://github.com/bobiverse-dev/bob.git", token="T")
    assert line == "https://x-access-token:T@github.com\n"


def test_store_line_ends_with_a_newline_because_git_reads_lines() -> None:
    line = credential_store_line(fork_url="https://github.com/o/r", token="T")
    assert line.endswith("\n")


def test_store_line_keeps_a_non_default_port() -> None:
    line = credential_store_line(fork_url="https://gh.example.com:8443/o/r", token="T")
    assert line == "https://x-access-token:T@gh.example.com:8443\n"


def test_a_token_with_a_newline_is_refused_not_written() -> None:
    # Перевод строки внутри токена дописал бы в стор ВТОРУЮ запись — чужой хост.
    with pytest.raises(IdentityConfigError):
        credential_store_line(fork_url="https://github.com/o/r", token="T\nhttps://evil")


def test_a_token_with_a_bare_carriage_return_is_refused_too() -> None:
    # 🔴 Нашла мутация: проверялся только ``\n``, поэтому одиночный ``\r`` (старый
    # macOS-перевод строки, и он же — способ «переписать» видимое содержимое строки в
    # терминале) уезжал в стор как часть пароля.
    with pytest.raises(IdentityConfigError):
        credential_store_line(fork_url="https://github.com/o/r", token="T\rhttps://evil")


def test_a_plain_http_fork_url_is_refused_because_the_token_would_travel_in_clear() -> None:
    # Значение константы-регекса, а не её вид: ``http://`` отправил бы токен открытым
    # текстом. Mutation про модульные константы не говорит ничего — поэтому юнит.
    with pytest.raises(IdentityConfigError):
        credential_store_line(fork_url="http://github.com/o/r", token="T")


def test_an_empty_token_is_refused_rather_than_written_as_empty_password() -> None:
    with pytest.raises(IdentityConfigError):
        credential_store_line(fork_url="https://github.com/o/r", token="   ")


def test_a_non_https_fork_url_is_refused() -> None:
    # По ssh installation-токен не работает вовсе, а в scp-форме пароля нет.
    with pytest.raises(IdentityConfigError):
        credential_store_line(fork_url="git@github.com:o/r.git", token="T")


def test_a_fork_url_that_already_carries_credentials_is_refused() -> None:
    with pytest.raises(IdentityConfigError):
        credential_store_line(fork_url="https://x-access-token:OLD@github.com/o/r", token="T")


def test_a_refusal_never_carries_the_token_value() -> None:
    # 🔴 Отказ уезжает в лог и в traceback; значение токена там осело бы навсегда.
    secret = "ghs_thisisthesecretvalue"  # noqa: S105 — фиктивный «токен» для проверки утечки
    with pytest.raises(IdentityConfigError) as failure:
        credential_store_line(fork_url="git@github.com:o/r.git", token=secret)
    assert secret not in str(failure.value)


def test_a_refusal_about_the_token_shape_never_echoes_it_either() -> None:
    secret = "ghs_secret\nhttps://evil"  # noqa: S105 — фиктивный «токен» для проверки утечки
    with pytest.raises(IdentityConfigError) as failure:
        credential_store_line(fork_url="https://github.com/o/r", token=secret)
    assert "ghs_secret" not in str(failure.value)
