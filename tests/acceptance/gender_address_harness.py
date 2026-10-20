# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Gender-of-address acceptance harness (BOB-078 A).

Drives the FULL GUPPI graph on fakes to witness, THROUGH the boundary, the live fix: Bob
must address a participant in the grammatical gender she reveals in her OWN speech — never
guessed from her name. The live bug was the reverse: Bob addressed Лиля in the masculine
(«он») though her speech was feminine («Пошла учить Python»).

The observable boundary here is the COMPOSE prompt the graph hands the Tier-1 model: once
Лиля self-presents feminine on ≥2 directed turns (BOB-078.8 — a single leading verb only
leans, it does not commit), perception accrues her gender past the threshold, and the
``who_is_writing_directive`` folds «обращайся … в женском роде» INTO that prompt. A capturing
provider records the composed prompt so a scenario asserts the feminine instruction reached
the model — never the detector's private state. The neutral control (no self-presentation,
only a name) leaves the prompt free of any forced gender.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.app import build_application
from bob.kernel.events import MessageReceived
from tests.acceptance.fake_gateway import (
    CHAT_ID,
    FakeGateway,
    _config,
    _seed_soul,
)
from tests.support.judge_stub import JUDGE_REPLY, is_judge_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.kernel.ports import LLMProvider

# A guest participant (not the owner) — her gender must be read from her speech, not her name.
_LILY_ID = 8080
_LILY_NAME = "Лиля"

_SCRIPTED_REPLY = "Здорово, что взялась за Python — если что, спрашивай."


class _CapturingProvider:
    """Answers the judge with REPLY and records every COMPOSE prompt it is handed.

    The compose prompt (any non-judge call) is joined + stored so a scenario can assert
    the gender instruction the graph folded in, at the boundary the model actually sees.
    """

    def __init__(self, *, reply: str) -> None:
        self._reply = reply
        self.compose_prompts: list[str] = []

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False
    ) -> str | AsyncIterator[str]:
        if is_judge_request(messages):
            return JUDGE_REPLY
        self.compose_prompts.append(
            "\n".join(str(m.get("content", "")) for m in messages)
        )
        return self._reply


async def run_gender_address_turn(tmp_path: Path, *, text: str) -> str:
    """Boot the graph, drive ONE directed guest turn ``text``; return the compose prompt.

    Лиля addresses Bob by name (vocative → directed_to_bob → the judge replies), so the
    graph composes a reply and the returned prompt carries whatever gender instruction
    perception resolved from ``text`` (feminine self-presentation → «в женском роде»).
    """
    _seed_soul(tmp_path)
    gateway = FakeGateway()
    provider = _CapturingProvider(reply=_SCRIPTED_REPLY)
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
                sender_id=_LILY_ID,
                sender_name=_LILY_NAME,
            )
        )
        await app.intake_dispatcher.wait_for_idle()
    finally:
        await app.shutdown()
    assert provider.compose_prompts, "граф не собрал ни одной реплики (compose не вызван)"
    # The graph makes several non-judge calls (privilege probe, room read, the reply
    # compose). The reply compose — the one that folds Bob's full base voice + the
    # who-is-writing directive — is by far the LARGEST prompt; select it deterministically
    # so the assertion sees exactly what the model was told to generate Bob's reply from.
    return max(provider.compose_prompts, key=len)
