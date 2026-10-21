# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Register-recall acceptance harness for the BDD layer (BOB-087 Срез C).

Drives Bob's register-aware recall through REAL boundaries — the same three-layer read
path :class:`~bob.application.usecases.handle_message.HandleMessage` runs, with the ONLY
fake being the local Tier-0 model (the classifier's LLM boundary), mirroring how the other
coding/memory harnesses fake the model:

1. a realistic archive (Bob's own ``work`` dev episodes + ordinary ``message`` chat) is
   deposited into a REAL SQLite memory store, so a memory must EARN its place in the pool by
   matching the incoming question — nothing is hand-fed into the pipeline;
2. the REAL keyword recall (:class:`~bob.memory.adapters.fts_recall.Fts5MemoryRecall`)
   builds the pool — OVER-FETCHED (``_RECALL_OVERFETCH_K``) when register-recall is wired,
   the plain ``_RECALL_K`` fetch when it is off (INV-5) — and the REAL disclosure gate
   (:func:`~bob.social.disclosure.filter_surfaceable`, a no-op for the trusted owner) runs;
3. the REAL :class:`~bob.memory.usecases.resolve_register.RegisterResolver` over the REAL
   :class:`~bob.memory.usecases.classify_work_talk.ClassifyWorkTalk` (fed by a fake Tier-0
   provider) resolves the turn's :class:`~bob.memory.register.Register`, and the REAL
   :func:`~bob.memory.register_pipeline.register_ranked` applies the register-aware teeth;
4. the REAL voice gate (:func:`~bob.personality.voice.recall_has_work` +
   :func:`~bob.personality.voice.recalled_work_directive`) decides whether the first-person
   anti-confabulation work directive folds into Bob's compose prompt.

The scenarios then witness Bob's OBSERVABLE take-away at the composed-recall boundary —
which memories fill his final recall slots, whether any is a ``work`` episode, whether the
work provenance directive is active — never the store's or resolver's internals. The
``plain_recall`` field is the pre-register (flag-OFF) pool, so a scenario can assert the OFF
path is byte-identical to today (INV-5) and contrast it with the muted ON path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter
from bob.kernel.events import MessageReceived
from bob.kernel.interlocutor import Trust
from bob.memory.adapters.fts_recall import Fts5MemoryRecall
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.register_pipeline import pool_has_work, register_ranked
from bob.memory.usecases.classify_work_talk import ClassifyWorkTalk
from bob.memory.usecases.resolve_register import RegisterResolver
from bob.memory.work_journal import WORK_EVENT_TYPE
from bob.personality.voice import recall_has_work, recalled_work_directive
from bob.social.disclosure import filter_surfaceable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

# The production recall depths (mirrored from HandleMessage): the plain fetch when register
# recall is off, and the over-fetch that gives C1's attenuation something below the display
# slots to promote when it is on. The final slot count is _RECALL_K.
_RECALL_K = 5
_RECALL_OVERFETCH_K = 20

OWNER_ID = 27468732
_OWNER_CHAT_ID = OWNER_ID
_DEV_DM_CHAT_ID = 555001
_GROUP_CHAT_ID = -100200

_MESSAGE_EVENT_TYPE = "message"


class _FakeTier0Provider:
    """Stands in for the local Tier-0 model — the classifier's ONLY boundary.

    Returns a fixed one-word verdict (``work``/``chat``) and counts calls, so a scenario
    can prove the economy gate (no work in the pool → the model is never consulted).
    """

    def __init__(self, verdict: str) -> None:
        self._verdict = verdict
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.calls += 1
        return self._verdict


@dataclass(frozen=True, slots=True)
class Episode:
    """One archive memory seeded for a scenario (content + which domain it lives on)."""

    content: str
    is_work: bool


@dataclass(slots=True)
class RegisterOutcome:
    """What Bob would OBSERVABLY carry into his reply this turn.

    ``final`` — the contents of his final recall slots (post register-aware ranking);
    ``final_categories`` — the domain (``event_type``) of each surfaced slot; ``work_surfaced``
    — whether any ``work`` episode reached the final slots; ``work_directive_active`` /
    ``directive`` — whether the first-person work-provenance voice line folds in, and its text;
    ``register`` — the resolved register value (``dev``/``casual``); ``classifier_calls`` — how
    many times the Tier-0 model was consulted (0 proves the economy gate); ``plain_recall`` —
    the pre-register flag-OFF pool contents (the INV-5 identity baseline).
    """

    final: tuple[str, ...] = ()
    final_categories: tuple[str, ...] = ()
    work_surfaced: bool = False
    work_directive_active: bool = False
    directive: str = ""
    register: str = ""
    classifier_calls: int = 0
    plain_recall: tuple[str, ...] = field(default_factory=tuple)


async def run_register_recall(
    tmp_path: Path,
    *,
    archive: Sequence[Episode],
    question: str,
    register_recall_enabled: bool,
    work_talk_verdict: str = "chat",
    in_dev_dm: bool = False,
    in_group: bool = False,
) -> RegisterOutcome:
    """Seed ``archive``, then answer ``question`` through the real register-aware read path.

    Every episode is deposited into a real SQLite store; the real recall builds the pool
    (over-fetched iff ``register_recall_enabled``); the real disclosure gate (owner-trusted,
    a no-op) runs; when enabled the real resolver — over the real classifier fed the fixed
    ``work_talk_verdict`` — resolves the register and the real ranking pipeline applies the
    teeth. ``in_dev_dm`` routes the turn through the deterministic dev-DM signal;
    ``in_group`` places it in a group chat. Returns the observable final slots + provenance.
    """
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    provider = _FakeTier0Provider(work_talk_verdict)
    try:
        await _seed(repo, archive)

        # The pre-register baseline: the plain _RECALL_K fetch HandleMessage uses with the
        # flag off — recall byte-identical to today (INV-5).
        plain = filter_surfaceable(
            await Fts5MemoryRecall(repo).recall(question, k=_RECALL_K), Trust.TRUSTED
        )
        plain_contents = tuple(str(item.get("content", "")) for item in plain)

        event = _event(question, in_dev_dm=in_dev_dm, in_group=in_group)
        if not register_recall_enabled:
            final = plain
            register = ""
        else:
            fetch_k = _RECALL_OVERFETCH_K
            surfaceable = filter_surfaceable(
                await Fts5MemoryRecall(repo).recall(question, k=fetch_k), Trust.TRUSTED
            )
            resolver = RegisterResolver(
                classify_work_talk=ClassifyWorkTalk(
                    router=LLMRouter(providers={0: provider})
                ),
                dev_dm_chat_id=_DEV_DM_CHAT_ID if in_dev_dm else None,
            )
            resolved = await resolver.resolve(
                event, pool_has_work=pool_has_work(surfaceable)
            )
            register = resolved.value
            final = register_ranked(surfaceable, resolved, display_k=_RECALL_K)
    finally:
        await repo.close()

    active = recall_has_work(final)
    categories = tuple(str(item.get("category", "")) for item in final)
    return RegisterOutcome(
        final=tuple(str(item.get("content", "")) for item in final),
        final_categories=categories,
        work_surfaced=WORK_EVENT_TYPE in categories,
        work_directive_active=active,
        directive=recalled_work_directive() if active else "",
        register=register,
        classifier_calls=provider.calls,
        plain_recall=plain_contents,
    )


async def _seed(repo: SqliteMemoryRepo, archive: Sequence[Episode]) -> None:
    """Deposit each episode as a real episodic-log row on the right domain seam.

    Work episodes land as ``work`` events carrying Bob's operator provenance tags; chat
    episodes land as ordinary ``message`` turns. Timestamps march forward so ordering is
    deterministic, but recall ranks on BM25 relevance to the question, not recency.
    """
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


def _event(text: str, *, in_dev_dm: bool, in_group: bool) -> MessageReceived:
    """Build the incoming owner turn, routed to the dev-DM / group / owner-DM channel."""
    if in_dev_dm:
        chat_id = _DEV_DM_CHAT_ID
    elif in_group:
        chat_id = _GROUP_CHAT_ID
    else:
        chat_id = _OWNER_CHAT_ID
    return MessageReceived(
        update_id=1,
        chat_id=chat_id,
        message_id=1,
        text=text,
        sender_id=OWNER_ID,
        sender_name="Владимир",
        is_group=in_group,
    )
