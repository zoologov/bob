# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-GIT acceptance: унаследованная git-переменная не переадресует спавн (bob-a6b.12).

Что здесь защищается: СТРУКТУРНОЕ свойство среза A — «у клона Боба свой ``.git``, поэтому
локальные трюки до ствола владельца не достают». Ревью (bob-a6b.6, MAJOR-5) показало, что
свойство держалось не структурой, а тем, что переменной никто не подсунул: при
унаследованном ``GIT_DIR`` ОДНА команда из клона Боба сдвинула ствол владельца назад
(``rc=0``, коммит потерян). Тот же класс, что MAJOR-1 (``GIT_CONFIG_PARAMETERS``):
переменную не «ставят изнутри», её НАСЛЕДУЮТ — git сам экспортирует ``GIT_DIR`` хукам,
``rebase --exec``, ``bisect run``, ``submodule foreach`` и алиасам.

🔴 Фейк здесь доказал бы контракт фейка (§0.3 п.4). Всё содержание этих тестов — поведение
НАСТОЯЩЕГО git: какая переменная перебивает обнаружение репозитория, какая уводит склад
объектов, какая — индекс, рабочее дерево, партицию refs или файл конфига. Поэтому каждый
тест — ПАРА на выброшенных репозиториях: сначала контроль «дорога РЕАЛЬНО есть» (без него
зелёный тест доказывал бы лишь, что мы ничего не подсунули), затем тот же вызов в
прод-окружении спавна. Главный вектор проверяется СРАВНЕНИЕМ SHA ствола до и после — ровно
так, как его воспроизвёл ревьюер.

🔴 Сеть не трогается ни одним тестом: все «удалённые» репозитории — локальные каталоги, а
там, где нужен апстрим, его нет вовсе.

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from bob.coding.push_guard import guarded_spawn_env
from bob.identity.adapters.spawn_isolation_files import SpawnIsolationFiles

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

