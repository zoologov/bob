# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Reflective «read the room» acceptance harness (BOB-066 Срез 2.2).

Drives the FULL GUPPI graph on fakes with ``presence.reflective`` ENABLED, so the BDD
scenarios witness the focus/periphery split through the outgoing boundary:

* FOCUS (INV-1) — a raw direct address always yields a reply, even when the reflective
  reader is scripted to IGNORE (the focus short-circuit bypasses the read).
* PERIPHERY — an ambient, low-salience read yields silence (no reply, no reaction).

The scripted Tier-1 provider answers the ROOM_READ request with a fixed reading and every
other request with the reply text; the reflective read only fires on the periphery path.
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

# A stable fragment of ROOM_READ_SYSTEM_PROMPT — present only on the reflective read call,
# so the fake provider can tell it from a normal reply/sentiment call.
_ROOM_READ_MARKER = "читаешь комнату"

# A low-salience IGNORE reading: on the periphery it silences Bob; on a FOCUS turn it is
# never consulted (the short-circuit replies regardless).
_IGNORE_READING = "situation: болтают ни о чём\nintent: ignore\nsalience: 0.05\nmood: neutral"

# A non-owner, non-Bob participant. Seeding one prior turn from them makes the recent thread
# MULTI-PARTY (``others_present`` True), so an ambient there is a genuine group aside — the
# realm of the periphery reflective read (a low-salience IGNORE silences Bob). An OWNER 1:1
# ambient (no such seed → ``others_present`` False) is Bob's own space and is answered
# deterministically (the legacy ENGAGE set), never reaching the periphery read.
_OTHER_ID = 602046171


async def _seed_other_participant(app: Application) -> None:
    """Seed a prior message from ANOTHER participant so the recent thread reads as multi-party."""
    connection = app.connection.connection
    await connection.execute(
        "INSERT INTO episodic_log (ts, event_type, content, sender_id, bob_message_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("2026-07-29T10:30:00+00:00", "message", "Алексей: всем привет", _OTHER_ID, None),
    )
    await connection.commit()


class _ReflectiveProvider:
    """A provider that answers the reflective read with a fixed reading, else the reply."""

    def __init__(self, *, reply: str, reading: str) -> None:
        self._reply = reply
        self._reading = reading

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False
    ) -> str | AsyncIterator[str]:
        if any(_ROOM_READ_MARKER in str(m.get("content", "")) for m in messages):
            return self._reading
        return self._reply


def _reflective_config(tmp_path: Path) -> dict[str, object]:
    config = _config(tmp_path)
    config["presence"] = {"reflective": True}
    return config


async def run_reflective_turn(
    tmp_path: Path, *, text: str, mentions_bob: bool, reply: str, others_present: bool = False
) -> FakeGateway:
    """Boot the graph with reflective presence ON and drive one turn end-to-end.

    ``mentions_bob`` picks the fork: ``True`` → a FOCUS turn (direct address), ``False`` →
    an AMBIENT periphery turn. ``others_present`` seeds a prior turn from another participant
    so an ambient reads as multi-party (the realm of the periphery reflective read). The
    reflective reader is scripted to a low-salience IGNORE, so the focus turn STILL replies
    (INV-1) while the multi-party periphery turn stays silent.
    """
    _seed_soul(tmp_path)
    gateway = FakeGateway()
    provider = _ReflectiveProvider(reply=reply, reading=_IGNORE_READING)
    providers: dict[int, LLMProvider] = {0: provider, 1: provider}
    app = build_application(
        config=_reflective_config(tmp_path),
        providers=providers,
        bob_bot=gateway,
        guppi_bot=gateway,
    )
    await app.startup()
    try:
        if others_present:
            await _seed_other_participant(app)
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
