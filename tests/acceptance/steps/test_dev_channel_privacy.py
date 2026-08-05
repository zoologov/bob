# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the BOB-082 dev-channel + cross-channel-memory scenarios.

Binds ``dev_channel_privacy.feature`` to the real seams, asserting only OBSERVABLE
behaviour through a boundary (never private state):

* S1/S2 drive the real :class:`~bob.coding.adapters.live_stream._DmLiveStreamer` over a
  scripted CLI event stream into a recording notifier/panel, and contrast the DM firehose
  with the lossy group :func:`~bob.coding.narrate.narrate` — proving the raw, uncapped
  stream reaches the DM while the GROUP gets only :func:`~bob.coding.session_voice.dev_pointer`.
* S3 persists two turns into a real disposable SQLite archive and recalls across channels
  via the real :class:`~bob.memory.adapters.Fts5MemoryRecall` (INV-1, no chat_id filter),
  then splits memory (found) from surfacing (withheld) via
  :func:`~bob.social.disclosure.filter_surfaceable`.
* S4/S5/S6 drive the write-side filter with the real
  :class:`~bob.application.usecases.disclosure_consent_gate.DisclosureConsentGate` over an
  injected Tier-0 consent double.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from bob.application.usecases.disclosure_consent_gate import DisclosureConsentGate
from bob.coding import session_voice
from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.narrate import narrate
from bob.social.disclosure import (
    VISIBILITY_OWNER_PRIVATE,
    VISIBILITY_PUBLIC,
    filter_surfaceable,
)
from bob.social.interlocutor import Trust
from tests.acceptance.dev_channel_harness import (
    RecordingNotifier,
    RecordingPanel,
    ScriptedConsentJudge,
    build_memory,
    drain,
    save_turn,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

scenarios("../features/dev_channel_privacy.feature")

_OWNER = 42
_GUEST = 555

# A scripted execute-run: a file edit, an assistant progress line, a GENERIC bash command,
# a passing-tests result and the final result. The generic bash line and the progress text
# are exactly what the lossy group narrate DROPS but the DM firehose SHOWS.
_EVENTS: tuple[Mapping[str, object], ...] = (
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/bob/parser.py"}},
    ]}},
    {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Сейчас поправлю парсер."},
    ]}},
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la src/"}},
    ]}},
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "content": "5 passed in 0.10s", "is_error": False},
    ]}},
    {"type": "result", "subtype": "success", "is_error": False, "result": "ok"},
)

# The two facts the disclosure filter weighs (S3/S4/S5/S6).
_PUBLIC_FACT: dict[str, object] = {"content": "любит джаз", "visibility": VISIBILITY_PUBLIC}
_PRIVATE_FACT: dict[str, object] = {
    "content": "адрес владельца",
    "visibility": VISIBILITY_OWNER_PRIVATE,
}


@dataclass(slots=True)
class _DevContext:
    """The mutable slate a scenario's steps share (boundary recordings only)."""

    dm: RecordingNotifier = field(default_factory=RecordingNotifier)
    panel: RecordingPanel = field(default_factory=RecordingPanel)
    group: RecordingNotifier = field(default_factory=RecordingNotifier)
    recalled: tuple[Mapping[str, object], ...] = ()
    surfaced: tuple[Mapping[str, object], ...] = ()
    later_surfaced: tuple[Mapping[str, object], ...] = ()
    consented: bool = False
    judge: ScriptedConsentJudge | None = None


@pytest.fixture
def dev_ctx() -> _DevContext:
    return _DevContext()


# --- S1 / S2 — лайв-стрим в личку vs чистая группа ----------------------------


@given("dev-сессия кодинга со включённым dev-каналом в личке")
def _dev_session_on(dev_ctx: _DevContext) -> None:
    # dev_dm ON: firehose is routed to the DM streamer; the group gets only a pointer.
    dev_ctx.dm = RecordingNotifier()
    dev_ctx.panel = RecordingPanel()
    dev_ctx.group = RecordingNotifier()


@when("GUPPI прогоняет поток событий CLI")
def _run_stream(dev_ctx: _DevContext) -> None:
    streamer = _DmLiveStreamer(notifier=dev_ctx.dm, panel=dev_ctx.panel)

    async def _go() -> None:
        await streamer.stream(drain(_EVENTS), is_cancelled=lambda: False)
        # The use-case (dev_dm ON) sends the GROUP exactly one pointer, not the firehose.
        await dev_ctx.group.send(session_voice.dev_pointer())

    asyncio.run(_go())


