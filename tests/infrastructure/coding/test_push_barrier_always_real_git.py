# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-GIT: барьер push стоит ВСЕГДА, а не только под owner-ослаблением (bob-c3r.1).

Лечение P0 ``bob-l3t``. Барьер был привязан к ``coder.allow_bypass``
(``guard_push=allow_bypass``), то есть страховка от нечаянного push включалась ТОЛЬКО
вместе с ослаблением, которое её же обесценивает. В живом конфиге ослабления нет — значит
не было и барьера.

🔴 ГАРД СФОРМУЛИРОВАН КАК ПОВЕДЕНИЕ СОБРАННОЙ СИСТЕМЫ (``CLAUDE.md`` §0.3 п.12), а не как
форма кода. Берётся окружение, которое ПРОДАКШН-ПРОВОДКА при форме живого конфига отдаёт
процессу ``claude``, и этим окружением запускается НАСТОЯЩИЙ git push в одноразовом
репозитории. Проверка «в окружении есть нужный ключ» здесь не годится: она осталась бы
зелёной и при барьере, выставленном ПУСТЫМ значением, — ровно тот саботаж-обман, который
§0.3 п.12 требует ловить. Пустая заглушка настоящий push не остановит, и тест краснеет.

Фейк тут не доказательство и по §0.3 п.4: вся мера — это поведение НАСТОЯЩЕГО git при
подсунутом окружении.

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bob.coding.adapters._exec import ExecRunner
from bob.coding.adapters.git_clone import GitClone
from tests.support.wired_spawn_env import wired_spawn_envs

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

#: Схема URL-заглушки в тексте ошибки git («remote helper '<схема>' aborted session»).
_STUB_SCHEME = "bob-push-blocked"

#: Имена двух рантаймов в порядке, который отдаёт :func:`wired_spawn_envs`.
_RUNTIMES = ("одноразовый кодер", "живой терминал")


def _git(cwd: Path, *args: str) -> str:
    """Run a one-shot git command in ``cwd`` (test setup / assertions only)."""
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout


def _git_try(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run git allowing failure — the guarded calls are EXPECTED to fail."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=False, capture_output=True, text=True, env=env
    )


def _shipped_config(tmp_path: Path, **coder: object) -> dict[str, object]:
    """Форма ЖИВОГО конфига: кодер и интерактив включены, ослабления НЕТ.

    ``allow_bypass`` не задан сознательно — именно в этой форме барьера и не было.
    """
    return {
        "coder": {
            "enabled": True,
            "interactive": True,
            "clone_root": str(tmp_path / "clones"),
            **coder,
        }
    }


def _spawn_env(config: dict[str, object], runtime: int) -> dict[str, str]:
    env = wired_spawn_envs(config)[runtime]
    assert env is not None, "проводка отдала спавну claude окружение без единой меры"
    return env


