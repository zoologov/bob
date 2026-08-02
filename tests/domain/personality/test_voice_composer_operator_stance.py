# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Voice-composer OPERATOR-stance gate (BOB-087.B2).

Bob is the human OPERATOR who DIRECTS GUPPI (the executor owns the mechanical
firehose now, slice A) and REACTS to the milestones in his own voice — never a
robotic per-edit narrator (the BOB-074 poisoning failure mode). The operator
framing is folded into the base persona, so it must appear in the EXACT system
prompt the model receives. These drive the REAL
:class:`~bob.personality.usecases.voice_composer.VoiceComposer` through the
plain-reply tier and assert on the composed prompt string — the true send
boundary, never private state.
"""

from __future__ import annotations

import asyncio

from bob.personality.expression import Verbosity
from bob.personality.voice import operator_stance
from tests.acceptance.formatting_harness import composed_prompt


def test_operator_stance_is_folded_into_the_composed_prompt() -> None:
    prompt = asyncio.run(composed_prompt(Verbosity.NORMAL))

    # The whole operator framing reaches the model verbatim (base persona).
    assert operator_stance() in prompt


def test_composed_prompt_directs_guppi_and_forbids_step_by_step_narration() -> None:
    lowered = asyncio.run(composed_prompt(Verbosity.NORMAL)).casefold()

    # Bob directs GUPPI as its operator …
    assert "оператор" in lowered
    assert "guppi" in lowered
    # … and the anti-narration guard (no per-edit / step-by-step retelling) holds.
    assert "построчн" in lowered or "пошагов" in lowered