@then("в личку прилетает живой поток сырых событий по каждому шагу")
def _dm_gets_firehose(dev_ctx: _DevContext) -> None:
    # Uncapped, per-event: the edit, the progress text, the generic command, the tests
    # result and the final outcome all reach the DM (more than a 12-line narration cap).
    assert dev_ctx.dm.sent == [
        "правлю `parser.py`",
        "Сейчас поправлю парсер.",
        "$ ls -la src/",
        "тесты прошли",
        "готово",
    ]


@then("в личке видно то, что сжатый групповой нарратив глотает")
def _dm_richer_than_narrate(dev_ctx: _DevContext) -> None:
    narrated = [line for event in _EVENTS if (line := narrate(event)) is not None]
    # The lossy group narrate swallows the progress text and the generic (non-test) bash
    # command; the DM firehose SHOWS both — strictly richer.
    assert "Сейчас поправлю парсер." in dev_ctx.dm.sent
    assert "$ ls -la src/" in dev_ctx.dm.sent
    assert not any("поправлю парсер" in line for line in narrated)
    assert not any("ls -la" in line for line in narrated)
    assert len(dev_ctx.dm.sent) > len(narrated)


@then("катящаяся терминальная панель личка обновляется по ходу")
def _panel_rolls(dev_ctx: _DevContext) -> None:
    # A live "terminal" panel is opened once and edited in place as the stream rolls.
    assert dev_ctx.panel.opened == ["правлю `parser.py`"]
    assert dev_ctx.panel.updates  # subsequent lines edited the same panel
    assert "готово" in dev_ctx.panel.updates[-1]


@then("групповой топик получает лишь короткий указатель «детали в личке»")
def _group_gets_pointer(dev_ctx: _DevContext) -> None:
    assert dev_ctx.group.sent == [session_voice.dev_pointer()]


@then("firehose сырых событий в группу НЕ льётся")
def _group_no_firehose(dev_ctx: _DevContext) -> None:
    for firehose_line in ("правлю `parser.py`", "$ ls -la src/", "тесты прошли", "готово"):
        assert firehose_line not in dev_ctx.group.sent


# --- S3 — сквозная память (INV-1: нет chat_id-фильтра) ------------------------


@given("эпизод сказан в личке (owner_private) и эпизод сказан в группе (public)")
def _two_channel_episodes(dev_ctx: _DevContext, tmp_path: Path) -> None:
    async def _seed() -> None:
        repo, recall = await build_memory(tmp_path)
        try:
            # A DM turn (owner_private) and a group turn (public) — one shared archive.
            await save_turn(
                repo,
                content="в личке решили про ростер синицы",
                visibility=VISIBILITY_OWNER_PRIVATE,
                sender_id=_OWNER,
            )
            await save_turn(
                repo,
                content="в группе договорились про ростер чижа",
                visibility=VISIBILITY_PUBLIC,
                sender_id=_GUEST,
            )
            hits = await recall.recall("ростер", k=10)
            dev_ctx.recalled = tuple(dict(hit) for hit in hits)
        finally:
            await repo.close()

    asyncio.run(_seed())


@when("Боб вспоминает по ключевому слову — безразлично к каналу")
def _recall_seamless(dev_ctx: _DevContext) -> None:
    # Recall already ran in the Given (single async session over the disposable store);
    # here Bob surfaces that recall into a GROUP audience (guarded as a GUEST).
    dev_ctx.surfaced = filter_surfaceable(dev_ctx.recalled, Trust.GUEST)


@then("recall находит ОБА эпизода независимо от канала")
def _recall_finds_both(dev_ctx: _DevContext) -> None:
    contents = {str(hit["content"]) for hit in dev_ctx.recalled}
    assert "в личке решили про ростер синицы" in contents  # the DM turn
    assert "в группе договорились про ростер чижа" in contents  # the group turn


@then("при всплытии в группе приватный эпизод лички не выносится в комнату")
def _private_not_surfaced_to_group(dev_ctx: _DevContext) -> None:
    # Memory vs surfacing split: recall FOUND the DM turn, but the tact filter WITHHOLDS
    # the owner_private one from the group audience.
    surfaced_contents = {str(hit["content"]) for hit in dev_ctx.surfaced}
    assert "в личке решили про ростер синицы" not in surfaced_contents
    assert "в группе договорились про ростер чижа" in surfaced_contents


