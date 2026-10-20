# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Dev-introspection acceptance harness (BOB-081.3).

Drives Bob's read-only dev-introspection tools THROUGH the boundary the PRD cares
about — the capability registry + the REAL
:class:`~bob.capabilities.usecases.tool_loop.ToolLoop` — over a scripted, disk-free
:class:`~tests.application.capabilities.fakes.FakeRepoIntrospector`. The scenarios
witness the OBSERVABLE outcome: the tool result that flows BACK to the model (the
``tool`` message the loop feeds into the next turn), never the loop's internals or
the port's private state. A grounded reply can only be summarised from real data, so
"the tool output fed to the model carries the real text" is the acceptance signal.

For the authz scenario (S5b) the boundary is the REAL
:class:`~bob.personality.usecases.voice_composer.VoiceComposer` gate: a guest turn
NEVER runs the tool-loop (INV-4), so the dev tools are never offered. The composer's
heavy collaborators are trivial fakes; the gate itself (``not is_guest``) is the real
production code under test, observed via a recording tool-loop factory.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from bob.capabilities.usecases.list_tasks import make_list_tasks_capability
from bob.capabilities.usecases.recent_commits import make_recent_commits_capability
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.show_task import make_show_task_capability
from bob.capabilities.usecases.task_comments import make_task_comments_capability
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.kernel.ports import ToolCall, ToolCallResult
from bob.personality.expression import ExpressionMode, ExpressionPlan, FormHint
from bob.personality.mood import Mood
from bob.personality.negotiation import NegotiationZone, Stance
from bob.personality.soul import SOUL
from bob.personality.taste import TasteAxis, TasteEngine, Verdict
from bob.personality.usecases.voice_composer import VoiceComposer
from bob.personality.voice import OffDayThresholds
from tests.application.capabilities.fakes import FakeRepoIntrospector

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from bob.capabilities.ports import Capability
    from bob.kernel.episode_types import Recalled
    from bob.kernel.ports import LLMMessage, ToolCallingProvider, ToolDefinition, ToolLoopMessage
    from bob.personality.negotiation import NegotiationZone as _Zone

# --- the four real dev-introspection capabilities over one fake port -----------


def _registry_over(introspector: FakeRepoIntrospector) -> CapabilityRegistry:
    """Register the four real dev-introspection tools over the given fake port."""
    registry = CapabilityRegistry()
    registry.register(make_recent_commits_capability(introspector))
    registry.register(make_list_tasks_capability(introspector))
    registry.register(make_show_task_capability(introspector))
    registry.register(make_task_comments_capability(introspector))
    return registry


