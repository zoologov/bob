# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Judge-stub helpers for the live-app e2e/acceptance fakes (BOB-049).

The LIVE pipeline now makes one Tier-0 response-judgment call per turn
(:class:`~bob.infrastructure.llm.response_judge.LlmResponseJudge`) before composing,
deciding REPLY / REACT / IGNORE by meaning. The end-to-end fakes drive a single
fixed/scripted provider per tier, so without modelling the judgment the extra call
would (a) fail to parse into an intent and break the turn, or (b) shift a scripted
provider's reply sequence. These helpers let a provider recognise the judge prompt and
answer a scripted REPLY — modelling "Bob chose to reply", which is what the pre-BOB-049
e2e expectations assume — WITHOUT consuming a sequenced reply.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# A stable fragment of RESPONSE_JUDGE_SYSTEM_PROMPT (BOB-049) — present only on the
# response-judgment call, so a fake can tell it from a normal reply/sentiment/extract call.
_JUDGE_MARKER = "how to respond socially"

# The labelled REPLY judgment a stub returns for the judge call: Bob chooses to answer in
# words, so the turn falls through to the existing compose+send path the e2e tests assert.
JUDGE_REPLY = "intent: reply\nreason: e2e stub"


def is_judge_request(messages: Sequence[Mapping[str, str]]) -> bool:
    """Whether a router payload is the BOB-049 response-judgment prompt."""
    return any(_JUDGE_MARKER in str(m.get("content", "")) for m in messages)
