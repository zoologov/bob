# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Formatting-for-the-reader acceptance harness (BOB-086.3).

Drives the two boundaries the PRD cares about, without the real LLM:

* the **composed system prompt** — the exact prompt string the model would receive —
  built by the REAL :class:`~bob.personality.usecases.voice_composer.VoiceComposer`
  over trivial fakes for its heavy collaborators. The GATE under test is production
  code (``formatting_directive() if verbosity is not Verbosity.TERSE else ""``): on a
  substantive turn (NORMAL/EXPANSIVE) the formatting guidance is folded in; on a TERSE
  (casual) turn it is withheld. We observe it via a recording ``plain_reply`` that
  captures the ``system_prompt`` it is handed — the true send boundary, never private
  state.
* the **converter** — the REAL
  :class:`~bob.infrastructure.telegram.rich.MarkdownToRichMessage`: a markdown GFM
  table becomes a native ``RichBlockTable`` (header / rows / alignment), the observable
  outcome a Telegram reader sees instead of a monospace wall.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.personality.expression import ExpressionMode, ExpressionPlan, FormHint, Verbosity
from bob.personality.mood import Mood
from bob.personality.negotiation import NegotiationZone, Stance
from bob.personality.soul import SOUL
from bob.personality.taste import TasteAxis, TasteEngine, Verdict
from bob.personality.usecases.voice_composer import VoiceComposer
from bob.personality.voice import OffDayThresholds

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from bob.memory.ports import Recalled
    from bob.personality.negotiation import NegotiationZone as _Zone


class _CapturingPlainReply:
    """The non-tool reply tier — records the ``system_prompt`` it is handed.

    This is the true send boundary: whatever prompt reaches ``__call__`` is exactly the
    prompt the LLM would receive. The scenarios assert on that captured text.
    """

    def __init__(self) -> None:
        self.system_prompt = ""

    async def __call__(self, system_prompt: str, text: str, context: str) -> str:  # noqa: ARG002
        self.system_prompt = system_prompt
        return "PLAIN-REPLY"


class _Essential:
    """Run the essential step inline (no retry for the prompt-assembly scenarios)."""

    async def run(
        self, operation: Callable[[], Awaitable[str]], *, step: str  # noqa: ARG002
    ) -> str:
        return await operation()


class _Addons:
    """Inert grounded-add-ons: pass context through untouched."""

    async def safe(self, awaitable: Awaitable[str], *, name: str = "") -> str:  # noqa: ARG002
        return await awaitable

    async def with_grounded_addons(
        self,
        context: str,
        text: str,  # noqa: ARG002
        plan: object,  # noqa: ARG002
        *,
        rng: object = None,  # noqa: ARG002
    ) -> str:
        return context


class _Assembler:
    """Inert recall-add-on ports (no absence / acknowledgment lines)."""

    def absence_for(
        self, history: object, interlocutor: object  # noqa: ARG002
    ) -> str | None:
        return None

    async def acknowledgment_for(self, interlocutor: object) -> str:  # noqa: ARG002
        return ""


class _Verify:
    """Inert epistemic-verify port (never adds a grounded/hedge note)."""

    async def note(
        self,
        text: str,  # noqa: ARG002
        history: object,  # noqa: ARG002
        *,
        interlocutor: object = None,  # noqa: ARG002
        chat_id: int | None = None,  # noqa: ARG002
    ) -> str:
        return ""


class _Social:
    """Canned stance so prompt assembly never touches the real social graph."""

    def decide_stance(
        self, soul: object, text: str, relationship: object  # noqa: ARG002
    ) -> tuple[Stance, Verdict, _Zone]:
        return (Stance.AGREE, Verdict.NEUTRAL, NegotiationZone.SHARED)

    def relationship_tone(self, relationship: object) -> str:  # noqa: ARG002
        return ""


class _EmptyRegistry:
    """Empty tool registry — the plain-reply path is taken regardless (provider=None)."""

    @property
    def is_empty(self) -> bool:
        return True

    def describe(self) -> str:
        return ""


