# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-GIT: код, подложенный МОДЕЛЬЮ в клон, не исполняется в процессе Боба (bob-a6b.14).

Три прохода ревью закрывали окружение СПАВНА. Но ``commit_and_push`` идёт в процессе самого
Боба — намеренно вне изоляции (там креды владельца и его ssh-ключ) — и при этом внутри
каталога, которым модель распоряжается целиком, включая ``<клон>/.git``. Ревьюер
воспроизвёл на настоящем git, что из этого следует: подложенные хуки ИСПОЛНИЛИСЬ в процессе
Боба, а прописанный локально ``remote.origin.pushurl`` увёл ветку В АПСТРИМ.

Здесь это закрыто и проверено ПОПЫТКАМИ, а не флагами в коде. Каждый тест — ПАРА
контроль/защита на настоящем git в одноразовых репозиториях (владелец + bare-форк +
bare-апстрим): сначала показываем, что вектор ЖИВОЙ (маркер появляется, ветка уезжает в
апстрим), потом — что продовая форма его закрывает. Фейк доказал бы контракт фейка (§0.3
п.4), а тест без контрольной половины доказывал бы, что маркера просто никто не поставил.

Три слоя и что каждый закрывает (состав выбран попытками, см. комментарии в тестах):

* ПАРЫ В ARGV (``core.hooksPath`` / ``core.fsmonitor`` / ``commit.gpgSign``) — вектор,
  которому не нужен конфиг (хуки — просто файлы), и вектора, которые конфиг называет
  командой. Пары стоят выше локального конфига и не зависят от момента проверки;
* PUSH ПО ЗНАЧЕНИЮ ``fork_url`` — имя remote'а модель переписывает, значение в argv — нет;
* ОТКАЗ по незнакомому ключу локального конфига — то, чего argv закрыть не может вовсе:
  ``filter.<d>.clean`` исполняется на ``add`` при любых парах, а ``url.*.pushInsteadOf``
  перезаписывает адрес ПОСЛЕ разбора argv.

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from bob.coding.adapters._exec import ExecRunner
from bob.coding.adapters._integrate import commit_and_push_branch
from bob.coding.adapters.git_clone import CloneError, GitClone
from bob.coding.adapters.git_worktree import GitWorktree

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

#: Хуки, которые модель кладёт в ``<клон>/.git/hooks`` — ровно три вида из отчёта ревьюера.
_PLANTED_HOOKS = ("pre-commit", "post-commit", "pre-push")


def _git(cwd: Path, *args: str) -> str:
    """Одноразовый git для подготовки и утверждений теста (никогда — продовая форма)."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _git_try(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """git, которому позволено упасть (в контрольной половине падение — часть факта)."""
    return subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)


def _plant_marker_script(path: Path, marker: Path, *, tail: str = "exit 0") -> None:
    """Положить исполняемый скрипт, который оставляет СЛЕД своего запуска."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\ntouch "{marker}"\n{tail}\n', encoding="utf-8")
    path.chmod(0o755)


def _plant_hooks(git_dir: Path, markers: Path) -> None:
    """«Модель» кладёт хуки всех трёх видов — обычной записью файлов в ``.git/hooks``."""
    for hook in _PLANTED_HOOKS:
        _plant_marker_script(git_dir / "hooks" / hook, markers / f"HOOK_{hook}")


def _traces(markers: Path) -> set[str]:
    """Что реально исполнилось в процессе Боба (перечисление, а не проверка известного)."""
    return {path.name for path in markers.iterdir()} if markers.exists() else set()


def _has_branch(bare: Path, branch: str) -> bool:
    return bool(_git(bare, "branch", "--list", branch).strip())


