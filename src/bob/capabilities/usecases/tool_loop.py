# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""ToolLoop — drive the model<->tools round-trip until a final answer.

GUPPI's tool-use loop, the act side of the capability seam. Given a seeded
conversation and the registry manifest, it:

1. asks the :class:`~bob.capabilities.ports.ToolCallingProvider` to complete the turn,
   offering the registered capabilities as ``tools``;
2. if the model requested tool calls, **dispatches** each through the registry
   (GUPPI executes), appends the assistant turn and a ``tool`` result message,
   and re-asks — looping until the model returns a final text answer;
3. caps the number of turns so a model that never finalises cannot run away.

An unknown tool is not fatal: the error is fed back as the tool result so the
model can recover, mirroring how a real tool failure would surface. This is pure
application policy; the capabilities' side effects live behind their own ports.

🔴 **The VOICE canon passes through here too (BOB-096.8).** The tool-loop is the SECOND —
and only other — point at which a payload leaves for a provider: the router builds one
kind of turn, this loop the other. The seam of BOB-096.3 stood only in the router, so the
loop's OWN caller — the one-shot privileged fulfilment
(:class:`~bob.application.usecases.privileged_fulfiller.PrivilegedRequestFulfiller`),
whose prompt says «You are Bob… Answer them directly, in character» — reached the model
with no ban on role-playing GUPPI at all (review MAJOR-1). So the same
:func:`~bob.application.router.voice_canon.fold_voice_canon` stands at THIS door too, and
every caller of the loop gets the canon by construction. It is idempotent, so the
conversational turn (whose persona already carries the ban verbatim) is byte-identical.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from bob.application.router.generation_door import TaskType, door_for
from bob.application.router.voice_canon import fold_voice_canon
from bob.capabilities.usecases.registry import UnknownCapabilityError
from bob.memory.self_action import SelfAction, SelfActionKind

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.application.router.voice_canon import VoiceCanon
    from bob.capabilities.ports import ToolCall, ToolCallingProvider
    from bob.capabilities.usecases.progress_announcer import ProgressAnnouncer
    from bob.capabilities.usecases.registry import CapabilityRegistry
    from bob.kernel.ports import ToolLoopMessage
    from bob.memory.ports import SelfActionRecorder

logger = logging.getLogger(__name__)

# Default ceiling on model turns in one loop: enough for a couple of tool hops,
# low enough that a model stuck requesting tools cannot loop forever.
_DEFAULT_MAX_TURNS = 6

# Cap on a recorded failure ``detail`` — one short line, so a self-action episode
# stays a terse first-person note, never a stack-trace dump in Bob's autobiography.
_MAX_DETAIL_CHARS = 80

# BOB-074 anti-narration backstop. A GUPPI mention TOGETHER with one of these
# intent-narration markers signals Bob narrated GUPPI's INTENT ("пошёл… заглянет…
# ищет… ждём отчёт") instead of returning a real tool result — the recall-poisoning
# few-shot signature. Kept deliberately NARROW: a miss only costs the pre-BOB-074
# behavior, a false hit wastes one Qwen call, so the predicate stays conservative.
_GUPPI_TOKENS = ("guppi", "гаппи", "гуппи")
_INTENT_MARKERS = (
    "пошёл",
    "пошел",
    "пошла",
    "заглян",
    "перебир",
    "ищет",
    "ищу",
    "сейчас посмотр",
    "сейчас гляну",
    "загружа",
    "ждём отчёт",
    "ждем отчет",
)

# The hard nudge injected for the ONE backstop retry: re-ask the model to emit a
# real tool call instead of narrating GUPPI's intent.
_NARRATION_NUDGE: ToolLoopMessage = {
    "role": "system",
    "content": (
        "Не описывай намерение GUPPI. Вызови нужный инструмент СЕЙЧАС (tool call) "
        "и верни реальный результат."
    ),
}


def _looks_like_tool_narration(text: str) -> bool:
    """True when ``text`` narrates GUPPI's tool INTENT instead of a real result.

    Conservative pure predicate (BOB-074): requires BOTH a GUPPI mention AND an
    intent-narration marker, so an ordinary reply (no GUPPI) or a GUPPI mention
    carrying a real result never trips it. It exists only to let the tool-loop
    re-ask ONCE for a real tool call; a miss is never worse than the pre-BOB-074
    behavior, a false hit only wastes one retry — hence the narrow signature.
    """
    lowered = text.lower()
    if not any(token in lowered for token in _GUPPI_TOKENS):
        return False
    return any(marker in lowered for marker in _INTENT_MARKERS)


