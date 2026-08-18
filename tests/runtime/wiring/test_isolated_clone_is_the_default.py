# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 Безопасная дорога — ДЕФОЛТ, а отказ от неё — явный (bob-c3r.1, лечение P0 bob-l3t).

Флаг, выставленный в untracked-файле на одной машине, — не фикс: на чистом клоне он снова
OFF, и P0 возвращается. Поэтому дефолт живёт в КОДЕ
(:func:`bob.runtime.wiring.coding._uses_isolated_clone`), а owner при желании отказывается
ЯВНО (``coder.isolated_clone: false``).

🔴 Гард — про ПОВЕДЕНИЕ СОБРАННОЙ ПРОВОДКИ на конфиге, где ключа НЕТ ВОВСЕ (§0.3 п.12), и
про ОБЕ половины одной гарантии сразу: рабочее место — клон со своим ``.git`` И окружение
спавна без кредов owner'а. Проверять их порознь нельзя: три чтения флага, разъехавшись,
дают ПОЛУ-включённое состояние, которое звучит как включённое.

Конфиг собирается НАСТОЯЩИМ :class:`ConfigLoader` из yaml формы живого файла — иначе тест
доказывал бы дефолт словаря в тесте, а не дефолт, с которым Боб поднимется у владельца.
Каждое утверждение об отсутствии кредов идёт с КОНТРОЛЕМ (§0.3 п.5): при явном отказе те же
креды в окружении спавна ЕСТЬ, то есть дорога к ним реально существует.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters import GitClone, GitWorktree
from bob.infrastructure.config.loader import ConfigLoader
from bob.runtime.config import _section
from bob.runtime.wiring.coding import _build_workspace
from tests.support.wired_spawn_env import wired_spawn_envs

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

#: Креды owner'а в окружении процесса Боба, которые спавн claude видеть не должен.
_OWNER_GH_TOKEN = "ghp_owner_token_must_not_reach_the_spawn"
_OWNER_SSH_AGENT = "/tmp/owner-ssh-agent.sock"  # noqa: S108 - строка окружения, не файл


def _loaded(tmp_path: Path, coder_lines: str = "") -> Mapping[str, object]:
    """Конфиг НАСТОЯЩЕГО загрузчика из yaml формы живого ``config/bob.yaml``.

    ``coder_lines`` дописывается в секцию ``coder``; пусто → ключа
    ``isolated_clone`` в конфиге НЕТ ВОВСЕ, что и есть проверяемый случай.
    """
    path = tmp_path / "bob.yaml"
    path.write_text(
        "coder:\n"
        "  enabled: true\n"
        "  interactive: true\n"
        f"  clone_root: {tmp_path / 'clones'}\n" + coder_lines,
        encoding="utf-8",
    )
    return ConfigLoader(yaml_path=path, env={}).load()


def _coder(tmp_path: Path, coder_lines: str = "") -> Mapping[str, object]:
    return _section(_loaded(tmp_path, coder_lines), "coder")


def _owner_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Положить в окружение процесса Боба креды, до которых спавн доставать не должен."""
    monkeypatch.setenv("GH_TOKEN", _OWNER_GH_TOKEN)
    monkeypatch.setenv("SSH_AUTH_SOCK", _OWNER_SSH_AGENT)


def _config_pairs(env: dict[str, str] | None) -> set[tuple[str, str]]:
    assert env is not None
    count = int(env["GIT_CONFIG_COUNT"])
    return {
        (env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"]) for i in range(count)
    }


# --------------------------------------------------------------------------- #
# Ключа нет вовсе → обе половины гарантии на месте
# --------------------------------------------------------------------------- #


def test_a_config_without_the_key_puts_bobs_workplace_in_a_clone(tmp_path: Path) -> None:
    assert isinstance(_build_workspace(_coder(tmp_path)), GitClone)


def test_a_config_without_the_key_keeps_the_owners_credentials_out_of_both_spawns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Вторая половина той же гарантии: клон закрывает ЛОКАЛЬНУЮ дорогу к стволу, изоляция —
    # АМБИЕНТНУЮ сетевую. Полу-включённое состояние звучало бы как включённое.
    _owner_credentials(monkeypatch)

    for env in wired_spawn_envs(_loaded(tmp_path)):
        assert env is not None
        assert "GH_TOKEN" not in env
        assert "SSH_AUTH_SOCK" not in env
        assert ("credential.helper", "") in _config_pairs(env)
        assert env["GIT_CONFIG_GLOBAL"].startswith(str(tmp_path / "clones"))


def test_the_control_shows_those_credentials_are_really_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 🔴 Контроль (§0.3 п.5): при ЯВНОМ отказе те же креды в окружении спавна есть. Без
    # него зелёный тест выше означал бы лишь «кредов не было и так».
    _owner_credentials(monkeypatch)

    for env in wired_spawn_envs(_loaded(tmp_path, "  isolated_clone: false\n")):
        assert env is not None
        assert env["GH_TOKEN"] == _OWNER_GH_TOKEN
        assert env["SSH_AUTH_SOCK"] == _OWNER_SSH_AGENT


# --------------------------------------------------------------------------- #
# Явный отказ owner'а уважается — во всех формах, которыми его пишут
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("written", ["false", '"false"', '"no"', '"off"', "0"])
def test_an_explicit_refusal_returns_the_previous_worktree(
    tmp_path: Path, written: str
) -> None:
    coder = _coder(tmp_path, f"  isolated_clone: {written}\n")

    assert isinstance(_build_workspace(coder), GitWorktree)


@pytest.mark.parametrize("written", ["true", '"true"', '"yes"', '"on"', "1"])
def test_an_explicit_yes_is_the_same_road_as_the_default(
    tmp_path: Path, written: str
) -> None:
    coder = _coder(tmp_path, f"  isolated_clone: {written}\n")

    assert isinstance(_build_workspace(coder), GitClone)


# --------------------------------------------------------------------------- #
# 🔴 «Включено только на вид» — громкий отказ, а не тихая дорога
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("written", ['""', '"мусор"', '"maybe"', '"да"', "[]"])
def test_a_value_that_only_looks_configured_is_refused_loudly(
    tmp_path: Path, written: str
) -> None:
    # Ровно класс этого эпика: значение, которое ЧИТАЕТСЯ как настройка, не смеет молча
    # решать судьбу защиты. Прежний ``_flag`` любую нераспознанную строку превращал в
    # False — то есть в безопасность, выключенную опечаткой при включённом на вид ключе.
    coder = _coder(tmp_path, f"  isolated_clone: {written}\n")

    with pytest.raises(ValueError, match=r"coder\.isolated_clone"):
        _build_workspace(coder)
