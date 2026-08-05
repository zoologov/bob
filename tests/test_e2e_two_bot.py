# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""BOB-003 BEAD-04 — two-bot integration e2e over the composition root.

``build_application`` now wires BOTH admin bots (Bob + GUPPI) into one
:class:`~bob.infrastructure.telegram.multibot.MultiBotGateway`: Bob is scoped to
his topic thread, GUPPI is the gatekeeper in General, and one poll drives both.
These tests prove that wiring end to end with fakes only — two fake aiogram bots
(no Telegram), fake LLM providers (no network), and a real temp SQLite database:

* (a) an unauthorized user in Bob's topic → GUPPI sends the visible reject and
  Bob's pipeline is NOT invoked (no reply from Bob's bot);
* (b) an authorized message in Bob's topic → Bob replies **into his thread**
  (``message_thread_id`` pinned to the topic);
* (c) owner ``/authorize <id>`` in General → consumed by GUPPI and persisted to
  the live SQLite allowlist (survives a restart);
* (d) a message in General / another topic → ignored by Bob (no Bob publish).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.app import Application, build_application
from bob.infrastructure.telegram.guppi import GUPPI_REJECT_TEXT
from bob.infrastructure.telegram.multibot import BotIdentity
from bob.memory.adapters import SqliteMemoryRepo
from bob.social.adapters.allowlist_store import KvAllowlistStore
from bob.social.adapters.soul_store import SoulStore
from tests.support.judge_stub import JUDGE_REPLY, is_judge_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from aiogram.types import InputRichMessage

    from bob.kernel.ports import LLMProvider

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32
_OWNER_ID = 27468732
_STRANGER_ID = 555
_OTHER_TOPIC_ID = 99
_REPLY = "Hello from Bob."


# --- Fakes at the external edges (no network, no Telegram) --------------------


class _Provider:
    """Fake LLMProvider returning a fixed reply (stands in for a tier)."""

    def __init__(self, *, reply: str) -> None:
        self.reply = reply

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        if is_judge_request(messages):  # BOB-049: model the judge choosing REPLY
            return JUDGE_REPLY
        return self.reply


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _FakeUser:
    id: int
    full_name: str = "Ada"


@dataclass
class _FakeChat:
    id: int
    type: str = "supergroup"


@dataclass
class _FakeUpdate:
    update_id: int
    message: _FakeMessage | None = None
    effective_chat: _FakeChat | None = None
    effective_user: _FakeUser | None = None


@dataclass
class _SendCall:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
    """Fake aiogram bot: scripted update batches + recorded sends."""

    updates_batches: list[list[_FakeUpdate]] = field(default_factory=list)
    sends: list[_SendCall] = field(default_factory=list)
    rich_sends: list[_SendCall] = field(default_factory=list)
    typings: int = 0
    next_message_id: int = 900

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[_FakeUpdate]:
        if not self.updates_batches:
            return []
        return self.updates_batches.pop(0)

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _FakeMessage:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=text, message_thread_id=message_thread_id)
        )
        msg = _FakeMessage(message_id=self.next_message_id, text=text)
        self.next_message_id += 1
        return msg

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
        self, *, chat_id: int, action: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> bool:
        self.typings += 1
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _FakeMessage:
        # In a topic Bob's committed reply is the rich final; record its markdown
        # so the test can assert the reply text landed in Bob's thread.
        self.rich_sends.append(
            _SendCall(
                chat_id=chat_id,
                text=rich_message.markdown or "",
                message_thread_id=message_thread_id,
            )
        )
        return _FakeMessage(message_id=0, text=rich_message.markdown)

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        # BOB-035: BotLike parity; this fake's tests never post a photo.
        raise NotImplementedError  # pragma: no cover


    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

# --- Config + builders --------------------------------------------------------