class ToolLoop:
    """Run the model<->capability tool-use loop to a final text answer."""

    def __init__(
        self,
        *,
        provider: ToolCallingProvider,
        registry: CapabilityRegistry,
        max_turns: int = _DEFAULT_MAX_TURNS,
        announcer: ProgressAnnouncer | None = None,
        recorder: SelfActionRecorder | None = None,
        sender_id: int | None = None,
        visibility: str | None = None,
        voice_canon: VoiceCanon | None = None,
    ) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns must be positive")
        self._provider = provider
        self._registry = registry
        self._max_turns = max_turns
        self._announcer = announcer
        # 🔴 The VOICE canon for the turns that leave THROUGH THIS LOOP (BOB-096.8). Same
        # shape as the router's seam: the TEXT belongs to the persona and arrives injected,
        # an unwired seam leaves the payload byte-for-byte (every hand-built test loop), and
        # the composition root supplies the implementation at each construction site — which
        # an architectural test guards by PROPERTY, not by module name.
        self._voice_canon = voice_canon
        # Autobiography seam (BOB-079.3): Bob records that HE used tools, first-person.
        # ``None`` (the default, and the OFF-flag NoOp) → zero writes, behaviour as before.
        self._recorder = recorder
        self._sender_id = sender_id
        self._visibility = visibility

    async def run(self, messages: Sequence[ToolLoopMessage]) -> str:
        """Complete ``messages`` through the tool-loop and return the final text.

        Self-action recording (BOB-079.3) rides the loop COALESCED: the names of tools
        SUCCESSFULLY dispatched across the whole run are collected (dedup, first-seen order)
        and, at every exit, condensed into ONE ``TOOL_USE`` episode — one per turn max, so
        Bob's autobiography never floods (lesson BOB-076). A tool that FAILS records its own
        ``TOOL_FAILURE`` and is excluded from that summary; a run with no tool calls writes
        nothing at all.

        🔴 The voice canon is folded ONCE, here at the entry: every re-ask of the loop
        (tool round-trip, narration backstop) re-sends this same conversation, so the ban
        rides all of them — exactly as the router's single payload build carries it into the
        rescue attempt. The turn is the conversational door: whatever this loop answers is
        published to a human as Bob's words and settles into his memory.
        """
        tools = self._registry.manifest()
        conversation: list[ToolLoopMessage] = fold_voice_canon(
            list(messages), door=door_for(TaskType.REPLY_TO_USER), canon=self._voice_canon
        )
        used_tools: list[str] = []
        retried = False
        for turn_index in range(self._max_turns):
            result = await self._provider.complete_with_tools(conversation, tools=tools)
            if not result.tool_calls:
                # BOB-074 backstop: a no-tool-call turn that merely NARRATES GUPPI's
                # intent (recall-poisoning few-shot mimicry) is not a real answer. Re-ask
                # ONCE with a hard nudge to emit a real tool call — bounded by ``retried``
                # so a stubborn narration cannot loop, and never on the LAST turn (that
                # would drop below the pre-backstop return). If the re-ask still narrates
                # (or answers plainly) that text is returned — never worse than before.
                is_last_turn = turn_index == self._max_turns - 1
                if (
                    not retried
                    and not is_last_turn
                    and _looks_like_tool_narration(result.text)
                ):
                    retried = True
                    conversation.append(_NARRATION_NUDGE)
                    continue
                await self._record_tool_use(used_tools)
                return result.text
            conversation.append(_assistant_turn(result.tool_calls))
            for call in result.tool_calls:
                message, succeeded = await self._run_tool(call)
                conversation.append(message)
                if succeeded and call.name not in used_tools:
                    used_tools.append(call.name)
        await self._record_tool_use(used_tools)
        logger.warning("Tool loop hit the turn cap (%d) without a final answer", self._max_turns)
        return ""

    async def _run_tool(self, call: ToolCall) -> tuple[ToolLoopMessage, bool]:
        """Dispatch one tool call (GUPPI executes); return its ``tool`` message + success.

        A dispatch failure is fed back to the model as the tool result (so it can recover)
        AND recorded as a first-person ``TOOL_FAILURE`` self-action (BOB-079.3); the returned
        flag lets :meth:`run` coalesce only the SUCCESSFUL names into one ``TOOL_USE``.
        """
        # Interim "searching…" line (BOB-055): before a SLOW capability runs, let the
        # announcer say a live word in Bob's voice so the owner is not left in silence.
        # Decorative and by-name — the announcer stays silent for fast skills. The seam
        # does NOT trust the announcer to be well-behaved: any error here is swallowed so
        # a decorative interim line can NEVER delay or break the dispatch below (review .4).
        if self._announcer is not None:
            try:
                await self._announcer.announce(call.name, call.arguments)
            except Exception:  # decorative: an announcer fault must not touch the turn
                logger.exception("progress announce failed for %s; ignoring", call.name)
        succeeded = False
        try:
            result = await self._registry.dispatch(call.name, call.arguments)
        except UnknownCapabilityError:
            content = f"error: unknown capability '{call.name}'"
            await self._record_failure(call.name, "неизвестный инструмент")
        except Exception as exc:  # a tool failure must not crash the turn
            logger.exception("Capability %s failed during dispatch", call.name)
            content = f"error: capability '{call.name}' failed"
            await self._record_failure(call.name, _short_detail(exc))
        else:
            content = _render_result(result)
            succeeded = True
        message: ToolLoopMessage = {
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": content,
        }
        return message, succeeded

    async def _record_tool_use(self, names: Sequence[str]) -> None:
        """Coalesce the SUCCESSFUL tool names into one ``TOOL_USE`` self-action (or none)."""
        if not names:
            return
        await self._safe_record(
            SelfAction(kind=SelfActionKind.TOOL_USE, target=", ".join(names))
        )

    async def _record_failure(self, name: str, detail: str) -> None:
        """Record a first-person ``TOOL_FAILURE`` self-action for a failed dispatch."""
        await self._safe_record(
            SelfAction(kind=SelfActionKind.TOOL_FAILURE, target=name, detail=detail)
        )

    async def _safe_record(self, action: SelfAction) -> None:
        """Write one self-action BEST-EFFORT — a recording fault never breaks the turn.

        No recorder wired (the default / OFF-flag NoOp) → a silent no-op. Any failure of the
        recorder is swallowed so autobiography can never break the tool loop or the reply
        (lesson Part D BOB-078).
        """
        if self._recorder is None:
            return
        try:
            await self._recorder.record(
                action, sender_id=self._sender_id, visibility=self._visibility
            )
        except Exception:  # best-effort: a recording fault must not touch the turn
            logger.exception("self-action recording failed for %s; ignoring", action.kind)


