# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Secondary-recall acceptance harness (BOB-087.C8) — the OTHER doors into Bob's reply.

Срез C guarded the primary reply-recall. Bob's memory reaches his reply through three more
doors, and this harness drives each of them through REAL boundaries — no hand-fed pools,
no fakes except where a fake is the boundary itself:

1. a realistic archive (Bob's own ``work`` dev episodes + ordinary chat) is deposited into a
   REAL SQLite memory store, so a memory must EARN its place by matching the query;
2. the REAL flag wiring (:func:`~bob.runtime.wiring.register_recall.build_secondary_recall`)
   decides what those doors draw through — the plain recall when ``memory.register_recall``
   is off, the REAL :class:`~bob.memory.adapters.casual_floor_recall.CasualFloorRecall` when
   it is on;
3. the doors themselves are the REAL collaborators: the REAL ``recall_memory`` capability
   dispatched through the REAL :class:`~bob.capabilities.usecases.registry.CapabilityRegistry`
   (the tool-loop's own path), the REAL
   :class:`~bob.personality.usecases.grounded_addons.GroundedAddons` folding its callback
   into a compose context, and the REAL
   :class:`~bob.conversation.usecases.recall_assembler.RecallAssembler` replaying the recent
   thread out of the same real store.

The scenarios then witness Bob's OBSERVABLE take-away at each door — what the tool hands
back, what text the compose context carries, what the replayed thread contains — never
private state. ``plain_*`` fields hold the flag-OFF result so a scenario can assert the OFF
path is byte-identical (INV-5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from random import Random
from typing import TYPE_CHECKING

from bob.capabilities.usecases.recall_memory import make_recall_memory_capability
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.conversation.usecases.recall_assembler import RecallAssembler
from bob.memory.adapters.fts_recall import Fts5MemoryRecall
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.work_journal import WORK_EVENT_TYPE
from bob.personality.expression import ExpressionMode, ExpressionPlan, FormHint
from bob.personality.usecases.grounded_addons import GroundedAddons
from bob.runtime.wiring.register_recall import build_secondary_recall
from tests.acceptance.register_recall_harness import OWNER_ID, Episode

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from bob.kernel.ports import MemoryRecall

_MESSAGE_EVENT_TYPE = "message"

# The tool draw the ``recall_memory`` capability advertises (its own default) and the recent
# thread window the assembler replays — production-shaped, not tuned for the scenarios.
_RECENT_TURNS = 14

_CALLBACK_PLAN = ExpressionPlan(
    mode=ExpressionMode.REPLY,
    leak_inner_life=False,
    callback=True,
    mention_fascination=False,
    form_hint=FormHint.NORMAL,
)


class _FixedClock:
    """The turn's clock — fixed, so the absence hint is deterministic."""

    def now(self) -> datetime:
        return datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


@dataclass(slots=True)
class SecondaryOutcome:
    """What Bob OBSERVABLY carries out of each secondary door this turn.

    ``tool_results`` — what the ``recall_memory`` tool handed the model; ``callback_line`` —
    the grounded-callback text folded into the compose context (``""`` when no moment was
    offered); ``replayed_thread`` — the recent-thread contents replayed into the prompt;
    ``work_in_tool`` / ``work_in_callback`` / ``work_in_thread`` — whether Bob's dev
    war-story got through that door; ``plain_tool_results`` / ``plain_callback_line`` — the
    flag-OFF baseline (the INV-5 identity).
    """

    tool_results: tuple[str, ...] = ()
    callback_line: str = ""
    replayed_thread: tuple[str, ...] = ()
    work_in_tool: bool = False
    work_in_callback: bool = False
    work_in_thread: bool = False
    plain_tool_results: tuple[str, ...] = field(default_factory=tuple)
    plain_callback_line: str = ""


async def run_secondary_doors(
    tmp_path: Path,
    *,
    archive: Sequence[Episode],
    question: str,
    register_recall_enabled: bool,
) -> SecondaryOutcome:
    """Seed ``archive``, then walk ``question`` through every secondary recall door.

    The doors draw through the port the REAL flag wiring builds (plain when register-recall
    is off, the CASUAL floor when on); the thread replay runs off the same real store. The
    flag-OFF baseline is always computed too, so a scenario can contrast the two.
    """
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    try:
        await _seed(repo, archive)
        plain_recall = Fts5MemoryRecall(repo)
        secondary = build_secondary_recall(
            _config(register_recall_enabled=register_recall_enabled), recall=plain_recall
        )

        tool_results = await _tool_recall(secondary, question)
        callback_line = await _callback_line(secondary, question)
        replayed = await _replayed_thread(repo)
        plain_tool_results = await _tool_recall(plain_recall, question)
        plain_callback_line = await _callback_line(plain_recall, question)
    finally:
        await repo.close()

    work_contents = tuple(
        episode.content for episode in archive if episode.is_work
    )
    return SecondaryOutcome(
        tool_results=tool_results,
        callback_line=callback_line,
        replayed_thread=replayed,
        work_in_tool=_holds_work(tool_results, work_contents),
        work_in_callback=_holds_work((callback_line,), work_contents),
        work_in_thread=_holds_work(replayed, work_contents),
        plain_tool_results=plain_tool_results,
        plain_callback_line=plain_callback_line,
    )


def _config(*, register_recall_enabled: bool) -> dict[str, object]:
    """The bare config slice the wiring reads — the real flag, nothing else."""
    return {"memory": {"register_recall": register_recall_enabled}}


async def _tool_recall(recall: MemoryRecall, question: str) -> tuple[str, ...]:
    """Dispatch the REAL ``recall_memory`` capability the way the tool-loop does."""
    registry = CapabilityRegistry()
    registry.register(make_recall_memory_capability(recall))
    result = await registry.dispatch("recall_memory", {"query": question})
    assert isinstance(result, dict)
    results = result["results"]
    assert isinstance(results, list)
    return tuple(str(item) for item in results)


async def _callback_line(recall: MemoryRecall, question: str) -> str:
    """Fold the REAL grounded callback over ``recall`` and return the added line."""
    addons = GroundedAddons(
        reflection=None,
        fascination=None,
        recall=recall,
        surface_old_freq=0.0,
        rng=Random(0),  # noqa: S311 — a seeded turn draw, not cryptography
    )
    context = await addons.with_grounded_addons("CONTEXT", question, _CALLBACK_PLAN)
    return context.removeprefix("CONTEXT").strip()


async def _replayed_thread(repo: SqliteMemoryRepo) -> tuple[str, ...]:
    """Replay the recent thread through the REAL assembler over the real store."""
    assembler = RecallAssembler(
        episodes=repo,
        recent_turns=_RECENT_TURNS,
        absence_hint_hours=8.0,
        notable_reaction=None,
        acknowledge_reaction_freq=0.0,
        clock=_FixedClock(),
        rng=Random(0),  # noqa: S311 — a seeded turn draw, not cryptography
    )
    history = await assembler.replay_recent_thread(None)
    return tuple(str(item.get("content", "")) for item in history)


def _holds_work(texts: Sequence[str], work_contents: Sequence[str]) -> bool:
    """Whether any of Bob's ``work`` episodes came through in ``texts``."""
    return any(work in text for text in texts for work in work_contents)


async def _seed(repo: SqliteMemoryRepo, archive: Sequence[Episode]) -> None:
    """Deposit each episode as a real episodic-log row on the right domain seam."""
    base = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)
    for index, episode in enumerate(archive):
        await repo.save_episode(
            {
                "ts": base.replace(minute=index).isoformat(),
                "event_type": WORK_EVENT_TYPE if episode.is_work else _MESSAGE_EVENT_TYPE,
                "content": episode.content,
                "tags": "work,dev,actor:bob" if episode.is_work else "",
                "sender_id": OWNER_ID,
            }
        )
