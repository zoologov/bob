# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit-тесты ядра «репозиторий, которым распоряжается модель» (BOB-089, bob-a6b.14).

Ядро решает две вещи и ничего не исполняет: какой ФОРМОЙ Боб зовёт git в каталоге, за
содержимое которого отвечает модель, и какие ключи локального конфига этого каталога
означают «дальше не идём». Здесь измеряется сила именно решений (mutation-цель).

🔴 Что именно ПОВЕДЕНИЕ настоящего git — проверяется на настоящем git
(``tests/infrastructure/coding/test_untrusted_repo_real_git.py``): что хук не исполнился,
что ветка не уехала в апстрим. Фейк доказал бы контракт фейка (§0.3 п.4).
"""

from __future__ import annotations

from bob.coding.untrusted_repo import (
    LOCAL_CONFIG_QUERY,
    hardened_git_argv,
    unsafe_local_config,
)

# --------------------------------------------------------------------------- #
# hardened_git_argv — чем наш вызов не даёт каталогу исполнить код в процессе Боба
# --------------------------------------------------------------------------- #


def test_the_hooks_directory_is_pointed_away_from_the_repository() -> None:
    # 🔴 Главная строка беады: хуки — ЕДИНСТВЕННЫЙ вектор, которому не нужен конфиг
    # (модель просто пишет файлы в ``<клон>/.git/hooks``), поэтому он закрывается ФОРМОЙ
    # вызова, а не проверкой конфига. На настоящем git 2.49 без этой пары исполнились все
    # три хука (pre-commit / post-commit / pre-push) в процессе Боба.
    assert "-c" in hardened_git_argv("git")
    assert "core.hooksPath=/dev/null" in hardened_git_argv("git")


def test_the_filesystem_monitor_command_is_switched_off() -> None:
    # ``core.fsmonitor`` — значение исполняется как КОМАНДА на ``add``/``status``
    # (воспроизведено). Пара в argv бьёт локальный конфиг клона.
    assert "core.fsmonitor=false" in hardened_git_argv("git")


def test_commit_signing_is_switched_off_so_the_named_gpg_program_never_runs() -> None:
    # ``commit.gpgsign=true`` + ``gpg.program=<скрипт>`` в локальном конфиге — исполнение
    # произвольной команды на нашем ``commit`` (воспроизведено). Гасится не имя программы,
    # а сама подпись: тогда ``gpg.program`` не нужен ни в каком виде.
    assert "commit.gpgSign=false" in hardened_git_argv("git")


def test_every_pin_is_passed_as_its_own_c_pair_before_the_subcommand() -> None:
    # Форма фиксированная: каждая пара — отдельные ``-c`` и ``key=value``, ни одной
    # склейки. И весь префикс стоит ДО подкоманды, иначе git читает его как аргумент
    # подкоманды.
    argv = hardened_git_argv("git")

    assert argv[0] == "git"
    pins = argv[1:]
    assert len(pins) % 2 == 0
    assert pins[::2] == ["-c"] * (len(pins) // 2)
    assert all("=" in pin for pin in pins[1::2])


def test_the_repository_is_addressed_by_minus_c_when_a_path_is_given() -> None:
    # ``-C <путь>`` стоит ПОСЛЕ пар: путь — динамический слот, пары — фиксированные.
    argv = hardened_git_argv("git", path="/clone dir")

    assert argv[-2:] == ["-C", "/clone dir"]
    assert "core.hooksPath=/dev/null" in argv


def test_without_a_path_the_form_carries_no_repository_argument() -> None:
    # ``git clone`` заводит каталог, которого ещё нет: ``-C`` тут нечего давать, а пары
    # нужны (клон исполняет ``post-checkout`` из шаблона).
    assert "-C" not in hardened_git_argv("git")


def test_the_injected_git_binary_is_used() -> None:
    assert hardened_git_argv("my-git", path="/clone")[0] == "my-git"


def test_the_local_config_query_asks_the_repository_scope_in_a_nul_form() -> None:
    # 🔴 ``--local`` (не полный ``--list``): полный показал бы конфиг ВЛАДЕЛЬЦА, и проверка
    # начала бы судить его настройки. ``-z`` — потому что значение ключа может содержать
    # перевод строки, и построчный разбор увидел бы выдуманные ключи.
    assert LOCAL_CONFIG_QUERY == ("config", "--local", "--list", "-z")


# --------------------------------------------------------------------------- #
# unsafe_local_config — ALLOW-список: что вообще имеет право лежать в конфиге клона
# --------------------------------------------------------------------------- #


def _listing(*pairs: tuple[str, str]) -> str:
    """Собрать вывод ``git config --local --list -z``: записи через NUL, ключ\\nзначение."""
    return "".join(f"{key}\n{value}\0" for key, value in pairs)


#: Ровно то, что оставляют в конфиге ``git clone`` + наша последовательность заведения
#: клона на этой машине (снято с настоящего git 2.49, а не выписано из документации).
_A_CLEAN_CLONE = (
    ("core.repositoryformatversion", "0"),
    ("core.filemode", "true"),
    ("core.bare", "false"),
    ("core.logallrefupdates", "true"),
    ("core.ignorecase", "true"),
    ("core.precomposeunicode", "true"),
    ("remote.origin.url", "https://github.com/org/bob.git"),
    ("remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"),
    ("branch.main.remote", "origin"),
    ("branch.main.merge", "refs/heads/main"),
    ("branch.bob/task.remote", "origin"),
    ("branch.bob/task.merge", "refs/heads/bob/task"),
    ("user.name", "bob[ai]"),
    ("user.email", "424242+bob-ai-work[bot]@users.noreply.github.com"),
)


def test_a_clone_we_set_up_ourselves_is_not_reported_as_unsafe() -> None:
    # Ложный отказ здесь стоит дорого: он остановил бы ЛЕГИТИМНУЮ работу Боба.
    assert unsafe_local_config(_listing(*_A_CLEAN_CLONE)) == ()


def test_an_empty_listing_is_safe() -> None:
    assert unsafe_local_config("") == ()


def test_a_content_filter_is_reported_because_argv_cannot_switch_it_off() -> None:
    # 🔴 ФАКТ (настоящий git): ``filter.<d>.clean`` исполнился на ``add -A`` ДАЖЕ с полным
    # набором пар в argv — у фильтров нет ключа-выключателя, гасить их нечем. Значит
    # единственный честный ответ — не идти дальше.
    assert unsafe_local_config(_listing(("filter.evil.clean", "/nowhere/x.sh"))) == (
        "filter.evil.clean",
    )


def test_a_push_url_rewrite_is_reported_because_it_survives_pushing_by_value() -> None:
    # 🔴 ФАКТ: ``url.<апстрим>.pushInsteadOf`` увёз ветку В АПСТРИМ даже когда push шёл по
    # ЗНАЧЕНИЮ URL форка — перезапись адреса происходит ПОСЛЕ разбора argv.
    listing = _listing(("url.https://github.com/owner/bob.git.pushinsteadof", "https://f"))

    assert unsafe_local_config(listing) == ("url.https://github.com/owner/bob.git.pushinsteadof",)


def test_a_second_push_address_on_the_remote_is_reported() -> None:
    # Push по значению делает ``remote.origin.pushurl`` бессильным, но его наличие само
    # означает, что каталог трогали не мы: отказываем громко.
    assert unsafe_local_config(_listing(("remote.origin.pushurl", "https://x"))) == (
        "remote.origin.pushurl",
    )


def test_a_credential_helper_in_the_clone_is_reported() -> None:
    # Хелпер — не только исполнение команды: git отдаёт ему УСПЕШНЫЕ реквизиты на
    # сохранение, то есть локальный хелпер получил бы токен владельца.
    assert unsafe_local_config(_listing(("credential.helper", "/nowhere/steal.sh"))) == (
        "credential.helper",
    )


def test_an_included_config_file_is_reported_because_it_hides_its_keys() -> None:
    # 🔴 ФАКТ, из-за которого проверка сделана ALLOW-списком: ``include.path`` подключает
    # ФАЙЛ, ключи которого ``config --local --list`` НЕ показывает (``--get`` отвечает
    # rc=1), а фильтр из этого файла исполняется. Перечень «опасных ключей» такую дорогу
    # не увидел бы вовсе — а незнакомый ключ виден.
    assert unsafe_local_config(_listing(("include.path", "/nowhere/extra.cfg"))) == (
        "include.path",
    )


def test_the_per_worktree_config_extension_is_reported_for_the_same_reason() -> None:
    # 🔴 ФАКТ: с ``extensions.worktreeConfig=true`` ключи уезжают в ``.git/config.worktree``
    # — ``--local --list`` их не видит, а git их применяет (проверено на core.hooksPath).
    listing = _listing(("extensions.worktreeconfig", "true"))

    assert unsafe_local_config(listing) == ("extensions.worktreeconfig",)


def test_the_object_format_extension_stays_allowed() -> None:
    # Единственное расширение, которое пишет сам git и которое не несёт ни кода, ни адреса.
    assert unsafe_local_config(_listing(("extensions.objectformat", "sha256"))) == ()


def test_an_unknown_core_key_is_reported_even_when_it_looks_harmless() -> None:
    # ALLOW-список закрывает и то, о чём мы не догадались: ``core.sshCommand``,
    # ``core.pager``, ``core.editor``, ``core.gitProxy``, ``core.alternateRefsCommand`` —
    # каждый из них называет КОМАНДУ, и перечислять их по одному значило бы обещать
    # полноту, которой нет.
    assert unsafe_local_config(_listing(("core.sshcommand", "ssh -i /tmp/k"))) == (
        "core.sshcommand",
    )
    assert unsafe_local_config(_listing(("core.pager", "sh -c x"))) == ("core.pager",)
    assert unsafe_local_config(_listing(("core.hookspath", "../hooks"))) == ("core.hookspath",)


def test_an_alias_is_reported() -> None:
    assert unsafe_local_config(_listing(("alias.st", "!touch /tmp/x"))) == ("alias.st",)


def test_every_offending_key_is_reported_not_just_the_first() -> None:
    # Отказ должен называть ВСЁ, что нашли: иначе owner чинит по одному ключу за прогон.
    listing = _listing(
        ("core.filemode", "true"),
        ("filter.a.clean", "x"),
        ("diff.b.textconv", "y"),
        ("merge.c.driver", "z"),
    )

    assert unsafe_local_config(listing) == ("diff.b.textconv", "filter.a.clean", "merge.c.driver")


def test_a_duplicated_offending_key_is_reported_once() -> None:
    listing = _listing(("filter.a.clean", "x"), ("filter.a.clean", "y"))

    assert unsafe_local_config(listing) == ("filter.a.clean",)


def test_a_branch_key_beyond_tracking_is_reported() -> None:
    # ``branch.<имя>.remote``/``.merge`` пишет сам git; всё остальное в этой секции —
    # чужая правка (``branch.<имя>.rebase``/``.pushRemote`` меняют, куда уедет работа).
    listing = _listing(("branch.bob/task.pushremote", "upstream"))

    assert unsafe_local_config(listing) == ("branch.bob/task.pushremote",)


def test_a_branch_name_with_dots_is_still_recognised_as_tracking() -> None:
    # Имя ветки — подсекция, и точки в ней законны: разбор идёт от КОНЦА ключа.
    assert unsafe_local_config(_listing(("branch.bob/fix.v2.merge", "refs/heads/x"))) == ()


def test_the_editor_helper_key_of_the_owner_s_ide_stays_allowed() -> None:
    # VS Code пишет ``branch.<имя>.vscode-merge-base`` (значение — имя ref'а, не команда),
    # когда owner открывает клон Боба в редакторе. Падать на этом было бы глупо.
    assert unsafe_local_config(_listing(("branch.main.vscode-merge-base", "origin/main"))) == ()


def test_a_key_with_upper_case_from_git_is_matched_case_insensitively() -> None:
    # git печатает секцию и имя в нижнем регистре, но полагаться на это в вопросе
    # безопасности нельзя: сверка регистронезависимая, а в отказ уезжает ключ КАК ЕСТЬ.
    assert unsafe_local_config(_listing(("Core.FileMode", "true"))) == ()
    assert unsafe_local_config(_listing(("Filter.Evil.Clean", "x"))) == ("Filter.Evil.Clean",)


def test_a_value_containing_a_newline_cannot_forge_a_key() -> None:
    # 🔴 Почему ``-z``: значение вправе содержать перевод строки. При построчном разборе
    # эта запись выглядела бы как ключ ``core.filemode`` + ключ ``filter.x.clean``.
    listing = _listing(("core.filemode", "true\nfilter.x.clean=/tmp/evil.sh"))

    assert unsafe_local_config(listing) == ()


def test_a_key_without_a_value_is_still_classified() -> None:
    # ``git config --local --list -z`` печатает ключ без значения (и без перевода строки),
    # когда ключ задан пустым: терять такую запись нельзя.
    assert unsafe_local_config("filter.a.clean\0") == ("filter.a.clean",)
    assert unsafe_local_config("core.bare\0") == ()


def test_surrounding_whitespace_in_the_listing_does_not_hide_a_key() -> None:
    assert unsafe_local_config("  filter.a.clean  \nx\0") == ("filter.a.clean",)
