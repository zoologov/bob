# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""ALL-FLAGS-ON wiring INTEGRATION harness (BOB-066 Срез W.5).

The four W dev slices (W.1–W.4) each threaded a deferred presence mechanism into the hot path
behind its own nested ``presence.<section>.enabled`` flag. Their per-slice wiring harnesses each
turn ONE flag on in isolation. This harness turns the WHOLE presence wiring ON at once — rhythm,
room-mood, series-budget, staleness, catch-up, endorsement, tact + the reflective split — and
boots the FULL GUPPI graph on fakes, so the integration scenarios can witness the cross-cutting
invariants THROUGH the outgoing boundary (:class:`~tests.acceptance.fake_gateway.FakeGateway`):

* 🔴 INV-1 (the focal guarantee) survives the whole stack — a direct address yields a reply even
  when the reflective judge is scripted to IGNORE, the share-of-voice ceiling is exhausted (Bob
  hogged the airtime), and Bob is обижен at the sender (sulk active). None of those throttle a
  focus turn to silence.
* the same all-on stack still STAYS SILENT on ambient chatter it has no business barging into —
  proof the on-stack is not a "reply to everything" regression.
* with every new flag OFF (:data:`ALL_FLAGS_OFF`) the same direct turn replies byte-identical to
  today's behaviour — the deferred mechanisms are inert unless wired.

Conditions the full graph cannot fabricate in a single turn (a burst collapsing to one reply, a
draft going stale mid-generation, an away-period backlog) are exercised at their real intake /
handler seam by the per-slice harnesses; the integration module composes those seam turns with
the full-graph turns here into one INV-1 matrix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.app import build_application
from bob.application.runtime.events import MessageReceived
from bob.runtime.config import _BOB_PERSONA
from tests.acceptance.fake_gateway import (
    CHAT_ID,
    OWNER_ID,
    FakeGateway,
    _config,
    _seed_soul,
)
from tests.support.judge_stub import JUDGE_REPLY, is_judge_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.kernel.ports import LLMProvider
    from bob.runtime import Application

# Stable prompt fragments that identify each cheap Tier-0/Tier-1 judge call, so the fake provider
# can answer the RIGHT contract for each instead of leaking the reply text into a judge parser.
_ROOM_READ_MARKER = "читаешь комнату"  # ReadTheRoom (BOB-066 2.2) system prompt
_STALENESS_MARKER = "ЧЕРНОВИК"  # LlmStalenessJudge (BOB-066 W.3) system prompt

# A low-salience IGNORE room reading: on the periphery it silences Bob, and on a FOCUS turn it is
# NEVER consulted — so a reply on a direct address can ONLY be the INV-1 focal short-circuit.
IGNORE_READING = "situation: болтают ни о чём\nintent: ignore\nsalience: 0.05\nmood: neutral"

# A high-salience REPLY room reading: Bob WOULD barge in on the periphery, so a silence there can
# only come from a downstream gate (the share-of-voice ceiling), never from the verdict itself.
REPLY_READING = "situation: живая беседа\nintent: reply\nsalience: 0.9\nmood: warm"

# A fail-safe staleness read (nothing shifted under the draft → the gate SENDs). The parser is
# format-tolerant, but answering the contract explicitly keeps the harness honest.
_STALENESS_SEND = "answered: no\nclosed: no\nclarified: no\nnew_question: no"

# How many prior Bob-sent turns to seed so Bob's share of voice is ~1.0 (he hogged the room),
# arming the share-of-voice ceiling to throttle any AMBIENT barge to silence.
_HOGGED_TURNS = 12

# The presence config with EVERY BOB-066 W flag ON (+ the pre-existing reflective split). The
# rhythm knobs are tuned aggressively so the ceiling throttle is deterministic regardless of the
# turn-local RNG draw (a near-zero floor + a steep curve collapse the hogged-airtime barge to ~0).
ALL_FLAGS_ON: dict[str, object] = {
    "reflective": True,
    "rhythm": {"enabled": True, "share_min_multiplier": 0.0001, "share_steepness": 8.0},
    "room_mood": {"enabled": True},
    "series_budget": {"enabled": True, "max_reactions": 1},
    "staleness": {"enabled": True},
    "catchup": {"enabled": True, "budget": 3, "absence_hours": 4.0},
    "endorsement": {"enabled": True},
    "tact": {"enabled": True},
}

# Every new W flag OFF (the reflective split is a pre-existing seam, not a W flag) — the
# byte-identical baseline the regression pass pins.
ALL_FLAGS_OFF: dict[str, object] = {}


class _AllFlagsProvider:
    """A fake ``LLMProvider`` that answers each judge contract, else returns the reply.

    One provider serves both tiers: it recognises the reflective room-read, the staleness judge,
    and the BOB-049 response judge by a stable fragment of each system prompt, and answers the
    scripted verdict; any other call (compose / sentiment / extract) returns ``reply``.
    """

    def __init__(self, *, reply: str, reading: str) -> None:
        self._reply = reply
        self._reading = reading

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        contents = [str(m.get("content", "")) for m in messages]
        if any(_ROOM_READ_MARKER in c for c in contents):
            return self._reading
        if any(_STALENESS_MARKER in c for c in contents):
            return _STALENESS_SEND
        if is_judge_request(messages):
            return JUDGE_REPLY
        return self._reply


def _presence_config(tmp_path: Path, *, flags_on: bool) -> dict[str, object]:
    """The fake-gateway config with the presence section all-on / all-off."""
    config = _config(tmp_path)
    config["presence"] = dict(ALL_FLAGS_ON) if flags_on else dict(ALL_FLAGS_OFF)
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


async def _seed_active_sulk(app: Application, *, sender_id: int) -> None:
    """Seed an ACTIVE per-person обида row so Bob is sulking at ``sender_id`` before the turn."""
    connection = app.connection.connection
    await connection.execute(
        "INSERT INTO person_sulk "
        "(persona_id, sender_id, active, intensity, low_streak, since, announced) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (_BOB_PERSONA, sender_id, 1, 0.9, 3, "2026-07-29T09:00:00+00:00", 1),
    )
    await connection.commit()


async def run_wiring_turn(
    tmp_path: Path,
    *,
    text: str,
    mentions_bob: bool,
    flags_on: bool = True,
    reading: str = IGNORE_READING,
    hog_airtime: bool = False,
    sulk: bool = False,
    reply: str = "Обожаю зонды — давай расскажу.",
) -> FakeGateway:
    """Boot the FULL graph (presence all-on / all-off) and drive ONE turn end-to-end.

    ``mentions_bob`` picks the fork: ``True`` → a direct @mention (a focus turn), ``False`` → an
    ambient periphery turn whose fate rests on the (scripted) reflective read and the ceiling.
    ``hog_airtime`` arms the share-of-voice ceiling; ``sulk`` makes Bob обижен at the sender. The
    returned :class:`FakeGateway` records what Bob emitted (a reply / a reaction / silence).
    """
    _seed_soul(tmp_path)
    gateway = FakeGateway()
    provider = _AllFlagsProvider(reply=reply, reading=reading)
    providers: dict[int, LLMProvider] = {0: provider, 1: provider}
    app = build_application(
        config=_presence_config(tmp_path, flags_on=flags_on),
        providers=providers,
        bob_bot=gateway,
        guppi_bot=gateway,
    )
    await app.startup()
    try:
        if hog_airtime:
            await _seed_hogged_airtime(app)
        if sulk:
            await _seed_active_sulk(app, sender_id=OWNER_ID)
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
