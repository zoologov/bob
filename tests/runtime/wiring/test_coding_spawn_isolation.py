# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты проводки изоляции окружения спавна (BOB-089, срез C).

Доезжает ли решение «спавн не видит кредов owner'а» до ГРАНИЦЫ ПРОЦЕССА — то есть до того
``env``, который оба рабочих рантайма (одноразовый кодер и живой терминал) передают
``claude``. Читается тот же флаг, что выбирает рабочее место (``coder.isolated_clone``): у
клона свой ``.git``, и изоляция кредов — вторая половина той же гарантии, поэтому отдельного
флага у неё нет.

🔴 OFF-путь: ни ключей изоляции в окружении, ни единого файла на диске. (Само окружение
при этом НЕ пустое: с bob-c3r.1 спавн всегда несёт push-барьер — это отдельная мера, и
раньше её отсутствие пряталось ровно за этой проверкой, см. пометку у OFF-раздела.)

🔴 Кредов спавну НЕ выдаётся даже при включённом флаге: ветку в форк пушит процесс САМОГО
Боба (``GitClone.commit_and_push``), а не ``claude`` внутри клона. Стор кредов появляется
только там, где токен передан явно — сейчас такого вызывающего в проде нет, и это записано
честно, а не выдано за готовую фичу.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.coding.push_guard import PUSH_GUARD_STUB_URL
from tests.support.wired_spawn_env import wired_spawn_envs

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def _spawn_envs(config: Mapping[str, object]) -> list[dict[str, str] | None]:
    """Окружение, которое каждый из двух рантаймов передаст спавну ``claude``.

    Сборка живёт в :mod:`tests.support.wired_spawn_env` — тем же доступом пользуется
    real-git тест барьера, и второй копии у него быть не должно.
    """
    return wired_spawn_envs(config)


def _config(tmp_path: Path, **coder: object) -> dict[str, object]:
    return {
        "coder": {
            "enabled": True,
            "interactive": True,
            "clone_root": str(tmp_path / "clones"),
            **coder,
        }
    }


# --------------------------------------------------------------------------- #
# OFF-путь (ЯВНЫЙ отказ owner'а): изоляции нет и файлов нет — но барьер push стоит
# --------------------------------------------------------------------------- #
#
# 🔴 ИСПРАВЛЕНО ПО ФАКТУ 2026-08-15, ДВАЖДЫ (bob-c3r.1; обе правки видимые).
# 1. Раздел утверждал «OFF-путь: ни окружения, ни файлов» и сверял окружение с
#    ``[None, None]``. Файлов по-прежнему нет, а вот пустое окружение означало, что вместе
#    с изоляцией отсутствовал и push-барьер: он был привязан к ``allow_bypass``, то есть
#    включался только вместе с ослаблением, которое его же обесценивает (P0 ``bob-l3t``).
#    Барьер теперь безусловен, поэтому OFF проверяется по ОТСУТСТВИЮ ИЗОЛЯЦИИ.
# 2. OFF-путём считался конфиг БЕЗ ключа. Это и была дыра: защита включалась только там,
#    где кто-то дописал ключ в gitignored ``config/bob.yaml``. Теперь дефолт — клон с
#    изоляцией, а OFF пишется ЯВНО; «ключа нет» проверяется в
#    ``test_isolated_clone_is_the_default.py`` — там оно означает ВКЛЮЧЕНО.


def _isolation_markers(env: dict[str, str] | None) -> list[str]:
    """Ключи изоляции кредов в окружении спавна (пусто → изоляции нет)."""
    assert env is not None
    return [key for key in ("GIT_CONFIG_GLOBAL", "GH_CONFIG_DIR") if key in env]


def test_an_explicit_off_flag_isolates_nothing_and_writes_nothing(tmp_path: Path) -> None:
    envs = _spawn_envs(_config(tmp_path, isolated_clone=False))

    assert [_isolation_markers(env) for env in envs] == [[], []]
    assert not (tmp_path / "clones").exists()


