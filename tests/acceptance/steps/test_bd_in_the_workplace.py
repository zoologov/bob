# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the «из рабочего места виден трекер» regression (BOB-088, срез 2).

Binds ``bd_in_the_workplace.feature`` to the production spawn-environment boundary. The
scenario pins the OBSERVABLE fact a future isolation edit must not silently break:

* by DEFAULT (an owner who configured nothing → the workplace is an isolated clone) BOTH
  spawn environments (one-shot coder + live terminal) carry ``BEADS_DIR`` pointing at the
  owner's tracker by the repository's ABSOLUTE path, and an inherited ``BEADS_DIR`` of the
  owner does NOT decide where the pipeline writes;
* the CONTROL: with the clone explicitly refused the pointer is NOT handed out — in a
  linked worktree ``bd`` finds the base by walking up, so the hole is neither needed nor
  opened.

The environment is exactly what the production wiring hands ``create_subprocess_exec`` in
both runtimes (:func:`tests.support.wired_spawn_env.wired_spawn_envs`). 🔴 This does NOT
prove ``bd`` really works with the pointer — that is the real tool's contract, closed
separately by a live smoke on the real ``bd``
(``tests/infrastructure/coding/test_bd_in_the_workplace_live_smoke.py``, §0.3 п.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pytest_bdd import given, scenarios, then, when

from bob.infrastructure.config.loader import ConfigLoader
from bob.runtime.config import _REPO_ROOT
from tests.support.wired_spawn_env import wired_spawn_envs

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import pytest

scenarios("../features/bd_in_the_workplace.feature")


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


@dataclass
class _Ctx:
    """Slate: the loaded config + the two spawn environments the runtimes produced."""

    config: Mapping[str, object] | None = None
    envs: list[dict[str, str] | None] = field(default_factory=list)


# --- Given ------------------------------------------------------------------


@given(
    "owner ничего про изоляцию не настраивал — рабочее место по умолчанию клон",
    target_fixture="btx",
)
def default_workplace_is_a_clone(tmp_path: Path) -> _Ctx:
    return _Ctx(config=_loaded(tmp_path))


@given("owner явно отказался от изолированного клона", target_fixture="btx")
def clone_explicitly_refused(tmp_path: Path) -> _Ctx:
    return _Ctx(config=_loaded(tmp_path, "  isolated_clone: false\n"))


# --- When -------------------------------------------------------------------


@when("собирается окружение спавна конвейера")
def the_spawn_environment_is_built(btx: _Ctx) -> None:
    assert btx.config is not None
    btx.envs = wired_spawn_envs(btx.config)


# --- Then -------------------------------------------------------------------


@then("обоим спавнам указан трекер owner'а абсолютным путём его репозитория")
def both_spawns_are_pointed_at_the_tracker(btx: _Ctx) -> None:
    expected = str(_REPO_ROOT / ".beads")
    assert len(btx.envs) == 2, f"ожидались оба рантайма: {btx.envs}"
    for env in btx.envs:
        assert env is not None
        assert env.get("BEADS_DIR") == expected, (
            f"спавн не знает про трекер owner'а: {env.get('BEADS_DIR')}"
        )
        # 🔴 Абсолютный путь ОТ КОРНЯ РЕПОЗИТОРИЯ (урок про clone_root): относительный
        # увёл бы спавн из другого cwd мимо трекера, и bd предложил бы завести второй.
        assert env["BEADS_DIR"].startswith("/")


@then("этот указатель не перебивается унаследованным указателем из окружения owner'а")
def the_pointer_wins_over_an_inherited_one(
    btx: _Ctx, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Тот же конфиг, но с чужим BEADS_DIR в окружении: пайплайн всё равно пишет в трекер
    # owner'а, а не туда, куда указывал унаследованный.
    monkeypatch.setenv("BEADS_DIR", str(tmp_path / "someone-elses" / ".beads"))
    expected = str(_REPO_ROOT / ".beads")
    for env in wired_spawn_envs(_loaded(tmp_path)):
        assert env is not None
        assert env["BEADS_DIR"] == expected, (
            f"чужой BEADS_DIR решил, куда пишет конвейер: {env['BEADS_DIR']}"
        )


@then("указателя на трекер спавнам не дают — в linked worktree bd находит базу сам")
def no_pointer_for_the_worktree(btx: _Ctx) -> None:
    assert len(btx.envs) == 2, f"ожидались оба рантайма: {btx.envs}"
    for env in btx.envs:
        assert env is not None
        assert "BEADS_DIR" not in env, (
            f"дыру открыли там, где она не нужна: {env.get('BEADS_DIR')}"
        )
