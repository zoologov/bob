# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Anti-narration backstop for ToolLoop (BOB-074).

Recall-poisoning makes Qwen mimic Bob's past «GUPPI пошёл… ждём отчёт» turns and
sometimes emit NO tool_call — the loop then returns that narration, which persists
and re-poisons. These pin the structural self-healing fix:

* :func:`_looks_like_tool_narration` — a conservative pure predicate (GUPPI mention
  + intent-narration marker, no real content);
* the loop backstop — on a no-tool-call NARRATION it re-asks EXACTLY ONCE with a hard
  nudge; a real tool call drives on, a legit plain answer returns immediately, and a
  stubborn narration is returned unchanged (never worse than before).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.capabilities.ports import ToolCall, ToolCallResult
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop, _looks_like_tool_narration

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.capabilities.ports import Permission, ToolDefinition
    from bob.kernel.ports import ToolLoopMessage


class _FakeCapability:
    name = "list_dir"
    description = "List a directory."
    input_schema: Mapping[str, object] = {"type": "object", "properties": {}}
    permission: Permission = "safe"

    def __init__(self, *, result: object = "main.py\nports.py") -> None:
        self._result = result
        self.calls: list[Mapping[str, object]] = []

    async def execute(self, args: Mapping[str, object]) -> object:
        self.calls.append(args)
        return self._result


class _ScriptedProvider:
    """Returns a scripted ToolCallResult per turn (clamped to the last one)."""

    def __init__(self, results: Sequence[ToolCallResult]) -> None:
        self._results = list(results)
        self.turns: list[list[dict[str, object]]] = []

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],  # noqa: ARG002
    ) -> ToolCallResult:
        self.turns.append([dict(m) for m in messages])
        index = min(len(self.turns) - 1, len(self._results) - 1)
        return self._results[index]

    @property
    def calls(self) -> int:
        return len(self.turns)


def _registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(_FakeCapability())
    return registry


def _seed() -> list[ToolLoopMessage]:
    return [{"role": "user", "content": "загляни в for-bob/presentation"}]


# --- predicate: narration → True -------------------------------------------------

_POISONED_NARRATION = (
    "GUPPI, загляни в for-bob/presentation. Он уже пошёл искать файлы. Ждём отчёт."
)


@pytest.mark.parametrize(
    "text",
    [
        _POISONED_NARRATION,
        "GUPPI сейчас посмотрю, что там в каталоге",
        "guppi перебирает файлы, скоро вернётся",
        "Гаппи пошёл заглянуть в папку",
    ],
)
def test_predicate_flags_guppi_intent_narration(text: str) -> None:
    assert _looks_like_tool_narration(text) is True


# --- predicate: legit / plain text → False (conservative) ------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Твоё имя — Ада.",
        "Вот содержимое каталога: main.py, ports.py, README.md",
        "GUPPI выполнил поиск, вот что нашлось: main.py, ports.py",  # GUPPI + real result
        "Он уже пошёл в магазин за хлебом",  # intent verb, no GUPPI → not our bug
        "Сейчас посмотрю расписание на завтра",  # no GUPPI
    ],
)
def test_predicate_ignores_plain_and_grounded_text(text: str) -> None:
    assert _looks_like_tool_narration(text) is False


# --- backstop: narration → exactly ONE retry that then calls the tool ------------


async def test_narration_without_tool_call_triggers_one_retry_then_drives_tool() -> None:
    call = ToolCall(id="c1", name="list_dir", arguments={"path": "for-bob/presentation"})
    provider = _ScriptedProvider(
        [
            ToolCallResult(text=_POISONED_NARRATION, tool_calls=()),  # turn 1: narration
            ToolCallResult(text="", tool_calls=(call,)),  # turn 2 (retry): real tool call
            ToolCallResult(text="Вот файлы: main.py, ports.py", tool_calls=()),  # turn 3
        ]
    )
    loop = ToolLoop(provider=provider, registry=_registry())

    answer = await loop.run(_seed())

    assert answer == "Вот файлы: main.py, ports.py"
    assert provider.calls == 3  # narration + retry(tool) + final
    # the hard nudge was injected before the retry
    nudge = "\n".join(str(m.get("content", "")) for m in provider.turns[1])
    assert "СЕЙЧАС" in nudge


# --- backstop: a real tool call on turn 1 → NO retry, no nudge -------------------


async def test_immediate_tool_call_is_not_retried() -> None:
    call = ToolCall(id="c1", name="list_dir", arguments={"path": "."})
    provider = _ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="готово", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=provider, registry=_registry())

    answer = await loop.run(_seed())

    assert answer == "готово"
    for turn in provider.turns:
        for message in turn:
            assert "СЕЙЧАС" not in str(message.get("content", ""))


# --- backstop: legit plain answer without tool call → immediate return, no retry -


async def test_legit_plain_answer_returns_without_retry() -> None:
    provider = _ScriptedProvider([ToolCallResult(text="Привет! Как ты?", tool_calls=())])
    loop = ToolLoop(provider=provider, registry=_registry())

    answer = await loop.run(_seed())

    assert answer == "Привет! Как ты?"
    assert provider.calls == 1  # no backstop retry on legit text


# --- backstop: stubborn narration → returned unchanged, bounded to ONE retry -----


async def test_repeated_narration_is_returned_and_retry_is_bounded() -> None:
    provider = _ScriptedProvider([ToolCallResult(text=_POISONED_NARRATION, tool_calls=())])
    loop = ToolLoop(provider=provider, registry=_registry())

    answer = await loop.run(_seed())

    assert answer == _POISONED_NARRATION  # not worse than before
    assert provider.calls == 2  # first + exactly ONE retry, then give up


# --- backstop: never retries on the LAST allowed turn (no worse than before) -----


async def test_no_retry_on_last_turn_returns_narration() -> None:
    provider = _ScriptedProvider([ToolCallResult(text=_POISONED_NARRATION, tool_calls=())])
    loop = ToolLoop(provider=provider, registry=_registry(), max_turns=1)

    answer = await loop.run(_seed())

    assert answer == _POISONED_NARRATION
    assert provider.calls == 1  # single turn budget → no retry attempted
