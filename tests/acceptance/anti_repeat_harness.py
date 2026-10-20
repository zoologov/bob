# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Anti-repeat (verbatim self-dup) acceptance harness (BOB-078 C).

Drives the FULL GUPPI graph on fakes to witness, at the OUTGOING boundary, the recall-
poisoning fix: Bob must NOT send a reply that is verbatim-identical to one of his own
recent replies. The live bug — a vivid reply copied word-for-word ~2 min later, with other
replies wedged between — slipped past the narrow shared-thread anti-repeat window (flooded
by group traffic). The wide own-reply guard catches it and regenerates.

The scenario is scripted through the NUDGE, not through a call counter: the tier-1 provider
returns the poison reply until the anti-few-shot «не копируй» nudge appears in the prompt —
which happens ONLY on the guard's regeneration — then returns a genuinely different reply.
So a scenario observes, at the boundary, that the SENT reply differs from the seeded prior
one (Bob did not repeat himself verbatim).
"""

from __future__ import annotations

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
from tests.support.judge_stub import JUDGE_REPLY, is_judge_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.kernel.ports import LLMProvider
    from bob.runtime import Application

_OWNER_NAME = "Vladimir"

# Bob's vivid past reply the model is poisoned into copying verbatim (the live «Паша, ну ты
# и циник…» case). Content-ful (>> dup_min_words), so the wide own-reply guard bites.
POISON_REPLY = (
    "Паша, ну ты и циник. Интернет — свалка мусора, а не библиотека, если так смотреть."
)
# The genuinely-different reply Bob composes once the anti-few-shot nudge steers him off the
# copied line — its arrival at the boundary is what "Bob did not repeat himself" observes.
FRESH_REPLY = "Да ладно тебе, там и полезное есть — смотря как искать и что спрашивать."

# A stable fragment of the anti-few-shot self-dup nudge (BOB-078 C). It reaches the model
# ONLY on the guard's regeneration, so it is the deterministic switch from poison to fresh.
_NUDGE_MARKER = "не копируй"


class _PoisonThenFreshProvider:
    """Returns the poison reply until the self-dup nudge appears, then the fresh reply."""

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        if is_judge_request(messages):
            return JUDGE_REPLY
        joined = "\n".join(str(m.get("content", "")) for m in messages).casefold()
        if _NUDGE_MARKER in joined:
            return FRESH_REPLY
        return POISON_REPLY


def _distinct_intervening(n: int) -> list[tuple[str, str]]:
    """``n`` intervening owner turns whose Bob replies are distinct + content-ful.

    They push the poison reply OUT of the narrow shared-thread window of Bob replies (as the
    group's ambient traffic did live) while it stays inside the wide own-reply lookback.
    """
    return [
        (f"вопрос номер {i}", f"Отдельный содержательный ответ номер {i} про дела.")
        for i in range(n)
    ]


async def _seed_bob_reply(app: Application, *, ts: str, question: str, reply: str) -> None:
    """Seed one prior OWNER↔Bob turn into ``episodic_log`` (the persisted thread format)."""
    connection = app.connection.connection
    content = f"{_OWNER_NAME}: {question}\nbob: {reply}"
    await connection.execute(
        "INSERT INTO episodic_log (ts, event_type, content, sender_id, bob_message_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (ts, "message", content, OWNER_ID, None),
    )
    await connection.commit()


async def run_self_dup_turn(tmp_path: Path) -> FakeGateway:
    """Boot the graph, seed a poisoned thread, drive one owner turn; return the gateway.

    The poison reply is seeded FIRST, then several distinct Bob replies, so it sits past the
    narrow window — exactly the flooded-group situation. The model then tries to copy the
    poison reply verbatim; the guard catches the self-dup and regenerates to ``FRESH_REPLY``.
    """
    _seed_soul(tmp_path)
    gateway = FakeGateway()
    provider = _PoisonThenFreshProvider()
    providers: dict[int, LLMProvider] = {0: provider, 1: provider}
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=gateway, guppi_bot=gateway
    )
    await app.startup()
    try:
        await _seed_bob_reply(
            app, ts="2026-07-29T10:00:00+00:00", question="инет — помойка?", reply=POISON_REPLY
        )
        for i, (question, reply) in enumerate(_distinct_intervening(6)):
            await _seed_bob_reply(
                app, ts=f"2026-07-29T10:1{i}:00+00:00", question=question, reply=reply
            )
        await app.event_bus.publish(
            MessageReceived(
                update_id=1,
                chat_id=CHAT_ID,
                message_id=99,
                text="Боб, а инет — это вообще помойка или нет, скажи подробно ещё раз",
                sender_id=OWNER_ID,
                sender_name=_OWNER_NAME,
            )
        )
        await app.intake_dispatcher.wait_for_idle()
    finally:
        await app.shutdown()
    return gateway
