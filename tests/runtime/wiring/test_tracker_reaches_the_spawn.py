# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 Названная дыра под гардом: из рабочего места виден трекер владельца (BOB-088, срез 2).

Срез 1 сделал рабочее место КЛОНОМ и этим сломал доступ к ``bd``: из клона база не
находится вовсе (``no beads database found`` — Dolt-каталог gitignored, а из linked
worktree база находилась подъёмом ВВЕРХ). Весь конвейер BOB-088 стоит на ``bd``, поэтому
спавн получает ``BEADS_DIR`` на трекер ВЛАДЕЛЬЦА — сознательная, названная дыра в изоляции
(разбор: :data:`bob.identity.spawn_isolation.PURGED_SPAWN_VARS`).

Гард здесь про ПОВЕДЕНИЕ СОБРАННОЙ ПРОВОДКИ, а не про запись в списке: берётся ровно то
окружение, которое уедет в ``create_subprocess_exec`` ОБОИХ рантаймов, и в нём смотрится
переменная. Отдельно — КОНТРОЛЬ на явном отказе владельца от клона: там дыры нет и не
нужно (в linked worktree ``bd`` находит базу сам).

🔴 Что этим НЕ доказывается: что ``bd`` с этой переменной РЕАЛЬНО работает. Это контракт
настоящего инструмента, и он проверяется настоящим ``bd``
(``tests/infrastructure/coding/test_bd_in_the_workplace_live_smoke.py``) — фейк доказал бы
контракт фейка (§0.3 п.4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.infrastructure.config.loader import ConfigLoader
from bob.runtime.config import _REPO_ROOT
from tests.support.wired_spawn_env import wired_spawn_envs

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import pytest


def _loaded(tmp_path: Path, coder_lines: str = "") -> Mapping[str, object]:
    """Конфиг НАСТОЯЩЕГО загрузчика из yaml формы живого ``config/bob.yaml``."""
    path = tmp_path / "bob.yaml"
    path.write_text(
        "coder:\n"
        "  enabled: true\n"
        "  interactive: true\n"
        f"  clone_root: {tmp_path / 'clones'}\n" + coder_lines,
        encoding="utf-8",
    )
    return ConfigLoader(yaml_path=path, env={}).load()


def test_both_spawns_are_told_where_the_owners_tracker_lives(tmp_path: Path) -> None:
    expected = str(_REPO_ROOT / ".beads")

    for env in wired_spawn_envs(_loaded(tmp_path)):
        assert env is not None
        assert env["BEADS_DIR"] == expected


def test_the_tracker_pointer_is_an_absolute_path_of_the_repository(tmp_path: Path) -> None:
    # 🔴 От КОРНЯ РЕПОЗИТОРИЯ, а не от ``cwd`` (урок bob-a6b.6 M4 про ``clone_root``):
    # спавн, поднятый из другого каталога, ушёл бы в несуществующий трекер — и ``bd``
    # предложил бы модели завести ВТОРОЙ, которого владелец никогда не увидит.
    for env in wired_spawn_envs(_loaded(tmp_path)):
        assert env is not None
        assert env["BEADS_DIR"].startswith("/")
        assert env["BEADS_DIR"].endswith("/.beads")


def test_an_inherited_pointer_of_the_owner_does_not_decide_where_the_pipeline_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEADS_DIR", str(tmp_path / "someone-elses" / ".beads"))

    for env in wired_spawn_envs(_loaded(tmp_path)):
        assert env is not None
        assert env["BEADS_DIR"] == str(_REPO_ROOT / ".beads")


def test_the_control_shows_the_hole_is_opened_only_for_the_clone(tmp_path: Path) -> None:
    # 🔴 КОНТРОЛЬ (§0.3 п.5): при ЯВНОМ отказе владельца от клона рабочее место — linked
    # worktree ВНУТРИ репозитория, ``bd`` находит базу подъёмом вверх, и открывать дорогу
    # не надо. Без этого утверждения «переменная есть» ничего не говорило бы о том, что она
    # появляется именно там, где нужна.
    for env in wired_spawn_envs(_loaded(tmp_path, "  isolated_clone: false\n")):
        assert env is not None
        assert "BEADS_DIR" not in env
