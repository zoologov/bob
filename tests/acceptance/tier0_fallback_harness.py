# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Harness for the Tier-0 fallback scenarios (BOB-087.E1/E2, BOB-Issues #34).

Drives a turn through the SAME boundary Bob's classifiers, inner monologue and coding
gates use — the real :class:`~bob.application.router.LLMRouter` over the real
:func:`~bob.infrastructure.llm.factory.build_tier_providers`, configured by the real
:class:`~bob.infrastructure.config.loader.ConfigLoader` (defaults <- env) — and reports
only what an observer OUTSIDE that boundary can see: what came back, which endpoint was
actually contacted, and what the operator's log says.

🔴 The endpoints are REAL loopback HTTP servers, not fakes. The BOB-084 lesson was that a
faked transport does not model the real one (a 64 KB reader limit that 4778 green fake
tests never saw crashed production), and this slice is ENTIRELY about transport failure:
so the outages here are genuine — a real timeout, a real 5xx, a real mid-request TCP
disconnect, a real refused connection — and the exceptions the policy classifies are the
ones aiohttp actually raises, never hand-constructed doubles.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from aiohttp import web

from bob.application.router import LLMRequest, LLMRouter, TaskType
from bob.infrastructure.config.loader import Config, ConfigLoader
from bob.infrastructure.llm.factory import build_tier_providers

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator, Mapping

# What an endpoint does with a request: answer it, break it, or kill the connection.
type _Reaction = Callable[[web.Request, str], Awaitable[web.StreamResponse]]

_CHAT_PATH = "/v1/chat/completions"

# What each endpoint says when it answers — the ONLY way a scenario can tell which model
# actually served the turn, observed through the router's return value.
CLOUD_REPLY: Final = "Отвечаю из облачного Tier-0."
LOCAL_REPLY: Final = "Отвечаю с локальной модели."
TIER1_REPLY: Final = "Отвечаю из Tier-1."

# A MEANINGFUL refusal by the model: a perfectly successful call whose content happens to
# be «нет». Never an outage — the fallback must not fire on it.
CLOUD_REFUSAL: Final = "Извини, на такое я отвечать не буду."

# The whole turn budget. Short so the «cloud never answers» outage is a real timeout that
# costs a fraction of a second; the hanging endpoint sleeps just past it.
_TIMEOUT_SECONDS: Final = 0.35
_HANG_SECONDS: Final = 1.0

# Endpoint behaviours a scenario can stage (see the module docstring: all are REAL).
ANSWERS: Final = "answers"
REFUSES: Final = "refuses"
BROKEN_SHAPE: Final = "broken_shape"
BAD_REQUEST: Final = "bad_request"
SERVER_ERROR: Final = "server_error"
HANGS: Final = "hangs"
DISCONNECTS: Final = "disconnects"
UNREACHABLE: Final = "unreachable"


@dataclass(slots=True)
class TurnOutcome:
    """What an observer outside the LLM boundary saw of one turn.

    Deliberately free of provider objects and internal state: a scenario may assert the
    text that came back, whether each endpoint was contacted, the failure that surfaced
    (and the failure attached as its cause), and the operator's warning log.
    """

    reply: str | None = None
    failure_text: str = ""
    failure_type: str = ""
    cause_text: str = ""
    cloud_tier0_calls: int = 0
    local_calls: int = 0
    tier1_calls: int = 0
    warnings: tuple[str, ...] = ()
    #: ``llm.tier0_fallback`` as the real loader resolved it for this turn.
    configured_fallback: str = ""


