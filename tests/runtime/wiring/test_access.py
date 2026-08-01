# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for composition-root access wiring — Authorizer built from config.

Focus: the ``owner_dm_chat_id`` plumbing (BOB-082.2). The kv repo is faked
because the owner-DM decision short-circuits before touching the allowlist store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bob.runtime.wiring.access import _build_authorizer

if TYPE_CHECKING:
    from bob.infrastructure.persistence import SqliteConnection

_OWNER = 7


class _FakeKvRepo:
    """Minimal kv double satisfying KvAllowlistStore (no grants stored)."""

    async def kv_get(self, key: str) -> str | None:  # noqa: ARG002
        return None

    async def kv_set(self, key: str, value: str) -> None:  # noqa: ARG002
        return None


def _repo() -> SqliteConnection:
    return cast("SqliteConnection", _FakeKvRepo())


async def test_owner_dm_chat_id_defaults_to_owner_id() -> None:
    # No explicit owner_dm_chat_id → the owner's own DM (chat.id == owner_id) is
    # authorized even though it is not in allowed_chat_ids.
    config = {"telegram": {"owner_id": _OWNER, "allowed_chat_ids": [100]}}

    authorizer = _build_authorizer(config, repo=_repo())

    assert await authorizer.is_authorized(user_id=_OWNER, chat_id=_OWNER) is True


async def test_explicit_owner_dm_chat_id_is_honoured() -> None:
    config = {
        "telegram": {
            "owner_id": _OWNER,
            "allowed_chat_ids": [100],
            "owner_dm_chat_id": 555,
        }
    }

    authorizer = _build_authorizer(config, repo=_repo())

    assert await authorizer.is_authorized(user_id=_OWNER, chat_id=555) is True
    # The owner_id chat is no longer the DM once overridden.
    assert await authorizer.is_authorized(user_id=_OWNER, chat_id=_OWNER) is False
