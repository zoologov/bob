# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Как Боб понимает ПУТЬ, заданный в конфиге — одно правило на весь проект (bob-a6b.15).

Правило одно и оно в три ветки: АБСОЛЮТНОЕ значение уважается как есть, значение с ``~``
раскрывается по домашнему каталогу, ОТНОСИТЕЛЬНОЕ привязывается к корню проекта (а не к
текущему каталогу процесса).

🔴 Почему это отдельный тест-модуль, а не строчка в тестах identity: на этом правиле уже
дважды горело. BOB-087.D5b — относительный путь рабочего места, разрешённый от ``cwd``, и
мёртвый в проде реюз worktree. bob-a6b.15 — абсолютный путь к приватному ключу, склеенный с
корнем репозитория (``/Users/o/bob//Users/o/.config/bob/secrets/...``), то есть ЕДИНСТВЕННАЯ
безопасная конфигурация (ключи вне дерева репозитория) оказалась нерабочей.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bob.kernel.config_paths import under_root

if TYPE_CHECKING:
    import pytest


def test_an_absolute_value_is_used_exactly_as_it_was_written() -> None:
    # 🔴 Репро bob-a6b.15: корень НЕ приклеивается к уже абсолютному значению.
    root = Path("/Users/o/bob")
    key = "/Users/o/.config/bob/secrets/bob-ai-work.private-key.pem"

    assert under_root(key, root=root) == Path(key)


def test_an_absolute_value_outside_the_root_stays_outside() -> None:
    # Ключи ЖИВУТ вне дерева репозитория (bob-zmp: read_code отдавал их содержимое), значит
    # «вне корня» — не экзотика, а штатная форма.
    resolved = under_root("/Volumes/keys/work.pem", root=Path("/Users/o/bob"))

    assert resolved == Path("/Volumes/keys/work.pem")
    assert not str(resolved).startswith("/Users/o/bob")


def test_a_relative_value_is_anchored_to_the_root(tmp_path: Path) -> None:
    assert under_root(".secrets/work.pem", root=tmp_path) == tmp_path / ".secrets/work.pem"


def test_a_relative_value_ignores_the_current_directory(tmp_path: Path) -> None:
    # 🔴 Урок BOB-087.D5b: разрешение от ``cwd`` зелено в тестах (они и так стоят в корне) и
    # мертво в проде, где процесс запущен из другого каталога. Здесь ``root`` заведомо НЕ
    # равен текущему каталогу, поэтому обе стороны утверждаются разом: путь пришёл от корня и
    # НЕ от cwd. Без ``chdir`` сознательно: тест из ``tests/domain``, меняющий cwd, ломает
    # фазу статистики mutmut (она резолвит ``source_paths`` относительно текущего каталога) —
    # то есть отобрал бы у этого правила мутационный гейт. Настоящая ловушка с одноимённым
    # файлом рядом с cwd стоит в стековом тесте на настоящем openssl.
    assert Path.cwd() != tmp_path

    resolved = under_root(".secrets/work.pem", root=tmp_path)

    assert resolved == tmp_path / ".secrets/work.pem"
    assert resolved != Path.cwd() / ".secrets/work.pem"


def test_a_home_relative_value_expands_to_the_home_not_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 🔴 ``~/.config/bob/secrets/...`` — то, как owner называет место ключей. Для pathlib
    # тильда НЕ абсолютна, поэтому без раскрытия она склеилась бы с корнем репозитория
    # (``<repo>/~/.config/...``) — тот же дефект, только другой формой записи.
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    resolved = under_root("~/.config/bob/secrets/work.pem", root=tmp_path / "repo")

    assert resolved == home / ".config/bob/secrets/work.pem"


def test_a_path_object_is_accepted_like_a_string(tmp_path: Path) -> None:
    # Значение приезжает и строкой (env/YAML), и путём (композиция) — правило одно.
    assert under_root(Path(".clones"), root=tmp_path) == tmp_path / ".clones"


def test_the_rule_does_not_require_the_path_to_exist(tmp_path: Path) -> None:
    # Чистое правило: файловую систему оно не трогает и о существовании не судит — иначе
    # его нельзя было бы применить к пути, который ещё только будет создан.
    resolved = under_root("does/not/exist/yet.pem", root=tmp_path)

    assert resolved == tmp_path / "does/not/exist/yet.pem"
    assert not resolved.exists()
