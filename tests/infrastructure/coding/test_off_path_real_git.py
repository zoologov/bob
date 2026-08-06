# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-GIT: OFF-путь BOB-089 доказан РАВЕНСТВОМ поведения, а не «похожестью».

Сборка OFF-пути (тип адаптера и его аргументы, ``None`` вместо окружения спавна, прежний
gh-путь интеграции) уже закреплена в ``tests/runtime/wiring/``. Здесь закрывается то, чего
сборкой не увидеть: **как ведёт себя настоящий git**, когда флаг выключен.

Два свойства, ни одно из которых не проверялось до этой волны:

* подпись ``bob[ai]`` в OFF-пути НЕ появляется — коммит в прежнем linked worktree
  подписан конфигурацией владельца, и в конфиге репозитория нет ни следа ботовской
  идентичности. Срез D ставит подпись внутри :class:`GitClone`, но убедиться в том, что
  она не протекла на прежнее рабочее место, можно только настоящим git: у ``worktree add``
  и ``clone`` разные правила, и «мы её там не вызываем» — это утверждение о коде, а не о
  поведении;
* прежний механизм остался прежним: linked worktree по-прежнему ДЕЛИТ ``.git`` с основным
  репозиторием. Это КОНТРОЛЬ, без которого ON-путь нечем мерить: именно из общего ``.git``
  растёт вектор ``update-ref refs/heads/main`` (живой в worktree — см.
  ``test_push_guard_real_git.py::test_the_guard_does_not_protect_local_refs_of_the_shared_git``,
  мёртвый в клоне — см. ``test_git_clone_real_git.py``). Если бы этот контроль позеленел
  «сам», сравнивать было бы не с чем.

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bob.coding.adapters._exec import ExecRunner
from bob.coding.adapters.git_worktree import GitWorktree

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

#: Продакшн-дефолт ``coder.worktree_root`` — ОТНОСИТЕЛЬНЫЙ, ровно как в конфиге.
_RELATIVE_ROOT = ".worktrees"
_BRANCH = "bob/task"


def _git(cwd: Path, *args: str) -> str:
    """Выполнить одноразовую git-команду в ``cwd`` (подготовка / утверждения)."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def owner_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Одноразовый репозиторий владельца; cwd внутри него — как у живого процесса Боба."""
    root = tmp_path / "owner-repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "owner@example.com")
    _git(root, "config", "user.name", "Owner")
    (root / "README.md").write_text("public readme\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial tracked tree")
    # Адаптер разрешает ОТНОСИТЕЛЬНЫЙ корень против cwd процесса, как живой бот (он
    # запускается из корня репозитория) — поэтому тест туда же и переходит.
    monkeypatch.chdir(root)
    return root


async def test_the_off_path_workplace_is_still_signed_by_the_owners_configuration(
    owner_repo: Path,
) -> None:
    # Коммит делается обычным git, без ``-c user.name`` и без переменных окружения: подпись
    # берётся ровно оттуда, куда её положил (или не положил) адаптер.
    path = Path(await GitWorktree(_RELATIVE_ROOT, runner=ExecRunner()).create(_BRANCH))
    (path / "feature.py").write_text("print('claude edit')\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "work in the previous workplace")

    assert _git(path, "log", "-1", "--format=%an").strip() == "Owner"
    assert _git(path, "log", "-1", "--format=%ae").strip() == "owner@example.com"


async def test_the_off_path_leaves_no_trace_of_bobs_identity_anywhere(
    owner_repo: Path,
) -> None:
    # Подпись Боба живёт ТОЛЬКО в конфиге клона (срез D). У linked worktree конфиг общий с
    # основным репозиторием, поэтому «протекла бы» она именно сюда.
    await GitWorktree(_RELATIVE_ROOT, runner=ExecRunner()).create(_BRANCH)

    assert "bob[ai]" not in (owner_repo / ".git" / "config").read_text(encoding="utf-8")
    assert _git(owner_repo, "config", "--local", "--get", "user.name").strip() == "Owner"


async def test_the_off_path_workplace_still_shares_the_repositorys_git(
    owner_repo: Path,
) -> None:
    # 🔴 КОНТРОЛЬ, а не свойство, которым мы гордимся: OFF-путь — это в точности прежний
    # механизм, общий ``.git`` и всё, что из него следует. Позеленей он «сам», ON-путь
    # (свой ``.git``, недостижимый main владельца) было бы нечем мерить.
    path = Path(await GitWorktree(_RELATIVE_ROOT, runner=ExecRunner()).create(_BRANCH))

    assert (path / ".git").is_file()  # у linked worktree это ФАЙЛ-указатель, не каталог
    shared = _git(path, "rev-parse", "--git-common-dir").strip()
    assert Path(path, shared).resolve() == (owner_repo / ".git").resolve()