class _Endpoint:
    """A real loopback HTTP endpoint speaking the OpenAI chat-completions shape."""

    def __init__(self, *, behaviour: str, reply: str) -> None:
        self._behaviour = behaviour
        self._reply = reply
        self._runner: web.AppRunner | None = None
        self.base_url = ""
        self.calls = 0

    async def start(self) -> None:
        """Bind on loopback; for ``UNREACHABLE``, bind then release so the port refuses."""
        app = web.Application()
        app.router.add_post(_CHAT_PATH, self._handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        host, port = runner.addresses[0][0], runner.addresses[0][1]
        self.base_url = f"http://{host}:{port}/v1"
        if self._behaviour == UNREACHABLE:
            # Hand back a URL nobody is listening on: the connection is genuinely
            # refused, exactly as when the Ollama daemon is not running.
            await runner.cleanup()
            return
        self._runner = runner

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        self.calls += 1
        await request.read()
        react = _REACTIONS.get(self._behaviour, _answer)
        return await react(request, self._reply)


async def _answer(_request: web.Request, reply: str) -> web.StreamResponse:
    return _completion(reply)


async def _refuse(_request: web.Request, _reply: str) -> web.StreamResponse:
    return _completion(CLOUD_REFUSAL)


async def _bad_request(_request: web.Request, _reply: str) -> web.StreamResponse:
    return web.json_response({"error": "unknown model"}, status=400)


async def _server_error(_request: web.Request, _reply: str) -> web.StreamResponse:
    return web.json_response({"error": "upstream exploded"}, status=503)


async def _broken_shape(_request: web.Request, _reply: str) -> web.StreamResponse:
    # A 200 whose body has no ``choices``: the call succeeded, the CONTENT is wrong.
    return web.json_response({"id": "resp-1"})


async def _hang(_request: web.Request, reply: str) -> web.StreamResponse:
    await asyncio.sleep(_HANG_SECONDS)
    return _completion(reply)


async def _disconnect(request: web.Request, _reply: str) -> web.StreamResponse:
    transport = request.transport
    if transport is not None:
        transport.abort()
    # 204 deliberately: a status that would NOT trigger a fallback on its own, so the
    # scenario can only go green because the CONNECTION really died.
    return web.Response(status=204)


# behaviour -> what the endpoint actually does with the request.
_REACTIONS: Final[dict[str, _Reaction]] = {
    ANSWERS: _answer,
    REFUSES: _refuse,
    BAD_REQUEST: _bad_request,
    SERVER_ERROR: _server_error,
    BROKEN_SHAPE: _broken_shape,
    HANGS: _hang,
    DISCONNECTS: _disconnect,
    # UNREACHABLE never reaches a handler — the port is closed before the turn runs.
}


def _completion(content: str) -> web.Response:
    return web.json_response({"choices": [{"message": {"content": content}}]})


class _WarningCollector(logging.Handler):
    """Collects the WARNING+ lines the operator would see from Bob's own loggers."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextlib.contextmanager
def _collected_warnings() -> Iterator[_WarningCollector]:
    collector = _WarningCollector()
    logger = logging.getLogger("bob")
    previous_level = logger.level
    logger.addHandler(collector)
    logger.setLevel(logging.WARNING)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(previous_level)


@dataclass(slots=True)
class TurnRequest:
    """How a scenario stages one turn: the three endpoints, the flag, the task."""

    cloud_tier0: str = ANSWERS
    local: str = ANSWERS
    tier1: str = ANSWERS
    fallback_on: bool = True
    #: WORK_TALK is a Tier-0 classifier (BOB-087.C2) — the task shape the outage kills.
    task_type: TaskType = TaskType.WORK_TALK
    extra_env: Mapping[str, str] = field(default_factory=dict)


async def run_turn(request: TurnRequest) -> TurnOutcome:
    """Run one real turn through the router and report what crossed the boundary."""
    cloud = _Endpoint(behaviour=request.cloud_tier0, reply=CLOUD_REPLY)
    local = _Endpoint(behaviour=request.local, reply=LOCAL_REPLY)
    tier1 = _Endpoint(behaviour=request.tier1, reply=TIER1_REPLY)
    endpoints = (cloud, local, tier1)
    for endpoint in endpoints:
        await endpoint.start()
    try:
        return await _drive(request, cloud=cloud, local=local, tier1=tier1)
    finally:
        for endpoint in endpoints:
            await endpoint.stop()


async def _drive(
    request: TurnRequest,
    *,
    cloud: _Endpoint,
    local: _Endpoint,
    tier1: _Endpoint,
) -> TurnOutcome:
    config = _load_config(request, cloud=cloud, local=local, tier1=tier1)
    llm_section = config["llm"]
    outcome = TurnOutcome(configured_fallback=str(llm_section["tier0_fallback"]))
    router = LLMRouter(providers=build_tier_providers(config))
    llm_request = LLMRequest(
        task_type=request.task_type,
        messages=[{"role": "user", "content": "Боб, чем ты сейчас занят?"}],
    )
    with _collected_warnings() as collector:
        try:
            outcome.reply = await router.run(llm_request)
        except Exception as error:  # the surfaced failure IS the subject of the scenario
            outcome.failure_text = str(error)
            outcome.failure_type = type(error).__name__
            outcome.cause_text = str(error.__cause__) if error.__cause__ is not None else ""
        outcome.warnings = tuple(collector.messages)
    outcome.cloud_tier0_calls = cloud.calls
    outcome.local_calls = local.calls
    outcome.tier1_calls = tier1.calls
    return outcome


def _load_config(
    request: TurnRequest,
    *,
    cloud: _Endpoint,
    local: _Endpoint,
    tier1: _Endpoint,
) -> Config:
    """Resolve the effective config through the REAL loader (defaults <- env).

    The local endpoint is started even when the fallback is OFF, but the config never
    names it — so «OFF» is provable the honest way: the local server records zero calls.
    """
    env = {
        "BOB_LLM__TIER0_BASE_URL": cloud.base_url,
        "BOB_LLM__TIER0_MODEL": "cloud-tier0",
        "BOB_LLM__TIER1_BASE_URL": tier1.base_url,
        "BOB_LLM__TIER1_MODEL": "cloud-tier1",
        "BOB_LLM__TIMEOUT_SECONDS": str(_TIMEOUT_SECONDS),
        **request.extra_env,
    }
    if request.fallback_on:
        env["BOB_LLM__TIER0_FALLBACK"] = "ollama"
        env["BOB_LLM__TIER0_FALLBACK_BASE_URL"] = local.base_url
        env["BOB_LLM__TIER0_FALLBACK_MODEL"] = "local-understudy"
    return ConfigLoader(yaml_path=None, env=env).load()


def default_fallback_setting() -> str:
    """``llm.tier0_fallback`` with NO YAML and NO env — the shipped default."""
    config = ConfigLoader(yaml_path=None, env={}).load()
    llm = config["llm"]
    return str(llm["tier0_fallback"])
