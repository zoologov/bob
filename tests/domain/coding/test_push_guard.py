# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты push_guard — окружение спавна claude с запретом исходящего push (BOB-087.E, bob-5ao).

Чистое доменное ядро (mutation-цель): во что превращается «наследуемое окружение +
владелец ослабил песочницу» — в git-конфиг через ``GIT_CONFIG_*``, который переписывает
любой push-URL в несуществующий remote-helper.

🔴 Что этот барьер НЕ делает — зафиксировано отдельным реальным git-тестом
(``tests/infrastructure/coding/test_push_guard_real_git.py``): он НЕ граница, а
страховка от нечаянного push. Здесь проверяется только форма вердикта.
"""

from __future__ import annotations

from bob.coding.push_guard import (
    PUSH_GUARD_STUB_URL,
    PUSH_GUARD_URL_PREFIXES,
    guarded_spawn_env,
)
from bob.identity.spawn_isolation import OWNER_CREDENTIAL_VARS, SpawnIsolation

#: Фиктивный «gh-токен owner'а»: в окружении спавна его быть не должно.
_OWNER_GH_TOKEN = "owner-gh-token"  # noqa: S105 — фиктивное значение для проверки вычистки

_ISOLATION = SpawnIsolation(
    config_global="/w/gitconfig",
    askpass="/w/askpass-disabled",
    ssh_identity="/w/ssh-identity-disabled",
    gh_config_dir="/w/gh",
)


def _pairs(env: dict[str, str]) -> list[tuple[str, str]]:
    """Пары git-конфига окружения В ПОРЯДКЕ индексов (порядок здесь — часть смысла)."""
    return [
        (env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"])
        for i in range(int(env["GIT_CONFIG_COUNT"]))
    ]

# --------------------------------------------------------------------------- #
# OFF-путь: барьер неактивен → спавн байт-в-байт прежний
# --------------------------------------------------------------------------- #


def test_inactive_guard_returns_no_env_override_at_all() -> None:
    # ``None`` — это ровно «не передавать env= в спавн», т.е. дефолтное наследование.
    assert guarded_spawn_env({"PATH": "/usr/bin"}, active=False) is None


def test_inactive_guard_ignores_an_existing_git_config_count() -> None:
    assert guarded_spawn_env({"GIT_CONFIG_COUNT": "2"}, active=False) is None


# --------------------------------------------------------------------------- #
# ON-путь: наследуем окружение и доклеиваем git-конфиг заглушки
# --------------------------------------------------------------------------- #


def test_active_guard_keeps_the_inherited_environment() -> None:
    # claude без PATH/HOME/токенов просто не запустится: барьер ДОПОЛНЯЕТ окружение.
    env = guarded_spawn_env({"PATH": "/usr/bin", "HOME": "/h"}, active=True)
    assert env is not None
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/h"


def test_active_guard_does_not_mutate_the_base_environment() -> None:
    base = {"PATH": "/usr/bin"}
    guarded_spawn_env(base, active=True)
    assert base == {"PATH": "/usr/bin"}


def test_active_guard_rewrites_every_guarded_url_prefix_to_the_stub() -> None:
    env = guarded_spawn_env({}, active=True)
    assert env is not None
    pairs = {
        (env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"])
        for i in range(int(env["GIT_CONFIG_COUNT"]))
    }
    assert pairs == {
        (f"url.{PUSH_GUARD_STUB_URL}.pushInsteadOf", prefix)
        for prefix in PUSH_GUARD_URL_PREFIXES
    }


def test_guarded_prefixes_cover_the_transports_a_push_to_github_can_use() -> None:
    # Прод-origin — ssh (``git@github.com:...``); https/ssh:// — обычные альтернативы.
    assert {"git@", "https://", "ssh://"} <= set(PUSH_GUARD_URL_PREFIXES)


def test_the_stub_scheme_names_itself_in_the_git_error() -> None:
    # git печатает «remote helper '<схема>' aborted session» — схема и есть объяснение.
    scheme = PUSH_GUARD_STUB_URL.split("://")[0]
    assert scheme.startswith("bob-")
    assert "push" in scheme


def test_count_matches_the_number_of_declared_pairs() -> None:
    env = guarded_spawn_env({}, active=True)
    assert env is not None
    assert env["GIT_CONFIG_COUNT"] == str(len(PUSH_GUARD_URL_PREFIXES))


def test_pairs_are_numbered_from_zero_without_gaps() -> None:
    env = guarded_spawn_env({}, active=True)
    assert env is not None
    for index in range(len(PUSH_GUARD_URL_PREFIXES)):
        assert f"GIT_CONFIG_KEY_{index}" in env
        assert f"GIT_CONFIG_VALUE_{index}" in env


# --------------------------------------------------------------------------- #
# Сосуществование с уже настроенным GIT_CONFIG_* окружения owner'а
# --------------------------------------------------------------------------- #


def test_an_existing_git_config_block_is_extended_not_clobbered() -> None:
    # У owner'а уже есть свои две записи (0 и 1) — наши обязаны встать ПОСЛЕ них,
    # иначе его настройки будут прочитаны git'ом как наши.
    base = {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "user.name",
        "GIT_CONFIG_VALUE_0": "owner",
        "GIT_CONFIG_KEY_1": "user.email",
        "GIT_CONFIG_VALUE_1": "o@example.com",
    }
    env = guarded_spawn_env(base, active=True)
    assert env is not None
    assert env["GIT_CONFIG_KEY_0"] == "user.name"
    assert env["GIT_CONFIG_KEY_1"] == "user.email"
    assert env["GIT_CONFIG_KEY_2"] == f"url.{PUSH_GUARD_STUB_URL}.pushInsteadOf"
    assert env["GIT_CONFIG_COUNT"] == str(2 + len(PUSH_GUARD_URL_PREFIXES))


def test_a_non_numeric_existing_count_is_treated_as_absent() -> None:
    # Мусор в GIT_CONFIG_COUNT git всё равно не прочитает — нумеруемся с нуля.
    for garbage in ["", "  ", "abc", "-1", "1.5", "0x2"]:
        env = guarded_spawn_env({"GIT_CONFIG_COUNT": garbage}, active=True)
        assert env is not None
        assert env["GIT_CONFIG_KEY_0"] == f"url.{PUSH_GUARD_STUB_URL}.pushInsteadOf"
        assert env["GIT_CONFIG_COUNT"] == str(len(PUSH_GUARD_URL_PREFIXES))


def test_a_padded_numeric_existing_count_is_honoured() -> None:
    env = guarded_spawn_env({"GIT_CONFIG_COUNT": " 3 "}, active=True)
    assert env is not None
    assert env["GIT_CONFIG_KEY_3"] == f"url.{PUSH_GUARD_STUB_URL}.pushInsteadOf"
    assert env["GIT_CONFIG_COUNT"] == str(3 + len(PUSH_GUARD_URL_PREFIXES))


def test_zero_existing_count_numbers_from_zero() -> None:
    env = guarded_spawn_env({"GIT_CONFIG_COUNT": "0"}, active=True)
    assert env is not None
    assert env["GIT_CONFIG_KEY_0"] == f"url.{PUSH_GUARD_STUB_URL}.pushInsteadOf"
    assert env["GIT_CONFIG_COUNT"] == str(len(PUSH_GUARD_URL_PREFIXES))


# --------------------------------------------------------------------------- #
# 🔴 Чего барьер ПО КОНСТРУКЦИИ не делает (защита от ложной уверенности)
# --------------------------------------------------------------------------- #


def test_the_guard_never_sets_a_remote_pushurl() -> None:
    # Проверено на реальном git: ``remote.<name>.pushurl`` из env НЕ замещает файловое
    # значение (ключ многозначный — git пушит во ВСЕ URL) и вдобавок ОТКЛЮЧАЕТ
    # ``pushInsteadOf``. Заглушка через pushurl была бы строго слабее — её тут нет.
    env = guarded_spawn_env({}, active=True)
    assert env is not None
    assert not any(value.endswith(".pushurl") for value in env.values())


def test_fetch_transports_are_left_alone() -> None:
    # Только ``pushInsteadOf`` (не ``insteadOf``): чтение (fetch/clone) не ломается.
    env = guarded_spawn_env({}, active=True)
    assert env is not None
    keys = [v for k, v in env.items() if k.startswith("GIT_CONFIG_KEY_")]
    assert keys
    assert all(key.endswith(".pushInsteadOf") for key in keys)


# --------------------------------------------------------------------------- #
# Изоляция кредов (BOB-089, срез C): ВТОРОГО механизма нет — тот же шов
# --------------------------------------------------------------------------- #


def test_without_the_barrier_and_without_isolation_nothing_is_overridden() -> None:
    # Оба выключены → ``None``, то есть спавн вообще без ``env=``: байт-в-байт прежний.
    assert guarded_spawn_env({"PATH": "/usr/bin"}, active=False, isolation=None) is None


def test_isolation_alone_already_overrides_the_environment() -> None:
    # Изоляция не требует ослабленной песочницы: клон-режим включается своим флагом.
    env = guarded_spawn_env({"PATH": "/usr/bin"}, active=False, isolation=_ISOLATION)
    assert env is not None
    assert env["PATH"] == "/usr/bin"
    assert env["GIT_CONFIG_GLOBAL"] == "/w/gitconfig"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_isolation_alone_resets_the_helper_list_and_adds_no_push_barrier() -> None:
    env = guarded_spawn_env({}, active=False, isolation=_ISOLATION)
    assert env is not None
    assert _pairs(env) == [("credential.helper", "")]


def test_the_barrier_and_the_isolation_compose_in_one_config_block() -> None:
    env = guarded_spawn_env({}, active=True, isolation=_ISOLATION)
    assert env is not None
    pairs = _pairs(env)
    assert len(pairs) == len(PUSH_GUARD_URL_PREFIXES) + 1
    assert pairs[-1] == ("credential.helper", "")
    assert all(key.endswith(".pushInsteadOf") for key, _ in pairs[:-1])


def test_the_owners_own_config_pairs_stay_ahead_of_the_helper_reset() -> None:
    # 🔴 Сброс хелперов обязан стоять ПОСЛЕ пар owner'а: иначе его helper, объявленный
    # в окружении, снова окажется в списке — то есть его креды снова отвечают git'у.
    base = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "GIT_CONFIG_VALUE_0": "osxkeychain",
    }
    env = guarded_spawn_env(base, active=False, isolation=_ISOLATION)
    assert env is not None
    assert _pairs(env) == [
        ("credential.helper", "osxkeychain"),
        ("credential.helper", ""),
    ]


def test_bobs_credential_store_arrives_as_the_last_helper() -> None:
    env = guarded_spawn_env(
        {},
        active=True,
        isolation=SpawnIsolation(
            config_global="/w/c",
            askpass="/w/a",
            ssh_identity="/w/i",
            credential_store="/w/creds",
        ),
    )
    assert env is not None
    pairs = _pairs(env)
    assert pairs[-2:] == [
        ("credential.helper", ""),
        ("credential.helper", "store --file=/w/creds"),
    ]


def test_the_owners_ambient_credentials_are_dropped_from_the_spawn() -> None:
    base = {
        "PATH": "/usr/bin",
        "GH_TOKEN": _OWNER_GH_TOKEN,
        "GITHUB_TOKEN": "owner-github-token",
        "SSH_AUTH_SOCK": "/tmp/agent.sock",  # noqa: S108 — фиктивный путь, не создаётся
    }
    env = guarded_spawn_env(base, active=False, isolation=_ISOLATION)
    assert env is not None
    assert env["PATH"] == "/usr/bin"
    for var in OWNER_CREDENTIAL_VARS:
        assert var not in env
    # И ни одно значение не переехало под другим именем.
    assert _OWNER_GH_TOKEN not in env.values()


def test_an_inherited_askpass_of_the_owner_is_replaced_not_kept() -> None:
    env = guarded_spawn_env(
        {"GIT_ASKPASS": "/opt/owner/askpass"}, active=False, isolation=_ISOLATION
    )
    assert env is not None
    assert env["GIT_ASKPASS"] == "/w/askpass-disabled"


def test_isolation_does_not_mutate_the_base_environment() -> None:
    base = {"GH_TOKEN": _OWNER_GH_TOKEN}
    guarded_spawn_env(base, active=True, isolation=_ISOLATION)
    assert base == {"GH_TOKEN": _OWNER_GH_TOKEN}


def test_the_push_barrier_alone_still_leaves_the_owners_credentials_in_place() -> None:
    # 🔴 Честная граница срезов: барьер bob-5ao кредов НЕ убирает (это и было дырой).
    env = guarded_spawn_env({"GH_TOKEN": _OWNER_GH_TOKEN}, active=True)
    assert env is not None
    assert env["GH_TOKEN"] == _OWNER_GH_TOKEN
    assert "GIT_CONFIG_GLOBAL" not in env


# --------------------------------------------------------------------------- #
# 🔴 Названная дыра: указатель на трекер owner'а ДОЕЗЖАЕТ до спавна (BOB-088, срез 2)
# --------------------------------------------------------------------------- #


def test_the_tracker_pointer_survives_the_purge_and_reaches_the_spawn() -> None:
    # 🔴 Прогоном, а не чтением списка вычищаемых: переменная, которую изоляция выдаёт и
    # тут же вычищает, была бы дырой ТОЛЬКО на бумаге — а конвейер молча остался бы без
    # ``bd``. Здесь та же склейка, что уедет в ``create_subprocess_exec``.
    env = guarded_spawn_env(
        {"PATH": "/usr/bin"},
        active=True,
        isolation=SpawnIsolation(
            config_global="/w/c",
            askpass="/w/a",
            ssh_identity="/w/i",
            beads_dir="/repo/.beads",
        ),
    )
    assert env is not None
    assert env["BEADS_DIR"] == "/repo/.beads"


def test_an_inherited_tracker_pointer_of_the_owner_is_replaced_by_ours() -> None:
    # Унаследованное значение решало бы, в КАКОЙ трекер пишет конвейер. Решает изоляция.
    env = guarded_spawn_env(
        {"BEADS_DIR": "/somewhere/else/.beads"},
        active=True,
        isolation=SpawnIsolation(
            config_global="/w/c",
            askpass="/w/a",
            ssh_identity="/w/i",
            beads_dir="/repo/.beads",
        ),
    )
    assert env is not None
    assert env["BEADS_DIR"] == "/repo/.beads"
