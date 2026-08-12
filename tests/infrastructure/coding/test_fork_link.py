# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""ForkCompareLink — Боб отдаёт ссылку на создание PR и ничего не открывает (BOB-089.D).

Адаптер под тем же портом :class:`~bob.coding.ports.PullRequestOpener`, что и
``GhPullRequestOpener``, но принципиально другой по содержанию: он НЕ выполняет никакого
действия — ни ``gh``, ни сети, ни процесса. Его «результат» — предзаполненная форма
сравнения, по которой PR создаёт owner (вариант A решения owner'а: cross-repo PR из
приватного форка installation-токену недоступен).

Отсутствие исполнения здесь — инвариант, а не деталь реализации, поэтому оно проверяется
структурно: у адаптера нет ни ``runner``, ни импорта командного шва.
"""

from __future__ import annotations

import pytest

import bob.coding.adapters.fork_link as fork_link_module
from bob.coding.adapters.fork_link import ForkCompareLink
from bob.coding.adapters.gh_pr import PullRequestError
from bob.coding.ports import PullRequestOpener

_UPSTREAM = "zoologov/bob"
_FORK = "bobiverse-dev/bob"


def _link(*, base: str = "main") -> ForkCompareLink:
    return ForkCompareLink(upstream=_UPSTREAM, fork=_FORK, base=base)


async def test_the_branch_becomes_a_prefilled_compare_form() -> None:
    url = await _link().open("bob/pr-link", "title", "body")

    assert url == (
        "https://github.com/zoologov/bob/compare/"
        "main...bobiverse-dev:bob:bob/pr-link?expand=1"
    )


async def test_the_configured_trunk_is_the_base_of_the_form() -> None:
    url = await _link(base="release").open("bob/task", "title", "body")

    assert "/compare/release...bobiverse-dev:bob:bob/task" in url


async def test_an_unsafe_branch_is_refused_like_a_pr_would_be() -> None:
    # Тот же предохранитель, что у gh-адаптера: ссылка на ствол не собирается вовсе.
    with pytest.raises(PullRequestError):
        await _link().open("main", "title", "body")


async def test_a_missing_fork_or_upstream_is_refused_at_assembly() -> None:
    # Отказ приходит на СБОРКЕ (как у GitClone с кредами в URL): половина координат дала
    # бы ссылку в никуда, а owner доверяет присланному адресу.
    with pytest.raises(PullRequestError):
        ForkCompareLink(upstream="", fork=_FORK, base="main")
    with pytest.raises(PullRequestError):
        ForkCompareLink(upstream=_UPSTREAM, fork="", base="main")


def test_the_link_satisfies_the_same_port_as_the_gh_opener() -> None:
    # Подмена возможна только потому, что порт один: use-case не различает эти пути.
    assert isinstance(_link(), PullRequestOpener)


def test_the_link_path_exposes_no_merge_or_push_surface() -> None:
    public = {name for name in dir(ForkCompareLink) if not name.startswith("_")}

    assert "open" in public
    for forbidden in ("merge", "push", "land", "approve"):
        assert forbidden not in public


def test_the_link_path_has_no_command_runner_at_all() -> None:
    # 🔴 Инвариант: этот путь НИЧЕГО не исполняет. Отсутствие командного шва — то, что
    # делает «Боб не открывает PR» структурным свойством, а не обещанием в докстроке.
    assert not hasattr(fork_link_module, "ExecRunner")
    assert not hasattr(fork_link_module, "CommandRunner")
    assert not hasattr(_link(), "_runner")
