# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the composition root (bob.app) — graph wiring on fakes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.app import SystemClock, build_application
from bob.application.runtime import AgentRuntime, AsyncEventBus, RuntimeState
from bob.application.usecases.handle_message import HandleMessage
from bob.application.usecases.heartbeat import (
    InnerMonologueTick,
    MoodDriftTick,
    ReflectTick,
)
from bob.capabilities.usecases import (
    CapabilityNotAllowedError,
    SafeCapabilityDispatcher,
)
from bob.social.adapters.soul_store import SoulStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.infrastructure.telegram.gateway import UpdateLike
    from bob.kernel.ports import LLMProvider


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


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
    return build_application(
        config=_config(tmp_path),
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )


def test_build_application_returns_wired_runtime_and_bus(tmp_path: Path) -> None:
    # Act
    app = _app(tmp_path)

    # Assert: composition root produced the GUPPI runtime + event bus.
    assert isinstance(app.runtime, AgentRuntime)
    assert isinstance(app.event_bus, AsyncEventBus)
    assert app.runtime.state is RuntimeState.STOPPED


def test_build_application_wires_handler_and_ticks(tmp_path: Path) -> None:
    # Act
    app = _app(tmp_path)

    # Assert: the message handler and all three heartbeat ticks were composed.
    assert isinstance(app.handle_message, HandleMessage)
    assert isinstance(app.inner_monologue_tick, InnerMonologueTick)
    assert isinstance(app.mood_drift_tick, MoodDriftTick)
    assert isinstance(app.reflect_tick, ReflectTick)


def test_self_improvement_off_by_default_wires_nothing(tmp_path: Path) -> None:
    # BOB-028 .3: the master switch defaults OFF → no rule is applied, the reflect tick
    # runs no detector/announcer, GUPPI has no rule store. Behaviour exactly as before.
    app = _app(tmp_path)

    assert app.handle_message._self_improvement is None
    assert app.reflect_tick._detect_patterns is None
    assert app.reflect_tick._announce_rules is None


def test_self_improvement_enabled_wires_the_apply_and_reflect_seams(
    tmp_path: Path,
) -> None:
    # BOB-028 .3: with the master switch ON, the apply reader + the reflect-tick detector
    # and announcer are wired (the owner can now approve a rule and have it softly applied).
    config = _config(tmp_path)
    config["self_improvement"] = {"enabled": True}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    assert app.handle_message._self_improvement is not None
    assert app.reflect_tick._detect_patterns is not None
    assert app.reflect_tick._announce_rules is not None


_INTROSPECTION_CAPS = {"inspect_architecture", "read_code", "list_work"}


def _registered_names(app: object) -> set[str]:
    manifest = app.registry.manifest()  # type: ignore[attr-defined]
    names: set[str] = set()
    for tool in manifest:
        function = tool["function"]
        assert isinstance(function, dict)
        names.add(str(function["name"]))
    return names


def test_introspection_capabilities_advertised_when_enabled(tmp_path: Path) -> None:
    # BOB-017 .2: with introspection on, the three read-only self-introspection skills
    # are registered (advertised to the model + in the persona describe() manifest) so
    # Bob knows he can inspect his own world.
    config = _config(tmp_path)
    config["introspection"] = {"enabled": True}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    assert _registered_names(app) >= _INTROSPECTION_CAPS
    described = app.registry.describe()
    for name in _INTROSPECTION_CAPS:
        assert name in described


def test_introspection_capabilities_absent_when_disabled(tmp_path: Path) -> None:
    # BOB-017 .2: with introspection off, none of the three are registered — the
    # registry holds exactly the memory capabilities, behaviour as before.
    config = _config(tmp_path)
    config["introspection"] = {"enabled": False}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    names = _registered_names(app)
    assert _INTROSPECTION_CAPS.isdisjoint(names)
    # Regression: the memory capabilities are untouched by the introspection switch —
    # disabling introspection leaves recall/search exactly as before.
    assert {"recall_memory", "search_memory"} <= names


