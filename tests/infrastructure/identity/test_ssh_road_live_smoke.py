# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 ЖИВОЙ смоук ssh-дороги: git из окружения спавна не доходит до апстрима (bob-a6b.10).

Почему живой, а не только ``ssh -G``: разбор конфигурации показывает, ЧТО ssh собирается
сделать, а «здоровается ли GitHub как owner» — вердикт чужого сервера. Ровно этого и не
хватало в срезе C: изоляция была написана, документы обещали закрытую сетевую дорогу, а
``ssh -T git@github.com`` из прод-окружения спавна отвечал «Hi <owner>! You've successfully
authenticated», и ``git ls-remote`` апстрима по ssh проходил.

🔴 И вторая половина того же смоука — ЧЕСТНАЯ РАМКА, тоже исполняемая: прямой вызов ``ssh``
из того же окружения по-прежнему здоровается как owner. Это не забытый тест, а НАЗВАННОЕ
ограничение: ``~`` OpenSSH раскрывает по записи в passwd, а НЕ по ``HOME`` (проверено:
``HOME=<пустой каталог> ssh -T git@github.com`` здоровается), поэтому ключ owner'а
недостижимым окружением не сделать — закрывает это только раздельный UID (BOB-093). Пока
ограничение живо, тест обязан быть ЗЕЛЁНЫМ; когда оно закроется, он покраснеет и заставит
переписать обещание в доках, а не наоборот.

Смоук **opt-in**: без ``BOB_LIVE_GITHUB_SMOKE=1`` пропускается с явной причиной — сеть в
обычном прогоне и в CI не трогается. Что делает в сети: два ``ssh``-хендшейка и один
``git ls-remote`` (чтение), ни одного ref'а никуда не уезжает.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from bob.coding.push_guard import guarded_spawn_env
from bob.identity.adapters.spawn_isolation_files import SpawnIsolationFiles

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(
    shutil.which("ssh") is None or shutil.which("git") is None,
    reason="real ssh/git are not available on this host",
)

_OPT_IN = "BOB_LIVE_GITHUB_SMOKE"

#: Слаг апстрима берётся из той же переменной, которой Боб настроен читать апстрим.
_UPSTREAM_VAR = "BOB_GITHUB__PROPOSE_REPO"

#: Что печатает GitHub, узнав ключ owner'а. Появление этой строки там, где её быть не
#: должно, и есть дефект, из-за которого заведена беада.
_GREETING = "successfully authenticated"

#: Отказ ИМЕННО по ключу, а не «не разобрали адрес» и не «нет такого репозитория».
_REFUSED = "Permission denied (publickey)"


def _live() -> None:
    if os.environ.get(_OPT_IN) != "1":
        pytest.skip(f"живой смоук выключен: не задан {_OPT_IN}=1 (сеть не трогаем)")


def _isolated_env(tmp_path: Path) -> dict[str, str]:
    """Ровно прод-окружение спавна: ``os.environ`` + изоляция под флагом (без токена)."""
    isolation = SpawnIsolationFiles(tmp_path / ".spawn-env").materialize()
    env = guarded_spawn_env(os.environ, active=False, isolation=isolation)
    assert env is not None
    return env


def _run(argv: list[str], env: dict[str, str]) -> str:
    result = subprocess.run(
        argv,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return result.stdout + result.stderr


def _ssh_hello(env: dict[str, str]) -> str:
    return _run(["ssh", "-T", "-o", "BatchMode=yes", "git@github.com"], env)


def _upstream_ssh_url() -> str:
    slug = os.environ.get(_UPSTREAM_VAR, "").strip()
    if not slug:
        pytest.skip(f"живой смоук пропущен: в окружении нет {_UPSTREAM_VAR} (слаг апстрима)")
    return f"git@github.com:{slug}.git"


# --------------------------------------------------------------------------- #
# Контроль: ssh-дорога owner'а к апстриму РЕАЛЬНО существует
# --------------------------------------------------------------------------- #


def test_the_owners_ssh_key_really_opens_github() -> None:
    _live()

    output = _ssh_hello(dict(os.environ))

    if _GREETING not in output:
        pytest.skip(f"на этом хосте ssh не аутентифицируется на github: {output.strip()[:120]}")


def test_the_owners_ssh_key_really_reaches_the_upstream_repository() -> None:
    _live()
    url = _upstream_ssh_url()

    output = _run(["git", "ls-remote", url, "HEAD"], dict(os.environ))

    if "HEAD" not in output:
        pytest.skip(f"на этом хосте апстрим по ssh не читается: {output.strip()[:120]}")


# --------------------------------------------------------------------------- #
# 🔴 Изоляция: git по ssh до апстрима не доходит
# --------------------------------------------------------------------------- #


def test_git_over_ssh_is_refused_from_the_isolated_spawn_environment(tmp_path: Path) -> None:
    _live()
    url = _upstream_ssh_url()
    # Контроль и проверка различаются РОВНО окружением: тот же git, тот же адрес, тот же
    # транспорт. Иначе зелёный тест мог бы означать «до апстрима и так не дойти».
    assert "HEAD" in _run(["git", "ls-remote", url, "HEAD"], dict(os.environ))

    output = _run(["git", "ls-remote", url, "HEAD"], _isolated_env(tmp_path))

    assert _REFUSED in output
    assert _GREETING not in output


def test_the_controlled_ssh_command_itself_is_not_greeted_as_the_owner(tmp_path: Path) -> None:
    # Та же команда, которой git ходит по ssh, но вызванная напрямую: отказ приходит от
    # GitHub по ключу, а не от git по адресу.
    _live()
    env = _isolated_env(tmp_path)

    output = _run(["sh", "-c", f'{env["GIT_SSH_COMMAND"]} -T git@github.com'], env)

    assert _REFUSED in output
    assert _GREETING not in output


# --------------------------------------------------------------------------- #
# 🔴 ЧЕСТНАЯ РАМКА: что этой беадой НЕ закрыто (и чем закрывается)
# --------------------------------------------------------------------------- #


def test_a_raw_ssh_from_the_isolated_environment_still_greets_the_owner(tmp_path: Path) -> None:
    # 🔴 Ограничение НАЗВАНО, а не забыто: ключ owner'а лежит на диске под тем же UID, а
    # ``~`` ssh раскрывает по записи в passwd (не по ``HOME``), поэтому ПРЯМОЙ ``ssh`` из
    # спавна ключ находит. Закрыта git-дорога — та, по которой пойдут и нечаянный
    # ``git push``, и модель, «доделавшая задачу»; прямой ssh закрывает только раздельный
    # UID (BOB-093). Красный этот тест означает «ограничение снято» — тогда правится
    # обещание в доках, а не тест.
    _live()
    env = _isolated_env(tmp_path)
    if _GREETING not in _ssh_hello(dict(os.environ)):
        pytest.skip("на этом хосте ssh-дороги owner'а нет — ограничение нечем показать")

    assert _GREETING in _ssh_hello(env)
