# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit-тесты чистого ядра ссылки «ветка в форке → форма создания PR» (BOB-089, срез D).

Ядро отвечает на два вопроса и ничего не исполняет: как из адреса форка достаётся его
``owner/repo`` и какой URL сравнения отдаётся owner'у. Здесь измеряется сила именно этих
решений (mutation-цель).

🔴 Почему ссылка, а не открытие PR: cross-repo PR из ПРИВАТНОГО форка невозможен —
installation-токен скоупится на одну установку, а форма сравнения требует читаемости обеих
сторон одним токеном (проверено три способа, не-цель PRD). Поэтому Боб доводит работу до
ветки в своём форке и отдаёт ссылку, а «Create pull request» жмёт owner.
"""

from __future__ import annotations

from bob.coding.pr_link import compare_url, repo_slug

# --------------------------------------------------------------------------- #
# repo_slug — чей форк на самом деле является целью push'а
# --------------------------------------------------------------------------- #


def test_the_slug_comes_from_the_scp_form_the_config_actually_carries() -> None:
    # 🔴 Слаг берётся из ТОГО ЖЕ ``coder.fork_url``, куда уходит push: иначе ссылка могла
    # бы указывать на один форк, а работа лежать в другом — тихая ложь owner'у.
    assert repo_slug("git@github.com:bobiverse-dev/bob.git") == "bobiverse-dev/bob"


def test_the_slug_comes_from_an_https_url_with_or_without_the_git_suffix() -> None:
    assert repo_slug("https://github.com/bobiverse-dev/bob.git") == "bobiverse-dev/bob"
    assert repo_slug("https://github.com/bobiverse-dev/bob") == "bobiverse-dev/bob"


def test_the_slug_survives_an_ssh_url_and_a_trailing_slash() -> None:
    assert repo_slug("ssh://git@github.com/bobiverse-dev/bob.git") == "bobiverse-dev/bob"
    assert repo_slug("https://github.com/bobiverse-dev/bob/") == "bobiverse-dev/bob"


def test_a_missing_fork_url_yields_no_slug() -> None:
    assert repo_slug("") == ""


def test_a_non_github_remote_yields_no_slug() -> None:
    # Форма сравнения — гитхабовская. Для чужого хоста честнее не иметь ссылки, чем
    # выдать заведомо нерабочую (в тестах на настоящем git форк вообще ``file://``).
    assert repo_slug("https://gitlab.com/bobiverse-dev/bob.git") == ""
    assert repo_slug("/srv/mirrors/bob.git") == ""


def test_an_unexpected_path_shape_yields_no_slug() -> None:
    # Ни глубже, ни короче ``owner/repo`` — иначе ссылка собиралась бы из догадки.
    assert repo_slug("https://github.com/bobiverse-dev") == ""
    assert repo_slug("https://github.com/bobiverse-dev/bob/tree/main") == ""


# --------------------------------------------------------------------------- #
# compare_url — что именно owner открывает одним нажатием
# --------------------------------------------------------------------------- #


def test_the_link_opens_the_prefilled_compare_form_of_the_fork_branch() -> None:
    assert compare_url(
        upstream="zoologov/bob", fork="bobiverse-dev/bob", branch="bob/pr-link", base="main"
    ) == (
        "https://github.com/zoologov/bob/compare/"
        "main...bobiverse-dev:bob:bob/pr-link?expand=1"
    )


def test_the_head_side_names_the_fork_owner_repo_and_branch() -> None:
    # ``owner:repo:branch`` — единственная форма, которой GitHub понимает голову из
    # ЧУЖОГО репозитория; ``owner:branch`` тут указал бы на репозиторий owner'а.
    url = compare_url(
        upstream="zoologov/bob", fork="bobiverse-dev/bob", branch="bob/task", base="main"
    )

    assert "...bobiverse-dev:bob:bob/task" in url


def test_the_form_is_prefilled_so_the_owner_only_presses_create() -> None:
    url = compare_url(
        upstream="zoologov/bob", fork="bobiverse-dev/bob", branch="bob/task", base="main"
    )

    assert url.endswith("?expand=1")


def test_the_base_is_the_configured_trunk_not_a_hardcoded_one() -> None:
    url = compare_url(
        upstream="zoologov/bob", fork="bobiverse-dev/bob", branch="bob/task", base="release"
    )

    assert "/compare/release...bobiverse-dev:bob:bob/task" in url


def test_the_branch_is_encoded_safely_yet_stays_readable() -> None:
    # Слэш ``bob/<slug>`` в пути легален и остаётся как есть (иначе ссылка стала бы
    # нечитаемой), а всё, что могло бы поехать в URL, экранируется.
    url = compare_url(
        upstream="zoologov/bob", fork="bobiverse-dev/bob", branch="bob/a b?x#y", base="main"
    )

    assert url == (
        "https://github.com/zoologov/bob/compare/"
        "main...bobiverse-dev:bob:bob/a%20b%3Fx%23y?expand=1"
    )