def test_memory_capabilities_present_in_both_introspection_modes(
    tmp_path: Path,
) -> None:
    # Regression guard: recall_memory + search_memory are registered regardless of the
    # introspection switch (BOB-017 adds skills behind the seam, removes none).
    base = {"recall_memory", "search_memory"}
    for enabled in (True, False):
        config = _config(tmp_path)
        config["introspection"] = {"enabled": enabled}
        app = build_application(
            config=config,
            providers=_providers(),
            bob_bot=_Bot(),
            guppi_bot=_Bot(),
        )
        assert base <= _registered_names(app)


def test_introspection_capabilities_not_on_autonomous_safe_allowlist(
    tmp_path: Path,
) -> None:
    # BOB-017 .2 stage boundary: the introspection skills stay conversation-only — they
    # are NEVER added to goals.safe_capabilities (the autonomous allowlist).
    config = _config(tmp_path)
    config["introspection"] = {"enabled": True}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    goals = app.config.get("goals", {})
    assert isinstance(goals, dict)
    safe = goals.get("safe_capabilities", [])
    assert isinstance(safe, list)
    assert _INTROSPECTION_CAPS.isdisjoint(set(safe))


async def test_safe_dispatcher_default_allowlist_refuses_introspection_caps(
    tmp_path: Path,
) -> None:
    # BOB-017 stage boundary, enforced (not just configured): a SafeCapabilityDispatcher
    # over the LIVE registry with the default/empty autonomous allowlist must NOT allow
    # or dispatch any introspection capability — they are conversation-only.
    config = _config(tmp_path)
    config["introspection"] = {"enabled": True}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    # The registry advertises them (conversation path) ...
    assert _registered_names(app) >= _INTROSPECTION_CAPS
    # ... but the autonomous safe dispatcher (default empty allowlist) refuses them.
    dispatcher = SafeCapabilityDispatcher(app.registry, allowlist=())
    for name in _INTROSPECTION_CAPS:
        assert dispatcher.allows(name) is False
        with pytest.raises(CapabilityNotAllowedError):
            await dispatcher.dispatch(name, {"ref": "bob", "query": "bob"})


# --- BOB-067: the repo-navigation skills ride the same seam --------------------


_NAVIGATION_CAPS = {"list_dir", "find_file"}


def test_navigation_capabilities_advertised_when_introspection_enabled(
    tmp_path: Path,
) -> None:
    # BOB-067: list_dir + find_file register behind the SAME introspection.enabled
    # flag (no new switch) so Bob can navigate his whole repo.
    config = _config(tmp_path)
    config["introspection"] = {"enabled": True}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    names = _registered_names(app)
    assert names >= _NAVIGATION_CAPS
    described = app.registry.describe()
    for name in _NAVIGATION_CAPS:
        assert name in described


def test_navigation_capabilities_absent_when_introspection_disabled(
    tmp_path: Path,
) -> None:
    # BOB-067: same switch as the other introspection skills — off means unregistered.
    config = _config(tmp_path)
    config["introspection"] = {"enabled": False}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    assert _registered_names(app).isdisjoint(_NAVIGATION_CAPS)


@pytest.mark.asyncio
async def test_navigation_capabilities_not_on_autonomous_safe_allowlist(
    tmp_path: Path,
) -> None:
    # BOB-067: the navigation skills stay conversation-only — never auto-dispatchable.
    config = _config(tmp_path)
    config["introspection"] = {"enabled": True}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    dispatcher = SafeCapabilityDispatcher(app.registry, allowlist=())
    for name in _NAVIGATION_CAPS:
        assert dispatcher.allows(name) is False
        with pytest.raises(CapabilityNotAllowedError):
            await dispatcher.dispatch(name, {"path": "src", "pattern": "*.py"})


# --- BOB-038: the code_rationale ("почему") skill rides the same seam ----------