#: Подпись коммитов: тестам нужен git без конфига пользователя (``HOME`` пустой).
_SIGNATURE = {
    "GIT_AUTHOR_NAME": "probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}

#: Содержимое отслеживаемого файла в репозитории «владельца» и в клоне Боба: одно имя,
#: разное содержимое — чтобы перезапись чужого рабочего дерева была видна глазами.
_OWNER_CONTENT = "OWNER-WORK\n"
_BOB_CONTENT = "BOB-WORK\n"

#: Имя файла, отслеживаемого в ОБОИХ репозиториях.
_TRACKED = "shared-name.txt"

#: Ствол «владельца»: та ветка, потеря коммитов на которой и есть худший исход.
_TRUNK = "refs/heads/main"


@dataclass(frozen=True)
class OwnerRepo:
    """Выброшенный репозиторий «владельца»: где он лежит и где стоял его ствол."""

    path: Path
    #: SHA, на котором ствол стоит сейчас (два коммита истории).
    trunk: str
    #: SHA предыдущего коммита — УЖЕ существующий у владельца объект, то есть откат
    #: ствола на него не требует ни сети, ни кредов, ни push'а.
    previous: str


def _run(
    argv: list[str], cwd: Path, env: dict[str, str], stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Выполнить git в заданном окружении (никогда не бросает: нас интересует факт)."""
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        input=stdin,
    )


def _plain(tmp_path: Path) -> dict[str, str]:
    """Окружение без всяких мер — то, в котором заводятся выброшенные репозитории."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(home), **_SIGNATURE}


@pytest.fixture
def plain_env(tmp_path: Path) -> dict[str, str]:
    return _plain(tmp_path)


@pytest.fixture
def owner_repo(tmp_path: Path, plain_env: dict[str, str]) -> Callable[[], OwnerRepo]:
    """Фабрика выброшенных репозиториев «владельца» (каждый — свой, ничего не общего).

    Фабрика, а не единственный репозиторий: контроль ДЕЙСТВИТЕЛЬНО двигает ствол, и
    восстанавливать его перед изолированной половиной значило бы проверять ещё и
    восстановление. Два одинаково собранных репозитория честнее.
    """
    counter = {"n": 0}

    def make() -> OwnerRepo:
        counter["n"] += 1
        path = tmp_path / f"owner-{counter['n']}"
        path.mkdir()
        _run(["git", "init", "-q", "-b", "main"], path, plain_env)
        (path / _TRACKED).write_text(_OWNER_CONTENT, encoding="utf-8")
        _run(["git", "add", "-A"], path, plain_env)
        _run(["git", "commit", "-q", "-m", "owner day one"], path, plain_env)
        previous = _run(["git", "rev-parse", "HEAD"], path, plain_env).stdout.strip()
        (path / _TRACKED).write_text(_OWNER_CONTENT + "day two\n", encoding="utf-8")
        _run(["git", "commit", "-qam", "owner day two"], path, plain_env)
        trunk = _run(["git", "rev-parse", "HEAD"], path, plain_env).stdout.strip()
        assert trunk != previous  # иначе «откат» ничего не значил бы
        return OwnerRepo(path=path, trunk=trunk, previous=previous)

    return make


@pytest.fixture
def bob_clone(tmp_path: Path, plain_env: dict[str, str]) -> Path:
    """Клон Боба: НЕЗАВИСИМЫЙ репозиторий со своим ``.git`` (структура среза A)."""
    path = tmp_path / "bob-clone"
    path.mkdir()
    _run(["git", "init", "-q", "-b", "main"], path, plain_env)
    (path / _TRACKED).write_text(_BOB_CONTENT, encoding="utf-8")
    _run(["git", "add", "-A"], path, plain_env)
    _run(["git", "commit", "-q", "-m", "bob work"], path, plain_env)
    return path


@pytest.fixture
def isolated(tmp_path: Path, plain_env: dict[str, str]) -> Callable[..., dict[str, str]]:
    """Собрать прод-окружение спавна (барьер push'а + изоляция) с унаследованными переменными."""
    isolation = SpawnIsolationFiles(tmp_path / "spawn-env").materialize()

    def build(**inherited: str) -> dict[str, str]:
        env = guarded_spawn_env({**plain_env, **inherited}, active=True, isolation=isolation)
        assert env is not None
        return env

    return build


def _trunk_sha(owner: OwnerRepo, plain_env: dict[str, str]) -> str:
    """Где стоит ствол владельца ПРЯМО СЕЙЧАС (его собственными глазами)."""
    return _run(["git", "rev-parse", _TRUNK], owner.path, plain_env).stdout.strip()


def _readable(sha: str, repo: Path, plain_env: dict[str, str]) -> bool:
    """Виден ли объект ``sha`` из репозитория ``repo`` (его собственным складом объектов)."""
    return _run(["git", "cat-file", "-t", sha], repo, plain_env).returncode == 0


# --------------------------------------------------------------------------- #
# 🔴 ГЛАВНЫЙ ВЕКТОР: GIT_DIR — откат ствола владельца ОДНОЙ командой
# --------------------------------------------------------------------------- #


def test_an_inherited_git_dir_no_longer_lets_the_spawn_move_the_owners_trunk(
    owner_repo: Callable[[], OwnerRepo],
    bob_clone: Path,
    plain_env: dict[str, str],
    isolated: Callable[..., dict[str, str]],
) -> None:
    # Контроль: дорога РЕАЛЬНО есть. Одна команда из клона Боба — и ствол владельца
    # уехал назад на предыдущий коммит, то есть коммит потерян. Ни сети, ни кредов, ни
    # push'а: ``.git`` у клона свой, но ``GIT_DIR`` указывает мимо него.
    control = owner_repo()
    rollback = ["git", "update-ref", _TRUNK, control.previous]
    result = _run(rollback, bob_clone, {**plain_env, "GIT_DIR": str(control.path / ".git")})

    assert result.returncode == 0
    assert _trunk_sha(control, plain_env) == control.previous  # 🔴 ствол СДВИНУТ

    # 🔴 В прод-окружении спавна той же командой ствол не двигается: SHA до = SHA после.
    victim = owner_repo()
    env = isolated(GIT_DIR=str(victim.path / ".git"))

    assert "GIT_DIR" not in env
    _run(["git", "update-ref", _TRUNK, victim.previous], bob_clone, env)

    assert _trunk_sha(victim, plain_env) == victim.trunk


# --------------------------------------------------------------------------- #
# Остальная семья: чем ещё унаследованная переменная переадресует операцию
# --------------------------------------------------------------------------- #


def test_an_inherited_work_tree_no_longer_lets_the_spawn_rewrite_the_owners_files(
    owner_repo: Callable[[], OwnerRepo],
    bob_clone: Path,
    plain_env: dict[str, str],
    isolated: Callable[..., dict[str, str]],
) -> None:
    # ``GIT_WORK_TREE`` уводит РАБОЧЕЕ ДЕРЕВО: коммиты владельца целы, а файлы на диске
    # затёрты содержимым из клона Боба — потеря незакоммиченной работы.
    control = owner_repo()
    checkout = ["git", "checkout", "HEAD", "--", _TRACKED]
    _run(checkout, bob_clone, {**plain_env, "GIT_WORK_TREE": str(control.path)})

    assert (control.path / _TRACKED).read_text(encoding="utf-8") == _BOB_CONTENT  # 🔴 затёрт

    victim = owner_repo()
    before = (victim.path / _TRACKED).read_text(encoding="utf-8")
    env = isolated(GIT_WORK_TREE=str(victim.path))

    assert "GIT_WORK_TREE" not in env
    _run(checkout, bob_clone, env)

    assert (victim.path / _TRACKED).read_text(encoding="utf-8") == before


def test_an_inherited_common_dir_no_longer_sends_bobs_objects_into_the_owners_store(
    owner_repo: Callable[[], OwnerRepo],
    bob_clone: Path,
    plain_env: dict[str, str],
    isolated: Callable[..., dict[str, str]],
) -> None:
    # ``GIT_COMMON_DIR`` подменяет НЕ-рабочие части ``.git``, в том числе склад объектов:
    # объект, записанный из клона Боба, оказывается в репозитории владельца, а в самом
    # клоне его нет. Это ровно тот ОБЩИЙ склад, за отказ от которого срез A заплатил.
    control = owner_repo()
    write = ["git", "hash-object", "-w", "--stdin"]
    common = {**plain_env, "GIT_COMMON_DIR": str(control.path / ".git")}
    sha = _run(write, bob_clone, common, stdin="object written from bobs clone\n").stdout.strip()

    assert sha
    assert _readable(sha, control.path, plain_env)  # 🔴 объект Боба лежит у владельца
    assert not _readable(sha, bob_clone, plain_env)

    victim = owner_repo()
    env = isolated(GIT_COMMON_DIR=str(victim.path / ".git"))

    assert "GIT_COMMON_DIR" not in env
    isolated_sha = _run(
        write, bob_clone, env, stdin="object written from bobs clone\n"
    ).stdout.strip()

    assert isolated_sha == sha  # то же содержимое, тот же хэш — разница только в АДРЕСЕ
    assert not _readable(sha, victim.path, plain_env)
    assert _readable(sha, bob_clone, plain_env)  # уехал в СВОЙ склад


def test_an_inherited_object_directory_no_longer_redirects_where_objects_land(
    owner_repo: Callable[[], OwnerRepo],
    bob_clone: Path,
    plain_env: dict[str, str],
    isolated: Callable[..., dict[str, str]],
) -> None:
    # ``GIT_OBJECT_DIRECTORY`` — вторая, независимая переменная того же следствия: она
    # называет каталог объектов напрямую.
    control = owner_repo()
    write = ["git", "hash-object", "-w", "--stdin"]
    payload = "another object written from bobs clone\n"
    into_owner = {**plain_env, "GIT_OBJECT_DIRECTORY": str(control.path / ".git" / "objects")}
    sha = _run(write, bob_clone, into_owner, stdin=payload).stdout.strip()

    assert sha
    assert _readable(sha, control.path, plain_env)  # 🔴
    assert not _readable(sha, bob_clone, plain_env)

    victim = owner_repo()
    env = isolated(GIT_OBJECT_DIRECTORY=str(victim.path / ".git" / "objects"))

    assert "GIT_OBJECT_DIRECTORY" not in env
    _run(write, bob_clone, env, stdin=payload)

    assert not _readable(sha, victim.path, plain_env)
    assert _readable(sha, bob_clone, plain_env)


def test_an_inherited_alternates_list_no_longer_reopens_the_owners_object_store(
    owner_repo: Callable[[], OwnerRepo],
    bob_clone: Path,
    plain_env: dict[str, str],
    isolated: Callable[..., dict[str, str]],
) -> None:
    # ``GIT_ALTERNATE_OBJECT_DIRECTORIES`` — дорога на ЧТЕНИЕ: коммиты владельца
    # становятся видны из клона Боба, то есть общий склад объектов возвращается.
    control = owner_repo()

    assert not _readable(control.trunk, bob_clone, plain_env)  # контроль контроля

    alternates = str(control.path / ".git" / "objects")
    with_alternates = {**plain_env, "GIT_ALTERNATE_OBJECT_DIRECTORIES": alternates}

    assert _readable(control.trunk, bob_clone, with_alternates)  # 🔴 чужой коммит читается

    env = isolated(GIT_ALTERNATE_OBJECT_DIRECTORIES=alternates)

    assert "GIT_ALTERNATE_OBJECT_DIRECTORIES" not in env
    assert not _readable(control.trunk, bob_clone, env)


def test_an_inherited_index_file_no_longer_clobbers_the_owners_staging_area(
    owner_repo: Callable[[], OwnerRepo],
    bob_clone: Path,
    plain_env: dict[str, str],
    isolated: Callable[..., dict[str, str]],
) -> None:
    # ``GIT_INDEX_FILE`` уводит ИНДЕКС: ``git add`` из клона Боба перезаписывает область
    # подготовленного у владельца — его подготовленная работа исчезает.
    control = owner_repo()
    status = ["git", "status", "--porcelain"]

    assert _run(status, control.path, plain_env).stdout == ""  # контроль: чисто

    add = ["git", "add", _TRACKED]
    _run(add, bob_clone, {**plain_env, "GIT_INDEX_FILE": str(control.path / ".git" / "index")})

    assert _run(status, control.path, plain_env).stdout != ""  # 🔴 индекс владельца затёрт

    victim = owner_repo()
    env = isolated(GIT_INDEX_FILE=str(victim.path / ".git" / "index"))

    assert "GIT_INDEX_FILE" not in env
    _run(add, bob_clone, env)

    assert _run(status, victim.path, plain_env).stdout == ""


def test_an_inherited_namespace_no_longer_switches_the_ref_partition(
    bob_clone: Path,
    plain_env: dict[str, str],
    isolated: Callable[..., dict[str, str]],
) -> None:
    # ``GIT_NAMESPACE`` подменяет ПАРТИЦИЮ refs — и делает это молча: refs, которые есть,
    # выглядят отсутствующими (а push уезжает в скрытую партицию, где Боб их не найдёт).
    # «Удалённый» репозиторий здесь — сам клон, локальным путём: сеть не трогается.
    ls_remote = ["git", "ls-remote", str(bob_clone / ".git")]

    assert _TRUNK in _run(ls_remote, bob_clone, plain_env).stdout  # контроль: refs видны
    assert _run(ls_remote, bob_clone, {**plain_env, "GIT_NAMESPACE": "hidden"}).stdout == ""  # 🔴

    env = isolated(GIT_NAMESPACE="hidden")

    assert "GIT_NAMESPACE" not in env
    assert _TRUNK in _run(ls_remote, bob_clone, env).stdout


def test_an_inherited_ceiling_no_longer_blinds_git_to_bobs_own_clone(
    bob_clone: Path,
    plain_env: dict[str, str],
    isolated: Callable[..., dict[str, str]],
) -> None:
    # ``GIT_CEILING_DIRECTORIES`` — обратная половина того же класса: она не уводит
    # операцию к чужому репозиторию, а ослепляет git к СВОЕМУ. Из подкаталога клона git
    # перестаёт находить ``.git`` вообще, и любая работа спавна падает необъяснимо.
    subdir = bob_clone / "sub"
    subdir.mkdir()
    toplevel = ["git", "rev-parse", "--show-toplevel"]

    assert _run(toplevel, subdir, plain_env).stdout.strip() == str(bob_clone)  # контроль
    blinded = _run(toplevel, subdir, {**plain_env, "GIT_CEILING_DIRECTORIES": str(bob_clone)})

    assert blinded.returncode != 0  # 🔴 «not a git repository»
    assert "not a git repository" in blinded.stderr

    env = isolated(GIT_CEILING_DIRECTORIES=str(bob_clone))

    assert "GIT_CEILING_DIRECTORIES" not in env
    assert _run(toplevel, subdir, env).stdout.strip() == str(bob_clone)


def test_an_inherited_legacy_git_config_no_longer_writes_into_the_owners_config(
    bob_clone: Path,
    plain_env: dict[str, str],
    isolated: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> None:
    # ``GIT_CONFIG`` (легаси, но живая на git 2.49) переадресует команду ``git config`` в
    # НАЗВАННЫЙ файл — и на чтение, и на ЗАПИСЬ. То есть спавн правит ``~/.gitconfig``
    # владельца, а туда пишутся алиасы и ``core.pager``, то есть код, который потом
    # запустит сам владелец.
    owner_config = tmp_path / "owner-gitconfig"
    original = "[user]\n\tname = OWNERNAME\n"
    owner_config.write_text(original, encoding="utf-8")
    plant = ["git", "config", "planted.by", "the-spawn"]
    read_name = ["git", "config", "--get", "user.name"]
    legacy = {**plain_env, "GIT_CONFIG": str(owner_config)}

    assert "OWNERNAME" in _run(read_name, bob_clone, legacy).stdout  # контроль: читается
    _run(plant, bob_clone, legacy)

    assert "planted" in owner_config.read_text(encoding="utf-8")  # 🔴 файл владельца изменён

    owner_config.write_text(original, encoding="utf-8")
    env = isolated(GIT_CONFIG=str(owner_config))

    assert "GIT_CONFIG" not in env
    _run(plant, bob_clone, env)

    assert owner_config.read_text(encoding="utf-8") == original
    assert "OWNERNAME" not in _run(read_name, bob_clone, env).stdout
