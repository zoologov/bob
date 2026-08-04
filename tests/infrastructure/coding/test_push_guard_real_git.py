# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-GIT acceptance: барьер push из ослабленной песочницы (BOB-087.E, bob-5ao).

Фейк не моделирует git (урок BOB-084), а вся мера — это ПОВЕДЕНИЕ настоящего git при
подсунутом окружении. Поэтому здесь берётся ровно то окружение, которое продакшн-раннер
передаёт процессу ``claude`` при ``coder.allow_bypass``, и им запускается НАСТОЯЩИЙ git в
НАСТОЯЩЕМ linked worktree одноразового репозитория с локальным bare-origin.

Проверяется обе стороны договора:

* под барьером push не уходит — ни через имя remote, ни по прямому URL, ни из дочернего
  процесса; при этом fetch (чтение) продолжает работать;
* ШТАТНЫЙ путь Боба (:meth:`GitWorktree.commit_and_push` через продакшн ``ExecRunner``)
  работает как раньше — Боб пушит из СВОЕГО процесса, барьер живёт только в окружении
  claude.

🔴 И отдельным блоком — то, чего барьер НЕ закрывает (тесты-документация, чтобы никто не
принял страховку за границу): снятие переменных окружения возвращает push, а локальные
refs общего ``.git`` барьера вообще не касаются. Если эти тесты когда-нибудь упадут —
значит гарантия УСИЛИЛАСЬ, и оговорки в доках/конфиге надо переписать.

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters._exec import ExecRunner
from bob.coding.adapters.claude_runner import SubprocessClaudeRunner, _ExecStreamRunner
from bob.coding.adapters.git_worktree import GitWorktree

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

#: Схема URL-заглушки в тексте ошибки git («remote helper '<схема>' aborted session»).
_STUB_SCHEME = "bob-push-blocked"