@pytest.fixture
def repo_with_origin(tmp_path: Path) -> tuple[Path, Path]:
    """Одноразовый репозиторий с локальным bare-origin и веткой работы.

    Origin намеренно ``file://`` — это сетевой транспорт git, который барьер перехватывает
    наравне с ``https://`` и ``git@host:``, поэтому отказ наблюдаем без сети.
    """
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "-b", "main")

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    _git(work, "remote", "add", "origin", f"file://{bare}")
    (work / "README.md").write_text("public readme\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "initial tree on main")
    _git(work, "push", "-u", "origin", "main")
    # 🔴 Ещё один коммит ПОСЛЕ первого push: без него ``push HEAD:main`` — no-op
    # («Everything up-to-date», код 0), и тест был бы зелёным при снятом барьере.
    (work / "feature.py").write_text("print('claude edit')\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "claude work")
    return work, bare


# --------------------------------------------------------------------------- #
# Барьер стоит без единого owner-ослабления
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("runtime", range(len(_RUNTIMES)), ids=_RUNTIMES)
def test_the_shipped_wiring_blocks_a_real_push_from_every_claude_spawn(
    repo_with_origin: tuple[Path, Path], tmp_path: Path, runtime: int
) -> None:
    # 🔴 Суть среза: ослабления в конфиге нет, а push из спавна claude всё равно умирает.
    work, bare = repo_with_origin
    trunk_before = _git(bare, "rev-parse", "main").strip()

    result = _git_try(
        work,
        "push",
        "--force",
        "origin",
        "HEAD:main",
        env=_spawn_env(_shipped_config(tmp_path), runtime),
    )

    assert result.returncode != 0
    assert _STUB_SCHEME in result.stderr  # ошибка сама называет причину
    assert _git(bare, "rev-parse", "main").strip() == trunk_before


@pytest.mark.parametrize("runtime", range(len(_RUNTIMES)), ids=_RUNTIMES)
def test_the_barrier_stands_beside_the_clone_isolation_too(
    repo_with_origin: tuple[Path, Path], tmp_path: Path, runtime: int
) -> None:
    # Состояние после этого среза: изоляция клона ВКЛЮЧЕНА. Две меры живут в одном блоке
    # ``GIT_CONFIG_*``, поэтому «включили изоляцию — потеряли барьер» проверяется, а не
    # предполагается.
    work, bare = repo_with_origin
    trunk_before = _git(bare, "rev-parse", "main").strip()
    config = _shipped_config(tmp_path, isolated_clone=True)

    result = _git_try(
        work, "push", "--force", "origin", "HEAD:main", env=_spawn_env(config, runtime)
    )

    assert result.returncode != 0
    assert _STUB_SCHEME in result.stderr
    assert _git(bare, "rev-parse", "main").strip() == trunk_before


@pytest.mark.parametrize("runtime", range(len(_RUNTIMES)), ids=_RUNTIMES)
def test_the_barrier_survives_the_owner_relaxation_it_used_to_depend_on(
    repo_with_origin: tuple[Path, Path], tmp_path: Path, runtime: int
) -> None:
    # Развязка двусторонняя: барьер больше не ЗАВИСИТ от ``allow_bypass``, но и не
    # ИСЧЕЗАЕТ при нём — иначе лечение открыло бы дыру ровно там, где раньше была
    # единственная страховка.
    work, bare = repo_with_origin
    trunk_before = _git(bare, "rev-parse", "main").strip()
    config = _shipped_config(tmp_path, allow_bypass=True)

    result = _git_try(
        work, "push", "--force", "origin", "HEAD:main", env=_spawn_env(config, runtime)
    )

    assert result.returncode != 0
    assert _STUB_SCHEME in result.stderr
    assert _git(bare, "rev-parse", "main").strip() == trunk_before


# --------------------------------------------------------------------------- #
# Контроли: падение вызвано барьером, а не сломанным репозиторием
# --------------------------------------------------------------------------- #


def test_the_same_push_without_the_spawn_environment_succeeds(
    repo_with_origin: tuple[Path, Path],
) -> None:
    # Кусачесть харнесса: ровно та же команда в унаследованном окружении проходит.
    work, bare = repo_with_origin

    result = _git_try(work, "push", "origin", "HEAD:refs/heads/control")

    assert result.returncode == 0
    assert "control" in _git(bare, "branch", "--list")


def test_clearing_the_git_config_block_removes_the_barrier(
    repo_with_origin: tuple[Path, Path], tmp_path: Path
) -> None:
    # 🔴 Второй контроль И честная оговорка разом: блокирует именно блок ``GIT_CONFIG_*``,
    # а не прочее содержимое окружения — и процесс, владеющий своим окружением, снимает
    # его одной командой. Это страховка от нечаянного push, а не граница.
    work, bare = repo_with_origin
    env = _spawn_env(_shipped_config(tmp_path), 0) | {"GIT_CONFIG_COUNT": "0"}

    result = _git_try(work, "push", "origin", "HEAD:refs/heads/escaped", env=env)

    assert result.returncode == 0
    assert "escaped" in _git(bare, "branch", "--list")


# --------------------------------------------------------------------------- #
# 🔴 Собственный путь Боба барьер НЕ трогает (измерено, а не прочитано в докстроке)
# --------------------------------------------------------------------------- #


async def test_bobs_own_integration_path_still_pushes_his_branch(
    repo_with_origin: tuple[Path, Path], tmp_path: Path
) -> None:
    # Проверка перед развязкой (задача 2 беады): барьер живёт в окружении СПАВНА claude, а
    # интеграцию Боб делает в СВОЁМ процессе — ``GitClone`` через продакшн ``ExecRunner``,
    # который спавнит git без ``env=``. Утверждение докстроки измеряется здесь настоящим
    # git: та же ветка, тот же bare-origin, что барьер только что не пустил.
    work, bare = repo_with_origin
    clone = GitClone(
        tmp_path / "bob-clones",
        source=work,
        fork_url=f"file://{bare}",
        runner=ExecRunner(),
    )
    path = await clone.create("bob/task")
    (Path(path) / "feature.py").write_text("print('bob work')\n", encoding="utf-8")

    pushed = await clone.commit_and_push(path, "bob/task", "[bob] work")

    assert pushed is True
    assert _git(bare, "log", "-1", "bob/task", "--format=%s").strip() == "[bob] work"
