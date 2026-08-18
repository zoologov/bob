# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening tests for the composition root (bob.app).

These cover the wiring/entrypoint branches the happy-path suite does not reach:
the real-bot construction + token validation, the aiogram bot adapter delegation,
the poll background task, the ``_run`` / ``main`` lifecycle, and the defensive
config-reader + soul-loading branches. Everything runs on fakes — no network,
no Telegram, no real aiogram ``Bot``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from random import Random
from typing import TYPE_CHECKING

import pytest

import bob.runtime.composition as composition_module
import bob.runtime.main as main_module
from bob.app import (
    Application,
    SystemClock,
    _AiogramBotAdapter,
    _build_real_bot,
    _build_reranker,
    _float,
    _int,
    _load_soul,
    _str,
    build_application,
    main,
)
from bob.application.runtime import RuntimeState
from bob.application.usecases.handle_message import PersonalityState
from bob.personality.disposition import DEFAULT_DISPOSITION
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.taste import TasteEngine
from bob.personality.usecases.evolve_phantoms import EvolvePhantoms
from bob.social.adapters.soul_store import SoulStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Mapping, Sequence
    from pathlib import Path

    from bob.infrastructure.telegram.gateway import UpdateLike
    from bob.kernel.ports import LLMProvider


# --- Fakes --------------------------------------------------------------------


class _Provider:
    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        return "ok"


class _Msg:
    message_id = 1
    text: str | None = None
    message_thread_id: int | None = None


