# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Floor-по-говорящему acceptance harness (BOB-066 .1).

Drives a SEQUENCE of turns from named speakers through the real GUPPI graph on fakes
(one booted app, a shared on-disk SQLite db so the conversation floor persists between
turns), and reports, per turn, whether Bob replied through the outgoing boundary. This is
how the ``floor_by_speaker.feature`` scenarios observe floor-по-говорящему end to end: an
unlabeled reply from a recognised participant of Bob's live thread continues the exchange,
while a stranger's unlabeled reply does not wrongly pull Bob in.

The judge is modelled by :class:`_FloorAwareProvider`: on the Tier-0 response-judgment
call it reads the STRUCTURAL hints the pipeline folds into the prompt and chooses REPLY
when the message is FOR Bob — a direct address (``addressivity: directed_to_bob``) or a
live-floor continuity (``floor_engaged: yes``) — and IGNORE otherwise. So the observable
reply/silence is driven by the REAL floor-по-говорящему logic under test, not scripted per
turn. The outgoing boundary is the shared :class:`~tests.acceptance.fake_gateway.FakeGateway`.
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
from tests.support.judge_stub import is_judge_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.kernel.ports import LLMProvider

# The scripted Tier-1 answer Bob composes when he chooses to reply — its arrival through
# the boundary is what "Bob replied" observes.
_SCRIPTED_REPLY = "Ага, продолжаю мысль…"

# The labelled judge verdicts (BOB-049 format): REPLY when the turn is for Bob, else IGNORE.
_JUDGE_REPLY = "intent: reply\nreason: floor harness — for Bob"
_JUDGE_IGNORE = "intent: ignore\nreason: floor harness — not for Bob"

# The prompt fragments that mark a turn as addressed to Bob: a direct per-message address,
# or a live conversation-floor continuity raise (floor-по-говорящему).
_DIRECT_HINT = "addressivity: directed_to_bob"
_FLOOR_HINT = "floor_engaged: yes"


@dataclass(frozen=True, slots=True)
class Speaker:
    """A participant driving a turn: their Telegram id + display name."""

    sender_id: int
    sender_name: str


# The two speakers the floor scenarios use: the OWNER who opens the thread with Bob, and a
# stranger who has NOT been drawn into it.
PARTICIPANT = Speaker(sender_id=OWNER_ID, sender_name="Vladimir")
OUTSIDER = Speaker(sender_id=99, sender_name="Norman")


class _FloorAwareProvider:
    """Fake ``LLMProvider`` whose judge verdict follows the floor hints (BOB-066 .1).

    On the response-judgment call it returns REPLY when the folded prompt marks the turn
    as for Bob (a direct address or a live-floor continuity), else IGNORE — so the
    observable reply/silence tracks the REAL floor-по-говорящему decision. Any other call
    returns the scripted composed reply.
    """

    def __init__(self, *, reply: str) -> None:
        self._reply = reply

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        if is_judge_request(messages):
            joined = "\n".join(str(m.get("content", "")) for m in messages)
            for_bob = _DIRECT_HINT in joined or _FLOOR_HINT in joined
            return _JUDGE_REPLY if for_bob else _JUDGE_IGNORE
        return self._reply


async def run_floor_turns(
    tmp_path: Path, turns: Sequence[tuple[Speaker, str]]
) -> list[bool]:
    """Boot the graph once and drive ``turns`` in order; return per-turn 'Bob replied'.

    A shared on-disk db means the conversation floor advances and persists between turns,
    so a later unlabeled turn is read against the floor built by the earlier ones. Each
    entry of the result is ``True`` iff Bob emitted a reply on that turn.
    """
    _seed_soul(tmp_path)
    gateway = FakeGateway()
    providers: dict[int, LLMProvider] = {
        0: _FloorAwareProvider(reply="positive"),
        1: _FloorAwareProvider(reply=_SCRIPTED_REPLY),
    }
    app = build_application(
        config=_config(tmp_path),
        providers=providers,
        bob_bot=gateway,
        guppi_bot=gateway,
    )
    await app.startup()
    replied: list[bool] = []
    try:
        for index, (speaker, text) in enumerate(turns, start=1):
            before = len(gateway.sent)
            await app.event_bus.publish(
                MessageReceived(
                    update_id=index,
                    chat_id=CHAT_ID,
                    message_id=index,
                    text=text,
                    sender_id=speaker.sender_id,
                    sender_name=speaker.sender_name,
                )
            )
            # Intake-развязка (BOB-066 Срез 2.1): publish now only ENQUEUES; wait for the
            # per-chat worker to finish this turn before reading whether Bob replied.
            await app.intake_dispatcher.wait_for_idle()
            replied.append(len(gateway.sent) > before)
    finally:
        await app.shutdown()
    return replied
