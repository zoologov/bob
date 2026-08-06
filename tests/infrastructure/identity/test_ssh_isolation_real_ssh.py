# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-SSH acceptance: спавн не ходит ключом owner'а (bob-a6b.10).

Фейк здесь доказал бы контракт фейка (§0.3 п.4), а всё содержание беады — это ПОВЕДЕНИЕ
настоящего OpenSSH: как он собирает список личностей из командной строки, из
``~/.ssh/config`` и из агента. Ровно на этом изоляция среза C и прогорела: ssh она не
касалась вовсе, и ``ssh -T git@github.com`` из прод-окружения спавна отвечал
«Hi <owner>! You've successfully authenticated», а ``git ls-remote`` апстрима по ssh
проходил (проверено ревьюером, воспроизведено этой волной).

Инструмент проверки — ``ssh -G``: это РАЗБОР конфигурации самим ssh (что он будет делать),
без единого сетевого пакета. Не наше сопоставление строк, а его собственный парсер. Отказ
аутентификации от настоящего GitHub проверяется отдельно и opt-in
(``test_ssh_road_live_smoke.py``).

Каждый тест — ПАРА: сначала контроль «дорога РЕАЛЬНО есть», затем то же в изоляции.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from bob.identity.spawn_isolation import controlled_ssh_command

pytestmark = pytest.mark.skipif(
    shutil.which("ssh") is None, reason="real ssh is not available on this host"
)

#: Хост в тестах — настоящий адрес GitHub, но ``-G`` только РАЗБИРАЕТ конфигурацию для него
#: и никуда не соединяется (стансы вида ``Host github.com`` иначе не сработали бы).
_HOST = "git@github.com"

#: Путь «ключа», которого нет: ровно то, что материализует адаптер.
_NOWHERE = "/nowhere/ssh-identity-disabled"


def _effective(*argv: str) -> dict[str, list[str]]:
    """Спросить у самого ssh, что он будет делать: ``ssh -G`` → ключ → список значений."""
    result = subprocess.run(
        [*argv, "-G", _HOST],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    config: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition(" ")
        config.setdefault(key.lower(), []).append(value)
    return config


def _controlled(**replace: str) -> dict[str, list[str]]:
    """Разбор ПРОД-команды ssh (опционально с подменой одного аргумента — для контроля)."""
    argv = shlex.split(controlled_ssh_command(identity=_NOWHERE))
    for old, new in replace.items():
        argv = [new if part == old else part for part in argv]
    return _effective(*argv)


def _owner_keys(config: dict[str, list[str]]) -> list[str]:
    """Личности из ``~/.ssh`` owner'а среди предложенных ssh (он печатает их с ``~``)."""
    home = str(Path.home())
    return [
        path
        for path in config.get("identityfile", [])
        if path.startswith(("~/.ssh/", f"{home}/.ssh/"))
    ]


# --------------------------------------------------------------------------- #
# Контроль: ключи owner'а РЕАЛЬНО предлагаются, иначе тесты ниже — вакуум
# --------------------------------------------------------------------------- #


def test_ambient_ssh_offers_the_owners_keys_from_his_home() -> None:
    config = _effective("ssh")

    if not _owner_keys(config):
        pytest.skip("на этом хосте ssh не предлагает ключей из ~/.ssh — паре нечего мерить")
    # И агентские личности при этом не отключены — вторая дорога тоже открыта.
    assert config["identitiesonly"] == ["no"]


# --------------------------------------------------------------------------- #
# 🔴 Изоляция: ssh предлагает ровно один «ключ», которого нет
# --------------------------------------------------------------------------- #


def test_the_controlled_command_offers_only_the_identity_that_does_not_exist() -> None:
    assert _controlled()["identityfile"] == [_NOWHERE]


def test_not_one_key_of_the_owner_survives_in_the_controlled_command() -> None:
    # 🔴 То самое, чего не хватало: ЯВНО названный IdentityFile замещает дефолтный список
    # ``~/.ssh/id_*``. Без него ssh здоровался как owner даже с ``IdentitiesOnly=yes``.
    assert _owner_keys(_controlled()) == []


def test_identities_offered_by_an_agent_are_refused_two_independent_ways() -> None:
    config = _controlled()
    assert config["identitiesonly"] == ["yes"]
    assert config["identityagent"] == ["none"]


def test_the_controlled_command_never_waits_for_a_prompt() -> None:
    assert _controlled()["batchmode"] == ["yes"]


# --------------------------------------------------------------------------- #
# 🔴 Почему ``-F none``: IdentityFile — МНОГОЗНАЧНАЯ опция, конфиг ДОБАВЛЯЕТ ключ
# --------------------------------------------------------------------------- #


def test_a_users_ssh_config_adds_its_key_to_ours_instead_of_being_overridden(
    tmp_path: Path,
) -> None:
    # 🔴 Тот же класс ловушки, что ``remote.origin.pushurl`` в bob-5ao: ключ МНОГОЗНАЧНЫЙ,
    # и значение из конфига не замещается нашим, а ДОБАВЛЯЕТСЯ в список. Стансa
    # ``Host github.com / IdentityFile ~/.ssh/id_ed25519`` — самая обычная запись в
    # ``~/.ssh/config``, и без ``-F none`` она вернула бы ключ owner'а в список
    # предлагаемых, то есть изоляция держалась бы на том, чего в чужом файле нет.
    planted_key = tmp_path / "planted-id_ed25519"
    config_file = tmp_path / "planted-config"
    config_file.write_text(f"Host *\n  IdentityFile {planted_key}\n", encoding="utf-8")

    # Контроль: та же прод-команда, но читающая подложенный конфиг вместо ``none``.
    with_config = _controlled(none=str(config_file))
    assert str(planted_key) in with_config["identityfile"]

    # И она же как есть: файл не читается вовсе, в списке только наш несуществующий путь.
    assert _controlled()["identityfile"] == [_NOWHERE]