class _Bot:
    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,  # noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _Msg:
        return _Msg()

    async def set_message_reaction(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        message_id: int,  # noqa: ARG002
        reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        # BOB-018: react-only seam; fakes accept the BotLike reaction call.
        return True

    async def send_chat_action(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        action: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        rich_message: object,  # noqa: ARG002
        message_thread_id: int | None = None,# noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _Msg:
        return _Msg()

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _Msg:
        # BOB-035: BotLike parity; this fake's tests never post a photo.
        raise NotImplementedError  # pragma: no cover


    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _Msg:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

def _config(tmp_path: Path) -> dict[str, object]:
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 1},
        "telegram": {
            "poll_timeout": 1,
            "bob": {"token": "bob-tok", "topic_id": 0},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _providers() -> dict[int, LLMProvider]:
    return {0: _Provider(), 1: _Provider()}


def _app(tmp_path: Path) -> Application:
    return build_application(
        config=_config(tmp_path),
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )


# --- Real-bot construction & token validation ---------------------------------


def test_build_real_bot_requires_a_token() -> None:
    # Act / Assert: an absent token must fail loudly, not build a broken bot.
    with pytest.raises(KeyError):
        _build_real_bot({}, "bob")


def test_build_real_bot_rejects_empty_token() -> None:
    # Act / Assert: an empty-string token is as invalid as a missing one.
    with pytest.raises(KeyError):
        _build_real_bot({"token": ""}, "bob")


def test_build_reranker_off_by_default_returns_none() -> None:
    # The reranker is an ADDITIVE boost, off by default: with no ``reranker`` section
    # the composition root wires None (the hybrid order ships) rather than erroring.
    assert _build_reranker({}) is None


def test_build_reranker_degrades_to_none_on_misconfiguration() -> None:
    # US-3 resilience: a malformed ``reranker`` section (enabled but missing required
    # fields) must NOT crash the boot — it degrades to None (hybrid order unchanged).
    misconfigured = {"reranker": {"enabled": True}}  # no base_url/model/top_n

    assert _build_reranker(misconfigured) is None


def test_build_application_builds_real_bots_when_none_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: stub the real-bot factory so no aiogram Bot / network is built. The
    # composition root now builds TWO real bots (Bob + GUPPI) from their sections.
    built_tokens: list[object] = []

    def fake_build_real_bot(
        bot_section: Mapping[str, object], identity: str
    ) -> _Bot:
        built_tokens.append(bot_section.get("token"))
        return _Bot()

    monkeypatch.setattr(composition_module, "_build_real_bot", fake_build_real_bot)

    # Act: omit both bot seams -> the real-bot path runs for each.
    app = build_application(
        config=_config(tmp_path), providers=_providers(), bob_bot=None, guppi_bot=None
    )

    # Assert: both bots were wired from their configured telegram sections.
    assert isinstance(app, Application)
    assert "bob-tok" in built_tokens
    assert "guppi-tok" in built_tokens


# --- aiogram bot adapter delegation -------------------------------------------


async def test_aiogram_adapter_delegates_every_call() -> None:
    # Arrange: a recording stand-in for aiogram's async Bot. get_updates returns
    # aiogram-shaped updates (chat/sender nested under message); send/draft return
    # sentinels the adapter forwards verbatim.
    @dataclass(frozen=True)
    class _AiogramChat:
        id: int
        type: str = "supergroup"

    @dataclass(frozen=True)
    class _AiogramUser:
        id: int
        full_name: str

    @dataclass(frozen=True)
    class _AiogramMessage:
        message_id: int
        text: str | None
        chat: _AiogramChat
        from_user: _AiogramUser

    @dataclass(frozen=True)
    class _AiogramUpdate:
        update_id: int
        message: _AiogramMessage

    class RecordingBot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def get_updates(
            self,
            *,
            offset: int,
            timeout: int,
            allowed_updates: Sequence[str] | None = None,  # noqa: ARG002
        ) -> list[_AiogramUpdate]:
            self.calls.append(("get_updates", {"offset": offset, "timeout": timeout}))
            return [
                _AiogramUpdate(
                    update_id=3,
                    message=_AiogramMessage(
                        message_id=7,
                        text="hi",
                        chat=_AiogramChat(id=42),
                        from_user=_AiogramUser(id=9, full_name="Ann"),
                    ),
                )
            ]

        async def send_message(
            self, *, chat_id: int, text: str, message_thread_id: int | None = None,  # noqa: ARG002
            reply_parameters: object = None,  # noqa: ARG002
        ) -> str:
            self.calls.append(("send_message", {"chat_id": chat_id, "text": text}))
            return "sent"

        async def set_message_reaction(
            self,
            *,
            chat_id: int,  # noqa: ARG002
            message_id: int,  # noqa: ARG002
            reaction: object,  # noqa: ARG002
            message_thread_id: int | None = None,  # noqa: ARG002
        ) -> bool:
            # BOB-018: react-only seam; fakes accept the BotLike reaction call.
            return True

        async def send_chat_action(
            self,
            *,
            chat_id: int,
            action: str,
            message_thread_id: int | None = None,  # noqa: ARG002
        ) -> bool:
            self.calls.append(
                ("typing", {"chat_id": chat_id, "action": action})
            )
            return True

    inner = RecordingBot()
    adapter = _AiogramBotAdapter(inner)

    # Act
    updates = await adapter.get_updates(offset=10, timeout=5)
    sent: object = await adapter.send_message(chat_id=42, text="hi")
    typed = await adapter.send_chat_action(chat_id=42, action="typing")

    # Assert: get_updates normalises the aiogram update into the gateway's flat
    # UpdateLike (chat/sender lifted up); send/typing forward verbatim.
    assert len(updates) == 1
    view = updates[0]
    assert view.update_id == 3
    assert view.effective_chat is not None
    assert view.effective_chat.id == 42
    assert view.effective_user is not None
    assert view.effective_user.id == 9
    assert view.effective_user.full_name == "Ann"
    assert sent == "sent"
    assert typed is True
    assert [name for name, _ in inner.calls] == ["get_updates", "send_message", "typing"]


# --- Poll background task ------------------------------------------------------


async def test_poll_background_task_polls_the_gateway(tmp_path: Path) -> None:
    # Arrange: a bot whose get_updates records that polling happened.
    class CountingBot(_Bot):
        def __init__(self) -> None:
            self.polls = 0

        async def get_updates(
            self,
            *,
            offset: int,  # noqa: ARG002
            timeout: int,  # noqa: ARG002
        ) -> Sequence[UpdateLike]:
            self.polls += 1
            return []

    bot = CountingBot()
    app = build_application(
        config=_config(tmp_path),
        providers=_providers(),
        bob_bot=bot,
        guppi_bot=_Bot(),
    )

    # Act: the poll loop is a supervised background task; let it tick.
    await app.runtime.start()
    await _spin_until(lambda: bot.polls >= 1)
    await app.shutdown()

    # Assert
    assert bot.polls >= 1


# BOB-107: a REAL sleep interval, not ``sleep(0)``. Small enough to keep the tests
# quick, large enough to actually release the GIL so worker threads (aiosqlite runs the
# connection in one) get scheduled instead of being starved by the poller.
_SPIN_INTERVAL_SECONDS = 0.005

# BOB-107: an outer bound on the whole lifecycle, so a real hang fails with a message
# instead of being killed by pytest-timeout with nothing pointing at the cause.
_LIFECYCLE_TIMEOUT_SECONDS = 60.0


async def _spin_until(
    predicate: Callable[[], bool], *, timeout_seconds: float = 20.0
) -> None:
    """Wait until ``predicate()`` holds, bounded by WALL-CLOCK time.

    🔴 BOB-107. This used to budget in **event-loop turns** (``limit=1000`` with
    ``await asyncio.sleep(0)``) — two defects in one line, and together they hung the
    whole lifecycle test on any host with few cores:

    1. ``sleep(0)`` does not sleep, it only yields. A thousand yields elapse in ~10 ms,
       so "1000 tries" was never a meaningful budget for startup work that takes
       hundreds of milliseconds of real I/O.
    2. Worse, the hot spin **starves the very system it polls**: it holds the GIL and
       never yields the CPU, while ``aiosqlite`` needs its worker THREAD scheduled to
       answer each round-trip. With a free core the worker replies within a few turns
       (measured: 921 turns of the 1000 budget on a many-core host — a 7.9% margin);
       under a 2-core quota it is starved, the budget burns out in 0.01 s, and the
       waiter dies before the runtime ever reports itself running.

    Sleeping a real interval fixes both: the budget is measured in seconds (meaningful
    on any host) and the GIL is actually released, so worker threads make progress
    instead of being crowded out by the poller.
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        if predicate():
            return
        if time.monotonic() >= deadline:
            msg = f"condition not reached within {timeout_seconds:.0f}s"
            raise AssertionError(msg)
        await asyncio.sleep(_SPIN_INTERVAL_SECONDS)


# --- Lifecycle entrypoint (_run via main) -------------------------------------


def test_main_builds_and_runs_until_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: pre-seed a SOUL so startup's Genesis is a no-op; stub the
    # real-bot factory + asyncio.run so main() drives _run without a network.
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    monkeypatch.setattr(composition_module, "_build_real_bot", lambda _section, _identity: _Bot())

    ran: dict[str, object] = {}

    def fake_asyncio_run(coro: Coroutine[object, object, None]) -> None:
        # Close the coroutine without awaiting (no event loop needed here).
        ran["coro"] = type(coro).__name__
        coro.close()

    monkeypatch.setattr("bob.runtime.main.asyncio.run", fake_asyncio_run)

    # build_application uses real config loader by default; inject config via env-free
    # path by patching build_application to use our fakes.
    monkeypatch.setattr(
        main_module,
        "build_application",
        lambda **_kw: _app(tmp_path),
    )

    # Act
    main()

    # Assert: main reached asyncio.run with the _run coroutine.
    assert ran["coro"] == "coroutine"


async def test_run_executes_full_lifecycle(tmp_path: Path) -> None:
    """The real lifecycle runs and comes back to a stopped state.

    🔴 BOB-107: this test used to be skipped on CI, blamed on «an aiosqlite event-loop
    deadlock». There was no deadlock. ``_spin_until`` budgeted in loop turns, so on a
    2-core host the stopper gave up ~10 ms in, died with an ``AssertionError`` **nobody
    ever retrieved** (the test only reaches ``await stopper`` *after* ``_run`` returns),
    and ``run_until_stopped()`` then waited on an event no one would ever set. The
    runtime itself was fine — it was simply never asked to stop.

    Two structural fixes keep that failure mode from ever being silent again:
    ``gather`` runs the lifecycle and the stopper together, so a stopper failure
    SURFACES as that error instead of hanging; and the whole thing is bounded, so a
    genuine hang fails with a message rather than being killed by ``pytest-timeout``
    with no attribution.
    """
    # Arrange: a pre-seeded soul; stop the runtime promptly so _run returns.
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    app = _app(tmp_path)

    async def stop_soon() -> None:
        await _spin_until(lambda: app.runtime.is_running)
        await app.runtime.stop()

    # Act: 🔴 gather, NOT create_task + await-after. If stop_soon raises, gather
    # propagates it here immediately instead of leaving _run to wait forever.
    async with asyncio.timeout(_LIFECYCLE_TIMEOUT_SECONDS):
        await asyncio.gather(main_module._run(app), stop_soon())

    # Assert: the runtime came back to a stopped state and the db closed.
    assert app.runtime.state is RuntimeState.STOPPED


# --- Config-reader defensive branches -----------------------------------------


@pytest.mark.parametrize(
    ("section", "default", "expected"),
    [
        ({"x": True}, 9, 9),  # bool is NOT treated as int
        ({"x": 3}, 9, 3),  # genuine int
        ({"x": "42"}, 9, 42),  # numeric string
        ({"x": "abc"}, 9, 9),  # non-numeric string -> default
        ({}, 9, 9),  # absent -> default
    ],
)
def test_int_reader_handles_each_type(
    section: dict[str, object], default: int, expected: int
) -> None:
    assert _int(section, "x", default) == expected


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ({"x": True}, 0.0),  # bool -> 0.0
        ({"x": 2}, 2.0),  # int -> float
        ({"x": 1.5}, 1.5),  # float passthrough
        ({"x": "nope"}, 0.0),  # string -> 0.0
        ({}, 0.0),  # absent -> 0.0
    ],
)
def test_float_reader_handles_each_type(section: dict[str, object], expected: float) -> None:
    assert _float(section, "x") == expected


def test_str_reader_falls_back_on_blank_and_nonstr() -> None:
    assert _str({"x": ""}, "x", "d") == "d"
    assert _str({"x": 5}, "x", "d") == "d"
    assert _str({"x": "v"}, "x", "d") == "v"


def test_system_clock_now_is_utc() -> None:
    now = SystemClock().now()
    offset = now.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0


# --- Soul loading from malformed / partial artifacts --------------------------


def test_load_soul_returns_default_when_no_soul(tmp_path: Path) -> None:
    # Arrange: an empty soul dir (no SOUL.md).
    store = SoulStore(tmp_path / "soul")

    # Act
    soul = _load_soul(store)

    # Assert: the neutral pre-Genesis default.
    assert "awaiting Genesis" in soul.identity


def test_load_soul_tolerates_malformed_json_profiles(tmp_path: Path) -> None:
    # Arrange: SOUL.md exists but the JSON profiles are the wrong shapes.
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nI am the Bob from the book.\n")
    store.write_json("mood", {"baseline": "not-a-mapping", "current": 123})
    store.write_json("taste_profile", {"axes": "not-a-list"})
    store.write_json("phantom_prefs", {"preferences": "not-a-list"})

    # Act
    soul = _load_soul(store)

    # Assert: malformed sections degrade to neutral defaults, no crash.
    assert soul.identity
    assert soul.mood.valence == 0.0
    assert soul.taste.axes == ()
    assert soul.phantom_prefs == ()


def test_load_soul_falls_back_to_canon_disposition_when_absent(tmp_path: Path) -> None:
    # Arrange: a soul with no disposition.json (an existing install).
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nBob.\n")

    # Act
    soul = _load_soul(store)

    # Assert: existing installs Just Work — Bob keeps his canon-optimist default.
    assert soul.disposition == DEFAULT_DISPOSITION


def test_load_soul_reads_persisted_disposition(tmp_path: Path) -> None:
    # Arrange: a fully-formed disposition.json on disk.
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nBob.\n")
    store.write_json("disposition", {"optimism": 0.42, "resilience": 0.66})

    # Act
    soul = _load_soul(store)

    # Assert: the persisted traits round-trip into the loaded soul.
    assert soul.disposition.optimism == pytest.approx(0.42)
    assert soul.disposition.resilience == pytest.approx(0.66)


def test_load_soul_tolerates_partial_disposition_with_canon_fields(tmp_path: Path) -> None:
    # Arrange: only one trait present / malformed shape.
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nBob.\n")
    store.write_json("disposition", {"optimism": 0.3})

    # Act
    soul = _load_soul(store)

    # Assert: the present field is read; the missing one falls back to canon.
    assert soul.disposition.optimism == pytest.approx(0.3)
    assert soul.disposition.resilience == pytest.approx(DEFAULT_DISPOSITION.resilience)


def test_load_soul_parses_well_formed_taste_axes(tmp_path: Path) -> None:
    # Arrange: a fully-formed taste profile + phantom prefs.
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nBob.\n")
    store.write_json(
        "taste_profile",
        {
            "axes": [
                {"name": "probes", "value": 0.7, "conviction": 0.5, "experience_count": 3},
                "skip-this-non-mapping",
                {"value": 0.1},  # no name -> skipped
            ]
        },
    )
    store.write_json("phantom_prefs", {"preferences": ["coffee", "sunset"]})

    # Act
    soul = _load_soul(store)

    # Assert: only the valid axis survived; phantom prefs loaded.
    assert [a.name for a in soul.taste.axes] == ["probes"]
    assert soul.phantom_prefs == ("coffee", "sunset")


async def test_evolved_phantoms_round_trip_through_soul_store(tmp_path: Path) -> None:
    # BOB-020 wave 3: a phantom-evolution step persists via SoulStore.write_json, and
    # _load_soul reads the evolved set straight back — the membership survives a reload.
    class _Grounding:
        async def latest_reflection_text(self) -> str | None:
            return None

        def strong_taste_topics(self) -> tuple[str, ...]:
            return ("night trains",)

    class _AlwaysFires(Random):
        def random(self) -> float:
            return 0.0

    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nBob.\n")
    state = PersonalityState(
        soul=SOUL(
            identity="Bob.",
            mood=Mood(),
            mood_baseline=Mood(),
            taste=TasteEngine(),
            phantom_prefs=("coffee",),
        )
    )

    # Act: evolve (persists), then reload from disk.
    step = EvolvePhantoms(
        state=state, writer=store, grounding=_Grounding(), rng=_AlwaysFires()
    )
    await step.run()
    reloaded = _load_soul(store)

    # Assert: the emerged phantom survives the round-trip.
    assert "night trains" in state.soul.phantom_prefs
    assert "night trains" in reloaded.phantom_prefs
    assert reloaded.phantom_prefs == state.soul.phantom_prefs