def _assistant_turn(tool_calls: Sequence[ToolCall]) -> ToolLoopMessage:
    """Render the assistant turn that requested ``tool_calls`` (OpenAI-native shape).

    Carries the tool intent in the STRUCTURAL ``tool_calls`` array the OpenAI schema
    defines — NOT as a ``[tool_calls] …`` string smuggled into ``content`` (BOB-069).
    The old string form left the re-ask malformed (an assistant turn with no
    ``tool_calls``, a ``tool`` result referencing an ``id`` absent from the history),
    so Qwen echoed the string back verbatim and it leaked into the chat. Here each
    call becomes ``{"id","type":"function","function":{"name","arguments"}}`` with
    ``arguments`` a JSON STRING (as OpenAI expects) and ``id`` matching the
    ``tool_call_id`` :meth:`ToolLoop._run_tool` puts on the result — so the model
    binds each ``tool`` result to its call and drives on to a final text answer.
    """
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(dict(call.arguments)),
                },
            }
            for call in tool_calls
        ],
    }


def _short_detail(exc: Exception) -> str:
    """A terse one-line reason for a ``TOOL_FAILURE`` note (first line, length-capped)."""
    text = str(exc).strip() or exc.__class__.__name__
    return text.splitlines()[0][:_MAX_DETAIL_CHARS]


def _render_result(result: object) -> str:
    """Render a capability result into the textual ``tool`` message content."""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result)
    except (TypeError, ValueError):
        return str(result)
