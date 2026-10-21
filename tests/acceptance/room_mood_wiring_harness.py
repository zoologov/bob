# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""RoomMood-в-тоне consumption WIRING acceptance harness (BOB-066 Срез W.2).

Drives the FULL GUPPI graph on fakes with the reflective «read the room» ON and — for the
wired scenario — ``presence.room_mood.enabled`` ON, so the BDD scenarios witness the *wired*
room-mood behaviour through the outgoing boundary:

* the reflective room-judge is scripted to REPLY at high salience on a HEAVY/heated room, so
  Bob barges into the periphery and composes a reply. With the room-mood seam wired, the
  «сбавь игривость» tone line is folded into Bob's compose system prompt (the LLM port is the
  boundary the fake provider observes); with the flag OFF the same heavy-room reply carries NO
  room tone line — proof the seam is inert unless wired (byte-identical regression).

(The «RoomMood never mutates Bob's personal Mood» invariant is pinned at the domain layer —
``room_tone.feature`` + the pure ``room_tone`` unit tests take floats, not a ``Mood``, by
construction — so the wiring feature stays focused on the consumption contract.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.app import build_application
from bob.kernel.events import MessageReceived
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

# A non-owner, non-Bob participant. Seeding one prior turn from them makes the recent thread
# MULTI-PARTY (``others_present`` True), so the heavy-room ambient is a genuine group aside —
# the realm of the periphery reflective read that folds the room-mood tone line into the voice.
# An OWNER 1:1 ambient (no such seed) is Bob's own space, answered deterministically, and never
# reaches that read.
_OTHER_ID = 602046171

# A high-salience REPLY reading of a HEAVY, heated room: on the periphery Bob WOULD barge in
# (so a reply is composed) AND the room reads heavy/tense → the tone line should fold in.
_HEAVY_REPLY_READING = (
    "situation: тяжёлый разговор, все на взводе\n"
    "intent: reply\nsalience: 0.9\nmood: heated"
)

# The stable fragment of the room-heavy tone line (personality.room_tone._ROOM_HEAVY_OR_TENSE).
_TONE_DOWN_FRAGMENT = "сбавь игривость"


class _CapturingProvider:
    """Answers the reflective read with a heavy REPLY, captures every compose system prompt."""

    def __init__(self, *, reply: str) -> None:
        self._reply = reply
        # The joined content of every non-read generation call — the compose call folds the
        # persona prompt (WITH the per-turn directives) into a system message, so the room-mood
        # tone line is detectable across the concatenated contents.
        self.generation_payloads: list[str] = []

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        contents = [str(m.get("content", "")) for m in messages]
        if any(_ROOM_READ_MARKER in c for c in contents):
            return _HEAVY_REPLY_READING
        # A normal generation call: record its full payload so the step can assert whether the
        # room-mood tone line was folded into Bob's voice this turn.
        self.generation_payloads.append("\n".join(contents))
        return self._reply


@dataclass(frozen=True, slots=True)
class RoomMoodOutcome:
    """What one wiring turn produced through the boundary."""

    gateway: FakeGateway
    tone_line_folded: bool


def _config_for(tmp_path: Path, *, room_mood_enabled: bool) -> dict[str, object]:
    """Config with reflective ON and the room-mood seam ON/OFF."""
    config = _config(tmp_path)
    presence: dict[str, object] = {"reflective": True}
    if room_mood_enabled:
        presence["room_mood"] = {"enabled": True}
    config["presence"] = presence
    return config


async def _seed_other_participant(app: Application) -> None:
    """Seed a prior message from ANOTHER participant so the recent thread reads as multi-party."""
    connection = app.connection.connection
    await connection.execute(
        "INSERT INTO episodic_log (ts, event_type, content, sender_id, bob_message_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("2026-07-29T10:30:00+00:00", "message", "Алексей: всем привет", _OTHER_ID, None),
    )
    await connection.commit()


async def run_heavy_room_turn(
    tmp_path: Path, *, text: str, room_mood_enabled: bool
) -> RoomMoodOutcome:
    """Boot the graph (reflective ON, room-mood ON/OFF) and drive one multi-party AMBIENT
    heavy-room turn (another participant seeded so the periphery reflective read runs)."""
    _seed_soul(tmp_path)
    gateway = FakeGateway()
    provider = _CapturingProvider(reply="Понимаю, давай по делу.")
    providers: dict[int, LLMProvider] = {0: provider, 1: provider}
    app = build_application(
        config=_config_for(tmp_path, room_mood_enabled=room_mood_enabled),
        providers=providers,
        bob_bot=gateway,
        guppi_bot=gateway,
    )
    await app.startup()
    try:
        await _seed_other_participant(app)
        await app.event_bus.publish(
            MessageReceived(
                update_id=1,
                chat_id=CHAT_ID,
                message_id=7,
                text=text,
                sender_id=OWNER_ID,
                sender_name="Vladimir",
                mentions_bob=False,  # ambient periphery — the reflective read drives the turn
            )
        )
    finally:
        await app.shutdown()
    tone_line_folded = any(
        _TONE_DOWN_FRAGMENT in p for p in provider.generation_payloads
    )
    return RoomMoodOutcome(gateway=gateway, tone_line_folded=tone_line_folded)
