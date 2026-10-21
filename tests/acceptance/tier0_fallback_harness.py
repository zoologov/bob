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
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from aiohttp import web

from bob.application.router import LLMRequest, LLMRouter, TaskType
from bob.infrastructure.config.loader import Config, ConfigLoader
from bob.infrastructure.llm.factory import build_tier_providers

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence

# What an endpoint does with a request: answer it, break it, or kill the connection.
type _Reaction = Callable[[web.Request, str], Awaitable[web.StreamResponse]]

_CHAT_PATH = "/v1/chat/completions"
_MODELS_PATH = "/v1/models"

# What each endpoint says when it answers — the ONLY way a scenario can tell which model
# actually served the turn, observed through the router's return value.
CLOUD_REPLY: Final = "Отвечаю из облачного Tier-0."
LOCAL_REPLY: Final = "Отвечаю с локальной модели."
TIER1_REPLY: Final = "Отвечаю из Tier-1."

# A MEANINGFUL refusal by the model: a perfectly successful call whose content happens to
# be «нет». Never an outage — the fallback must not fire on it.
CLOUD_REFUSAL: Final = "Извини, на такое я отвечать не буду."

# 🔴 The two halves of the context split (Variant 2, VISION §7.1), staged as recognisable
# strings so a scenario can assert — on the RAW HTTP BODY each endpoint received — which
# half actually crossed which boundary. ``PRIVATE`` is genuinely-internal material a
# Tier-0-policy task legitimately carries; it must never appear in a Tier-1 request, not
# even along the emergency escalation path.
PRIVATE_CONTEXT: Final = "ВНУТРЕННЕЕ: черновик внутреннего монолога, не для облака."
SHAREABLE_CONTEXT: Final = "Из разговора: собеседника зовут Алиса."

# The whole turn budget. Short so the «cloud never answers» outage is a real timeout that
# costs a fraction of a second; the hanging endpoint sleeps just past it.
_TIMEOUT_SECONDS: Final = 0.35
_HANG_SECONDS: Final = 1.0

# Endpoint behaviours a scenario can stage (see the module docstring: all are REAL).
ANSWERS: Final = "answers"
REFUSES: Final = "refuses"
BROKEN_SHAPE: Final = "broken_shape"
BAD_REQUEST: Final = "bad_request"
UNAUTHORIZED: Final = "unauthorized"
FORBIDDEN: Final = "forbidden"
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
    #: The RAW request bodies each endpoint received, concatenated — the only honest way to
    #: ask what material actually crossed a boundary (BOB-087.E-M1 privacy scenarios).
    cloud_tier0_payload: str = ""
    local_payload: str = ""
    tier1_payload: str = ""


class LoopbackEndpoint:
    """A real loopback HTTP endpoint speaking the OpenAI chat-completions shape.

    Public for the LLM-health harness (BOB-116), which stages the same endpoints under a
    whole application: ``behaviour`` can be changed between calls (a provider that comes
    back), ``script`` stages the first calls one by one (a single 503 among answers), and
    ``models`` makes the endpoint answer ``GET /models`` in the Ollama shape, which the
    understudy check at startup reads. ``calls`` counts chat completions only.
    """

    def __init__(
        self,
        *,
        behaviour: str,
        reply: str,
        script: Sequence[str] = (),
        models: Sequence[str] | None = None,
    ) -> None:
        self.behaviour = behaviour
        self._reply = reply
        self._script = list(script)
        self._models = None if models is None else tuple(models)
        self._runner: web.AppRunner | None = None
        self.base_url = ""
        self.calls = 0
        #: ``GET /models`` lookups — the understudy check at startup, not a completion.
        self.model_lookups = 0
        #: Raw request bodies, in arrival order — what this endpoint was actually sent.
        self.bodies: list[str] = []

    async def start(self) -> None:
        """Bind on loopback; for ``UNREACHABLE``, bind then release so the port refuses."""
        app = web.Application()
        app.router.add_post(_CHAT_PATH, self._handle)
        if self._models is not None:
            app.router.add_get(_MODELS_PATH, self._list_models)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        host, port = runner.addresses[0][0], runner.addresses[0][1]
        self.base_url = f"http://{host}:{port}/v1"
        if self.behaviour == UNREACHABLE:
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
        # Keep the body BEFORE reacting: even a hanging or disconnecting endpoint has
        # already been told everything, so «what crossed the wire» stays observable.
        self.bodies.append((await request.read()).decode("utf-8", errors="replace"))
        behaviour = self._script.pop(0) if self._script else self.behaviour
        react = _REACTIONS.get(behaviour, _answer)
        return await react(request, self._reply)

    async def _list_models(self, _request: web.Request) -> web.StreamResponse:
        self.model_lookups += 1
        listed = [{"id": model} for model in self._models or ()]
        return web.json_response({"object": "list", "data": listed})

    @property
    def payload(self) -> str:
        """Everything this endpoint was ever sent, as a human would read it."""
        return "\n".join(_readable(body) for body in self.bodies)


