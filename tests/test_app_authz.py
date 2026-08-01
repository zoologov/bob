# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for authz wiring in the composition root (bob.app).

Verifies that ``build_application`` constructs an :class:`Authorizer` from the
``telegram.owner_id`` / ``telegram.allowed_chat_ids`` config over a SQLite-backed
allowlist, hands it to the multi-bot gateway, and that the wired gate end-to-end
(via the central router) drops an unauthorized user in Bob's topic while a
persisted ``/authorize`` grant from the owner in General survives a restart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.app import build_application
from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram.multibot import BotIdentity
from bob.memory.adapters import SqliteMemoryRepo
from bob.social.adapters.allowlist_store import KvAllowlistStore
from bob.social.adapters.soul_store import SoulStore
from bob.social.usecases import Authorizer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.infrastructure.telegram.gateway import UpdateLike
    from bob.kernel import ports

_OWNER = 1
_CHAT = 100
_TOPIC = 32


class _Provider:
    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        return "ok"


class _Msg:
    def __init__(
        self, text: str | None = None, *, thread_id: int | None = None
    ) -> None:
        self.message_id = 1
        self.text = text
        self.message_thread_id: int | None = thread_id


class _Chat:
    def __init__(self, chat_id: int, chat_type: str = "supergroup") -> None:
        self.id = chat_id
        self.type = chat_type


class _User:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.full_name = "U"


class _Update:
    def __init__(
        self,
        update_id: int,
        *,
        chat_id: int,
        user_id: int,
        text: str,
        thread_id: int | None = _TOPIC,
    ) -> None:
        self.update_id = update_id
        self.message = _Msg(text, thread_id=thread_id)
        self.message.message_id = update_id
        self.effective_chat = _Chat(chat_id)
        self.effective_user = _User(user_id)


class _Bot:
    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,  # noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _Msg:
        return _Msg(text)

    async def set_message_reaction(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        message_id: int,  # noqa: ARG002
        reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        # BOB-018: react-only seam; fakes accept the BotLike reaction call.
        return True

    async def send_chat_action(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        action: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        rich_message: object,  # noqa: ARG002
        message_thread_id: int | None = None,# noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _Msg:
        return _Msg()

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _Msg:
        # BOB-035: BotLike parity; this fake's tests never post a photo.
        raise NotImplementedError  # pragma: no cover


    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _Msg:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

def _config(tmp_path: Path) -> dict[str, object]:
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 1},
        "telegram": {
            "poll_timeout": 1,
            "chat_id": _CHAT,
            "owner_id": _OWNER,
            "allowed_chat_ids": [_CHAT],
            "bob": {"token": "bob-tok", "topic_id": _TOPIC},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _build(tmp_path: Path):  # type: ignore[no-untyped-def]
    return build_application(
        config=_config(tmp_path),
        providers={0: _Provider(), 1: _Provider()},
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )


def test_build_application_wires_an_authorizer(tmp_path: Path) -> None:
    app = _build(tmp_path)
    assert isinstance(app.authorizer, Authorizer)


@pytest.mark.asyncio
async def test_wired_gate_routes_guest_in_topic_but_drops_foreign_chat(
    tmp_path: Path,
) -> None:
    # BOB-019 bob-apv.2: an unauthorized sender IN the allowed chat + Bob's topic is
    # a GUEST → Bob's pipeline (restricted mode is downstream). An unauthorized
    # sender OUTSIDE the allowed chat stays dropped (chat-scope intact). The owner is
    # the trusted path as ever.
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    app = _build(tmp_path)
    await app.startup()
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    app.event_bus.subscribe(MESSAGE_RECEIVED, handler)
    try:
        guest = await app.multibot.route(
            _Update(1, chat_id=_CHAT, user_id=555, text="hi"), BotIdentity.BOB
        )
        foreign = await app.multibot.route(
            _Update(2, chat_id=_CHAT + 1, user_id=555, text="hi", thread_id=None),
            BotIdentity.BOB,
        )
        owner = await app.multibot.route(
            _Update(3, chat_id=_CHAT, user_id=_OWNER, text="hi"), BotIdentity.BOB
        )
    finally:
        await app.shutdown()

    assert guest is True  # guest in Bob's topic reaches the pipeline
    assert foreign is False  # outside the allowed chat → still dropped
    assert owner is True
    # Only the guest (1) and the owner (3) reached the pipeline; the foreign chat
    # message (2) was dropped at the router.
    assert [event.update_id for event in received] == [1, 3]


@pytest.mark.asyncio
async def test_authorize_grant_survives_a_restart(tmp_path: Path) -> None:
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    app = _build(tmp_path)
    await app.startup()
    try:
        # The owner runs /authorize in General (no thread) → GUPPI consumes it.
        await app.multibot.route(
            _Update(
                1,
                chat_id=_CHAT,
                user_id=_OWNER,
                text="/authorize 555",
                thread_id=None,
            ),
            BotIdentity.GUPPI,
        )
    finally:
        await app.shutdown()

    # Restart: a fresh store on the same db must still see the grant.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    try:
        assert await KvAllowlistStore(repo).load() == {555}
    finally:
        await repo.close()
