# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Права инструментов живой сессии — чистое ядро denylist/allowlist (BOB-088, срез 3).

Предмет: :func:`bob.interactive.tool_permissions.tool_permission_argv` — то, чем спавн
параметризуется, чтобы необратимое не случилось МОЛЧА, а рутина ехала сама.

🔴 Каждое утверждение ниже про шаблоны — не выдумка, а запись живого прогона настоящим
``claude`` 2.1.233 (протокол в комментарии беады ``bob-c3r.3``): по каждому пункту
проверялось И событие отказа, И ЭФФЕКТ (двинулись ли refs, исчез ли каталог). Отсюда же
единственное отступление от текста ТЗ: ``Bash(rm -rf:*)`` в прогоне НЕ ловит ``rm -fr`` —
каталог был удалён, — поэтому в списке стоит ``Bash(rm:*)``.
"""

from __future__ import annotations

import pytest

from bob.interactive.tool_permissions import tool_permission_argv

# Команды, на которых denylist ПРОВЕРЕН живым прогоном (каждая дала permission_denied).
_MEASURED_DENIALS = [
    "git push origin master",
    "git push --force origin master",
    "git remote add evil https://example.com/evil.git",
    "git reset --hard HEAD",
    "rm -rf .git",
    "rm -fr treasure",
    "gh pr merge 1 --squash",
    "curl -s https://example.com -o page.html",
    "wget -q https://example.com -O page.html",
]


def _denied(argv: list[str]) -> list[str]:
    """Шаблоны запрета из хвоста argv (всё после ``--disallowedTools``)."""
    assert "--disallowedTools" in argv
    return argv[argv.index("--disallowedTools") + 1 :]


def _allowed(argv: list[str]) -> list[str]:
    """Шаблоны разрешения (между ``--allowedTools`` и ``--disallowedTools``)."""
    if "--allowedTools" not in argv:
        return []
    return argv[argv.index("--allowedTools") + 1 : argv.index("--disallowedTools")]


def _blocks(pattern: str, command: str) -> bool:
    """Ловит ли шаблон команду — ПРЕФИКСНОЕ правило самого CLI (перемерено прогоном)."""
    body = pattern.removeprefix("Bash(").removesuffix(":*)").removesuffix(")")
    return command.startswith(body)


# --------------------------------------------------------------------------- #
# Запрет необратимого стоит ВСЕГДА и не выключается словом
# --------------------------------------------------------------------------- #


def test_the_default_spawn_already_forbids_the_irreversible() -> None:
    # 🔴 Урок среза 1: защита, которую можно выключить одним ключом в untracked-конфиге,
    # в проде оказывается выключенной. Параметра «без запрета» здесь нет ВООБЩЕ.
    argv = tool_permission_argv()

    assert argv[0] == "--disallowedTools"
    assert len(_denied(argv)) == len(set(_denied(argv)))  # без дублей
    assert "--allowedTools" not in argv  # рутина — отдельное решение владельца


@pytest.mark.parametrize("command", _MEASURED_DENIALS)
def test_every_command_measured_as_denied_is_covered_by_a_pattern(command: str) -> None:
    # Дословный протокол живых прогонов: каждая из этих команд получила отказ CLI.
    patterns = _denied(tool_permission_argv())

    assert any(_blocks(pattern, command) for pattern in patterns), command


def test_the_rm_pattern_is_the_broad_one_because_the_narrow_one_leaked() -> None:
    # 🔴 Замер: Bash(rm -rf:*) НЕ поймал `rm -fr treasure` — каталог был удалён.
    assert "Bash(rm:*)" in _denied(tool_permission_argv())
    assert "Bash(rm -rf:*)" not in _denied(tool_permission_argv())


@pytest.mark.parametrize(
    "routine_command",
    [
        "git status --short",
        "git add -A",
        'git commit -m "срез 3"',
        "uv run pytest",
        "uv run ruff check src/",
        "uv run mypy src/",
        "bd ready",
        "beadloom lint --strict",
    ],
)
def test_the_routine_of_the_pipeline_is_not_forbidden(routine_command: str) -> None:
    # Гибрид, которого хотел владелец: запрещено только необратимое и наружное.
    patterns = _denied(tool_permission_argv())

    assert not any(_blocks(pattern, routine_command) for pattern in patterns)


# --------------------------------------------------------------------------- #
# Рутина конвейера — ЯВНОЕ разрешение владельца (coder.pipeline_tools)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "routine_command",
    [
        "git status",
        "git add",
        "git commit",
        "uv run pytest",
        "uv run ruff",
        "uv run mypy",
        "bd",
        "beadloom",
    ],
)
def test_the_routine_list_names_what_the_pipeline_lives_on(routine_command: str) -> None:
    # 🔴 Замер: БЕЗ этого списка `git add -A` и `git commit` отказываются встроенным
    # гейтом CLI («This command requires approval») — конвейер встал бы на первом коммите.
    allowed = _allowed(tool_permission_argv(routine=True))

    assert any(_blocks(pattern, routine_command) for pattern in allowed), routine_command


def test_the_routine_list_does_not_open_the_forbidden() -> None:
    # 🔴 Замерено на настоящем CLI: запрет СИЛЬНЕЕ разрешения. Но полагаться на это
    # мало — сам список рутины не смеет накрывать необратимое.
    allowed = _allowed(tool_permission_argv(routine=True))

    for command in _MEASURED_DENIALS:
        assert not any(_blocks(pattern, command) for pattern in allowed), command


def test_the_routine_list_keeps_the_whole_denylist() -> None:
    assert _denied(tool_permission_argv(routine=True)) == _denied(tool_permission_argv())


# --------------------------------------------------------------------------- #
# Доразрешение: ОДИН пункт, на ОДИН заход
# --------------------------------------------------------------------------- #


def test_an_approved_command_is_allowed_exactly_and_its_pattern_steps_aside() -> None:
    # 🔴 Замер: разрешение работает, только если снять И шаблон запрета (запрет сильнее),
    # И назвать ТОЧНУЮ команду — по ней модель повторила ровно её, push прошёл.
    argv = tool_permission_argv(allow_once="git push origin master")

    assert "Bash(git push origin master)" in _allowed(argv)
    assert "Bash(git push:*)" not in _denied(argv)


def test_an_approval_lifts_only_what_it_has_to() -> None:
    argv = tool_permission_argv(allow_once="git push origin master")

    # Всё остальное необратимое остаётся запрещённым в ТОМ ЖЕ заходе.
    for command in ["rm -rf .git", "curl -s https://example.com", "gh pr merge 1"]:
        assert any(_blocks(pattern, command) for pattern in _denied(argv)), command


def test_the_approval_is_one_shot_because_it_is_an_argument_and_not_a_state() -> None:
    # 🔴 Одноразовость СТРУКТУРНА: снятие живёт в параметре одного вызова, хранить его
    # негде. Следующий спавн зовёт ту же функцию без него — и список снова полон.
    tool_permission_argv(allow_once="rm -rf .git")

    assert "Bash(rm:*)" in _denied(tool_permission_argv())


def test_an_approval_that_no_pattern_forbids_still_asks_for_nothing_extra() -> None:
    # Отказ мог прийти от ВСТРОЕННОГО гейта CLI (у нас такой команды в списке нет):
    # тогда снимать нечего, а точечное разрешение всё равно нужно.
    argv = tool_permission_argv(allow_once="git add -A")

    assert "Bash(git add -A)" in _allowed(argv)
    assert _denied(argv) == _denied(tool_permission_argv())


@pytest.mark.parametrize(
    "junk",
    [
        "",
        "   ",
        "\n",
        "--dangerously-skip-permissions",
        "  --add-dir /etc  ",
        "rm -rf /\x00",
        "git push\norigin master",
        "git push origin master)",
    ],
)
def test_a_command_that_cannot_be_an_approval_lifts_nothing(junk: str) -> None:
    # 🔴 Худший исход мусорного значения — тихо снять запрет: сессия поехала бы БЕЗ
    # барьера, и выглядело бы это как «владелец разрешил». Мусор не снимает ничего.
    argv = tool_permission_argv(allow_once=junk)

    assert "--allowedTools" not in argv
    assert _denied(argv) == _denied(tool_permission_argv())


def test_an_approval_travels_together_with_the_routine_list() -> None:
    argv = tool_permission_argv(routine=True, allow_once="git push origin master")
    allowed = _allowed(argv)

    assert "Bash(git push origin master)" in allowed
    assert any(_blocks(pattern, "git commit -m x") for pattern in allowed)