class _RecordingContext:
    """The conversation context assembler — records the recalled set it is handed.

    The second observable boundary: whatever reaches the assembler is exactly the material
    that grounds the reply. Scenarios use it to prove что провенанс НИЧЕГО не вырезает —
    сквозная память (BOB-082) остаётся сквозной (BOB-090.C1).
    """

    def __init__(self) -> None:
        self.recalled: tuple[Recalled, ...] = ()

    def __call__(
        self,
        soul: object,  # noqa: ARG002
        topic: str,  # noqa: ARG002
        recalled: Sequence[Recalled],
        history: object,  # noqa: ARG002
        *,
        absence: str | None = None,  # noqa: ARG002
    ) -> str:
        self.recalled = tuple(recalled)
        return ""


def _soul() -> SOUL:
    """A minimal, neutral SOUL (mood/taste never branch on the formatting gate)."""
    return SOUL(
        identity="I am Bob — yes, that Bob.",
        mood=Mood(),
        mood_baseline=Mood(),
        taste=TasteEngine(axes=(TasteAxis(name="coffee", value=0.5, conviction=0.5),)),
    )


_PLAN = ExpressionPlan(
    mode=ExpressionMode.REPLY,
    leak_inner_life=False,
    callback=False,
    mention_fascination=False,
    form_hint=FormHint.NORMAL,
)


@dataclass(frozen=True, slots=True)
class ComposedTurn:
    """What ONE composed turn let us observe at the two boundaries.

    ``system_prompt`` — the exact prompt the model would receive; ``context_recalled`` —
    the recalled material that actually reached the context assembler (the grounding set).
    """

    system_prompt: str
    context_recalled: tuple[Recalled, ...]


async def compose_turn(
    verbosity: Verbosity,
    *,
    recalled: Sequence[Recalled] = (),
    origin_provenance: bool = False,
) -> ComposedTurn:
    """Compose ONE turn at ``verbosity`` and return what both boundaries observed.

    Routes through the plain-reply tier (``tool_provider=None``) so the captured
    ``system_prompt`` is exactly the prompt production would hand the LLM — the
    formatting gate (``verbosity is not TERSE``) is the real code under test. An
    optional ``recalled`` set feeds the recall-conditioned directives (e.g. the
    work-provenance line) through the REAL composer; ``origin_provenance`` is the
    production flag for the BOB-090.C1 «где это было» line (default OFF).
    """
    capturing = _CapturingPlainReply()
    context = _RecordingContext()
    composer = VoiceComposer(
        registry=_EmptyRegistry(),
        tool_provider=None,
        offday_thresholds=OffDayThresholds(),
        addons=_Addons(),  # type: ignore[arg-type]
        essential=_Essential(),
        assemble_context=context,
        assembler=_Assembler(),
        verify=_Verify(),
        social=_Social(),
        plain_reply=capturing,
        announcer_factory=lambda *, chat_id, sender_name: None,  # type: ignore[arg-type]  # noqa: ARG005
        tool_loop_factory=lambda provider, announcer: None,  # type: ignore[arg-type]  # noqa: ARG005
        origin_provenance=origin_provenance,
    )
    await composer.compose(
        "дай список багов из bob-issues с приоритетами",
        _soul(),
        recalled,
        (),
        _PLAN,
        verbosity=verbosity,
        chat_id=None,
    )
    return ComposedTurn(
        system_prompt=capturing.system_prompt, context_recalled=context.recalled
    )


async def composed_prompt(
    verbosity: Verbosity,
    *,
    recalled: Sequence[Recalled] = (),
    origin_provenance: bool = False,
) -> str:
    """The system prompt of ONE composed turn — the boundary most scenarios assert on."""
    turn = await compose_turn(
        verbosity, recalled=recalled, origin_provenance=origin_provenance
    )
    return turn.system_prompt