def _config(tmp_path: Path) -> dict[str, object]:
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 0},
        "llm": {
            "tier0_base_url": "http://localhost:8080/v1",
            "tier0_model": "tier0",
            "tier1_base_url": "https://api.example/v1",
            "tier1_model": "tier1",
            "tier1_api_key": "sk-test",
        },
        "telegram": {
            "poll_timeout": 1,
            "chat_id": _CHAT_ID,
            "owner_id": _OWNER_ID,
            "allowed_chat_ids": [_CHAT_ID],
            "bob": {"token": "bob-tok", "topic_id": _BOB_TOPIC_ID},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _seed_soul(tmp_path: Path) -> None:
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nI am the Bob from the book.\n")
    zero = {"valence": 0.0, "arousal": 0.0, "openness": 0.0, "social": 0.0, "stability": 0.0}
    store.write_json("mood", {"baseline": zero, "current": zero})
    store.write_json("taste_profile", {"axes": []})
    store.write_json("phantom_prefs", {"preferences": []})


def _providers() -> dict[int, LLMProvider]:
    return {0: _Provider(reply="positive"), 1: _Provider(reply=_REPLY)}


def _build(
    tmp_path: Path, *, bob_bot: _FakeBot, guppi_bot: _FakeBot
) -> Application:
    return build_application(
        config=_config(tmp_path),
        providers=_providers(),
        bob_bot=bob_bot,
        guppi_bot=guppi_bot,
    )


def _update(
    update_id: int,
    *,
    text: str,
    chat_id: int = _CHAT_ID,
    thread_id: int | None = _BOB_TOPIC_ID,
    user_id: int = _OWNER_ID,
) -> _FakeUpdate:
    return _FakeUpdate(
        update_id=update_id,
        message=_FakeMessage(
            message_id=update_id, text=text, message_thread_id=thread_id
        ),
        effective_chat=_FakeChat(id=chat_id),
        effective_user=_FakeUser(id=user_id),
    )


# --- Tests --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_bots_are_registered_in_the_gateway(tmp_path: Path) -> None:
    # Arrange/Act: the composition root builds both bots behind one gateway.
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot)

    # Assert: both identities are registered with their scopes.
    bob_reg = app.multibot.registry.get(BotIdentity.BOB)
    guppi_reg = app.multibot.registry.get(BotIdentity.GUPPI)
    assert bob_reg.bot is bob_bot
    assert guppi_reg.bot is guppi_bot
    assert bob_reg.scope.chat_id == _CHAT_ID
    assert bob_reg.scope.topic_id == _BOB_TOPIC_ID
    assert guppi_reg.scope.chat_id == _CHAT_ID
    assert guppi_reg.scope.topic_id is None


@pytest.mark.asyncio
async def test_unauthorized_in_bob_topic_reaches_bob_as_guest(
    tmp_path: Path,
) -> None:
    # BOB-019 bob-apv.2: a stranger (not owner, not allowlisted) in the allowed chat
    # + Bob's topic is a GUEST — Bob's social pipeline runs (the restricted mode is
    # enforced inside HandleMessage), NOT GUPPI's old hard reject.
    _seed_soul(tmp_path)
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    bob_bot.updates_batches = [
        [
            _update(
                10,
                text="расскажи подробно про себя, Bob",
                thread_id=_BOB_TOPIC_ID,
                user_id=_STRANGER_ID,
            )
        ]
    ]
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot)
    await app.startup()

    # Act: one poll drives both bots through the central router.
    try:
        published = await app.multibot.poll_once()
    finally:
        await app.shutdown()

    # Assert: the guest reached Bob's pipeline and Bob replied into his thread; no
    # GUPPI hard-reject was sent.
    assert published == 1
    assert bob_bot.rich_sends, "Bob should have replied to the guest (restricted)"
    assert all(s.text != GUPPI_REJECT_TEXT for s in guppi_bot.sends)


@pytest.mark.asyncio
async def test_authorized_message_in_bob_topic_replies_into_thread(
    tmp_path: Path,
) -> None:
    # Arrange: the owner (always authorized in the allowed chat) writes in Bob's
    # topic. Drive the full pipeline via the multi-bot gateway's central router.
    _seed_soul(tmp_path)
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    bob_bot.updates_batches = [
        [_update(11, text="расскажи подробно про зонды, Bob", user_id=_OWNER_ID)]
    ]
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot)
    await app.startup()

    # Act
    try:
        published = await app.multibot.poll_once()
    finally:
        await app.shutdown()

    # Assert: exactly one turn published; Bob's bot committed the reply (the rich
    # final of the live-edit stream) pinned to his topic thread; GUPPI did not
    # reject.
    assert published == 1
    assert bob_bot.rich_sends, "Bob should have replied (rich final)"
    final = bob_bot.rich_sends[-1]
    assert _REPLY in final.text
    assert final.message_thread_id == _BOB_TOPIC_ID
    assert all(s.text != GUPPI_REJECT_TEXT for s in guppi_bot.sends)


