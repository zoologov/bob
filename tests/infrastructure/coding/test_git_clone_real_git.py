# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-GIT acceptance: рабочее место Боба — отдельный КЛОН (BOB-089, срез A).

Фейк здесь доказал бы контракт фейка (уроки BOB-084, BOB-087.D5b/c): всё содержание
среза — это ПОВЕДЕНИЕ настоящего git. У ``git clone`` иные правила, чем у ``git worktree
add``, поэтому приватность клона доказывается, а не предполагается: содержимое каталога
перечисляется целиком и сверяется с трекнутыми файлами.

Проверяется пять вещей, каждая — на настоящем git в одноразовом репозитории, который
повторяет гитигнор Боба (``data/``, ``bob.db*``, ``.env*``, ``config/bob.yaml``,
``.secrets/``):

* приватность: в клоне НЕТ приватных данных Боба, только трекнутые файлы;
* изоляция: у клона свой ``.git``, свои объекты (ни хардлинков, ни alternates) и свои
  refs — ``update-ref refs/heads/main`` внутри клона не двигает main owner'а (ровно тот
  вектор, который проходит в linked worktree, см. ``test_push_guard_real_git.py``);
* адресация: origin переписан на форк (или удалён вовсе), рабочая копия owner'а не
  остаётся адресом для push, апстрим не прописан;
* штатный путь: ``ensure`` переиспользует место (работа накапливается), а
  ``commit_and_push`` доводит ветку до форка;
* 🔴 честная рамка (bob-a6b.5): что клон НЕ закрывает — путь к репозиторию владельца
  остаётся читаемым в reflog клона, а процесс под тем же UID доводит намеренную дорогу до
  ствола в три шага. Мера описана вместе с её границей, иначе доки обещают больше прав, чем
  есть.

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bob.coding.adapters._exec import ExecRunner
from bob.coding.adapters.git_clone import CloneError, GitClone
from bob.coding.ports import PersistentWorkspace, Worktree

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

#: Приватные данные Боба — то, чего в клоне быть не должно ни при каких обстоятельствах.
_PRIVATE_FILES = (
    "data/soul/self_model.md",
    "bob.db",
    "bob.db-wal",
    ".env",
    ".env.local",
    "config/bob.yaml",
    ".secrets/bob-ai-work.pem",
)

#: Трекнутые файлы — ровно они и составляют рабочее место.
_TRACKED_FILES = (
    ".gitignore",
    "README.md",
    "config/bob.example.yaml",
    "src/bob/app.py",
)

_GITIGNORE = """\
data/
bob.db*
.env
.env.*
config/bob.yaml
.secrets/
"""


def _git(cwd: Path, *args: str) -> str:
    """Run a one-shot git command in ``cwd`` (test setup / assertions only)."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _git_try(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git allowing failure (used where the failure IS the assertion)."""
    return subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)


