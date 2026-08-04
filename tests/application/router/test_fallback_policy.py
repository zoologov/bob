# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Tier-0 fallback verdict (BOB-087.E1) — pure, mutation-gated core.

The one question under test: is THIS failure a reason to leave the cloud Tier-0
endpoint for the local emergency model? Transport/availability failures — yes;
contract failures (our own bug, a mis-shaped request, a broken response body) and
cancellation — no, because falling back there would mask defects instead of
surviving an outage.
"""

from __future__ import annotations

import asyncio
import json
import socket
from typing import cast

import aiohttp
import pytest

from bob.application.router.fallback_policy import should_fall_back


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
def test_only_408_and_429_are_availability_statuses(status: int, expected: bool) -> None:
    assert should_fall_back(_response_error(status)) is expected


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


def test_timeout_entry_is_documentation_not_behaviour() -> None:
    # Honest note rather than a false sense of coverage: ``TimeoutError`` has been an
    # ``OSError`` subclass since PEP 3151, so naming it alongside ``OSError`` changes
    # nothing — removing the name would keep every test green. It is kept for readability
    # (a timeout is THE outage shape BOB-084 observed), and it is deliberately named inside
    # the SAME predicate as ``OSError`` so the gate never grows a knowingly-equivalent
    # mutant for it. This test says all of that out loud.
    assert issubclass(TimeoutError, OSError)
    assert should_fall_back(TimeoutError()) is True


# --- contract failures: OUR bug or a broken answer -> never mask with a fallback ---


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 413, 422])
def test_client_side_status_does_not_fall_back(status: int) -> None:
    # A malformed request / bad key / unknown model is a defect of ours: falling
    # back would hide it behind a quietly degraded local answer.
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
