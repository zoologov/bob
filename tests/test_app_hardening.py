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
from dataclasses import dataclass
from random import Random
from typing import TYPE_CHECKING

import pytest

import bob.app as app_module
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
from bob.application.usecases.evolve_phantoms import EvolvePhantoms
from bob.application.usecases.handle_message import PersonalityState
from bob.domain.personality.disposition import DEFAULT_DISPOSITION
from bob.domain.personality.mood import Mood
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteEngine
from bob.infrastructure.persistence import SoulStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Mapping, Sequence
    from pathlib import Path

    from bob.domain.ports import LLMProvider
    from bob.infrastructure.telegram.gateway import UpdateLike


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
        self, *, chat_id: int, text: str, message_thread_id: int | None = None  # noqa: ARG002
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
        message_thread_id: int | None = None,  # noqa: ARG002
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

    monkeypatch.setattr(app_module, "_build_real_bot", fake_build_real_bot)

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
            self, *, chat_id: int, text: str, message_thread_id: int | None = None  # noqa: ARG002
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


async def _spin_until(predicate: Callable[[], bool], *, limit: int = 1000) -> None:
    for _ in range(limit):
        if predicate():
            return
        await asyncio.sleep(0)
    msg = "condition not reached"
    raise AssertionError(msg)


# --- Lifecycle entrypoint (_run via main) -------------------------------------


def test_main_builds_and_runs_until_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: pre-seed a SOUL so startup's Genesis is a no-op; stub the
    # real-bot factory + asyncio.run so main() drives _run without a network.
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    monkeypatch.setattr(app_module, "_build_real_bot", lambda _section, _identity: _Bot())

    ran: dict[str, object] = {}

    def fake_asyncio_run(coro: Coroutine[object, object, None]) -> None:
        # Close the coroutine without awaiting (no event loop needed here).
        ran["coro"] = type(coro).__name__
        coro.close()

    monkeypatch.setattr("bob.app.asyncio.run", fake_asyncio_run)

    # build_application uses real config loader by default; inject config via env-free
    # path by patching build_application to use our fakes.
    monkeypatch.setattr(
        app_module,
        "build_application",
        lambda **_kw: _app(tmp_path),
    )

    # Act
    main()

    # Assert: main reached asyncio.run with the _run coroutine.
    assert ran["coro"] == "coroutine"


async def test_run_executes_full_lifecycle(tmp_path: Path) -> None:
    # Arrange: a pre-seeded soul; stop the runtime promptly so _run returns.
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    app = _app(tmp_path)

    # Act: run the lifecycle, scheduling a stop so run_until_stopped resolves.
    async def stop_soon() -> None:
        await _spin_until(lambda: app.runtime.is_running)
        await app.runtime.stop()

    stopper = asyncio.create_task(stop_soon())
    await app_module._run(app)
    await stopper

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