def test_code_rationale_advertised_when_introspection_enabled(tmp_path: Path) -> None:
    # BOB-038: code_rationale is the fourth read-only introspection skill — advertised
    # to the model (and described) when introspection is on, alongside the other three.
    config = _config(tmp_path)
    config["introspection"] = {"enabled": True}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    names = _registered_names(app)
    assert "code_rationale" in names
    # Regression: BOB-038 ADDS a skill behind the seam, it removes none of the prior 3.
    assert names >= _INTROSPECTION_CAPS
    assert "code_rationale" in app.registry.describe()


def test_code_rationale_absent_when_introspection_disabled(tmp_path: Path) -> None:
    # BOB-038: with the seam off, code_rationale is not registered — same switch as
    # the other introspection skills, no separate exposure.
    config = _config(tmp_path)
    config["introspection"] = {"enabled": False}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    names = _registered_names(app)
    assert "code_rationale" not in names
    assert _INTROSPECTION_CAPS.isdisjoint(names)
    # Regression: the memory capabilities are untouched by the switch.
    assert {"recall_memory", "search_memory"} <= names


def test_code_rationale_not_on_autonomous_safe_allowlist(tmp_path: Path) -> None:
    # BOB-038 stage boundary: code_rationale is conversation-only — it is NEVER added
    # to goals.safe_capabilities (the autonomous allowlist).
    config = _config(tmp_path)
    config["introspection"] = {"enabled": True}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    goals = app.config.get("goals", {})
    assert isinstance(goals, dict)
    safe = goals.get("safe_capabilities", [])
    assert isinstance(safe, list)
    assert "code_rationale" not in safe


async def test_safe_dispatcher_default_allowlist_refuses_code_rationale(
    tmp_path: Path,
) -> None:
    # BOB-038 stage boundary, ENFORCED: a SafeCapabilityDispatcher over the live
    # registry with the default/empty autonomous allowlist neither allows nor
    # dispatches code_rationale — even though the conversation registry advertises it.
    config = _config(tmp_path)
    config["introspection"] = {"enabled": True}
    app = build_application(
        config=config,
        providers=_providers(),
        bob_bot=_Bot(),
        guppi_bot=_Bot(),
    )

    assert "code_rationale" in _registered_names(app)
    dispatcher = SafeCapabilityDispatcher(app.registry, allowlist=())
    assert dispatcher.allows("code_rationale") is False
    with pytest.raises(CapabilityNotAllowedError):
        await dispatcher.dispatch("code_rationale", {"query": "src/bob/app.py"})


def test_system_clock_returns_timezone_aware_now() -> None:
    # Act
    now = SystemClock().now()

    # Assert
    assert now.tzinfo is not None


@pytest.mark.asyncio
async def test_application_runtime_starts_and_stops(tmp_path: Path) -> None:
    # Arrange: pre-seed a SOUL so startup's Genesis is a no-op.
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    app = _app(tmp_path)
    await app.startup()

    # Act
    await app.runtime.start()
    running = app.runtime.is_running
    await app.shutdown()

    # Assert
    assert running is True
    assert app.runtime.state is RuntimeState.STOPPED


@pytest.mark.parametrize(
    ("missing", "identity"),
    [("bob", "bob"), ("guppi", "guppi")],
)
def test_build_application_without_injected_bot_requires_token(
    tmp_path: Path, missing: str, identity: str
) -> None:
    # Arrange: no injected bot for one identity AND its token blanked → the real
    # aiogram-bot path is taken and must reject the empty token (secrets are env
    # only; a missing token is a config error, never a silent network attempt).
    config = _config(tmp_path)
    telegram = config["telegram"]
    assert isinstance(telegram, dict)
    bot_section = telegram[missing]
    assert isinstance(bot_section, dict)
    bot_section["token"] = ""
    # Inject only the OTHER bot so the failure is isolated to `missing`.
    bob_bot = None if missing == "bob" else _Bot()
    guppi_bot = None if missing == "guppi" else _Bot()

    # Act / Assert
    with pytest.raises(KeyError, match=f"telegram.{identity}.token"):
        build_application(
            config=config,
            providers=_providers(),
            bob_bot=bob_bot,
            guppi_bot=guppi_bot,
        )