def test_the_push_barrier_stands_even_with_the_isolation_off(tmp_path: Path) -> None:
    # Барьер и изоляция — РАЗНЫЕ меры: выключенная изоляция не снимает страховку от
    # нечаянного push. Что барьер при этом настоящий (а не «ключ на месте»), доказывает
    # прогон настоящего git — ``test_push_barrier_always_real_git.py``.
    for env in _spawn_envs(_config(tmp_path, isolated_clone=False)):
        assert env is not None
        values = [env[f"GIT_CONFIG_KEY_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))]
        assert any(PUSH_GUARD_STUB_URL in value for value in values)


# --------------------------------------------------------------------------- #
# ON-путь: обе границы процесса получают одну и ту же изоляцию
# --------------------------------------------------------------------------- #


def test_the_isolated_clone_flag_isolates_both_spawns_from_the_owners_credentials(
    tmp_path: Path,
) -> None:
    envs = _spawn_envs(_config(tmp_path, isolated_clone=True))

    for env in envs:
        assert env is not None
        assert env["GIT_CONFIG_GLOBAL"].startswith(str(tmp_path / "clones"))
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GIT_ASKPASS"].startswith(str(tmp_path / "clones"))
        assert env["GH_CONFIG_DIR"].startswith(str(tmp_path / "clones"))
        pairs = [
            (env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"])
            for i in range(int(env["GIT_CONFIG_COUNT"]))
        ]
        assert ("credential.helper", "") in pairs


def test_both_runtimes_get_one_and_the_same_isolation(tmp_path: Path) -> None:
    # Одно решение на загрузку: разойдись они — и «изолирован» был бы только один рантайм.
    one_shot, live = _spawn_envs(_config(tmp_path, isolated_clone=True))
    assert one_shot is not None
    assert live is not None
    assert one_shot["GIT_CONFIG_GLOBAL"] == live["GIT_CONFIG_GLOBAL"]


def test_the_spawn_gets_no_credential_store_because_bob_pushes_himself(
    tmp_path: Path,
) -> None:
    # 🔴 Никаких кредов спавну: ветку в форк пушит процесс Боба, а не claude в клоне.
    envs = _spawn_envs(_config(tmp_path, isolated_clone=True))

    for env in envs:
        assert env is not None
        assert not any("store --file=" in value for value in env.values())
    assert not (tmp_path / "clones" / ".spawn-env" / "credentials").exists()


def test_the_controlled_environment_is_materialised_on_disk(tmp_path: Path) -> None:
    _spawn_envs(_config(tmp_path, isolated_clone=True))

    root = tmp_path / "clones" / ".spawn-env"
    assert (root / "gitconfig").is_file()
    assert (root / "gh").is_dir()
    # «В никуда» — значит этого файла нет.
    assert not (root / "askpass-disabled").exists()


def test_the_isolation_lives_beside_the_clones_never_inside_one(tmp_path: Path) -> None:
    # Каталог рабочего места — ``<clone_root>/<slug ветки>``; точка в начале имени в
    # ``bob/<slug>``-ветке невыразима, поэтому столкновения имён не бывает.
    _spawn_envs(_config(tmp_path, isolated_clone=True))

    assert [item.name for item in (tmp_path / "clones").iterdir()] == [".spawn-env"]


# --------------------------------------------------------------------------- #
# Два слоя: барьер push'а остаётся вторым, а не заменяется
# --------------------------------------------------------------------------- #


def test_the_push_barrier_and_the_isolation_reach_the_spawn_together(
    tmp_path: Path,
) -> None:
    # Пары обеих мер живут в ОДНОМ блоке ``GIT_CONFIG_*`` и нумеруются подряд, поэтому
    # «одна затёрла другую» проверяется, а не предполагается. ``allow_bypass`` здесь
    # больше не про барьер (он безусловен, bob-c3r.1) — это самая сильная комбинация
    # флагов, на которой обе меры обязаны доехать целыми.
    envs = _spawn_envs(_config(tmp_path, isolated_clone=True, allow_bypass=True))

    for env in envs:
        assert env is not None
        values = [env[f"GIT_CONFIG_KEY_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))]
        assert any(PUSH_GUARD_STUB_URL in value for value in values)
        assert "credential.helper" in values