def _write(root: Path, relative: str, text: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _tree_of(root: Path) -> set[str]:
    """Перечислить ВСЁ содержимое рабочего дерева (без ``.git``) — как ``find``.

    Именно перечисление, а не проверка нескольких известных путей: приватный файл, о
    котором тест не догадался спросить, всё равно попадёт в это множество.
    """
    return {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


@pytest.fixture
def owner_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Одноразовое «хозяйство owner'а»: репозиторий с приватными данными + bare-форк.

    Возвращает ``(work, fork)``. ``work`` — рабочая копия owner'а на ``main`` (её и
    клонирует адаптер), ``fork`` — bare-репозиторий, играющий роль форка Боба.
    """
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "owner@example.com")
    _git(work, "config", "user.name", "Owner")
    _write(work, ".gitignore", _GITIGNORE)
    _write(work, "README.md", "public readme\n")
    _write(work, "config/bob.example.yaml", "coder:\n  enabled: false\n")
    _write(work, "src/bob/app.py", "def main() -> None: ...\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "initial tracked tree")
    for private in _PRIVATE_FILES:
        _write(work, private, f"SECRET {private}\n")

    fork = tmp_path / "fork.git"
    fork.mkdir()
    _git(fork, "init", "--bare", "-b", "main")
    return work, fork


def _adapter(
    tmp_path: Path, work: Path, *, fork_url: str = "", app_user_id: str = ""
) -> GitClone:
    return GitClone(
        tmp_path / "clones",
        source=work,
        fork_url=fork_url,
        app_user_id=app_user_id,
        runner=ExecRunner(),
    )


def _config_of(scope: str, cwd: Path) -> list[str | None]:
    """Прочитать имя и e-mail в области ``scope`` (``--global`` / ``--local``).

    ``None`` — «ключ не задан»: отличать «не задан» от «задан пустым» тут обязательно,
    иначе сравнение «до/после» прошло бы и в случае, когда настройка ПОЯВИЛАСЬ.
    """
    values: list[str | None] = []
    for key in ("user.name", "user.email"):
        result = _git_try(cwd, "config", scope, "--get", key)
        values.append(result.stdout.strip() if result.returncode == 0 else None)
    return values


# --------------------------------------------------------------------------- #
# 🔴 Приватность — ДОКАЗАННАЯ перечислением, а не предположенная
# --------------------------------------------------------------------------- #


async def test_the_clone_holds_exactly_the_tracked_files_and_nothing_else(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, _fork = owner_repo
    # Контроль: приватные данные РЕАЛЬНО лежат в репозитории owner'а — иначе тест
    # доказывал бы лишь то, что их там не было.
    assert (work / ".env").exists()
    assert (work / ".secrets/bob-ai-work.pem").exists()

    path = await _adapter(tmp_path, work).create("bob/task")

    assert _tree_of(Path(path)) == set(_TRACKED_FILES)


async def test_no_private_path_of_bob_reaches_the_clone(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, _fork = owner_repo

    path = await _adapter(tmp_path, work).create("bob/task")

    for private in _PRIVATE_FILES:
        assert not (Path(path) / private).exists(), private


async def test_uncommitted_owner_work_does_not_leak_into_the_clone(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # Клон везёт ОБЪЕКТЫ, а не рабочее дерево: незакоммиченная правка owner'а остаётся
    # у owner'а (у ``worktree add`` тут то же свойство, но проверить надо на клоне).
    work, _fork = owner_repo
    (work / "README.md").write_text("draft the owner has not committed\n", encoding="utf-8")

    path = await _adapter(tmp_path, work).create("bob/task")

    assert (Path(path) / "README.md").read_text(encoding="utf-8") == "public readme\n"


# --------------------------------------------------------------------------- #
# 🔴 Изоляция — свой .git, свои объекты, свои refs
# --------------------------------------------------------------------------- #


async def test_the_clone_owns_its_git_directory(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, _fork = owner_repo

    path = await _adapter(tmp_path, work).create("bob/task")

    # У linked worktree ``.git`` — ФАЙЛ-указатель на общий каталог; у клона — свой каталог.
    assert (Path(path) / ".git").is_dir()
    common = _git(Path(path), "rev-parse", "--absolute-git-dir").strip()
    assert Path(common).resolve() == (Path(path) / ".git").resolve()
    assert _git(work, "rev-parse", "--absolute-git-dir").strip() != common


async def test_the_clone_shares_no_object_storage_with_the_owners_repository(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # 🔴 Голый локальный путь заставил бы git ХАРДЛИНКОВАТЬ файлы объектов — общее
    # хранилище с репозиторием owner'а. ``file://`` этого не делает; проверяем фактом:
    # ни alternates, ни файла объектов со счётчиком ссылок > 1.
    work, _fork = owner_repo

    path = await _adapter(tmp_path, work).create("bob/task")

    objects = Path(path) / ".git" / "objects"
    assert not (objects / "info" / "alternates").exists()
    shared = [
        str(item.relative_to(objects))
        for item in objects.rglob("*")
        if item.is_file() and item.stat().st_nlink > 1
    ]
    assert shared == []


async def test_moving_main_inside_the_clone_leaves_the_owners_main_untouched(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # 🔴 ЭТО ГЛАВНЫЙ ТЕСТ СРЕЗА. В linked worktree ровно эта команда двигает main
    # owner'а — без сети, без кредов, мимо любого push-барьера (проверено bob-5ao,
    # зафиксировано в test_push_guard_real_git.py). В клоне она двигает ЧУЖОЙ ref.
    work, _fork = owner_repo
    trunk_before = _git(work, "rev-parse", "main").strip()
    path = await _adapter(tmp_path, work).create("bob/task")
    (Path(path) / "feature.py").write_text("print('claude edit')\n", encoding="utf-8")
    _git(Path(path), "add", ".")
    _git(Path(path), "commit", "-m", "claude work")
    head = _git(Path(path), "rev-parse", "HEAD").strip()

    result = _git_try(Path(path), "update-ref", "refs/heads/main", head)

    assert result.returncode == 0  # внутри своего репозитория это законная операция
    assert _git(Path(path), "rev-parse", "main").strip() == head  # сдвинулся ЕГО main
    assert _git(work, "rev-parse", "main").strip() == trunk_before  # main owner'а — нет


async def test_the_clone_carries_the_full_history_not_a_shallow_one(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # Решение по цене: ``--depth 1`` отвергнут — Бобу нужна история (``git log``/``blame``).
    work, _fork = owner_repo

    path = await _adapter(tmp_path, work).create("bob/task")

    assert not (Path(path) / ".git" / "shallow").exists()
    assert _git(Path(path), "rev-list", "--count", "HEAD").strip() == (
        _git(work, "rev-list", "--count", "main").strip()
    )


# --------------------------------------------------------------------------- #
# 🔴 Адресация: куда клон вообще может пушить
# --------------------------------------------------------------------------- #


async def test_the_owners_working_copy_never_stays_as_the_remote(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, fork = owner_repo

    path = await _adapter(tmp_path, work, fork_url=f"file://{fork}").create("bob/task")

    remotes = _git(Path(path), "remote", "-v")
    assert str(work) not in remotes  # обратной дороги к репозиторию owner'а нет
    assert f"file://{fork}" in remotes


async def test_without_a_fork_url_the_clone_has_no_remote_at_all(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, _fork = owner_repo

    path = await _adapter(tmp_path, work).create("bob/task")

    assert _git(Path(path), "remote").strip() == ""


async def test_a_fork_url_carrying_a_token_is_refused_without_echoing_the_secret(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # 🔴 argv виден в ``ps``: installation-токен в URL — утечка того самого секрета, ради
    # которого строится схема прав. Отказ приходит ДО любого git, и текст отказа секрет
    # не повторяет.
    work, _fork = owner_repo
    secret = "ghs_supersecrettokenvalue"

    with pytest.raises(CloneError) as excinfo:
        _adapter(tmp_path, work, fork_url=f"https://x-access-token:{secret}@host/org/bob.git")

    assert secret not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# 🔴 Идентичность (срез D): подпись bob[ai] стоит ЛОКАЛЬНО и только в клоне
# --------------------------------------------------------------------------- #


async def test_a_commit_made_in_the_clone_is_authored_by_bob_ai(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # US-2: в ``git log`` работа Боба отличима от работы owner'а. Коммит делается обычным
    # git, без ``-c user.name`` и без переменных окружения: подпись берётся ровно оттуда,
    # куда её положил адаптер.
    work, _fork = owner_repo

    path = await _adapter(tmp_path, work, app_user_id="424242").create("bob/task")
    (Path(path) / "feature.py").write_text("print('claude edit')\n", encoding="utf-8")
    _git(Path(path), "add", ".")
    _git(Path(path), "commit", "-m", "claude work")

    assert _git(Path(path), "log", "-1", "--format=%an").strip() == "bob[ai]"
    assert _git(Path(path), "log", "-1", "--format=%ae").strip() == (
        "424242+bob-ai-work[bot]@users.noreply.github.com"
    )


async def test_the_clone_commits_as_bob_even_without_an_app_user_id(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # Без числового id адрес просто не сшивается GitHub'ом с ботом — но ИМЯ стоит, потому
    # что иначе git подписал бы работу Боба конфигурацией owner'а (та самая
    # неразличимость, против которой US-2).
    work, _fork = owner_repo

    path = await _adapter(tmp_path, work).create("bob/task")
    (Path(path) / "feature.py").write_text("print('claude edit')\n", encoding="utf-8")
    _git(Path(path), "add", ".")
    _git(Path(path), "commit", "-m", "claude work")

    assert _git(Path(path), "log", "-1", "--format=%an").strip() == "bob[ai]"
    assert _git(Path(path), "log", "-1", "--format=%ae").strip() == (
        "bob-ai-work[bot]@users.noreply.github.com"
    )


async def test_setting_bobs_identity_does_not_touch_the_owners_configuration(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # 🔴 ГЛАВНЫЙ ТЕСТ СРЕЗА D. Глобальная настройка переподписала бы коммиты owner'а в его
    # собственном репозитории как ``bob[ai]`` — ровно та путаница идентичностей, от которой
    # уходим. Сравниваются ФАКТИЧЕСКИЕ значения до и после, и в двух областях сразу:
    # глобальной (на этом хосте) и локальной в репозитории owner'а.
    work, _fork = owner_repo
    global_before = _config_of("--global", work)
    local_before = _config_of("--local", work)

    await _adapter(tmp_path, work, app_user_id="424242").create("bob/task")

    assert _config_of("--global", work) == global_before
    assert _config_of("--local", work) == local_before
    assert local_before == ["Owner", "owner@example.com"]  # контроль: было что менять


async def test_the_owner_keeps_signing_his_own_commits_after_bob_gets_a_workplace(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # То же свойство, но через ПОВЕДЕНИЕ, а не через чтение конфигурации: owner делает
    # коммит у себя ПОСЛЕ того, как у Боба появилось рабочее место, и коммит по-прежнему
    # его. Именно это owner увидит в ``git log``.
    work, _fork = owner_repo

    await _adapter(tmp_path, work, app_user_id="424242").create("bob/task")
    _write(work, "owner-note.md", "правка owner'а\n")
    _git(work, "add", "owner-note.md")
    _git(work, "commit", "-m", "owner work")

    assert _git(work, "log", "-1", "--format=%an").strip() == "Owner"
    assert _git(work, "log", "-1", "--format=%ae").strip() == "owner@example.com"


async def test_the_signature_lives_in_the_clones_own_config_file_only(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, _fork = owner_repo

    path = await _adapter(tmp_path, work, app_user_id="424242").create("bob/task")

    assert "bob[ai]" in (Path(path) / ".git" / "config").read_text(encoding="utf-8")
    assert "bob[ai]" not in (work / ".git" / "config").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Штатный путь: ensure переиспользует место, commit_and_push доводит ветку до форка
# --------------------------------------------------------------------------- #


async def test_ensure_reuses_the_clone_so_work_accumulates(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, _fork = owner_repo
    adapter = _adapter(tmp_path, work)
    first = await adapter.ensure("bob/epic-bob-089")
    (Path(first) / "accumulated.py").write_text("print('yesterday')\n", encoding="utf-8")

    second = await adapter.ensure("bob/epic-bob-089")

    assert second == first
    assert (Path(second) / "accumulated.py").exists()  # место НЕ пересоздано


async def test_ensure_starts_from_a_branch_the_source_already_accumulated(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # 🔴 Урок BOB-087.D5b: существующая ветка ЧЕКАУТИТСЯ, а не пересоздаётся поверх HEAD,
    # иначе накопленная в ней работа молча исчезает.
    work, _fork = owner_repo
    _git(work, "switch", "-c", "bob/epic-old")
    _write(work, "earlier.py", "print('earlier session')\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "work from an earlier session")
    _git(work, "switch", "main")

    path = await _adapter(tmp_path, work).ensure("bob/epic-old")

    assert (Path(path) / "earlier.py").exists()


async def test_ensure_refuses_a_foreign_directory_without_touching_it(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, _fork = owner_repo
    adapter = _adapter(tmp_path, work)
    foreign = tmp_path / "clones" / "epic-bob-089"
    foreign.mkdir(parents=True)
    (foreign / "owner-notes.md").write_text("важные заметки\n", encoding="utf-8")

    with pytest.raises(CloneError):
        await adapter.ensure("bob/epic-bob-089")

    assert (foreign / "owner-notes.md").read_text(encoding="utf-8") == "важные заметки\n"


async def test_commit_and_push_lands_the_branch_in_the_fork(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, fork = owner_repo
    adapter = _adapter(tmp_path, work, fork_url=f"file://{fork}")
    path = await adapter.create("bob/task")
    # Идентичность в клон ставит сам адаптер (срез D) — руками её здесь больше не задают,
    # поэтому прохождение коммита ЗАВИСИТ от того, что подпись реально проставлена.
    (Path(path) / "feature.py").write_text("print('claude edit')\n", encoding="utf-8")

    committed = await adapter.commit_and_push(path, "bob/task", "[bob] work")

    assert committed is True
    assert _git(fork, "log", "-1", "bob/task", "--format=%s").strip() == "[bob] work"


async def test_commit_and_push_reports_nothing_to_commit_honestly(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, fork = owner_repo
    adapter = _adapter(tmp_path, work, fork_url=f"file://{fork}")
    path = await adapter.create("bob/task")

    assert await adapter.commit_and_push(path, "bob/task", "[bob] nothing") is False


async def test_pushing_main_is_refused_before_git_runs(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, fork = owner_repo
    adapter = _adapter(tmp_path, work, fork_url=f"file://{fork}")
    path = await adapter.create("bob/task")

    with pytest.raises(CloneError):
        await adapter.commit_and_push(path, "main", "[bob] trunk")

    assert "main" not in _git(fork, "branch", "--list")


async def test_an_unsafe_branch_is_refused_before_git_runs(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    work, _fork = owner_repo

    with pytest.raises(CloneError):
        await _adapter(tmp_path, work).create("bob/../escape")

    assert not (tmp_path / "clones").exists()


async def test_remove_deletes_the_clone(owner_repo: tuple[Path, Path], tmp_path: Path) -> None:
    work, _fork = owner_repo
    adapter = _adapter(tmp_path, work)
    path = await adapter.create("bob/task")

    await adapter.remove(path)

    assert not Path(path).exists()


async def test_remove_is_idempotent(owner_repo: tuple[Path, Path], tmp_path: Path) -> None:
    work, _fork = owner_repo
    adapter = _adapter(tmp_path, work)
    path = await adapter.create("bob/task")
    await adapter.remove(path)

    await adapter.remove(path)  # уборка в ``finally`` не должна падать вторым вызовом


async def test_remove_refuses_a_path_outside_the_clone_root(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # 🔴 Проверено на кусачесть: каталог намеренно ВЫГЛЯДИТ клоном (внутри есть ``.git``),
    # иначе отказ приходил бы от второго предохранителя и тест проходил бы «по другой
    # причине» — при снятой проверке вложенности он остался бы зелёным. Ровно этот
    # вакуумный ассерт был найден саботажем.
    work, _fork = owner_repo
    outside = tmp_path / "precious"
    (outside / ".git").mkdir(parents=True)
    (outside / "notes.md").write_text("не удалять\n", encoding="utf-8")

    with pytest.raises(CloneError):
        await _adapter(tmp_path, work).remove(str(outside))

    assert (outside / "notes.md").exists()


async def test_remove_refuses_a_directory_that_is_not_a_clone(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # Внутри корня, но не клон: удалять нечего, а ``rmtree`` по такому пути — потеря данных.
    work, _fork = owner_repo
    stray = tmp_path / "clones" / "stray"
    stray.mkdir(parents=True)
    (stray / "notes.md").write_text("не удалять\n", encoding="utf-8")

    with pytest.raises(CloneError):
        await _adapter(tmp_path, work).remove(str(stray))

    assert (stray / "notes.md").exists()


# --------------------------------------------------------------------------- #
# 🔴 ЧЕСТНАЯ РАМКА: что клон НЕ закрывает (bob-a6b.5)
# --------------------------------------------------------------------------- #
# Пара к тестам выше — того же рода, что ``test_the_push_barrier_alone_leaves_that_road_open``
# в срезе C: мера описывается вместе с её границей, иначе доки начинают обещать больше, чем
# держат права. Клон убирает дорогу, которая открывалась САМА (общий ``.git``: обычный
# ``update-ref`` в рабочем месте двигал ствол владельца). Дороги НАМЕРЕННОЙ он не убирает:
# процесс живёт под тем же UID, и путь к репозиторию владельца из рабочего места узнаётся.
# Это не дефект адаптера, а рамка гарантии — но записана она должна быть исполняемо.


async def test_the_clones_reflog_still_names_the_repository_it_came_from(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # ``git clone`` пишет источник в собственный reflog (``clone: from file://…``), и
    # переадресация remote'а его оттуда не убирает: путь к репозиторию владельца остаётся
    # ЧИТАЕМЫМ изнутри рабочего места.
    work, _fork = owner_repo

    path = await _adapter(tmp_path, work).create("bob/task")

    reflog = (Path(path) / ".git" / "logs" / "HEAD").read_text(encoding="utf-8")
    assert str(work) in reflog
    # При этом адресом для push источник не является — это разные вещи (см. тест выше).
    assert str(work) not in _git(Path(path), "remote", "-v")


async def test_a_deliberate_local_push_plus_update_ref_still_reaches_the_owners_trunk(
    owner_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    # 🔴 Ровно то, что осталось «на доверии», а не стало невозможным СТРУКТУРНО — и оно
    # СЛОЖНЕЕ, чем в linked worktree, но не невозможно. Три шага, каждый доступен процессу
    # под тем же UID:
    #   1. ``update-ref`` с явным ``--git-dir`` в чужом репозитории ОТКАЗЫВАЕТ — у клона свой
    #      склад объектов, и нужного объекта у владельца просто нет (вот это клон и дал);
    #   2. локальный транспорт по пути из reflog кладёт объекты в репозиторий владельца:
    #      прямо в ``main`` git не пустит (``branch is currently checked out`` — это ЗАЩИТА
    #      GIT, не наша), а в боковую ветку пустит, кредов локальному пути не нужно;
    #   3. после этого объект у владельца ЕСТЬ, и ``--git-dir update-ref`` двигает его ствол.
    # Правами этот класс не закрывается вовсе (файлы, не сеть) — только раздельным UID. Пока
    # UID общий, «до main владельца локальные трюки не достают» — про случайность, не про
    # намерение; отчёт в комментарии bob-a6b.5.
    work, fork = owner_repo
    trunk_before = _git(work, "rev-parse", "main").strip()
    path = Path(await _adapter(tmp_path, work, fork_url=f"file://{fork}").create("bob/task"))
    (path / "feature.py").write_text("print('claude edit')\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "claude work")
    head = _git(path, "rev-parse", "HEAD").strip()
    assert head != trunk_before  # контроль: двигать ствол есть куда

    # (1) свой склад объектов — сам по себе барьер: сдвинуть ref на объект, которого у
    # владельца нет, не получается.
    blind = _git_try(path, "--git-dir", str(work / ".git"), "update-ref", "refs/heads/main", head)
    assert blind.returncode != 0
    assert _git(work, "rev-parse", "main").strip() == trunk_before

    # (2) путь к репозиторию владельца берётся из reflog клона, объекты уезжают боковой ветвью.
    denied = _git_try(path, "push", f"file://{work}", f"{head}:refs/heads/main")
    assert denied.returncode != 0
    assert "checked out" in denied.stderr  # отказ ДАЁТ GIT, а не наша схема прав
    assert _git_try(path, "push", f"file://{work}", f"{head}:refs/heads/side").returncode == 0

    # (3) объект у владельца появился — и ствол сдвигается.
    assert (
        _git_try(
            path, "--git-dir", str(work / ".git"), "update-ref", "refs/heads/main", head
        ).returncode
        == 0
    )
    assert _git(work, "rev-parse", "main").strip() == head


# --------------------------------------------------------------------------- #
# Подстановка под те же порты (композиция не должна знать, worktree это или клон)
# --------------------------------------------------------------------------- #


def test_the_clone_adapter_satisfies_both_workplace_ports(tmp_path: Path) -> None:
    adapter = GitClone(tmp_path / "clones", source=tmp_path / "work")
    assert isinstance(adapter, Worktree)
    assert isinstance(adapter, PersistentWorkspace)