@pytest.mark.asyncio
async def test_owner_authorize_in_general_is_handled_by_guppi_and_persisted(
    tmp_path: Path,
) -> None:
    # Arrange: the owner sends /authorize in General (no thread).
    _seed_soul(tmp_path)
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    guppi_bot.updates_batches = [
        [_update(12, text="/authorize 555", thread_id=None, user_id=_OWNER_ID)]
    ]
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot)
    await app.startup()

    # Act
    try:
        published = await app.multibot.poll_once()
    finally:
        await app.shutdown()

    # Assert: GUPPI consumed it (no Bob publish), confirmed, and the grant landed
    # in the live SQLite allowlist (survives a restart).
    assert published == 0
    assert bob_bot.sends == []
    assert len(guppi_bot.sends) == 1
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    try:
        assert await KvAllowlistStore(repo).load() == {555}
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_owner_deauthorize_in_general_persists_revocation(
    tmp_path: Path,
) -> None:
    # US-3: owner manages access via GUPPI in General. Pre-authorize a user, then
    # /deauthorize them; the revocation must land in the live SQLite allowlist
    # (survives a restart) — the same authz store BOB-002 owns, driven by GUPPI.
    _seed_soul(tmp_path)
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    try:
        await KvAllowlistStore(repo).add(555)
    finally:
        await repo.close()

    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    guppi_bot.updates_batches = [
        [_update(15, text="/deauthorize 555", thread_id=None, user_id=_OWNER_ID)]
    ]
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot)
    await app.startup()

    # Act
    try:
        published = await app.multibot.poll_once()
    finally:
        await app.shutdown()

    # Assert: GUPPI consumed it (Bob untouched); the allowlist is empty again.
    assert published == 0
    assert bob_bot.sends == []
    assert len(guppi_bot.sends) == 1
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    try:
        assert await KvAllowlistStore(repo).load() == set()
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_non_owner_authorize_in_general_is_ignored_and_not_persisted(
    tmp_path: Path,
) -> None:
    # US-3: only the owner drives GUPPI. A stranger's /authorize in General is
    # ignored — no grant persisted, no reveal (GUPPI stays silent).
    _seed_soul(tmp_path)
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    guppi_bot.updates_batches = [
        [_update(16, text="/authorize 999", thread_id=None, user_id=_STRANGER_ID)]
    ]
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot)
    await app.startup()

    # Act
    try:
        published = await app.multibot.poll_once()
    finally:
        await app.shutdown()

    # Assert: nothing published, both bots silent, allowlist untouched.
    assert published == 0
    assert bob_bot.sends == []
    assert guppi_bot.sends == []
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    try:
        assert await KvAllowlistStore(repo).load() == set()
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_cross_bot_duplicate_is_processed_once_end_to_end(
    tmp_path: Path,
) -> None:
    # US-4: both admin bots are in the group, so the same Bob-topic message can be
    # delivered to BOTH update streams. The (chat_id, message_id) dedup must make
    # the full pipeline run exactly once — one reply from Bob, not two.
    _seed_soul(tmp_path)
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()

    def _dup(update_id: int) -> _FakeUpdate:
        # Same chat+message_id on both streams (distinct update_ids per stream).
        return _FakeUpdate(
            update_id=update_id,
            message=_FakeMessage(
                message_id=17,
                text="расскажи подробно, Bob",
                message_thread_id=_BOB_TOPIC_ID,
            ),
            effective_chat=_FakeChat(id=_CHAT_ID),
            effective_user=_FakeUser(id=_OWNER_ID),
        )

    bob_dup, guppi_dup = _dup(17), _dup(99)
    bob_bot.updates_batches = [[bob_dup]]
    guppi_bot.updates_batches = [[guppi_dup]]
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot)
    await app.startup()

    # Act
    try:
        published = await app.multibot.poll_once()
    finally:
        await app.shutdown()

    # Assert: processed once; exactly one committed Bob reply (the rich final of
    # the live-edit stream) pinned to his thread.
    assert published == 1
    committed = [s for s in bob_bot.rich_sends if _REPLY in s.text]
    assert len(committed) == 1
    assert committed[0].message_thread_id == _BOB_TOPIC_ID


@pytest.mark.asyncio
async def test_message_in_general_or_other_topic_is_ignored_by_bob(
    tmp_path: Path,
) -> None:
    # Arrange: the owner writes in General and in another topic — neither is Bob's.
    _seed_soul(tmp_path)
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    bob_bot.updates_batches = [
        [
            _update(13, text="hello", thread_id=None, user_id=_OWNER_ID),
            _update(14, text="hello", thread_id=_OTHER_TOPIC_ID, user_id=_OWNER_ID),
        ]
    ]
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot)
    await app.startup()

    # Act
    try:
        published = await app.multibot.poll_once()
    finally:
        await app.shutdown()

    # Assert: Bob never replied (neither message was in his topic); nothing
    # published onto Bob's pipeline.
    assert published == 0
    assert bob_bot.sends == []


@pytest.mark.asyncio
async def test_turn_lands_in_sqlite_with_its_exact_origin(tmp_path: Path) -> None:
    # BOB-090.C2 через целый граф: настоящий апдейт (несёт ``message_thread_id``) →
    # мультибот-роутер → гейтвей → событие → HandleMessage → живой SQLite. Юнит на
    # фейковом репозитории доказал бы контракт фейка; здесь адрес обязан долететь до
    # реальной таблицы, иначе фича мертва в проде при зелёном suite (урок BOB-087.D).
    _seed_soul(tmp_path)
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    bob_bot.updates_batches = [
        [_update(21, text="расскажи подробно про зонды, Bob", user_id=_OWNER_ID)]
    ]
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot)
    await app.startup()

    try:
        published = await app.multibot.poll_once()
        await app.intake_dispatcher.wait_for_idle()
        episodes = await app.memory_repo.load_episodes(limit=10)
    finally:
        await app.shutdown()

    assert published == 1
    turns = [e for e in episodes if "зонды" in str(e["content"])]
    assert turns, f"ход не осел в episodic_log: {episodes}"
    turn = turns[0]
    assert turn["origin_chat_id"] == _CHAT_ID
    assert turn["origin_topic_id"] == _BOB_TOPIC_ID
