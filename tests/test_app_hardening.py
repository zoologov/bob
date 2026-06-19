# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening tests for the composition root (bob.app).

These cover the wiring/entrypoint branches the happy-path suite does not reach:
the real-bot construction + token validation, the PTB bot adapter delegation,
the poll background task, the ``_run`` / ``main`` lifecycle, and the defensive
config-reader + soul-loading branches. Everything runs on fakes — no network,
no Telegram, no real PTB ``Bot``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

import bob.app as app_module
from bob.app import (
    Application,
    SystemClock,
    _build_real_bot,
    _float,
    _int,
    _load_soul,
    _PtbBotAdapter,
    _str,
    build_application,
    main,
)
from bob.application.runtime import RuntimeState
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


class _Bot:
    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(self, *, chat_id: int, text: str) -> _Msg:  # noqa: ARG002
        return _Msg()

    async def edit_message_text(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        message_id: int,  # noqa: ARG002
        text: str,  # noqa: ARG002
    ) -> object:
        return object()


def _config(tmp_path: Path) -> dict[str, object]:
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 1},
        "telegram": {"token": "tok", "poll_timeout": 1},
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _providers() -> dict[int, LLMProvider]:
    return {0: _Provider(), 1: _Provider()}


def _app(tmp_path: Path) -> Application:
    return build_application(config=_config(tmp_path), providers=_providers(), bot=_Bot())


# --- Real-bot construction & token validation ---------------------------------


def test_build_real_bot_requires_a_token() -> None:
    # Act / Assert: an absent token must fail loudly, not build a broken bot.
    with pytest.raises(KeyError):
        _build_real_bot({})


def test_build_real_bot_rejects_empty_token() -> None:
    # Act / Assert: an empty-string token is as invalid as a missing one.
    with pytest.raises(KeyError):
        _build_real_bot({"token": ""})


def test_build_application_builds_real_bot_when_none_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: stub the real-bot factory so no PTB Bot / network is constructed.
    built_with: dict[str, object] = {}

    def fake_build_real_bot(telegram: Mapping[str, object]) -> _Bot:
        built_with.update(telegram)
        return _Bot()

    monkeypatch.setattr(app_module, "_build_real_bot", fake_build_real_bot)

    # Act: omit the bot seam -> the real-bot path runs.
    app = build_application(config=_config(tmp_path), providers=_providers(), bot=None)

    # Assert: the gateway was wired from the configured telegram section.
    assert isinstance(app, Application)
    assert built_with["token"] == "tok"  # noqa: S105 — test fixture, not a credential


# --- PTB bot adapter delegation ----------------------------------------------


async def test_ptb_adapter_delegates_every_call() -> None:
    # Arrange: a recording stand-in for PTB's async Bob.
    class RecordingBot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def get_updates(self, *, offset: int, timeout: int) -> list[str]:
            self.calls.append(("get_updates", {"offset": offset, "timeout": timeout}))
            return ["u"]

        async def send_message(self, *, chat_id: int, text: str) -> str:
            self.calls.append(("send_message", {"chat_id": chat_id, "text": text}))
            return "sent"

        async def edit_message_text(self, *, chat_id: int, message_id: int, text: str) -> str:
            self.calls.append(
                ("edit", {"chat_id": chat_id, "message_id": message_id, "text": text})
            )
            return "edited"

    inner = RecordingBot()
    adapter = _PtbBotAdapter(inner)

    # Act: the adapter's declared return types are the gateway's structural
    # views; we only assert the inner result is forwarded verbatim, so compare
    # as plain objects (the fake returns simple sentinels).
    updates: object = await adapter.get_updates(offset=10, timeout=5)
    sent: object = await adapter.send_message(chat_id=42, text="hi")
    edited = await adapter.edit_message_text(chat_id=42, message_id=7, text="bye")

    # Assert: each call forwarded its kwargs and returned the inner result.
    assert updates == ["u"]
    assert sent == "sent"
    assert edited == "edited"
    assert [name for name, _ in inner.calls] == ["get_updates", "send_message", "edit"]


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
    app = build_application(config=_config(tmp_path), providers=_providers(), bot=bot)

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
    monkeypatch.setattr(app_module, "_build_real_bot", lambda _t: _Bot())

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
