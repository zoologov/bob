# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Tier-0 fallback verdict (BOB-087.E1, BOB-116) — pure, mutation-gated core.

Two questions under test, the second built on the first:

* :func:`classify_failure` — WHICH kind of failure is this (``auth`` / ``rate`` / ``server``
  / ``timeout`` / ``connection`` / ``shape`` / ``contract``)? The class is what the health
  monitor counts and what the owner is told (BOB-116 RFC «Класс отказа»);
* :func:`should_fall_back` — is THIS failure a reason to leave the preferred model for a
  weaker one? Every class but ``contract`` — yes. ``contract`` (our own bug, a mis-shaped
  request, a broken response body) and cancellation — no, because falling back there
  would mask defects instead of surviving an outage.

🔴 BOB-116: 401/403 moved from «contract» to ``auth`` → fallback. Bob was mute for ten days
on a 403 from the cloud because the policy called a revoked key «our defect» and let it
surface on every turn instead of letting the understudy answer.
"""

from __future__ import annotations

import asyncio
import json
import socket
from typing import cast

import aiohttp
import pytest

from bob.application.router.fallback_policy import classify_failure, should_fall_back


def _response_error(status: int) -> aiohttp.ClientResponseError:
    # The verdict reads only ``status``; the request metadata is irrelevant to it, so
    # the double leaves it empty rather than staging a full aiohttp request.
    request_info = cast("aiohttp.RequestInfo", None)
    return aiohttp.ClientResponseError(request_info, (), status=status, message="boom")


def _connector_error() -> aiohttp.ClientConnectorError:
    key = aiohttp.client_reqrep.ConnectionKey(
        host="api.qwen.example",
        port=443,
        is_ssl=True,
        ssl=True,
        proxy=None,
        proxy_auth=None,
        proxy_headers_hash=None,
    )
    return aiohttp.ClientConnectorError(key, ConnectionRefusedError("refused"))


# --- transport failures: the cloud endpoint is unreachable/unavailable -> fall back ---


def test_timeout_falls_back() -> None:
    # The 77-outage-in-a-row shape of BOB-084: the cloud call never answered.
    assert should_fall_back(TimeoutError()) is True


def test_asyncio_timeout_falls_back() -> None:
    # asyncio.TimeoutError is the builtin TimeoutError on 3.11+, asserted through the
    # asyncio name so the alias can never silently drift out of the transport class.
    error: BaseException = asyncio.TimeoutError()  # noqa: UP041 — the alias IS the subject
    assert should_fall_back(error) is True


def test_connection_refused_falls_back() -> None:
    assert should_fall_back(_connector_error()) is True


def test_server_disconnected_falls_back() -> None:
    # Not an OSError in aiohttp's hierarchy — it must be classified explicitly.
    assert should_fall_back(aiohttp.ServerDisconnectedError()) is True


def test_payload_error_falls_back() -> None:
    # The body was cut off mid-transfer: the transport died, not our request.
    assert should_fall_back(aiohttp.ClientPayloadError("truncated")) is True


def test_plain_os_error_falls_back() -> None:
    # DNS/socket-level failures surface as bare OSError subclasses.
    assert should_fall_back(socket.gaierror("name resolution failed")) is True


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_side_status_falls_back(status: int) -> None:
    assert should_fall_back(_response_error(status)) is True


def test_status_at_server_error_floor_falls_back() -> None:
    # 500 is IN the fallback class; 499 (the last 4xx) is NOT — pins the boundary.
    assert should_fall_back(_response_error(500)) is True
    assert should_fall_back(_response_error(499)) is False


def test_request_timeout_status_falls_back() -> None:
    # 408: the endpoint itself gave up waiting — an availability failure.
    assert should_fall_back(_response_error(408)) is True


def test_rate_limited_status_falls_back() -> None:
    # 429: the cloud will not serve us right now; the local model can.
    assert should_fall_back(_response_error(429)) is True


# --- the thresholds themselves, pinned from BOTH sides ---------------------------
#
# 🔴 These tests ARE the mutation gate of this policy (BOB-087.E3). mutmut mutates function
# BODIES only — while the 500 floor, the {408, 429} set and the transport roster lived in
# module-level constants, not a single mutant on those VALUES was even generated (4 mutants
# total, all on operators) and the reported 100% was stronger than the gate it measured.
# The policy values now live inside the function bodies, so mutmut really does shift the
# floor to 501, swap 408→409 / 429→430 and neutralise each transport shape one at a time —
# and each of those mutants dies on a case below, because every boundary is nailed from
# BOTH sides and every transport shape has a case that ONLY it can satisfy.


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (498, False),  # deep inside the client-error half
        (499, False),  # the last status that is still OUR problem
        (500, True),  # the floor itself
        (501, True),  # just above it
    ],
)
def test_server_error_floor_is_exactly_500(status: int, expected: bool) -> None:
    assert should_fall_back(_response_error(status)) is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (407, False),  # proxy auth required — a config defect of ours
        (408, True),  # the endpoint gave up waiting
        (409, False),  # conflict — a contract failure
        (428, False),  # precondition required — a contract failure
        (429, True),  # rate-limited: the cloud will not serve US right now
        (430, False),  # unassigned — must not be swept in with 429
    ],
)
def test_408_and_429_are_availability_statuses_and_their_neighbours_are_not(
    status: int, expected: bool
) -> None:
    assert should_fall_back(_response_error(status)) is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, False),  # bad request — OUR malformed call, surfaces
        (401, True),  # unauthorized — the key is revoked/expired: unavailable for us
        (402, False),  # payment required — not in the auth pair, stays a contract failure
        (403, True),  # forbidden — the BOB-116 shape: ten days mute on a 403
        (404, False),  # unknown model / path — a config defect of ours, surfaces
    ],
)
def test_only_401_and_403_are_auth_statuses(status: int, expected: bool) -> None:
    # 🔴 BOB-116: a revoked key or an exhausted account is not a defect a weaker model would
    # HIDE — the cloud refuses to serve us, exactly as on 429 — so for ROUTING it is an
    # outage. Both neighbours of each code are pinned so the pair cannot widen silently.
    assert should_fall_back(_response_error(status)) is expected


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_falls_back(status: int) -> None:
    assert should_fall_back(_response_error(status)) is True


# --- the class of a failure: what the health monitor counts and the owner is told ---


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        # auth — the cloud refuses US: revoked key, exhausted account
        pytest.param(_response_error(401), "auth", id="401 auth"),
        pytest.param(_response_error(403), "auth", id="403 auth"),
        # rate — rate-limited
        pytest.param(_response_error(429), "rate", id="429 rate"),
        # server — broken on their side, or the endpoint gave up waiting
        pytest.param(_response_error(408), "server", id="408 server"),
        pytest.param(_response_error(500), "server", id="500 server"),
        pytest.param(_response_error(501), "server", id="501 server"),
        pytest.param(_response_error(503), "server", id="503 server"),
        pytest.param(_response_error(599), "server", id="599 server"),
        # timeout — the request never came back
        pytest.param(TimeoutError(), "timeout", id="TimeoutError timeout"),
        pytest.param(aiohttp.ServerTimeoutError(), "timeout", id="ServerTimeoutError timeout"),
        # connection — the channel could not be established or held
        pytest.param(_connector_error(), "connection", id="refused connection"),
        pytest.param(aiohttp.ServerDisconnectedError(), "connection", id="disconnect connection"),
        pytest.param(socket.gaierror("dns"), "connection", id="gaierror connection"),
        pytest.param(ConnectionResetError("reset"), "connection", id="reset connection"),
        # shape — the body was cut off mid-transfer
        pytest.param(aiohttp.ClientPayloadError("truncated"), "shape", id="truncated shape"),
        # contract — our defect or a broken answer: surfaces, never masked
        pytest.param(_response_error(400), "contract", id="400 contract"),
        pytest.param(_response_error(402), "contract", id="402 contract"),
        pytest.param(_response_error(404), "contract", id="404 contract"),
        pytest.param(_response_error(407), "contract", id="407 contract"),
        pytest.param(_response_error(409), "contract", id="409 contract"),
        pytest.param(_response_error(413), "contract", id="413 contract"),
        pytest.param(_response_error(422), "contract", id="422 contract"),
        pytest.param(_response_error(428), "contract", id="428 contract"),
        pytest.param(_response_error(430), "contract", id="430 contract"),
        pytest.param(_response_error(499), "contract", id="499 contract"),
        pytest.param(ValueError("no choices"), "contract", id="ValueError contract"),
        pytest.param(json.JSONDecodeError("bad", "{", 0), "contract", id="JSON contract"),
        pytest.param(aiohttp.InvalidURL("http://[bad"), "contract", id="InvalidURL contract"),
        pytest.param(aiohttp.ClientError("x"), "contract", id="bare ClientError contract"),
        pytest.param(TypeError("x"), "contract", id="TypeError contract"),
        pytest.param(RuntimeError("x"), "contract", id="RuntimeError contract"),
        pytest.param(asyncio.CancelledError(), "contract", id="CancelledError contract"),
        pytest.param(KeyboardInterrupt(), "contract", id="KeyboardInterrupt contract"),
    ],
)
def test_classify_failure(error: BaseException, expected: str) -> None:
    assert classify_failure(error) == expected


@pytest.mark.parametrize(
    "error",
    [
        _response_error(401),
        _response_error(429),
        _response_error(503),
        TimeoutError(),
        _connector_error(),
        aiohttp.ClientPayloadError("truncated"),
        _response_error(400),
        ValueError("no choices"),
        asyncio.CancelledError(),
    ],
)
def test_should_fall_back_is_every_class_but_contract(error: BaseException) -> None:
    # The two answers cannot drift apart: the routing verdict IS «the class is not contract».
    assert should_fall_back(error) is (classify_failure(error) != "contract")


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(socket.gaierror("name resolution failed"), id="OSError entry"),
        pytest.param(aiohttp.ServerDisconnectedError(), id="ClientConnectionError entry"),
        pytest.param(aiohttp.ClientPayloadError("truncated"), id="ClientPayloadError entry"),
    ],
)
def test_each_transport_entry_is_load_bearing(error: BaseException) -> None:
    # Each error here matches EXACTLY ONE shape of the transport roster and nothing else
    # (``socket.gaierror`` is only an OSError; ``ServerDisconnectedError`` and
    # ``ClientPayloadError`` are aiohttp ClientErrors, NOT OSErrors) — so dropping any
    # single shape turns one of these red. This is what kills the mutants that neutralise
    # the roster one predicate at a time.
    assert should_fall_back(error) is True


def test_timeout_is_asked_before_the_socket_shape() -> None:
    # ``TimeoutError`` has been an ``OSError`` subclass since PEP 3151, and aiohttp's
    # ``ServerTimeoutError`` is a ``ClientConnectionError``. For the ROUTING verdict that
    # overlap is harmless (both fall back), but since BOB-116 the CLASS is reported to the
    # owner: a timeout read as «connection» would tell him the wrong thing. So the timeout
    # shape is load-bearing now, and asked first.
    assert issubclass(TimeoutError, OSError)
    assert classify_failure(TimeoutError()) == "timeout"
    assert classify_failure(aiohttp.ServerTimeoutError()) == "timeout"
    assert classify_failure(OSError("socket")) == "connection"


# --- contract failures: OUR bug or a broken answer -> never mask with a fallback ---


@pytest.mark.parametrize("status", [400, 404, 409, 413, 422])
def test_client_side_status_does_not_fall_back(status: int) -> None:
    # A malformed request / unknown model / oversized payload is a defect of ours: falling
    # back would hide it behind a quietly degraded local answer. 401/403 are NOT here since
    # BOB-116 — a revoked key is the cloud refusing us, see ``test_auth_failure_falls_back``.
    assert should_fall_back(_response_error(status)) is False


def test_content_type_error_does_not_fall_back() -> None:
    # A wrong content-type means the endpoint answered something we cannot parse —
    # a contract break to surface, not an outage to survive.
    assert should_fall_back(_response_error(400)) is False


def test_malformed_response_body_does_not_fall_back() -> None:
    # `_extract_message_content` raises ValueError when the body has no choices.
    assert should_fall_back(ValueError("completion response has no choices")) is False


def test_json_decode_error_does_not_fall_back() -> None:
    assert should_fall_back(json.JSONDecodeError("bad", "{", 0)) is False


def test_invalid_url_does_not_fall_back() -> None:
    # A mis-configured base_url is a config defect; the local model must not hide it.
    assert should_fall_back(aiohttp.InvalidURL("http://[bad")) is False


def test_type_error_does_not_fall_back() -> None:
    assert should_fall_back(TypeError("non-stream completion must return str")) is False


def test_empty_but_valid_reply_is_not_an_error_at_all() -> None:
    # A meaningful model refusal / empty-but-valid answer never raises, so nothing
    # reaches the policy. The closest raised shape — a RuntimeError from our own
    # orchestration — is still not a transport failure.
    assert should_fall_back(RuntimeError("model declined")) is False


def test_cancellation_does_not_fall_back() -> None:
    # Shutdown/caller cancellation must propagate instantly — never be "retried"
    # on the local model.
    assert should_fall_back(asyncio.CancelledError()) is False


def test_keyboard_interrupt_does_not_fall_back() -> None:
    assert should_fall_back(KeyboardInterrupt()) is False


def test_generic_client_error_does_not_fall_back() -> None:
    # A bare aiohttp.ClientError carries no evidence of a transport outage; only
    # the explicitly-classified transport shapes above do.
    assert should_fall_back(aiohttp.ClientError("something")) is False