@pytest.fixture
def hosting(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Хозяйство: рабочая копия владельца, bare-ФОРК, bare-АПСТРИМ и каталог маркеров.

    Форк и апстрим — разные репозитории, поэтому вопрос «куда уехала ветка» имеет
    однозначный ответ, а не «куда-то в сеть».
    """
    fork = tmp_path / "fork.git"
    upstream = tmp_path / "upstream.git"
    for bare in (fork, upstream):
        bare.mkdir()
        _git(bare, "init", "--bare", "-b", "main")

    work = tmp_path / "owner"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "owner@example.com")
    _git(work, "config", "user.name", "Owner")
    (work / "README.md").write_text("readme\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "initial tree on main")
    _git(work, "push", str(fork), "refs/heads/main:refs/heads/main")
    _git(work, "push", str(upstream), "refs/heads/main:refs/heads/main")

    markers = tmp_path / "markers"
    markers.mkdir()
    return work, fork, upstream, markers


def _clone_adapter(tmp_path: Path, work: Path, fork: Path) -> GitClone:
    return GitClone(
        tmp_path / "clones",
        source=work,
        fork_url=f"file://{fork}",
        app_user_id="424242",
        runner=ExecRunner(),
    )


async def _model_edits(clone: Path) -> None:
    (clone / "feature.py").write_text("print('модель поработала')\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. Хуки: вектор, которому не нужен конфиг — модель просто пишет файлы
# --------------------------------------------------------------------------- #


async def test_planted_hooks_run_without_the_pins_and_never_run_with_them(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    work, fork, _upstream, markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)

    # --- КОНТРОЛЬ: та же последовательность БЕЗ пар — хуки исполняются в нашем процессе.
    control = Path(await adapter.create("bob/control"))
    _plant_hooks(control / ".git", markers)
    await _model_edits(control)
    _git(control, "add", "-A")
    _git(control, "commit", "-m", "[bob] control")
    _git(control, "push", str(fork), "refs/heads/bob/control:refs/heads/bob/control")

    assert _traces(markers) == {f"HOOK_{hook}" for hook in _PLANTED_HOOKS}

    # --- ЗАЩИТА: продовый путь с теми же хуками — ни одного следа.
    for stale in markers.iterdir():
        stale.unlink()
    guarded = Path(await adapter.create("bob/task"))
    _plant_hooks(guarded / ".git", markers)
    await _model_edits(guarded)

    committed = await adapter.commit_and_push(str(guarded), "bob/task", "[bob] работа")

    assert committed is True
    assert _traces(markers) == set()  # 🔴 код модели в процессе Боба не исполнялся
    assert _has_branch(fork, "bob/task")  # и легитимная работа всё равно доехала


async def test_a_hooks_directory_named_by_the_model_is_overridden_too(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    # Хук можно положить не только в ``.git/hooks``: ``core.hooksPath`` в локальном конфиге
    # переносит каталог куда угодно. Пара в argv стоит ВЫШЕ локального конфига — проверено
    # тем, что след не появился (а без пары появлялся, см. тест выше).
    work, fork, _upstream, markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)
    clone = Path(await adapter.create("bob/task"))
    _plant_marker_script(clone / "myhooks" / "pre-commit", markers / "HOOK_elsewhere")
    _plant_marker_script(clone / "myhooks" / "post-commit", markers / "HOOK_elsewhere_post")
    _git(clone, "config", "--local", "core.hooksPath", str(clone / "myhooks"))
    await _model_edits(clone)

    # Ключ ``core.hooksPath`` в конфиге клона — сам по себе повод отказать (его там не мы
    # заводили), поэтому вектор проверяется на общей форме интеграции.
    committed = await commit_and_push_branch(
        ExecRunner(),
        git_bin="git",
        path=str(clone),
        branch="bob/task",
        message="[bob] работа",
        timeout=60.0,
        push_target=f"file://{fork}",
        identity=(),
    )

    assert committed is True
    assert _traces(markers) == set()


# --------------------------------------------------------------------------- #
# 2. Push ПО ЗНАЧЕНИЮ: имя remote'а модель переписывает, значение в argv — нет
# --------------------------------------------------------------------------- #


async def test_a_local_push_url_sends_the_branch_upstream_by_name_but_not_by_value(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    work, fork, upstream, _markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)

    # --- КОНТРОЛЬ: push по ИМЕНИ remote'а с прописанным моделью ``pushurl`` — ветка
    # уезжает В АПСТРИМ. Ровно тот факт, который принёс ревьюер.
    control = Path(await adapter.create("bob/control"))
    _git(control, "config", "--local", "remote.origin.pushurl", f"file://{upstream}")
    await _model_edits(control)
    _git(control, "add", "-A")
    _git(control, "commit", "-m", "[bob] control")
    _git(control, "push", "-u", "origin", "bob/control")

    assert _has_branch(upstream, "bob/control")
    assert not _has_branch(fork, "bob/control")

    # --- ЗАЩИТА: та же подмена, но push идёт ПО ЗНАЧЕНИЮ ``fork_url`` — ветка в форке.
    guarded = Path(await adapter.create("bob/task"))
    _git(guarded, "config", "--local", "remote.origin.pushurl", f"file://{upstream}")
    await _model_edits(guarded)

    committed = await commit_and_push_branch(
        ExecRunner(),
        git_bin="git",
        path=str(guarded),
        branch="bob/task",
        message="[bob] работа",
        timeout=60.0,
        push_target=f"file://{fork}",
        identity=(),
    )

    assert committed is True
    assert _has_branch(fork, "bob/task")
    assert not _has_branch(upstream, "bob/task")  # 🔴 в апстрим не уехало


async def test_the_adapter_ignores_the_remote_url_the_model_repointed_at_the_upstream(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    # 🔴 Второй адрес push'а (``pushurl``) отказ ловит — а вот ``remote.origin.url`` в
    # ALLOW-списке ЕСТЬ (его пишет сам ``git clone``), и переписать его модель может тем же
    # ``git remote set-url``. Отказать тут нечем — и не нужно: push идёт по ЗНАЧЕНИЮ
    # ``fork_url``, поэтому имя ``origin`` никуда не ведёт. Ровно этот тест и краснеет,
    # если адресат push'а вернуть к имени remote'а.
    work, fork, upstream, _markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)
    clone = Path(await adapter.create("bob/task"))
    _git(clone, "remote", "set-url", "origin", f"file://{upstream}")
    await _model_edits(clone)

    committed = await adapter.commit_and_push(str(clone), "bob/task", "[bob] работа")

    assert committed is True
    assert _has_branch(fork, "bob/task")
    assert not _has_branch(upstream, "bob/task")  # 🔴 адрес взят из конфигурации, не из клона


async def test_the_clone_adapter_refuses_when_the_fork_is_not_configured(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    # Без URL форка remote удаляется при заведении клона — пушить некуда, и это должно
    # звучать как отказ по конфигурации, а не как загадочная ошибка git.
    work, fork, _upstream, _markers = hosting
    adapter = GitClone(tmp_path / "clones", source=work, fork_url="", runner=ExecRunner())
    clone = Path(await adapter.create("bob/task"))
    await _model_edits(clone)

    with pytest.raises(CloneError, match="fork"):
        await adapter.commit_and_push(str(clone), "bob/task", "[bob] работа")

    assert not _has_branch(fork, "bob/task")


# --------------------------------------------------------------------------- #
# 3. Конфиг, называющий КОМАНДУ: fsmonitor и подпись коммита
# --------------------------------------------------------------------------- #


async def test_a_filesystem_monitor_command_runs_without_the_pin_and_not_with_it(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    work, fork, _upstream, markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)

    control = Path(await adapter.create("bob/control"))
    _plant_marker_script(control / "fsmonitor.sh", markers / "FSMONITOR", tail="exit 1")
    _git(control, "config", "--local", "core.fsmonitor", str(control / "fsmonitor.sh"))
    await _model_edits(control)
    _git(control, "add", "-A")

    assert "FSMONITOR" in _traces(markers)

    (markers / "FSMONITOR").unlink()
    guarded = Path(await adapter.create("bob/task"))
    _plant_marker_script(guarded / "fsmonitor.sh", markers / "FSMONITOR", tail="exit 1")
    _git(guarded, "config", "--local", "core.fsmonitor", str(guarded / "fsmonitor.sh"))
    await _model_edits(guarded)

    committed = await commit_and_push_branch(
        ExecRunner(),
        git_bin="git",
        path=str(guarded),
        branch="bob/task",
        message="[bob] работа",
        timeout=60.0,
        push_target=f"file://{fork}",
        identity=(),
    )

    assert committed is True
    assert _traces(markers) == set()


async def test_a_signing_program_runs_without_the_pin_and_not_with_it(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    # ``commit.gpgsign=true`` + ``gpg.program=<скрипт>`` — исполнение произвольной команды
    # ровно на нашем ``commit``. Гасится не имя программы, а сама подпись.
    work, fork, _upstream, markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)

    control = Path(await adapter.create("bob/control"))
    _plant_marker_script(control / "gpg.sh", markers / "GPG", tail="exit 1")
    _git(control, "config", "--local", "commit.gpgsign", "true")
    _git(control, "config", "--local", "gpg.program", str(control / "gpg.sh"))
    await _model_edits(control)
    _git(control, "add", "-A")
    _git_try(control, "commit", "-m", "[bob] control")

    assert "GPG" in _traces(markers)

    (markers / "GPG").unlink()
    guarded = Path(await adapter.create("bob/task"))
    _plant_marker_script(guarded / "gpg.sh", markers / "GPG", tail="exit 1")
    _git(guarded, "config", "--local", "commit.gpgsign", "true")
    _git(guarded, "config", "--local", "gpg.program", str(guarded / "gpg.sh"))
    await _model_edits(guarded)

    committed = await commit_and_push_branch(
        ExecRunner(),
        git_bin="git",
        path=str(guarded),
        branch="bob/task",
        message="[bob] работа",
        timeout=60.0,
        push_target=f"file://{fork}",
        identity=(),
    )

    assert committed is True
    assert _traces(markers) == set()


# --------------------------------------------------------------------------- #
# 4. Чего argv не закрывает — и почему тогда громкий отказ
# --------------------------------------------------------------------------- #


async def test_a_content_filter_runs_even_with_every_pin_so_the_adapter_refuses(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    work, fork, _upstream, markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)

    # --- ФАКТ: у фильтров нет ключа-выключателя. Полная форма с парами — фильтр всё равно
    # исполняется на ``add -A``. Это и есть причина третьего слоя.
    control = Path(await adapter.create("bob/control"))
    _plant_marker_script(control / "filter.sh", markers / "FILTER", tail="cat")
    _git(control, "config", "--local", "filter.evil.clean", str(control / "filter.sh"))
    (control / ".gitattributes").write_text("* filter=evil\n", encoding="utf-8")
    await _model_edits(control)
    await commit_and_push_branch(
        ExecRunner(),
        git_bin="git",
        path=str(control),
        branch="bob/control",
        message="[bob] control",
        timeout=60.0,
        push_target=f"file://{fork}",
        identity=(),
    )

    assert "FILTER" in _traces(markers)

    # --- ЗАЩИТА: продовый адаптер до ``add`` не доходит — отказ по незнакомому ключу.
    (markers / "FILTER").unlink()
    guarded = Path(await adapter.create("bob/task"))
    _plant_marker_script(guarded / "filter.sh", markers / "FILTER", tail="cat")
    _git(guarded, "config", "--local", "filter.evil.clean", str(guarded / "filter.sh"))
    (guarded / ".gitattributes").write_text("* filter=evil\n", encoding="utf-8")
    await _model_edits(guarded)

    with pytest.raises(CloneError, match=re.escape("filter.evil.clean")):
        await adapter.commit_and_push(str(guarded), "bob/task", "[bob] работа")

    assert _traces(markers) == set()  # фильтр не запускался: до ``add`` не дошло
    assert not _has_branch(fork, "bob/task")
    assert _git(guarded, "log", "--oneline", "-1", "--format=%s").strip() != "[bob] работа"


async def test_a_push_url_rewrite_survives_pushing_by_value_so_the_adapter_refuses(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    work, fork, upstream, _markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)

    # --- ФАКТ: ``url.<апстрим>.pushInsteadOf`` перезаписывает адрес ПОСЛЕ разбора argv —
    # push по ЗНАЧЕНИЮ форка всё равно уезжает в апстрим.
    control = Path(await adapter.create("bob/control"))
    _git(
        control,
        "config",
        "--local",
        f"url.file://{upstream}.pushInsteadOf",
        f"file://{fork}",
    )
    await _model_edits(control)
    await commit_and_push_branch(
        ExecRunner(),
        git_bin="git",
        path=str(control),
        branch="bob/control",
        message="[bob] control",
        timeout=60.0,
        push_target=f"file://{fork}",
        identity=(),
    )

    assert _has_branch(upstream, "bob/control")
    assert not _has_branch(fork, "bob/control")

    # --- ЗАЩИТА: продовый адаптер отказывает ДО push'а, и в апстрим ничего не уезжает.
    guarded = Path(await adapter.create("bob/task"))
    _git(
        guarded,
        "config",
        "--local",
        f"url.file://{upstream}.pushInsteadOf",
        f"file://{fork}",
    )
    await _model_edits(guarded)

    with pytest.raises(CloneError, match="pushinsteadof"):
        await adapter.commit_and_push(str(guarded), "bob/task", "[bob] работа")

    assert not _has_branch(upstream, "bob/task")
    assert not _has_branch(fork, "bob/task")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        # 🔴 Обе дороги ПРЯЧУТ ключи от ``config --local --list``: включённый файл
        # (проверено: фильтр из него исполняется, а ``--get`` отвечает rc=1) и
        # конфиг-на-worktree (ключ уезжает в ``.git/config.worktree``). Перечень «опасных
        # ключей» их не увидел бы — виден только сам незнакомый ключ.
        ("include.path", "/nowhere/extra.cfg"),
        ("extensions.worktreeConfig", "true"),
        # Второй адрес push'а и хелпер кредов: первый — попытка увезти работу, второй
        # получил бы от git реквизиты владельца на сохранение.
        ("remote.origin.pushurl", "file:///nowhere/elsewhere.git"),
        ("credential.helper", "/nowhere/steal.sh"),
        ("core.sshCommand", "ssh -i /nowhere/key"),
        ("alias.st", "!touch /nowhere/x"),
    ],
)
async def test_any_key_the_clone_setup_never_writes_stops_the_integration(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path, key: str, value: str
) -> None:
    work, fork, _upstream, _markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)
    clone = Path(await adapter.create("bob/task"))
    _git(clone, "config", "--local", key, value)
    await _model_edits(clone)

    with pytest.raises(CloneError, match="local config"):
        await adapter.commit_and_push(str(clone), "bob/task", "[bob] работа")

    assert not _has_branch(fork, "bob/task")


async def test_the_untouched_clone_of_a_real_session_passes_the_check(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    # 🔴 Ложный отказ стоит дорого: он остановил бы легитимную работу Боба. Проверяется на
    # том конфиге, который оставляют НАСТОЯЩИЙ ``git clone`` и наша последовательность
    # заведения клона (включая ``switch -c`` от ветки форка в долгоживущем месте).
    work, fork, _upstream, _markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)
    first = Path(await adapter.ensure("bob/epic-work"))
    await _model_edits(first)

    assert await adapter.commit_and_push(str(first), "bob/epic-work", "[bob] первый заход")

    shutil.rmtree(first)  # каталог потерян — место поднимается из форка
    second = Path(await adapter.ensure("bob/epic-work"))
    (second / "more.py").write_text("print('ещё')\n", encoding="utf-8")

    assert await adapter.commit_and_push(str(second), "bob/epic-work", "[bob] второй заход")
    assert _has_branch(fork, "bob/epic-work")


# --------------------------------------------------------------------------- #
# 5. Обход через СОСТАВ ALLOW-списка: путь к дереву и подпись (ревью MAJOR-8)
# --------------------------------------------------------------------------- #


async def test_a_working_tree_pointed_at_the_owners_repository_stops_the_integration(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    # 🔴 ФАКТ ревьюера, воспроизведённый здесь ПОПЫТКОЙ: ``core.worktree`` чистый ``git
    # clone`` не пишет вовсе, поэтому в конфиге клона он бывает только от модели. Указав им
    # дерево ВЛАДЕЛЬЦА, модель добивается того, что ``add -A`` собирает ЕГО дерево: работа
    # Боба в ветку не попадает, а незакоммиченный черновик владельца уезжает в форк кредами
    # самого Боба. Это дорога утечки чужой работы, а не путаница каталогов.
    work, fork, _upstream, _markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)

    # --- КОНТРОЛЬ: ключ разрешён (как было) → уезжает дерево ВЛАДЕЛЬЦА.
    control = Path(await adapter.create("bob/control"))
    (control / "bob_work.py").write_text("print('работа Боба')\n", encoding="utf-8")
    (work / "secret_notes.md").write_text("черновик владельца\n", encoding="utf-8")
    _git(control, "config", "--local", "core.worktree", str(work))
    await commit_and_push_branch(
        ExecRunner(),
        git_bin="git",
        path=str(control),
        branch="bob/control",
        message="[bob] control",
        timeout=60.0,
        push_target=f"file://{fork}",
        identity=(),
    )

    leaked = _git(fork, "ls-tree", "--name-only", "-r", "bob/control").split()
    assert "secret_notes.md" in leaked  # черновик владельца уехал в форк
    assert "bob_work.py" not in leaked  # а работа Боба в ветку не попала

    # --- ЗАЩИТА: продовый адаптер отказывает ДО ``add``, называя виновный ключ.
    guarded = Path(await adapter.create("bob/task"))
    (guarded / "bob_work.py").write_text("print('работа Боба')\n", encoding="utf-8")
    _git(guarded, "config", "--local", "core.worktree", str(work))

    with pytest.raises(CloneError, match=re.escape("core.worktree")):
        await adapter.commit_and_push(str(guarded), "bob/task", "[bob] работа")

    assert not _has_branch(fork, "bob/task")
    assert _git(work, "status", "--porcelain").strip()  # черновик остался у владельца


async def test_an_identity_planted_by_the_model_cannot_re_sign_the_work_of_bob(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    # 🔴 ФАКТ ревьюера, воспроизведённый попыткой: ``user.name``/``user.email`` в локальном
    # конфиге клона переподписывают коммит в форке ВЛАДЕЛЬЦЕМ — прямое попадание в US-2
    # («в истории видно, кто что сделал»). Ключи из ALLOW-списка не выкинуть (их пишем мы
    # сами), поэтому решает не конфиг, а ПАРЫ В ARGV.
    work, fork, _upstream, _markers = hosting
    adapter = _clone_adapter(tmp_path, work, fork)
    planted = ("Vladimir Zoologov", "owner@example.com")

    # --- КОНТРОЛЬ: прежняя форма (без пар подписи) — автор в форке становится ВЛАДЕЛЬЦЕМ.
    control = Path(await adapter.create("bob/control"))
    _git(control, "config", "--local", "user.name", planted[0])
    _git(control, "config", "--local", "user.email", planted[1])
    await _model_edits(control)
    await commit_and_push_branch(
        ExecRunner(),
        git_bin="git",
        path=str(control),
        branch="bob/control",
        message="[bob] control",
        timeout=60.0,
        push_target=f"file://{fork}",
        identity=(),
    )

    assert _git(fork, "log", "-1", "--format=%an <%ae>", "bob/control").strip() == (
        f"{planted[0]} <{planted[1]}>"
    )

    # --- ЗАЩИТА: продовый путь с тем же подложенным конфигом — подпись всё равно Боба.
    guarded = Path(await adapter.create("bob/task"))
    _git(guarded, "config", "--local", "user.name", planted[0])
    _git(guarded, "config", "--local", "user.email", planted[1])
    await _model_edits(guarded)

    committed = await adapter.commit_and_push(str(guarded), "bob/task", "[bob] работа")

    assert committed is True
    assert _git(fork, "log", "-1", "--format=%an <%ae>", "bob/task").strip() == (
        "bob[ai] <424242+bob-ai-work[bot]@users.noreply.github.com>"
    )


# --------------------------------------------------------------------------- #
# 6. Прежнее рабочее место (linked worktree) — тот же процесс Боба, те же хуки
# --------------------------------------------------------------------------- #


async def test_hooks_of_the_shared_git_dir_do_not_run_for_the_worktree_adapter(
    hosting: tuple[Path, Path, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Linked worktree делит ``.git`` с репозиторием владельца, поэтому хуки лежат в ОБЩЕМ
    # каталоге — и модель, работающая в worktree, пишет их для чужого процесса. Флаг
    # ``coder.isolated_clone`` по умолчанию OFF, то есть это ДЕЙСТВУЮЩИЙ путь.
    #
    # 🔴 ``GitWorktree`` не передаёт git ни ``-C``, ни ``cwd``: он работает с тем
    # репозиторием, в котором СТОИТ ПРОЦЕСС (так его и запускает бот). Без ``chdir`` в
    # одноразовое хозяйство тест правил бы ЖИВОЙ репозиторий Боба — что и случилось на
    # первом прогоне: в нём появились ветка ``bob/control`` и зарегистрированный worktree.
    work, fork, _upstream, markers = hosting
    _git(work, "remote", "add", "origin", str(fork))
    monkeypatch.chdir(work)
    adapter = GitWorktree(tmp_path / "worktrees", runner=ExecRunner())

    control = Path(await adapter.create("bob/control"))
    _plant_hooks(work / ".git", markers)
    await _model_edits(control)
    _git(control, "add", "-A")
    _git(control, "commit", "-m", "[bob] control")

    assert {"HOOK_pre-commit", "HOOK_post-commit"} <= _traces(markers)

    for stale in markers.iterdir():
        stale.unlink()
    guarded = Path(await adapter.create("bob/task"))
    await _model_edits(guarded)

    committed = await adapter.commit_and_push(str(guarded), "bob/task", "[bob] работа")

    assert committed is True
    assert _traces(markers) == set()
    assert _has_branch(fork, "bob/task")