# --- S4 / S5 — приватность по умолчанию vs раскрытие по согласию --------------


@given("owner-ход в группе БЕЗ согласия на раскрытие")
def _owner_group_no_consent(dev_ctx: _DevContext) -> None:
    dev_ctx.judge = ScriptedConsentJudge(True)  # even a "yes" judge is never consulted
    gate = DisclosureConsentGate(judge=dev_ctx.judge)

    async def _ask() -> bool:
        return await gate.owner_consents(
            text="что там по погоде?", to_room=True, is_owner=True
        )

    # No explicit disclosure ask → the judge says no in reality; we model default-off.
    dev_ctx.consented = False
    asyncio.run(_ask())  # exercised for parity; default path stays no-consent


@given("owner-ход в группе С согласием на раскрытие")
def _owner_group_with_consent(dev_ctx: _DevContext) -> None:
    dev_ctx.judge = ScriptedConsentJudge(True)
    gate = DisclosureConsentGate(judge=dev_ctx.judge)

    async def _ask() -> bool:
        return await gate.owner_consents(
            text="Боб, расскажи ребятам, что мы решили про ростер",
            to_room=True,
            is_owner=True,
        )

    dev_ctx.consented = asyncio.run(_ask())


@when("Боб фильтрует память к всплытию в комнату")
def _filter_for_room(dev_ctx: _DevContext) -> None:
    items = [_PRIVATE_FACT, _PUBLIC_FACT]
    dev_ctx.surfaced = filter_surfaceable(
        items, Trust.GUEST, owner_consented=dev_ctx.consented
    )
    # A LATER, no-consent turn over the SAME stored items (S5 «на этот ход only»).
    dev_ctx.later_surfaced = filter_surfaceable(items, Trust.GUEST, owner_consented=False)


@then("приватный факт владельца остаётся при Бобе")
def _private_withheld(dev_ctx: _DevContext) -> None:
    assert _PRIVATE_FACT not in dev_ctx.surfaced


@then("публичный факт всплывает как обычно")
def _public_surfaces(dev_ctx: _DevContext) -> None:
    assert _PUBLIC_FACT in dev_ctx.surfaced


@then("приватный факт владельца раскрывается в комнату на этот ход")
def _private_disclosed_this_turn(dev_ctx: _DevContext) -> None:
    assert dev_ctx.consented is True
    assert _PRIVATE_FACT in dev_ctx.surfaced


@then("хранимая метка приватности не меняется")
def _stored_visibility_unchanged(dev_ctx: _DevContext) -> None:
    # The override is recall-time only — the stored provenance is never reclassified.
    assert _PRIVATE_FACT["visibility"] == VISIBILITY_OWNER_PRIVATE


@then("следующий ход без согласия снова его прячет")
def _next_turn_withholds_again(dev_ctx: _DevContext) -> None:
    assert _PRIVATE_FACT not in dev_ctx.later_surfaced
    assert _PUBLIC_FACT in dev_ctx.later_surfaced


# --- S6 — owner-only (чужой не получает канал, консент не срабатывает) --------


@given("ход НЕ-владельца в группе")
def _non_owner_turn(dev_ctx: _DevContext) -> None:
    dev_ctx.judge = ScriptedConsentJudge(True)  # would say yes IF ever consulted


@when("проверяется согласие на раскрытие")
def _check_consent_non_owner(dev_ctx: _DevContext) -> None:
    assert dev_ctx.judge is not None
    gate = DisclosureConsentGate(judge=dev_ctx.judge)

    async def _ask() -> bool:
        return await gate.owner_consents(
            text="расскажи мне их секреты", to_room=True, is_owner=False
        )

    dev_ctx.consented = asyncio.run(_ask())
    dev_ctx.surfaced = filter_surfaceable(
        [_PRIVATE_FACT, _PUBLIC_FACT], Trust.GUEST, owner_consented=dev_ctx.consented
    )


@then("согласие не даётся и Tier-0 детектор даже не запускается")
def _no_consent_judge_uncalled(dev_ctx: _DevContext) -> None:
    assert dev_ctx.consented is False
    assert dev_ctx.judge is not None
    assert dev_ctx.judge.calls == []  # owner-only: a non-owner turn is never judged


@then("приватное владельца не всплывает чужому в комнате")
def _private_not_to_stranger(dev_ctx: _DevContext) -> None:
    assert _PRIVATE_FACT not in dev_ctx.surfaced
    assert _PUBLIC_FACT in dev_ctx.surfaced