def _git(cwd: Path, *args: str) -> str:
    """Run a one-shot git command in ``cwd`` (test setup / assertions only)."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _git_try(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run git allowing failure — the guarded calls are EXPECTED to fail."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _guarded_env() -> dict[str, str]:
    """Ровно то окружение, которое продакшн отдаёт claude при ``coder.allow_bypass``.

    Берётся не из тестовой копии политики, а из собранного продакшн-раннера — так тест
    проверяет всю цепочку «owner-флаг → раннер → окружение процесса».
    """
    runner = SubprocessClaudeRunner(allow_bypass=True)._runner
    assert isinstance(runner, _ExecStreamRunner)
    env = runner._env
    assert env is not None
    return env


@pytest.fixture
def worktree_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Одноразовый репозиторий: bare-origin + main + LINKED worktree на ``bob/task``.

    Возвращает ``(work, bare, wt)``. Origin намеренно задан как ``file://`` URL — это
    сетевой транспорт git, который барьер перехватывает, поэтому его отказ наблюдаем без
    сети (прод-origin Боба — ``git@github.com:…``, он покрыт тем же механизмом, см.
    отдельный тест про scp-подобный URL).
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

    wt = tmp_path / "wt"
    _git(work, "worktree", "add", str(wt), "-b", "bob/task")
    (wt / "feature.py").write_text("print('claude edit')\n", encoding="utf-8")
    _git(wt, "add", ".")
    _git(wt, "commit", "-m", "claude work")
    return work, bare, wt


# --------------------------------------------------------------------------- #
# Барьер держит: push из ослабленной песочницы не уходит
# --------------------------------------------------------------------------- #


def test_guarded_push_to_main_fails_and_the_trunk_does_not_move(
    worktree_repo: tuple[Path, Path, Path],
) -> None:
    _work, bare, wt = worktree_repo
    trunk_before = _git(bare, "rev-parse", "main").strip()

    result = _git_try(wt, "push", "--force", "origin", "HEAD:main", env=_guarded_env())

    assert result.returncode != 0
    assert _STUB_SCHEME in result.stderr  # ошибка сама называет причину
    assert _git(bare, "rev-parse", "main").strip() == trunk_before


def test_guarded_push_to_a_direct_url_fails(
    worktree_repo: tuple[Path, Path, Path],
) -> None:
    # Обход «в лоб»: не имя remote, а URL прямо в командной строке.
    _work, bare, wt = worktree_repo

    result = _git_try(
        wt, "push", "--force", f"file://{bare}", "HEAD:main", env=_guarded_env()
    )

    assert result.returncode != 0
    assert _STUB_SCHEME in result.stderr
    assert _git_try(bare, "rev-parse", "--verify", "refs/heads/main").stdout.strip() != (
        _git(wt, "rev-parse", "HEAD").strip()
    )


def test_guarded_push_to_a_freshly_added_remote_fails(
    worktree_repo: tuple[Path, Path, Path],
) -> None:
    # Обход «заведу свой remote» — барьер привязан к URL, а не к имени.
    _work, bare, wt = worktree_repo
    _git(wt, "remote", "add", "mine", f"file://{bare}")

    result = _git_try(wt, "push", "mine", "HEAD:refs/heads/sneak", env=_guarded_env())

    assert result.returncode != 0
    assert _STUB_SCHEME in result.stderr
    assert "sneak" not in _git(bare, "branch", "--list")


def test_guarded_push_to_an_ssh_style_github_url_never_leaves_the_machine(
    worktree_repo: tuple[Path, Path, Path],
) -> None:
    # Прод-форма origin — scp-подобный ``git@host:path``. Переписывание происходит ДО
    # любого обращения к сети, поэтому тест сетевой не становится.
    _work, _bare, wt = worktree_repo

    result = _git_try(
        wt, "push", "git@example.invalid:owner/repo.git", "HEAD:main", env=_guarded_env()
    )

    assert result.returncode != 0
    assert _STUB_SCHEME in result.stderr


def test_a_child_process_inherits_the_guard(
    worktree_repo: tuple[Path, Path, Path],
) -> None:
    # claude вызывает git не сам, а из шелла/подпроцессов — окружение наследуется.
    _work, bare, wt = worktree_repo
    trunk_before = _git(bare, "rev-parse", "main").strip()

    result = subprocess.run(
        ["/bin/sh", "-c", "git push --force origin HEAD:main"],
        cwd=wt,
        check=False,
        capture_output=True,
        text=True,
        env=_guarded_env(),
    )

    assert result.returncode != 0
    assert _STUB_SCHEME in result.stderr
    assert _git(bare, "rev-parse", "main").strip() == trunk_before


def test_reading_from_the_remote_still_works_under_the_guard(
    worktree_repo: tuple[Path, Path, Path],
) -> None:
    # Правится ТОЛЬКО push (``pushInsteadOf``): работа claude с историей не ломается.
    _work, _bare, wt = worktree_repo

    result = _git_try(wt, "fetch", "origin", env=_guarded_env())

    assert result.returncode == 0


# --------------------------------------------------------------------------- #
# Штатный путь Боба не сломан (барьер живёт ТОЛЬКО в окружении claude)
# --------------------------------------------------------------------------- #


async def test_bobs_own_commit_and_push_still_lands_the_feature_branch(
    worktree_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    # Как в проде: Боб пушит из СВОЕГО процесса через продакшн ExecRunner (без барьера),
    # после чего у ``gh pr create`` есть цель. Это и есть путь работы в main.
    _work, bare, wt = worktree_repo
    (wt / "more.py").write_text("print('more')\n", encoding="utf-8")
    adapter = GitWorktree(tmp_path / "roots", runner=ExecRunner())

    committed = await adapter.commit_and_push(str(wt), "bob/task", "[bob] work")

    assert committed is True
    assert _git(bare, "log", "-1", "bob/task", "--format=%s").strip() == "[bob] work"


def test_an_unguarded_push_from_the_same_worktree_succeeds(
    worktree_repo: tuple[Path, Path, Path],
) -> None:
    # Контроль «кусачести»: без барьера ровно та же команда проходит — значит падения
    # выше вызваны именно им, а не поломанным репозиторием.
    _work, bare, wt = worktree_repo

    result = _git_try(wt, "push", "origin", "HEAD:refs/heads/control")

    assert result.returncode == 0
    assert "control" in _git(bare, "branch", "--list")


# --------------------------------------------------------------------------- #
# 🔴 Чего барьер НЕ закрывает — зафиксировано исполняемо
# --------------------------------------------------------------------------- #


def test_clearing_the_environment_removes_the_guard(
    worktree_repo: tuple[Path, Path, Path],
) -> None:
    # 🔴 Фундаментальный предел: процесс работает под тем же UID и владеет своим
    # окружением. Одной команды достаточно — значит это страховка, а не граница.
    _work, bare, wt = worktree_repo
    env = _guarded_env() | {"GIT_CONFIG_COUNT": "0"}

    result = _git_try(wt, "push", "origin", "HEAD:refs/heads/escaped", env=env)

    assert result.returncode == 0
    assert "escaped" in _git(bare, "branch", "--list")


def test_an_explicit_pushurl_overrides_the_guard(
    worktree_repo: tuple[Path, Path, Path],
) -> None:
    # 🔴 Документированное поведение git: непустой ``remote.<name>.pushurl`` отменяет
    # ``pushInsteadOf``. Заглушка через сам ``pushurl`` не спасла бы — ключ многозначный,
    # env-значение лишь ДОБАВЛЯЕТСЯ, и git пушит во все URL сразу.
    _work, bare, wt = worktree_repo
    _git(wt, "remote", "set-url", "--push", "origin", f"file://{bare}")

    result = _git_try(wt, "push", "origin", "HEAD:refs/heads/viapushurl", env=_guarded_env())

    assert result.returncode == 0
    assert "viapushurl" in _git(bare, "branch", "--list")


def test_the_guard_does_not_protect_local_refs_of_the_shared_git(
    worktree_repo: tuple[Path, Path, Path],
) -> None:
    # 🔴 Совсем другой класс: linked worktree делит ``.git`` с основным репозиторием, и
    # ``update-ref`` двигает main ЛОКАЛЬНО, вообще не обращаясь к remote. Push-барьер
    # тут ни при чём — это закрывается только отдельным клоном/принципалом.
    work, _bare, wt = worktree_repo
    head = _git(wt, "rev-parse", "HEAD").strip()

    result = _git_try(wt, "update-ref", "refs/heads/main", head, env=_guarded_env())

    assert result.returncode == 0
    assert _git(work, "rev-parse", "main").strip() == head
