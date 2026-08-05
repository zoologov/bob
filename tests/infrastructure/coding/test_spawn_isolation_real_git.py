# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-GIT acceptance: спавн не достаёт кредов owner'а (BOB-089, срез C).

Фейк здесь доказал бы контракт фейка (уроки BOB-084, BOB-087.D5b/c): всё содержание среза —
это ПОВЕДЕНИЕ настоящего git, а именно то, как он собирает список credential-хелперов из
системного, глобального, локального и env-конфига и в каком порядке их спрашивает.

Каждый тест устроен как ПАРА: сначала контроль — «дорога к кредам owner'а РЕАЛЬНО есть»
(без него зелёный тест доказывал бы лишь, что кредов не было и так), затем тот же вызов в
изолированном окружении. Три независимые дороги проверяются отдельно, потому что закрыты
они РАЗНЫМИ механизмами:

* helper в СИСТЕМНОМ конфиге (на машине owner'а это ``osxkeychain``) — закрыт
  ``GIT_CONFIG_NOSYSTEM``, потому что ``GIT_CONFIG_GLOBAL`` его не замещает;
* helper в ГЛОБАЛЬНОМ конфиге owner'а — закрыт подменой ``GIT_CONFIG_GLOBAL``;
* helper, объявленный прямо в ОКРУЖЕНИИ (``GIT_CONFIG_KEY_i``) — закрыт сбросом списка,
  который встаёт ПОСЛЕ пар owner'а.

🔴 Хост в тестах — заведомо несуществующий ``.invalid``: настоящий ``github.com`` заставил
бы системный ``osxkeychain`` отвечать НАСТОЯЩИМИ кредами owner'а, чего в тестах быть не
должно. Сеть не трогается ни одним тестом файла.

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from bob.coding.push_guard import PUSH_GUARD_STUB_URL, guarded_spawn_env
from bob.identity.adapters.spawn_isolation_files import SpawnIsolationFiles

if TYPE_CHECKING:
    from pathlib import Path

    from bob.identity.spawn_isolation import SpawnIsolation

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

#: Хост, которого нет в DNS: ни один тест файла не может случайно уйти в сеть или в
#: keychain owner'а за настоящими кредами.
_PROBE_HOST = "bob-isolation-probe.invalid"

#: Пароль «owner'а»: если он появился в выводе, значит спавн дотянулся до чужих кредов.
_OWNER_SECRET = "OWNERSECRET"  # noqa: S105 — фиктивный «пароль» контрольной дороги

#: Токен «Боба»: с ним, и только с ним, изолированный спавн имеет право работать.
_BOB_TOKEN = "ghs_bobs_installation_token"  # noqa: S105 — фиктивный токен

_OWNER_HELPER = (
    '"!f() { echo username=owner; echo password=' + _OWNER_SECRET + '; }; f"'
)


def _helper_config(path: Path) -> Path:
    """Написать конфиг git с helper'ом owner'а и вернуть его путь."""
    path.write_text(f"[credential]\n\thelper = {_OWNER_HELPER}\n", encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Одноразовый репозиторий: ``git credential`` работает внутри репозитория."""
    work = tmp_path / "clone"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=work, check=True)
    return work


@pytest.fixture
def owner_env(tmp_path: Path) -> dict[str, str]:
    """Окружение «как у owner'а»: helper и в системном, и в глобальном конфиге.

    Системный конфиг подставляется через ``GIT_CONFIG_SYSTEM`` — это точная модель факта,
    найденного на машине owner'а: ``credential.helper = osxkeychain`` живёт именно в
    системном файле (``/opt/homebrew/etc/gitconfig``), и подмена глобального его не
    убирает.
    """
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path / "home"),
        "GIT_CONFIG_SYSTEM": str(_helper_config(tmp_path / "systemconfig")),
        "GIT_CONFIG_GLOBAL": str(_helper_config(tmp_path / "ownerconfig")),
    }


def _isolation(tmp_path: Path, *, token: str = "") -> SpawnIsolation:
    """Материализовать изоляцию в одноразовом каталоге (с токеном Боба или без)."""
    return SpawnIsolationFiles(tmp_path / "spawn-env").materialize(
        fork_url=f"https://{_PROBE_HOST}/bobiverse-dev/bob.git", token=token
    )


def _fill(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Спросить у git креды для ``https://<probe-host>`` в окружении ``env``.

    ``git credential fill`` — это ровно тот механизм, которым пользуется ``git push``:
    что ответит он, то получил бы и push, только без сети.
    """
    return subprocess.run(
        ["git", "credential", "fill"],
        cwd=repo,
        env=env,
        input=f"protocol=https\nhost={_PROBE_HOST}\n\n",
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


# --------------------------------------------------------------------------- #
# Контроль: дорога к кредам owner'а РЕАЛЬНО есть (иначе тесты ниже — вакуум)
# --------------------------------------------------------------------------- #


def test_without_isolation_the_owners_helper_hands_over_his_password(
    repo: Path, owner_env: dict[str, str]
) -> None:
    result = _fill(repo, owner_env)

    assert result.returncode == 0
    assert f"password={_OWNER_SECRET}" in result.stdout


def test_the_push_barrier_alone_leaves_that_road_open(
    repo: Path, owner_env: dict[str, str]
) -> None:
    # 🔴 Честная граница срезов: барьер bob-5ao (bob-5ao/BOB-087.E) переписывает push-URL,
    # но кредов не убирает — сетевая дорога к апстриму оставалась живой.
    env = guarded_spawn_env(owner_env, active=True)
    assert env is not None

    result = _fill(repo, env)

    assert f"password={_OWNER_SECRET}" in result.stdout


# --------------------------------------------------------------------------- #
# 🔴 Изоляция: ни одна из трёх дорог к кредам owner'а не отвечает
# --------------------------------------------------------------------------- #


def test_the_isolated_spawn_gets_no_credentials_at_all(
    repo: Path, owner_env: dict[str, str], tmp_path: Path
) -> None:
    env = guarded_spawn_env(owner_env, active=False, isolation=_isolation(tmp_path))
    assert env is not None

    result = _fill(repo, env)

    assert result.returncode != 0
    assert _OWNER_SECRET not in result.stdout
    assert "password=" not in result.stdout
    # Отказ приходит от ОТСУТСТВИЯ кредов, а не от зависшего запроса пароля.
    assert "terminal prompts disabled" in result.stderr


def test_the_system_config_road_is_closed_too(
    repo: Path, owner_env: dict[str, str], tmp_path: Path
) -> None:
    # Только системный helper (глобального нет вовсе) — та самая дорога, которую
    # ``GIT_CONFIG_GLOBAL`` НЕ закрывает.
    only_system = dict(owner_env)
    only_system["GIT_CONFIG_GLOBAL"] = str(tmp_path / "absent-global")

    assert f"password={_OWNER_SECRET}" in _fill(repo, only_system).stdout  # контроль

    env = guarded_spawn_env(only_system, active=False, isolation=_isolation(tmp_path))
    assert env is not None
    assert _OWNER_SECRET not in _fill(repo, env).stdout


def test_a_helper_declared_in_the_owners_environment_is_reset(
    repo: Path, owner_env: dict[str, str], tmp_path: Path
) -> None:
    # 🔴 Порядок пар: сброс обязан встать ПОСЛЕ пар owner'а, иначе его helper снова первый
    # в списке и снова отвечает.
    in_env = dict(owner_env)
    in_env["GIT_CONFIG_COUNT"] = "1"
    in_env["GIT_CONFIG_KEY_0"] = "credential.helper"
    in_env["GIT_CONFIG_VALUE_0"] = _OWNER_HELPER.strip('"')

    assert f"password={_OWNER_SECRET}" in _fill(repo, in_env).stdout  # контроль

    env = guarded_spawn_env(in_env, active=False, isolation=_isolation(tmp_path))
    assert env is not None
    assert _OWNER_SECRET not in _fill(repo, env).stdout


def test_a_helper_in_the_repositorys_own_config_is_reset(
    repo: Path, owner_env: dict[str, str], tmp_path: Path
) -> None:
    # Локальный конфиг клона — четвёртая дорога: env-сброс читается git'ом последним и
    # гасит и её.
    subprocess.run(
        ["git", "config", "--local", "credential.helper", _OWNER_HELPER.strip('"')],
        cwd=repo,
        check=True,
    )

    assert f"password={_OWNER_SECRET}" in _fill(repo, owner_env).stdout  # контроль

    env = guarded_spawn_env(owner_env, active=False, isolation=_isolation(tmp_path))
    assert env is not None
    assert _OWNER_SECRET not in _fill(repo, env).stdout


def test_stripping_the_env_config_block_from_inside_still_leaves_no_credentials(
    repo: Path, owner_env: dict[str, str], tmp_path: Path
) -> None:
    # 🔴 Известный обход мер, живущих в окружении: ``GIT_CONFIG_COUNT=0`` изнутри снимает
    # весь блок пар (проверено на bob-5ao против барьера push'а). Здесь он снимает и наш
    # сброс хелперов — и креды owner'а всё равно не отвечают, потому что подменный
    # global-конфиг несёт тот же сброс ФАЙЛОМ. Второй слой существует ровно для этого.
    env = guarded_spawn_env(owner_env, active=True, isolation=_isolation(tmp_path))
    assert env is not None
    stripped = {**env, "GIT_CONFIG_COUNT": "0"}

    result = _fill(repo, stripped)

    assert _OWNER_SECRET not in result.stdout
    assert "password=" not in result.stdout


def test_the_owners_askpass_helper_is_not_used_either(
    repo: Path, owner_env: dict[str, str], tmp_path: Path
) -> None:
    # Вторая механика выдачи пароля в git — ``GIT_ASKPASS``. Без подмены исполняемый
    # askpass owner'а отвечал бы вместо хелпера.
    askpass = tmp_path / "owner-askpass.sh"
    askpass.write_text(f"#!/bin/sh\necho {_OWNER_SECRET}\n", encoding="utf-8")
    askpass.chmod(0o700)
    with_askpass = dict(owner_env)
    with_askpass["GIT_CONFIG_SYSTEM"] = str(tmp_path / "absent-system")
    with_askpass["GIT_CONFIG_GLOBAL"] = str(tmp_path / "absent-global")
    with_askpass["GIT_ASKPASS"] = str(askpass)

    assert _OWNER_SECRET in _fill(repo, with_askpass).stdout  # контроль

    env = guarded_spawn_env(with_askpass, active=False, isolation=_isolation(tmp_path))
    assert env is not None
    result = _fill(repo, env)
    assert _OWNER_SECRET not in result.stdout
    # «В никуда» — это буквально несуществующий путь, и git это честно печатает.
    assert "cannot exec" in result.stderr


# --------------------------------------------------------------------------- #
# Легитимный путь: с токеном БОБА тот же механизм креды отдаёт
# --------------------------------------------------------------------------- #


def test_bobs_own_token_is_what_the_isolated_spawn_gets(
    repo: Path, owner_env: dict[str, str], tmp_path: Path
) -> None:
    env = guarded_spawn_env(
        owner_env, active=False, isolation=_isolation(tmp_path, token=_BOB_TOKEN)
    )
    assert env is not None

    result = _fill(repo, env)

    assert result.returncode == 0
    assert f"password={_BOB_TOKEN}" in result.stdout
    assert "username=x-access-token" in result.stdout
    # 🔴 И именно вместо кредов owner'а, а не вдобавок к ним.
    assert _OWNER_SECRET not in result.stdout


def test_bobs_token_never_appears_in_the_process_arguments(
    repo: Path, owner_env: dict[str, str], tmp_path: Path
) -> None:
    # Токен приезжает файлом; в окружении есть только ПУТЬ к нему (argv виден в ``ps``).
    env = guarded_spawn_env(
        owner_env, active=False, isolation=_isolation(tmp_path, token=_BOB_TOKEN)
    )
    assert env is not None

    assert not any(_BOB_TOKEN in value for value in env.values())


# --------------------------------------------------------------------------- #
# Два слоя вместе: барьер push'а остаётся вторым слоем
# --------------------------------------------------------------------------- #


def test_the_push_barrier_still_bites_under_isolation(
    repo: Path, owner_env: dict[str, str], tmp_path: Path
) -> None:
    env = guarded_spawn_env(
        owner_env, active=True, isolation=_isolation(tmp_path, token=_BOB_TOKEN)
    )
    assert env is not None
    signature = {
        "GIT_AUTHOR_NAME": "bob[ai]",
        "GIT_AUTHOR_EMAIL": "bob@example.invalid",
        "GIT_COMMITTER_NAME": "bob[ai]",
        "GIT_COMMITTER_EMAIL": "bob@example.invalid",
    }
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "work"],
        cwd=repo,
        check=True,
        env={**env, **signature},
    )

    result = subprocess.run(
        ["git", "push", f"https://{_PROBE_HOST}/zoologov/bob.git", "HEAD:refs/heads/main"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode != 0
    # Барьер отработал ДО сети: имя схемы-заглушки само объясняет отказ.
    stub_scheme = PUSH_GUARD_STUB_URL.split("://")[0]
    assert stub_scheme in result.stderr
