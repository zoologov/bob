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
    PURGED_SPAWN_VARS,
    REDIRECTING_GIT_VARS,
    SpawnIsolation,
    controlled_ssh_command,
    credential_store_line,
    isolation_config_pairs,
    isolation_env,
)

_ISOLATION = SpawnIsolation(
    config_global="/w/gitconfig",
    askpass="/w/askpass-disabled",
    ssh_identity="/w/ssh-identity-disabled",
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
    env = isolation_env(SpawnIsolation(config_global="/w/c", askpass="/w/a", ssh_identity="/w/i"))
    assert "GH_CONFIG_DIR" not in env


def test_isolation_without_a_controlled_global_config_is_refused() -> None:
    # «Изоляция» без подменного global-конфига — это не изоляция, а её видимость.
    with pytest.raises(IdentityConfigError):
        isolation_env(SpawnIsolation(config_global="", askpass="/w/a", ssh_identity="/w/i"))


def test_isolation_without_an_askpass_target_is_refused() -> None:
    with pytest.raises(IdentityConfigError):
        isolation_env(SpawnIsolation(config_global="/w/c", askpass="", ssh_identity="/w/i"))


# --------------------------------------------------------------------------- #
# 🔴 ssh-дорога: чем git ходит по ``git@host:`` (bob-a6b.10)
#
# До этой беады изоляция ssh не касалась ВОВСЕ, и это был не пробел в тексте, а открытая
# дорога: ``ssh -T git@github.com`` из ровно прод-окружения спавна отвечал «Hi <owner>!»,
# а ``git ls-remote`` апстрима по ssh проходил. Здесь — форма вердикта; то, что настоящий
# ssh с этими опциями действительно не аутентифицируется, проверяется на настоящем
# инструменте (``tests/infrastructure/identity/test_ssh_isolation_real_ssh.py``) и вживую
# против настоящего GitHub (``tests/infrastructure/identity/test_ssh_road_live_smoke.py``).
# --------------------------------------------------------------------------- #


def test_git_is_given_a_controlled_ssh_command() -> None:
    assert isolation_env(_ISOLATION)["GIT_SSH_COMMAND"] == controlled_ssh_command(
        identity="/w/ssh-identity-disabled"
    )


def test_the_controlled_command_names_an_identity_file_explicitly() -> None:
    # 🔴 ГЛАВНЫЙ факт, найденный на настоящем ssh 10.2: ``IdentitiesOnly=yes`` САМ ПО СЕБЕ
    # ключи owner'а НЕ отключает — «configured identity» включает ДЕФОЛТНЫЕ файлы
    # ``~/.ssh/id_*``, и с одним этим флагом ssh по-прежнему здоровался как owner. Дорогу
    # закрывает только ЯВНО названный IdentityFile, которого нет.
    assert "-o IdentityFile=/w/ssh-identity-disabled" in controlled_ssh_command(
        identity="/w/ssh-identity-disabled"
    )


def test_the_controlled_command_reads_no_ssh_config_of_the_owner() -> None:
    # ``~/.ssh/config`` owner'а вернул бы и IdentityFile, и IdentityAgent, и ProxyCommand.
    assert "-F none" in controlled_ssh_command(identity="/w/i")


def test_the_controlled_command_refuses_identities_offered_by_an_agent() -> None:
    # Проверено вживую: с агентом, в который добавлен настоящий ключ owner'а, БЕЗ этих
    # опций ssh здоровается как owner, а с каждой из них — «Permission denied (publickey)».
    command = controlled_ssh_command(identity="/w/i")
    assert "-o IdentitiesOnly=yes" in command
    assert "-o IdentityAgent=none" in command


def test_the_controlled_command_never_waits_for_a_prompt() -> None:
    # Тот же смысл, что у ``GIT_TERMINAL_PROMPT=0``: неинтерактивный спавн обязан упасть.
    assert "-o BatchMode=yes" in controlled_ssh_command(identity="/w/i")


def test_the_controlled_command_starts_with_ssh_itself() -> None:
    assert controlled_ssh_command(identity="/w/i").split()[0] == "ssh"


def test_an_identity_path_with_a_space_is_quoted_for_the_shell() -> None:
    # 🔴 git исполняет ``GIT_SSH_COMMAND`` ЧЕРЕЗ ШЕЛЛ, а ``coder.clone_root`` — значение из
    # конфига owner'а. Без кавычек путь с пробелом разъехался бы на два аргумента, ssh взял
    # бы IdentityFile до пробела — и, не найдя его, всё равно упал бы, но по НЕ ТОЙ
    # причине; а «-o IdentityFile=…» с обрезанным путём легко читается как исправное.
    command = controlled_ssh_command(identity="/w/my clones/ssh-identity-disabled")
    assert "'IdentityFile=/w/my clones/ssh-identity-disabled'" in command


def test_the_identity_path_is_written_stripped_of_surrounding_whitespace() -> None:
    # Пустоту функция мерит по ``strip()`` — писать она обязана то же, что проверила.
    assert controlled_ssh_command(identity="  /w/i  ") == controlled_ssh_command(identity="/w/i")


def test_a_controlled_command_without_an_identity_target_is_refused() -> None:
    # Пустой путь дал бы ``-o IdentityFile=`` — а это для ssh «опции нет», то есть
    # ДЕФОЛТНЫЕ ключи owner'а. Тихо отдать половину меры хуже, чем упасть на сборке.
    with pytest.raises(IdentityConfigError):
        controlled_ssh_command(identity="   ")


def test_isolation_without_an_ssh_identity_target_is_refused() -> None:
    with pytest.raises(IdentityConfigError):
        isolation_env(SpawnIsolation(config_global="/w/c", askpass="/w/a", ssh_identity=""))


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
        SpawnIsolation(
            config_global="/w/c",
            askpass="/w/a",
            ssh_identity="/w/i",
            credential_store="/w/creds",
        )
    )
    assert pairs == (
        ("credential.helper", ""),
        ("credential.helper", "store --file=/w/creds"),
    )


