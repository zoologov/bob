# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``_build_pr_integration`` — «gh открывает PR» или «ссылка owner'у» (BOB-089.D).

Это ЕДИНСТВЕННОЕ место, где решается, каким путём работа Боба доезжает до owner'а. Путь
ссылки заводится только тогда, когда он ОСМЫСЛЕН: рабочее место — клон
(``coder.isolated_clone``), у клона настроен форк на GitHub (``coder.fork_url``) и известен
апстрим (``coder.upstream_repo``). Любой неполный набор → прежний gh-путь, и это
доказывается РАВЕНСТВОМ сборки, а не «похожестью».

🔴 Развилка парная: адаптер и реплика Боба ОБЯЗАНЫ соответствовать друг другу. Собрать
ссылочный путь и оставить реплику «вот PR» значило бы соврать owner'у, поэтому здесь же
проверено, что use-case получает ``opens_pr`` согласованно с выбранным адаптером.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from bob.coding.adapters.fork_link import ForkCompareLink
from bob.coding.adapters.gh_pr import GhPullRequestOpener
from bob.runtime.wiring.coding import _build_coding_assistant, _build_pr_integration

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.coding.usecases.coding_assistant import WorkJournalRecorder
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.kernel.ports import Clock
    from bob.memory.ports import SelfActionRecorder
    from bob.social.usecases import Authorizer

_OWNER_ID = 27468732
_FORK_URL = "git@github.com:bobiverse-dev/bob.git"
_UPSTREAM = "zoologov/bob"


class _StubBot: ...


class _StubAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 5, tzinfo=UTC)


class _StubConnection: ...


class _StubRecorder:
    async def record_self_action(self, *args: object, **kwargs: object) -> None: ...


def _bot() -> BotLike:
    return cast("BotLike", _StubBot())


def _coder_deps() -> dict[str, object]:
    return {
        "repo": cast("SqliteConnection", _StubConnection()),
        "authorizer": cast("Authorizer", _StubAuthorizer()),
        "notifier_bot": _bot(),
        "stream_bot": _bot(),
        "chat_id": -100123,
        "topic_id": None,
        "owner_id": _OWNER_ID,
        "clock": cast("Clock", _StubClock()),
        "recorder": cast("SelfActionRecorder", _StubRecorder()),
        "work_journal": cast("WorkJournalRecorder", _StubRecorder()),
    }


def _integration(
    config: dict[str, object],
) -> tuple[GhPullRequestOpener | ForkCompareLink, bool]:
    return _build_pr_integration(cast("Mapping[str, object]", config))


# --------------------------------------------------------------------------- #
# Прежний gh-путь — везде, где ссылка не осмыслена (доказано равенством)
# --------------------------------------------------------------------------- #


def test_the_default_assembly_is_the_previous_gh_opener() -> None:
    opener, opens_pr = _integration({})

    assert type(opener) is GhPullRequestOpener
    assert opener._gh_bin == "gh"
    assert opens_pr is True


def test_a_clone_without_a_fork_keeps_the_gh_opener() -> None:
    # Форк не настроен → у клона нет remote'а вовсе, пушить некуда, ссылка бессмысленна.
    opener, opens_pr = _integration({"isolated_clone": True, "upstream_repo": _UPSTREAM})

    assert type(opener) is GhPullRequestOpener
    assert opens_pr is True


def test_a_clone_without_a_known_upstream_keeps_the_gh_opener() -> None:
    # Не зная апстрима, ссылку было бы некуда нацелить — гадать здесь нельзя.
    opener, opens_pr = _integration({"isolated_clone": True, "fork_url": _FORK_URL})

    assert type(opener) is GhPullRequestOpener
    assert opens_pr is True


def test_a_fork_on_a_foreign_host_keeps_the_gh_opener() -> None:
    # Форма сравнения — гитхабовская; для чужого remote'а честнее не давать ссылки.
    opener, opens_pr = _integration(
        {
            "isolated_clone": True,
            "fork_url": "https://gitlab.com/bobiverse-dev/bob.git",
            "upstream_repo": _UPSTREAM,
        }
    )

    assert type(opener) is GhPullRequestOpener
    assert opens_pr is True


def test_a_configured_fork_without_the_clone_flag_keeps_the_gh_opener() -> None:
    # Пока рабочее место — linked worktree, ветка уезжает в репозиторий owner'а, и PR
    # открывается как раньше. Ссылочный путь принадлежит клону.
    opener, opens_pr = _integration({"fork_url": _FORK_URL, "upstream_repo": _UPSTREAM})

    assert type(opener) is GhPullRequestOpener
    assert opens_pr is True


# --------------------------------------------------------------------------- #
# Ссылочный путь — только при полном наборе
# --------------------------------------------------------------------------- #


def test_a_fork_backed_clone_hands_the_owner_a_compare_link() -> None:
    opener, opens_pr = _integration(
        {"isolated_clone": True, "fork_url": _FORK_URL, "upstream_repo": _UPSTREAM}
    )

    assert type(opener) is ForkCompareLink
    assert opener._upstream == _UPSTREAM
    assert opener._fork == "bobiverse-dev/bob"  # слаг из ТОГО ЖЕ адреса, куда идёт push
    assert opener._base == "main"  # ствол апстрима — тот же, что у gh-пути
    assert opens_pr is False


# --------------------------------------------------------------------------- #
# Адаптер и реплика — из ОДНОГО решения (иначе Боб соврал бы)
# --------------------------------------------------------------------------- #


def test_the_assistant_speaks_the_link_line_when_it_cannot_open_a_pr() -> None:
    config = {
        "coder": {
            "enabled": True,
            "isolated_clone": True,
            "fork_url": _FORK_URL,
            "upstream_repo": _UPSTREAM,
        }
    }
    assistant = _build_coding_assistant(config, **_coder_deps())  # type: ignore[arg-type]

    assert assistant is not None
    assert type(assistant._pr_opener) is ForkCompareLink
    assert assistant._opens_pr is False


def test_the_assistant_keeps_the_pr_line_on_the_default_path() -> None:
    config = {"coder": {"enabled": True}}
    assistant = _build_coding_assistant(config, **_coder_deps())  # type: ignore[arg-type]

    assert assistant is not None
    assert type(assistant._pr_opener) is GhPullRequestOpener
    assert assistant._opens_pr is True