def _readable(body: str) -> str:
    """A captured request body with its JSON escaping undone.

    aiohttp serialises ``json=`` with ``ensure_ascii=True``, so Cyrillic context arrives on
    the wire as ``\\uXXXX``. Un-escaping it here keeps the assertions honest AND readable:
    the scenario asks for the very string it staged, not for its transport encoding.
    """
    try:
        return json.dumps(json.loads(body), ensure_ascii=False)
    except ValueError:
        return body


async def _answer(_request: web.Request, reply: str) -> web.StreamResponse:
    return _completion(reply)


async def _refuse(_request: web.Request, _reply: str) -> web.StreamResponse:
    return _completion(CLOUD_REFUSAL)


async def _bad_request(_request: web.Request, _reply: str) -> web.StreamResponse:
    return web.json_response({"error": "unknown model"}, status=400)


async def _unauthorized(_request: web.Request, _reply: str) -> web.StreamResponse:
    # A revoked / expired key: the cloud refuses US (BOB-116) — not our malformed request.
    return web.json_response({"error": "invalid api key"}, status=401)


async def _forbidden(_request: web.Request, _reply: str) -> web.StreamResponse:
    # The BOB-116 production shape: an exhausted account / access denied, ten days of 403.
    return web.json_response({"error": "access denied"}, status=403)


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
    UNAUTHORIZED: _unauthorized,
    FORBIDDEN: _forbidden,
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
    #: The caller's tier choice for THIS turn (BOB-006 hybrid tiering: a short casual reply
    #: to the user runs on the fast Tier-0 model). ``None`` → the task's own default.
    tier_override: int | None = None
    #: The two halves of the context split — staged only by the privacy scenarios.
    shareable_context: str | None = None
    private_context: str | None = None
    extra_env: Mapping[str, str] = field(default_factory=dict)


async def run_turn(request: TurnRequest) -> TurnOutcome:
    """Run one real turn through the router and report what crossed the boundary."""
    cloud = LoopbackEndpoint(behaviour=request.cloud_tier0, reply=CLOUD_REPLY)
    local = LoopbackEndpoint(behaviour=request.local, reply=LOCAL_REPLY)
    tier1 = LoopbackEndpoint(behaviour=request.tier1, reply=TIER1_REPLY)
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
    cloud: LoopbackEndpoint,
    local: LoopbackEndpoint,
    tier1: LoopbackEndpoint,
) -> TurnOutcome:
    config = _load_config(request, cloud=cloud, local=local, tier1=tier1)
    llm_section = config["llm"]
    outcome = TurnOutcome(configured_fallback=str(llm_section["tier0_fallback"]))
    router = LLMRouter(providers=build_tier_providers(config))
    llm_request = LLMRequest(
        task_type=request.task_type,
        messages=[{"role": "user", "content": "Боб, чем ты сейчас занят?"}],
        shareable_context=request.shareable_context,
        private_context=request.private_context,
        tier_override=request.tier_override,
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
    outcome.cloud_tier0_payload = cloud.payload
    outcome.local_payload = local.payload
    outcome.tier1_payload = tier1.payload
    return outcome


def _load_config(
    request: TurnRequest,
    *,
    cloud: LoopbackEndpoint,
    local: LoopbackEndpoint,
    tier1: LoopbackEndpoint,
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