def test_every_pair_configures_only_the_credential_helper() -> None:
    pairs = isolation_config_pairs(
        SpawnIsolation(
            config_global="/w/c",
            askpass="/w/a",
            ssh_identity="/w/i",
            credential_store="/w/creds",
        )
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


def test_the_inherited_git_config_parameters_block_is_named_for_removal() -> None:
    # 🔴 Найдено ревью (bob-a6b.6, MAJOR-1) и подтверждено на git 2.49: git читает
    # ``GIT_CONFIG_PARAMETERS`` ПОСЛЕ пар ``GIT_CONFIG_KEY_i``, поэтому унаследованная
    # переменная встаёт ПОСЛЕ нашего сброса и возвращает credential.helper owner'а. Она
    # не «снимается изнутри», а НАСЛЕДУЕТСЯ (Боб запущен из-под ``git -c …`` / алиаса /
    # хука) — то есть ровно тот класс, от которого мера и заведена.
    assert "GIT_CONFIG_PARAMETERS" in OWNER_CREDENTIAL_VARS


def test_removal_list_never_names_a_variable_the_isolation_itself_sets() -> None:
    # Иначе изоляция сняла бы свою же настройку — и это молча.
    assert not set(PURGED_SPAWN_VARS) & set(isolation_env(_ISOLATION))


# --------------------------------------------------------------------------- #
# 🔴 Семья переадресующих переменных (ревью bob-a6b.6, MAJOR-5)
#
# Состав — это и есть содержание фикса, поэтому он закреплён СПИСКОМ: добавление
# переменной в семью обязано быть осознанным, а пропажа — красным тестом. Что каждая из
# них РЕАЛЬНО делает на настоящем git (и что перестаёт делать в изоляции), доказано парами
# в ``tests/infrastructure/coding/test_spawn_redirect_vars_real_git.py`` — здесь только
# форма вердикта.
# --------------------------------------------------------------------------- #


def test_the_variables_that_repoint_a_git_operation_at_another_repository_are_named() -> None:
    # Указатели на ЧАСТИ чужого репозитория: каталог, рабочее дерево, общий каталог,
    # индекс, склад объектов (запись и чтение) и партиция refs.
    assert set(REDIRECTING_GIT_VARS) == {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
        "GIT_CEILING_DIRECTORIES",
        "GIT_CONFIG",
    }


def test_the_main_vector_of_the_family_is_named_first() -> None:
    # 🔴 ``GIT_DIR`` — та самая переменная, которой ревьюер сдвинул ствол владельца ОДНОЙ
    # командой из клона Боба (rc=0, коммит потерян).
    assert "GIT_DIR" in REDIRECTING_GIT_VARS


def test_the_spawn_purges_credentials_and_pointers_as_one_list() -> None:
    # Один шов вычистки: и креды, и указатели. Иначе вторая половина семьи молча осталась
    # бы в окружении (ровно то, чем MAJOR-5 и оказался рядом с закрытым MAJOR-1).
    both_halves = (*OWNER_CREDENTIAL_VARS, *REDIRECTING_GIT_VARS)
    assert both_halves == PURGED_SPAWN_VARS


def test_the_two_halves_of_the_purge_list_do_not_overlap() -> None:
    # Пересечение означало бы, что одна из двух причин вычистки — фикция.
    assert not set(OWNER_CREDENTIAL_VARS) & set(REDIRECTING_GIT_VARS)


def test_the_env_config_block_of_the_owner_is_left_alone_on_purpose() -> None:
    # 🔴 Ревью проверило, что унаследованные ``GIT_CONFIG_KEY_i`` и ``XDG_CONFIG_HOME``
    # изоляцию НЕ пробивают: наши пары встают ПОСЛЕ пар owner'а (и потому его helper
    # сбрасывается), а XDG перекрыт ``GIT_CONFIG_GLOBAL``. Вычистка этих переменных
    # сломала бы документированный контракт ``guarded_spawn_env`` про продолжение
    # нумерации — поэтому их отсутствие в списке НАМЕРЕННО.
    assert not {
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
        "GIT_CONFIG_GLOBAL",
        "XDG_CONFIG_HOME",
    } & set(PURGED_SPAWN_VARS)


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


def test_a_fork_url_with_a_line_break_is_refused_just_like_a_token_with_one() -> None:
    # 🔴 Найдено ревью (bob-a6b.6, MAJOR-4): запрет стоял ТОЛЬКО на токене, а адрес
    # проверку не проходил — и класс ``[^/]`` в разборе authority перевод строки МАТЧИТ.
    # Ревьюер получил в сторе ДВЕ строки: 'https://x-access-token:<TOK>@github.com\n
    # https:\n'. Запрет — на любой перевод строки в ЛЮБОМ поле, из которого собирается
    # строка стора, иначе несущий инвариант функции держится только на одном её аргументе.
    with pytest.raises(IdentityConfigError, match="fork URL"):
        credential_store_line(fork_url="https://github.com\nhttps://evil.invalid/o/r", token="T")


def test_a_fork_url_with_a_bare_carriage_return_is_refused_too() -> None:
    with pytest.raises(IdentityConfigError, match="line break or control character"):
        credential_store_line(fork_url="https://github.com\rhttps://evil.invalid/o/r", token="T")


def test_a_fork_url_with_a_control_character_is_refused() -> None:
    # Управляющие символы в поле строки стора не имеют смысла ни в одной форме: git читает
    # файл построчно, а терминал, в котором владелец его посмотрит, ими управляется.
    with pytest.raises(IdentityConfigError, match="control character"):
        credential_store_line(fork_url="https://git\thub.com/o/r", token="T")


def test_a_token_with_a_control_character_is_refused() -> None:
    with pytest.raises(IdentityConfigError, match="installation token containing a line break"):
        credential_store_line(fork_url="https://github.com/o/r", token="T\tT")


def test_the_assembled_line_is_always_exactly_one_line() -> None:
    # Контракт целиком, а не по полям: что бы ни пришло на вход, в стор уезжает ОДНА
    # запись. Тест ловит и будущее поле, о котором проверка забудет.
    line = credential_store_line(fork_url="https://gh.example.com:8443/o/r", token="T-o_k.en")
    assert line.count("\n") == 1
    assert line.endswith("\n")


def test_a_token_containing_an_at_sign_is_refused_rather_than_silently_truncated() -> None:
    # 🔴 Ревьюер показал форму отказа молча: 'https://x-access-token:tok@en@github.com' —
    # git берёт ПЕРВЫЙ '@', то есть паролем становится 'tok', а хостом 'en@github.com'.
    # Токен обрезан и записан НЕ ТОМУ хосту; отказ честнее.
    with pytest.raises(IdentityConfigError, match="'@'"):
        credential_store_line(fork_url="https://github.com/o/r", token="tok@en")


def test_a_refusal_about_an_at_sign_in_the_token_never_echoes_it() -> None:
    secret = "ghs_secret@evil.invalid"  # noqa: S105 — фиктивный «токен» для проверки утечки
    with pytest.raises(IdentityConfigError) as failure:
        credential_store_line(fork_url="https://github.com/o/r", token=secret)
    assert "ghs_secret" not in str(failure.value)


def test_surrounding_whitespace_is_stripped_from_the_token_that_gets_written() -> None:
    # Пустоту функция мерит по ``strip()``, а писала — сырое значение: несовпадение
    # проверки и записи. Пишется то, что проверено.
    assert credential_store_line(fork_url="https://github.com/o/r", token="  T  ") == (
        "https://x-access-token:T@github.com\n"
    )


def test_a_token_of_exactly_the_permitted_length_is_still_accepted() -> None:
    # Граница предела ВКЛЮЧИТЕЛЬНАЯ, и это проверяется: мутация ``>`` → ``>=`` иначе
    # выживает, то есть отказ уезжал бы на один символ раньше объявленного.
    token = "t" * 4096
    assert credential_store_line(fork_url="https://github.com/o/r", token=token) == (
        f"https://x-access-token:{token}@github.com\n"
    )


def test_an_absurdly_long_token_is_refused_instead_of_being_written() -> None:
    # Installation-токен GitHub — десятки байт. 100 КБ в этом поле означают, что на вход
    # приехало не токен, а что-то другое; писать это в стор кредов незачем.
    with pytest.raises(IdentityConfigError, match="longer than"):
        credential_store_line(fork_url="https://github.com/o/r", token="t" * 100_000)


def test_a_plain_http_fork_url_is_refused_because_the_token_would_travel_in_clear() -> None:
    # Значение константы-регекса, а не её вид: ``http://`` отправил бы токен открытым
    # текстом. Mutation про модульные константы не говорит ничего — поэтому юнит.
    with pytest.raises(IdentityConfigError):
        credential_store_line(fork_url="http://github.com/o/r", token="T")


def test_an_empty_token_is_refused_rather_than_written_as_empty_password() -> None:
    with pytest.raises(IdentityConfigError, match="empty installation token"):
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
