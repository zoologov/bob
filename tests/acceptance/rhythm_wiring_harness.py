# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Rhythm consumption WIRING acceptance harness (BOB-066 Срез W).

Drives the FULL GUPPI graph on fakes with the reflective «read the room» ON and the presence
rhythm layer ON (``presence.rhythm.enabled``), so the BDD scenarios witness the *wired* ritm
behaviour through the outgoing boundary:

* the reflective room-judge is scripted to REPLY at high salience — so on the periphery Bob
  WOULD barge in — and Bob has hogged the room's airtime (a bob-heavy episodic window seeded
  before the turn). With the share-of-voice ceiling tuned aggressively, an AMBIENT barge is
  throttled to silence, while a DIRECT address bypasses the ceiling entirely (INV-1) and
  replies.
* with the flag OFF (``run_unwired_turn``) the SAME hogged-airtime ambient turn still replies —
  proof the ceiling is inert unless wired (byte-identical regression).

The seeded episodic rows (all Bob-sent, one speaker) push Bob's share of voice to ~1.0 against
a fair target of ~0.5, so the tuned damping collapses the ambient barge probability to ~0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.app import build_application
from bob.application.runtime.events import MessageReceived
from tests.acceptance.fake_gateway import (
    CHAT_ID,
    OWNER_ID,
    FakeGateway,
    _config,
    _seed_soul,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.kernel.ports import LLMProvider
    from bob.runtime import Application

# A stable fragment of ROOM_READ_SYSTEM_PROMPT — present only on the reflective read call.
_ROOM_READ_MARKER = "читаешь комнату"

# A high-salience REPLY reading: on the periphery Bob WOULD barge in — so a silence can only
# come from the share-of-voice ceiling, never from the reflective verdict itself.
_REPLY_READING = (
    "situation: активная беседа\nintent: reply\nsalience: 0.9\nmood: warm"
)

# How many prior Bob-sent turns to seed so Bob's share of voice is ~1.0 (he hogged the room).
_HOGGED_TURNS = 12

# A non-owner, non-Bob participant. Seeding one prior turn from them makes the recent thread
# MULTI-PARTY (``others_present`` True), so an ambient there is a genuine group aside — the
# realm of the share-of-voice ceiling. An OWNER 1:1 ambient (no such seed) is Bob's own space
# and is answered deterministically (the legacy ENGAGE set), never reaching the ceiling.
_OTHER_ID = 602046171


class _ReplyRoomProvider:
    """Answers the reflective read with a high-salience REPLY, every other call with the reply."""

    def __init__(self, *, reply: str) -> None:
        self._reply = reply

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        if any(_ROOM_READ_MARKER in str(m.get("content", "")) for m in messages):
            return _REPLY_READING
        return self._reply


def _rhythm_config(tmp_path: Path, *, rhythm_enabled: bool) -> dict[str, object]:
    """Config with reflective ON and the rhythm layer ON/OFF + an aggressive ceiling."""
    config = _config(tmp_path)
    presence: dict[str, object] = {"reflective": True}
    if rhythm_enabled:
        presence["rhythm"] = {
            "enabled": True,
            # Collapse the damping the moment Bob runs past his fair share: a near-zero floor
            # + a steep curve make the hogged-airtime ambient barge probability ~0, so the
            # throttle is deterministic regardless of the turn-local draw.
            "share_min_multiplier": 0.0001,
            "share_steepness": 8.0,
        }
    config["presence"] = presence
    return config


async def _seed_hogged_airtime(app: Application) -> None:
    """Seed a bob-heavy episodic window so Bob's share of voice is ~1.0 before the turn."""
    connection = app.connection.connection
    for i in range(_HOGGED_TURNS):
        await connection.execute(
            "INSERT INTO episodic_log (ts, event_type, content, sender_id, bob_message_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"2026-07-29T10:{i:02d}:00+00:00", "message", "turn", OWNER_ID, 900 + i),
        )
    await connection.commit()


async def _seed_other_participant(app: Application) -> None:
    """Seed a prior message from ANOTHER participant so the recent thread reads as multi-party."""
    connection = app.connection.connection
    await connection.execute(
        "INSERT INTO episodic_log (ts, event_type, content, sender_id, bob_message_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("2026-07-29T10:30:00+00:00", "message", "Алексей: всем привет", _OTHER_ID, None),
    )
    await connection.commit()


async def _run(
    tmp_path: Path,
    *,
    text: str,
    mentions_bob: bool,
    rhythm_enabled: bool,
    others_present: bool = False,
) -> FakeGateway:
    _seed_soul(tmp_path)
    gateway = FakeGateway()
    provider = _ReplyRoomProvider(reply="Обожаю зонды — давай расскажу…")
    providers: dict[int, LLMProvider] = {0: provider, 1: provider}
    app = build_application(
        config=_rhythm_config(tmp_path, rhythm_enabled=rhythm_enabled),
        providers=providers,
        bob_bot=gateway,
        guppi_bot=gateway,
    )
    await app.startup()
    try:
        if others_present:
            await _seed_other_participant(app)
        await _seed_hogged_airtime(app)
        await app.event_bus.publish(
            MessageReceived(
                update_id=1,
                chat_id=CHAT_ID,
                message_id=7,
                text=text,
                sender_id=OWNER_ID,
                sender_name="Vladimir",
                mentions_bob=mentions_bob,
            )
        )
    finally:
        await app.shutdown()
    return gateway


async def run_wired_ambient_turn(tmp_path: Path, *, text: str) -> FakeGateway:
    """Rhythm ON: a busy-group ambient barge while Bob has hogged the room → throttled silent."""
    return await _run(
        tmp_path, text=text, mentions_bob=False, rhythm_enabled=True, others_present=True
    )


async def run_wired_focus_turn(tmp_path: Path, *, text: str) -> FakeGateway:
    """Rhythm ON: a direct address bypasses the ceiling (INV-1) → replies promptly."""
    return await _run(tmp_path, text=text, mentions_bob=True, rhythm_enabled=True)


async def run_unwired_ambient_turn(tmp_path: Path, *, text: str) -> FakeGateway:
    """Rhythm OFF: the SAME busy-group ambient turn still replies (byte-identical)."""
    return await _run(
        tmp_path, text=text, mentions_bob=False, rhythm_enabled=False, others_present=True
    )
