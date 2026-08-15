# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-GIT: рабочее место провизионируется под трекер — и это не ломает PR (BOB-088, срез 2).

Фейк здесь доказал бы контракт фейка: и запись ключа, и последующий отказ интеграции — это
поведение НАСТОЯЩЕГО git. Проверяется ровно то, что владелец увидел бы сам, открыв клон.

🔴 ВТОРОЙ ВХОД — главное в этом файле. Провизионирование состоит из ДВУХ решений в разных
модулях, и они обязаны не разъехаться:

1. ``git -C <клон> config --local beads.role maintainer`` при заведении места
   (:func:`bob.coding.clone_plan.tracker_argv`);
2. имя ``beads.role`` в ALLOW-списке локального конфига
   (:data:`bob.coding.untrusted_repo._ALLOWED_KEYS`), потому что перед интеграцией Боб
   ОТКАЗЫВАЕТСЯ идти в каталог, где лежит ключ, которого его собственная последовательность
   там не оставляла.

Сделай только первое — и всё выглядит рабочим: ключ на месте, ``bd`` доволен, тесты про
трекер зелёные. А конвейер отработает волну и умрёт НА ПУТИ К PR, отказавшись от
собственного провизионирования. Поэтому здесь оба утверждения стоят рядом.

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from bob.coding.adapters._exec import ExecRunner
from bob.coding.adapters.git_clone import CloneError, GitClone

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _git_try(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)


def _write(root: Path, relative: str, text: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@pytest.fixture
def owner_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Одноразовое хозяйство: рабочая копия владельца + bare-репозиторий «форка Боба»."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "owner@example.com")
    _git(work, "config", "user.name", "Owner")
    _write(work, "README.md", "public readme\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "initial tracked tree")

    fork = tmp_path / "fork.git"
    fork.mkdir()
    _git(fork, "init", "--bare", "-b", "main")
    return work, fork


def _adapter(tmp_path: Path, work: Path, *, fork_url: str = "") -> GitClone:
    return GitClone(
        tmp_path / "clones", source=work, fork_url=fork_url, runner=ExecRunner()
    )


# --------------------------------------------------------------------------- #
# Решение 1: роль записана — и записана В КЛОНЕ
# --------------------------------------------------------------------------- #


async def test_a_fresh_workplace_is_provisioned_with_the_tracker_role(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, _fork = owner_repo

    path = await _adapter(tmp_path, work).create("bob/task")

    assert _git(Path(path), "config", "--local", "--get", "beads.role").strip() == "maintainer"


async def test_a_long_lived_workplace_is_provisioned_too(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # Долгоживущее место — та самая дверь, которой открывается эпик; без роли конвейер
    # получал бы предупреждение ``bd`` на каждый из десятков вызовов за волну.
    work, _fork = owner_repo

    path = await _adapter(tmp_path, work).ensure("bob/epic-bob-088")

    assert _git(Path(path), "config", "--local", "--get", "beads.role").strip() == "maintainer"


async def test_the_role_is_never_written_into_the_owners_repository(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # 🔴 Та же граница, что у подписи (BOB-089.D): ``--local`` в КЛОНЕ. Глобальная запись
    # назначила бы роль владельцу в его собственном репозитории.
    work, _fork = owner_repo
    before = _git_try(work, "config", "--local", "--get", "beads.role").returncode

    await _adapter(tmp_path, work).create("bob/task")

    assert before != 0  # контроль: ключа не было и до нас
    assert _git_try(work, "config", "--local", "--get", "beads.role").returncode != 0


# --------------------------------------------------------------------------- #
# 🔴 Решение 2 (второй вход): собственное провизионирование не отменяет интеграцию
# --------------------------------------------------------------------------- #


async def test_the_provisioned_workplace_still_reaches_the_fork(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # Полный прод-путь: завести место (с ролью), поработать, довести ветку до форка. Ключ,
    # которого нет в ALLOW-списке, остановил бы ровно этот шаг — и конвейер умирал бы у
    # самого PR, из-за того что мы сами же дописали в его конфиг.
    work, fork = owner_repo
    adapter = _adapter(tmp_path, work, fork_url=f"file://{fork}")
    path = await adapter.create("bob/task")
    (Path(path) / "feature.py").write_text("print('claude edit')\n", encoding="utf-8")

    committed = await adapter.commit_and_push(path, "bob/task", "[bob] work")

    assert committed is True
    assert _git(fork, "log", "-1", "bob/task", "--format=%s").strip() == "[bob] work"


async def test_the_refusal_still_bites_on_a_key_we_never_write(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # 🔴 КОНТРОЛЬ к тесту выше (§0.3 п.5): ALLOW-список не стал пропускать ВСЁ подряд —
    # разрешено ровно ОДНО новое имя, и даже сосед по той же секции ``beads.*``
    # по-прежнему останавливает интеграцию, называя себя.
    work, fork = owner_repo
    adapter = _adapter(tmp_path, work, fork_url=f"file://{fork}")
    path = await adapter.create("bob/task")
    (Path(path) / "feature.py").write_text("print('claude edit')\n", encoding="utf-8")
    _git(Path(path), "config", "--local", "beads.autoflush", "false")

    with pytest.raises(CloneError, match=re.escape("beads.autoflush")):
        await adapter.commit_and_push(path, "bob/task", "[bob] work")
