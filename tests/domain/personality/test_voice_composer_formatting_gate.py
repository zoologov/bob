# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Voice-composer formatting GATE (BOB-086.3).

The formatting directive is a distinct STRUCTURE axis from brevity's LENGTH axis: the
real ``VoiceComposer`` folds ``formatting_directive()`` into the system prompt EXACTLY
on a substantive turn (``verbosity is not TERSE``) and withholds it on a casual TERSE
turn — so a one-liner is never pushed toward a list. These tests assert on the composed
prompt string (the boundary the model receives), driving the real composer through the
plain-reply tier, never private state.
"""

from __future__ import annotations

import asyncio

import pytest

from bob.personality.expression import Verbosity
from bob.personality.voice import formatting_directive
from tests.acceptance.formatting_harness import composed_prompt


@pytest.mark.parametrize("verbosity", [Verbosity.NORMAL, Verbosity.EXPANSIVE])
def test_formatting_directive_present_on_substantive_turn(
    verbosity: Verbosity,
) -> None:
    prompt = asyncio.run(composed_prompt(verbosity))

    assert formatting_directive() in prompt


def test_formatting_directive_withheld_on_terse_turn() -> None:
    prompt = asyncio.run(composed_prompt(Verbosity.TERSE))

    assert formatting_directive() not in prompt
    # The casual turn still carries its strong short-answer brevity instruction.
    assert "очень коротко" in prompt.casefold()
