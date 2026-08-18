# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-GIT: на ДЕФОЛТЕ Боб получает настоящий клон, а не имя класса (bob-c3r.1).

Сборку («какой адаптер собран на конфиге без ключа») закрепляет
``tests/runtime/wiring/test_isolated_clone_is_the_default.py``. Здесь — то, чего сборкой не
увидеть и что фейком не доказать (§0.3 п.4): настоящий git заводит рабочее место, и у него
СВОЙ ``.git``, поэтому локальной дороги к стволу владельца (``update-ref refs/heads/main``)
из этого каталога не существует.

КОНТРОЛЬ рядом обязателен: при ЯВНОМ отказе (``isolated_clone: false``) то же место —
linked worktree, чей ``.git`` — ФАЙЛ-указатель в общий репозиторий, и та дорога жива. Без
этой пары зелёное выше означало бы лишь «в этом каталоге ничего не работает».

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bob.runtime.wiring.coding import _build_workspace
from tests.support.wired_spawn_env import wired_spawn_envs

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

_BRANCH = "bob/default-road"
_OWNER_GH_TOKEN = "ghp_owner_token_must_not_reach_the_spawn"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    """Одноразовый репозиторий-источник: из него поднимается рабочее место."""
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("public readme\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial tree on main")
    return repo


def _coder(tmp_path: Path, **extra: object) -> dict[str, object]:
    """Секция ``coder`` БЕЗ ключа ``isolated_clone``, если его не передали явно."""
    return {
        "enabled": True,
        "interactive": True,
        "clone_root": str(tmp_path / "clones"),
        "worktree_root": str(tmp_path / "worktrees"),
        **extra,
    }


async def test_the_default_road_raises_a_real_clone_with_its_own_git(
    source_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Источник клона — корень репозитория; на время теста им становится одноразовый.
    monkeypatch.setattr("bob.runtime.wiring.coding._REPO_ROOT", source_repo)
    workspace = _build_workspace(_coder(tmp_path))

    path = await workspace.create(_BRANCH)

    clone = Path(path)
    trunk_before = _git(source_repo, "rev-parse", "main").strip()
    assert (clone / ".git").is_dir()  # СВОЙ репозиторий, а не указатель в чужой
    assert _git(clone, "rev-parse", "--git-common-dir").strip() == ".git"
    assert _git(clone, "remote", "-v").strip() == ""  # без fork_url пушить некуда
    assert _git(clone, "branch", "--show-current").strip() == _BRANCH
    # Локальной дороги к стволу владельца нет: сдвиг main внутри клона его не трогает.
    head = _git(clone, "rev-parse", "HEAD").strip()
    _git(clone, "update-ref", "refs/heads/main", head)
    assert _git(source_repo, "rev-parse", "main").strip() == trunk_before


async def test_the_control_an_explicit_refusal_still_shares_the_owners_git(
    source_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 🔴 КОНТРОЛЬ: прежняя дорога жива и ведёт в ОБЩИЙ ``.git`` — есть с чем сравнивать.
    monkeypatch.chdir(source_repo)
    workspace = _build_workspace(_coder(tmp_path, isolated_clone=False))

    path = await workspace.create(_BRANCH)

    worktree = Path(path)
    head = _git(worktree, "rev-parse", "HEAD").strip()
    assert (worktree / ".git").is_file()  # указатель в общий репозиторий
    _git(worktree, "update-ref", "refs/heads/main", head)
    assert _git(source_repo, "rev-parse", "main").strip() == head  # ствол СДВИНУЛСЯ


def test_the_default_road_also_hides_the_owners_credentials_from_the_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Настоящий git отвечает на тот же вопрос, что задал бы push: какой credential.helper
    # он видит из окружения спавна. КОНТРОЛЬ — тот же вопрос при явном отказе.
    monkeypatch.setenv("GH_TOKEN", _OWNER_GH_TOKEN)
    default_env = wired_spawn_envs({"coder": _coder(tmp_path)})[0]
    control_env = wired_spawn_envs({"coder": _coder(tmp_path, isolated_clone=False)})[0]
    assert default_env is not None
    assert control_env is not None

    seen = subprocess.run(
        ["git", "config", "--get-all", "credential.helper"],
        cwd=tmp_path,
        env=default_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert seen.stdout.strip() == ""
    assert "GH_TOKEN" not in default_env
    assert control_env["GH_TOKEN"] == _OWNER_GH_TOKEN
