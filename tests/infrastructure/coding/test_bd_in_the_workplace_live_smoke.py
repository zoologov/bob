# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 ЖИВОЙ СМОУК: настоящий ``bd`` из настоящего рабочего места Боба (BOB-088, срез 2).

Весь конвейер BOB-088 стоит на трекере: волна берёт беаду, оставляет чекпоинты и закрывает
работу. Срез 1 сделал рабочее место КЛОНОМ — и этим доступ к трекеру сломал: из клона
``bd`` не находит базу вовсе. Тест на фейке доказал бы контракт фейка (§0.3 п.4), поэтому
здесь всё настоящее: настоящий ``git clone`` продакшн-адаптером, настоящий ``bd``,
настоящая база (одноразовая, ``bd init`` в tmp — трекер владельца не трогается) и то самое
окружение, которое продакшн-шов отдаёт спавну ``claude``.

Утверждается ПАРА, и порознь ни одна половина ничего не стоит:

* КОНТРОЛЬ — из рабочего места БЕЗ указателя на трекер ``bd`` отказывает («no beads
  database found»). Без этого утверждения «с указателем работает» означало бы лишь, что
  ``bd`` работает где угодно;
* ПРЕДМЕТ — с продакшн-окружением ``bd`` из того же места видит ТУ ЖЕ базу и делает это
  МОЛЧА: провизионирование ``beads.role`` (:func:`bob.coding.clone_plan.tracker_argv`)
  снимает предупреждение GH#2950, которое иначе печатается на каждый из десятков вызовов
  за волну.

Skips with a clear reason when ``git`` / ``bd`` is unavailable.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from bob.coding.adapters._exec import ExecRunner
from bob.coding.adapters.git_clone import GitClone
from bob.coding.push_guard import guarded_spawn_env
from bob.identity.adapters.spawn_isolation_files import SpawnIsolationFiles

pytestmark = [
    pytest.mark.skipif(
        shutil.which("git") is None, reason="real git is not available on this host"
    ),
    pytest.mark.skipif(
        shutil.which("bd") is None, reason="the real bd CLI is not available on this host"
    ),
    pytest.mark.slow,
]

#: Строка, которой ``bd`` сообщает, что базы он не нашёл (снята с настоящего ``bd`` 1.0.4).
_NO_DATABASE = "no beads database found"

#: Предупреждение, которое ``bd`` печатает, пока роль не названа (GH#2950, дословно).
_NO_ROLE_WARNING = "beads.role not configured"

#: Маячок в одноразовой базе: по нему видно, что дотянулись ИМЕННО до неё.
_BEACON = "маячок живого смоука BOB-088"

#: Потолок на один вызов инструмента: он локальный, а тест не имеет права висеть.
_BD_TIMEOUT_S = 45


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _bd(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Позвать НАСТОЯЩИЙ ``bd`` в ``cwd`` (окружение — как у спавна, если задано)."""
    return subprocess.run(
        ["bd", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=_BD_TIMEOUT_S,
    )


@pytest.fixture(scope="module")
def throwaway_tracker(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Одноразовая база beads: ``bd init`` в своём репозитории (не трекер владельца)."""
    root = tmp_path_factory.mktemp("tracker")
    _git(root, "init", "-b", "main")
    created = subprocess.run(
        ["bd", "init", "--prefix", "smoke"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if created.returncode != 0:  # pragma: no cover — среда без рабочего bd
        pytest.skip(f"bd init failed on this host: {created.stderr.strip()[:200]}")
    # Маячок: по нему видно, что рабочее место дотянулось ИМЕННО до этой базы, а не просто
    # «до какой-то». Заводится ЗДЕСЬ, в репозитории трекера, а читается — из клона.
    marked = _bd(root, "create", _BEACON)
    if marked.returncode != 0:  # pragma: no cover — среда без рабочего bd
        pytest.skip(f"bd create failed on this host: {marked.stderr.strip()[:200]}")
    return root / ".beads"


@pytest.fixture
def workplace(tmp_path: Path) -> Path:
    """Настоящее рабочее место Боба: клон, заведённый ПРОДАКШН-адаптером."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "owner@example.com")
    _git(work, "config", "user.name", "Owner")
    (work / "README.md").write_text("public readme\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "initial tracked tree")
    clone = GitClone(tmp_path / "clones", source=work, runner=ExecRunner())
    return Path(asyncio.run(clone.create("bob/task")))


def _spawn_env(tmp_path: Path, *, beads_dir: str) -> dict[str, str]:
    """Ровно тот шов окружения, которым продакшн собирает спавн ``claude``."""
    isolation = SpawnIsolationFiles(tmp_path / "spawn-env").materialize(beads_dir=beads_dir)
    env = guarded_spawn_env(os.environ, active=True, isolation=isolation)
    assert env is not None
    return env


def test_without_the_pointer_the_workplace_cannot_reach_the_tracker_at_all(
    workplace: Path, tmp_path: Path
) -> None:
    # 🔴 КОНТРОЛЬ. Ровно это и нашлось замером после среза 1: у клона свой пустой ``.beads``
    # (Dolt-каталог gitignored и в клон не попадает), а подъём вверх упирается в него же.
    result = _bd(workplace, "list", env=_spawn_env(tmp_path, beads_dir=""))

    assert result.returncode != 0
    assert _NO_DATABASE in (result.stderr + result.stdout)


def test_with_the_production_environment_bd_sees_the_tracker_and_says_nothing_extra(
    workplace: Path, tmp_path: Path, throwaway_tracker: Path
) -> None:
    result = _bd(workplace, "list", env=_spawn_env(tmp_path, beads_dir=str(throwaway_tracker)))

    assert result.returncode == 0, result.stderr
    assert _NO_DATABASE not in (result.stderr + result.stdout)
    # И это ТА САМАЯ база: в выводе виден маячок, заведённый в одноразовом трекере.
    assert _BEACON in result.stdout
    # 🔴 Вторая половина провизионирования: молча. Роль записана в конфиг КЛОНА самим
    # адаптером, поэтому предупреждения GH#2950 в потоке волны нет.
    assert _NO_ROLE_WARNING not in result.stderr


def test_the_role_warning_is_what_the_provisioning_actually_silences(
    workplace: Path, tmp_path: Path, throwaway_tracker: Path
) -> None:
    # 🔴 КОНТРОЛЬ к утверждению «молча» (§0.3 п.5): снимаем роль, которую записал адаптер, —
    # и предупреждение возвращается дословно. Без этого «в stderr пусто» ничего не
    # доказывало бы: пусто было бы и у ``bd``, который так не предупреждает вовсе.
    subprocess.run(
        ["git", "config", "--local", "--unset", "beads.role"],
        cwd=workplace,
        check=True,
        capture_output=True,
        text=True,
    )

    result = _bd(workplace, "list", env=_spawn_env(tmp_path, beads_dir=str(throwaway_tracker)))

    assert result.returncode == 0, result.stderr
    assert _NO_ROLE_WARNING in result.stderr
