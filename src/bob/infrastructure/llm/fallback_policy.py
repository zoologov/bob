# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Tier-0 fallback verdict: is THIS failure a reason to leave the cloud for local?

One question, one answer (BOB-087.E1, BOB-Issues #34). The cloud Tier-0 endpoint
(Qwen/Aliyun) periodically drops off the network — BOB-084 observed 77 consecutive
outages — and Tier 0 has no fallback of its own, so an outage takes the register
classifier, the inner monologue and the coding gates down with it. A local Ollama
model is the emergency understudy; :func:`should_fall_back` decides when to call it.

The classification is deliberately conservative, because a fallback that fires too
eagerly does not add resilience — it **hides defects** behind a quietly degraded
local answer:

**Falls back (transport / availability — the endpoint could not serve us):**

* a timeout (``TimeoutError``, which ``asyncio.TimeoutError`` aliases on 3.11+) —
  the request never came back;
* a connection failure (``aiohttp.ClientConnectionError`` and its OS-level kin —
  refused / reset / DNS) and a bare ``OSError`` (socket, ``socket.gaierror``);
* a disconnect mid-flight (``ServerDisconnectedError``) or a truncated body
  (``ClientPayloadError``) — the transport died while answering;
* HTTP **5xx** — the upstream is broken on its own side;
* HTTP **408** (the endpoint gave up waiting) and **429** (rate-limited: the cloud
  will not serve *us* right now, which is an availability failure from where we sit).

**Does NOT fall back (contract — a defect to surface, not an outage to survive):**

* HTTP **4xx** other than 408/429 — a malformed request, a bad key, an unknown
  model: our own bug or misconfiguration. Masking it with a local answer would let
  a broken Tier-0 configuration live on undetected;
* a broken response shape (``ValueError`` from the body parsers,
  ``json.JSONDecodeError``) — the call succeeded, the *content* is wrong;
* ``aiohttp.InvalidURL`` — a config defect (it is a ``ValueError``, not a network
  event), and any other bare ``aiohttp.ClientError`` with no transport evidence;
* ``TypeError`` / ``RuntimeError`` and friends — programming errors;
* cancellation (``asyncio.CancelledError``) and process-level interrupts
  (``KeyboardInterrupt``, ``SystemExit``) — a shutdown must propagate instantly,
  never be "retried" on the local model.

A meaningful refusal by the model, or an empty-but-valid reply, never raises at all
(:mod:`bob.infrastructure.llm.openai_compat` degrades missing content to ``""``), so
it can never reach this policy — the fallback is for outages only.

Pure and deterministic: no I/O, no clock, no state — just the verdict.
"""

from __future__ import annotations

import aiohttp

# HTTP statuses that mean "the endpoint cannot serve this request right now" rather
# than "this request is wrong": 408 the endpoint timed out waiting, 429 rate-limited.
_AVAILABILITY_STATUS_CODES = frozenset({408, 429})

# Everything from 500 up is an upstream-side failure; 499 and below is the client
# (us) being wrong — the boundary between "outage" and "our defect".
_SERVER_ERROR_FLOOR = 500

# Exception types that always mean the transport, not the contract, failed.
_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    TimeoutError,
    OSError,
    aiohttp.ClientConnectionError,
    aiohttp.ClientPayloadError,
)


def should_fall_back(error: BaseException) -> bool:
    """Is ``error`` a transport/availability failure worth the local model?

    ``True`` only for failures of the *channel* to the cloud endpoint; ``False`` for
    every failure of the *contract* (ours or the upstream's) and for cancellation —
    see the module docstring for the full classification and its rationale.
    """
    if isinstance(error, aiohttp.ClientResponseError):
        return _is_availability_status(error.status)
    return isinstance(error, _TRANSPORT_ERRORS)


def _is_availability_status(status: int) -> bool:
    """Does this HTTP status mean the upstream could not serve us (vs. we asked wrong)?"""
    return status >= _SERVER_ERROR_FLOOR or status in _AVAILABILITY_STATUS_CODES
