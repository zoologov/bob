# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Guest-engage acceptance harness (BOB-071).

Drives the FULL GUPPI graph on fakes to witness, through the OUTGOING boundary + the
``episodic_log`` store, the two halves of the guest-engage fix:

* **Seam A** — a guest addressing Bob by name WITH A TRAILING DOT («Привет, Боб.») is a
  direct address, so Bob replies (the judge folds ``addressivity: directed_to_bob`` into
  the prompt and answers). Before the fix the dot made it AMBIENT → reflective IGNORE →
  silence to the guest.
* **Seam B** — a genuinely-ambient participant turn Bob deliberately leaves unanswered on
  the reflective periphery is STILL remembered: the incoming message lands in
  ``episodic_log`` so the thread is not torn, mirroring the judge non-reply path.

Both are observed at the boundary a user would witness (a sent reply / a stored turn),
never via the detector's private state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.app import build_application
from bob.application.runtime.events import MessageReceived
from tests.acceptance.fake_gateway import (
    CHAT_ID,
    FakeGateway,
    _config,
    _seed_soul,
)
from tests.support.judge_stub import is_judge_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.kernel.ports import LLMProvider
    from bob.runtime import Application

# A guest — a recognised, non-owner participant of Bob's topic (authz gates only tools /
# owner-private, never a social reply — BOB-071). A distinct id keeps them off the owner path.
_GUEST_ID = 8080
_GUEST_NAME = "Лилия"

# The scripted composed reply — its arrival at the boundary is what "Bob replied" observes.
_SCRIPTED_REPLY = "Ага, всё чиню потихоньку — спасибо, что спросила."

# Labelled judge verdicts (BOB-049): REPLY when the folded prompt marks the turn as for Bob.
_JUDGE_REPLY = "intent: reply\nreason: guest harness — for Bob"
_JUDGE_IGNORE = "intent: ignore\nreason: guest harness — not for Bob"
_DIRECT_HINT = "addressivity: directed_to_bob"

# A stable fragment of the reflective ROOM_READ prompt — present only on the read call.
_ROOM_READ_MARKER = "читаешь комнату"
# A low-salience IGNORE reading: on the multi-party periphery it silences Bob.
_IGNORE_READING = "situation: болтают ни о чём\nintent: ignore\nsalience: 0.05\nmood: neutral"

# Another participant seeded into the thread so an ambient reads as MULTI-PARTY
# (``others_present`` True) — the realm of the reflective periphery read.
_OTHER_ID = 602046171


class _GuestJudgeProvider:
    """A provider whose judge follows the direct-address hint, else returns the reply."""

    def __init__(self, *, reply: str) -> None:
        self._reply = reply

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False
    ) -> str | AsyncIterator[str]:
        if is_judge_request(messages):
            joined = "\n".join(str(m.get("content", "")) for m in messages)
            return _JUDGE_REPLY if _DIRECT_HINT in joined else _JUDGE_IGNORE
        return self._reply


class _ReflectiveIgnoreProvider:
    """A provider that answers the reflective read with a low-salience IGNORE, else the reply."""

    def __init__(self, *, reply: str) -> None:
        self._reply = reply

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False
    ) -> str | AsyncIterator[str]:
        if any(_ROOM_READ_MARKER in str(m.get("content", "")) for m in messages):
            return _IGNORE_READING
        return self._reply


def _reflective_config(tmp_path: Path) -> dict[str, object]:
    config = _config(tmp_path)
    config["presence"] = {"reflective": True}
    return config


async def _seed_other_participant(app: Application) -> None:
    """Seed a prior turn from ANOTHER participant so the recent thread reads as multi-party."""
    connection = app.connection.connection
    await connection.execute(
        "INSERT INTO episodic_log (ts, event_type, content, sender_id, bob_message_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("2026-07-29T10:30:00+00:00", "message", "Алексей: всем привет", _OTHER_ID, None),
    )
    await connection.commit()


async def _episodic_contents(app: Application) -> list[str]:
    """Every ``episodic_log`` content row (the stored thread) as plain strings."""
    connection = app.connection.connection
    cursor = await connection.execute("SELECT content FROM episodic_log ORDER BY id")
    rows = await cursor.fetchall()
    return [str(row[0]) for row in rows]


async def run_guest_direct_dot_turn(tmp_path: Path, *, text: str) -> FakeGateway:
    """Boot the graph and drive ONE guest turn that addresses Bob by name-with-a-dot.

    The judge folds the REAL addressivity into the prompt; a dot-vocative («Привет, Боб.»)
    now classifies ``directed_to_bob`` → the judge replies. The returned gateway records
    whether Bob answered the guest at the boundary.
    """
    _seed_soul(tmp_path)
    gateway = FakeGateway()
    provider = _GuestJudgeProvider(reply=_SCRIPTED_REPLY)
    providers: dict[int, LLMProvider] = {0: provider, 1: provider}
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=gateway, guppi_bot=gateway
    )
    await app.startup()
    try:
        await app.event_bus.publish(
            MessageReceived(
                update_id=1,
                chat_id=CHAT_ID,
                message_id=1,
                text=text,
                sender_id=_GUEST_ID,
                sender_name=_GUEST_NAME,
            )
        )
        await app.intake_dispatcher.wait_for_idle()
    finally:
        await app.shutdown()
    return gateway


async def run_guest_ambient_unanswered_turn(
    tmp_path: Path, *, text: str
) -> tuple[FakeGateway, list[str]]:
    """Drive ONE ambient guest turn Bob leaves unanswered; return (gateway, episodic contents).

    Reflective presence is ON and the room-judge is scripted to a low-salience IGNORE, and a
    prior turn from another participant makes the thread multi-party — so the ambient guest
    turn stays SILENT on the periphery. Seam B still persists the incoming message, so the
    returned episodic contents contain the guest's turn even though Bob never replied.
    """
    _seed_soul(tmp_path)
    gateway = FakeGateway()
    provider = _ReflectiveIgnoreProvider(reply=_SCRIPTED_REPLY)
    providers: dict[int, LLMProvider] = {0: provider, 1: provider}
    app = build_application(
        config=_reflective_config(tmp_path),
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
                sender_id=_GUEST_ID,
                sender_name=_GUEST_NAME,
            )
        )
        await app.intake_dispatcher.wait_for_idle()
        contents = await _episodic_contents(app)
    finally:
        await app.shutdown()
    return gateway, contents