class _ToolProbeProvider:
    """A ``ToolCallingProvider`` that requests ONE tool, then finalises.

    Turn 1 asks for ``tool_name`` with ``arguments``; turn 2+ returns a plain final
    answer. It records the tool names it was OFFERED (the manifest) and the ``tool``
    result content fed BACK to it — the observable boundary the scenarios assert on.
    """

    def __init__(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> None:
        self._tool_name = tool_name
        self._arguments = arguments
        self._turn = 0
        self.offered_tools: list[str] = []
        self.fed_back_tool_results: list[str] = []

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        self.offered_tools = [_tool_name(tool) for tool in tools]
        for message in messages:
            if message.get("role") == "tool":
                self.fed_back_tool_results.append(str(message.get("content", "")))
        self._turn += 1
        if self._turn == 1:
            return ToolCallResult(
                text="",
                tool_calls=(
                    ToolCall(id="c1", name=self._tool_name, arguments=self._arguments),
                ),
            )
        return ToolCallResult(text="Готово, рассказываю своими словами.")


def _tool_name(tool: ToolDefinition) -> str:
    """Extract the advertised function name from a tool definition."""
    function = tool.get("function", {})
    name = function.get("name", "") if isinstance(function, dict) else ""
    return str(name)


async def run_dev_tool(
    introspector: FakeRepoIntrospector,
    *,
    tool: str,
    arguments: Mapping[str, object],
) -> str:
    """Drive the REAL tool-loop for ``tool`` and return the result fed back to the model.

    The loop renders the capability's dict result into the ``tool`` message content as
    JSON (the real wire shape the model receives). We decode that JSON back into its
    concatenated string values — the exact text a JSON-parsing model reconstructs and
    summarises from — so the scenario asserts on the real grounded content. Empty if
    nothing flowed back.
    """
    registry = _registry_over(introspector)
    provider = _ToolProbeProvider(tool, arguments)
    loop = ToolLoop(provider=provider, registry=registry)
    await loop.run([{"role": "user", "content": "тест-запрос"}])
    if not provider.fed_back_tool_results:
        return ""
    return _decode_tool_content(provider.fed_back_tool_results[0])


def _decode_tool_content(content: str) -> str:
    """Reconstruct the model-visible text from a ``tool`` message's JSON content.

    The tool-loop JSON-encodes the capability's dict result (ASCII-escaped on the
    wire); a JSON-parsing model decodes it. We mirror that: parse the JSON and join
    its string values, so the assertion sees the same grounded text the model does.
    Non-JSON content is returned verbatim.
    """
    try:
        decoded = json.loads(content)
    except (TypeError, ValueError):
        return content
    if isinstance(decoded, dict):
        return "\n".join(str(value) for value in decoded.values())
    return str(decoded)


# --- S5b: the guest authz gate through the REAL VoiceComposer ------------------


class _Essential:
    """Run the essential step inline (no retry needed for the gate scenario)."""

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
    """Canned stance so the prompt assembly never touches the real social graph."""

    def decide_stance(
        self, soul: object, text: str, relationship: object  # noqa: ARG002
    ) -> tuple[Stance, Verdict, _Zone]:
        return (Stance.AGREE, Verdict.NEUTRAL, NegotiationZone.SHARED)

    def relationship_tone(self, relationship: object) -> str:  # noqa: ARG002
        return ""


def _assemble_context(
    soul: object,
    topic: str,
    recalled: object,
    history: object,
    *,
    absence: str | None = None,
    mark_places: bool = False,
) -> str:
    return ""


async def _plain_reply(system_prompt: str, text: str, context: str) -> str:
    """The non-tool reply tier — the ONLY path a guest turn may take."""
    return "PLAIN-REPLY"


class _RecordingToolLoop:
    """A tool-loop that offers the registry manifest to the provider, then answers."""

    def __init__(
        self, provider: ToolCallingProvider, registry: CapabilityRegistry
    ) -> None:
        self._provider = provider
        self._registry = registry

    async def run(self, messages: Sequence[LLMMessage]) -> str:
        await self._provider.complete_with_tools(
            list(messages), tools=self._registry.manifest()
        )
        return "TOOL-REPLY"


class _RecordingToolLoopFactory:
    """Records whether the composer ever built a tool-loop (the non-guest gate)."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry
        self.calls = 0

    def __call__(
        self, provider: ToolCallingProvider, announcer: object  # noqa: ARG002
    ) -> _RecordingToolLoop:
        self.calls += 1
        return _RecordingToolLoop(provider, self._registry)


def _soul() -> SOUL:
    """A minimal, neutral SOUL for the gate scenario (mood/taste never branch here)."""
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


class _GateProbeProvider:
    """Records the tools it was offered when (and only when) the tool-loop runs."""

    def __init__(self) -> None:
        self.offered_tools: list[str] = []

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],  # noqa: ARG002
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        self.offered_tools = [_tool_name(tool) for tool in tools]
        return ToolCallResult(text="answered")


def _dev_capabilities() -> list[Capability]:
    """The four real dev tools over an empty fake port (execution never runs here)."""
    introspector = FakeRepoIntrospector()
    return [
        make_recent_commits_capability(introspector),
        make_list_tasks_capability(introspector),
        make_show_task_capability(introspector),
        make_task_comments_capability(introspector),
    ]


async def compose_turn(*, is_guest: bool) -> tuple[int, list[str]]:
    """Compose one turn through the REAL VoiceComposer gate.

    Returns ``(tool_loop_calls, offered_tool_names)``: for a guest the tool-loop is
    never built (0 calls, no tools offered); for an authorised turn it is (1 call, the
    dev tools offered). The gate (``not is_guest``) is the production code under test.
    """
    registry = _registry_over(FakeRepoIntrospector())
    provider = _GateProbeProvider()
    factory = _RecordingToolLoopFactory(registry)
    composer = VoiceComposer(
        registry=registry,
        tool_provider=provider,
        offday_thresholds=OffDayThresholds(),
        # ``addons`` is a CONCRETE collaborator (not a Protocol); the fake stubs its
        # behaviour at the boundary since the guest GATE never depends on add-on output.
        addons=_Addons(),  # type: ignore[arg-type]
        essential=_Essential(),
        assemble_context=_assemble_context,
        assembler=_Assembler(),
        verify=_Verify(),
        social=_Social(),
        plain_reply=_plain_reply,
        # Announcer is never built here (``chat_id=None``); the factory only satisfies the seam.
        announcer_factory=lambda *, chat_id, sender_name: None,  # type: ignore[arg-type]  # noqa: ARG005
        tool_loop_factory=factory,
    )
    recalled: Sequence[Recalled] = ()
    await composer.compose(
        "глянь последние коммиты",
        _soul(),
        recalled,
        (),
        _PLAN,
        is_guest=is_guest,
        chat_id=None,
    )
    return factory.calls, provider.offered_tools
