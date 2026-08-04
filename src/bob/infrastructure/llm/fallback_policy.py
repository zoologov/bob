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

🔴 Every value this policy is made of — the 500 floor, the ``{408, 429}`` availability
set, the roster of transport exception types — lives INSIDE a function body on purpose
(BOB-087.E3, bob-abk.33). Mutation testing mutates bodies, not module-level constants:
hoisted into constants, these values were invisible to ``scripts/mutation.sh``, which
found only operator mutants and reported a comfortable 100% for a gate that could not
have noticed the floor moving to 400 or a transport type quietly dropping out. For the
same reason each transport shape is its own named predicate rather than one merged
``isinstance`` tuple: mutation refuses to look inside an ``isinstance`` call, but it
does neutralise a predicate call. The prose above and the names below keep the policy
self-documenting; keeping the values in the bodies keeps the gate real. Do not "tidy"
them back into module-level constants or a single tuple.
"""

from __future__ import annotations

import aiohttp


def should_fall_back(error: BaseException) -> bool:
    """Is ``error`` a transport/availability failure worth the local model?

    ``True`` only for failures of the *channel* to the cloud endpoint; ``False`` for
    every failure of the *contract* (ours or the upstream's) and for cancellation —
    see the module docstring for the full classification and its rationale.
    """
    if isinstance(error, aiohttp.ClientResponseError):
        return _is_availability_status(error.status)
    return _is_transport_failure(error)


def _is_availability_status(status: int) -> bool:
    """Does this HTTP status mean the upstream could not serve us (vs. we asked wrong)?

    Everything from **500** up is an upstream-side failure; **499** and below is the
    client (us) being wrong — that is the boundary between "outage" and "our defect".
    Two 4xx codes sit on the outage side anyway: **408** (the endpoint itself gave up
    waiting) and **429** (rate-limited — the cloud will not serve *us* right now).
    """
    server_error_floor = 500  # 500+ — broken on their side; 499 and below — on ours
    availability_4xx = {408, 429}  # the endpoint gave up waiting / rate-limited us
    return status >= server_error_floor or status in availability_4xx


def _is_transport_failure(error: BaseException) -> bool:
    """Did the *channel* to the endpoint fail, rather than the exchange over it?

    The roster of transport shapes IS the policy, so each shape is a named predicate
    of its own rather than one merged ``isinstance`` tuple: that keeps the roster's
    composition testable (mutation never reaches inside an ``isinstance`` call, but it
    does neutralise each call below — so dropping a shape flips exactly one outage).
    An error matching no shape is a contract failure and must surface.
    """
    return (
        _is_timeout_or_socket_failure(error)
        or _is_connection_failure(error)
        or _is_truncated_body(error)
    )


def _is_timeout_or_socket_failure(error: BaseException) -> bool:
    """The request never came back, or the socket/DNS layer refused to carry it.

    ``TimeoutError`` has been an ``OSError`` since PEP 3151 (and is what
    ``asyncio.TimeoutError`` aliases on 3.11+), so it is named here for readability,
    not reach: a timeout is THE outage shape BOB-084 saw 77 times in a row.
    """
    return isinstance(error, TimeoutError | OSError)


def _is_connection_failure(error: BaseException) -> bool:
    """aiohttp could not establish or hold the connection.

    Refused / reset / DNS (``ClientConnectorError``) and a ``ServerDisconnectedError``
    mid-flight — the latter is NOT an ``OSError`` in aiohttp's hierarchy, which is why
    this shape cannot be folded into the socket-level one above.
    """
    return isinstance(error, aiohttp.ClientConnectionError)


def _is_truncated_body(error: BaseException) -> bool:
    """The body was cut off mid-transfer — the transport died while answering."""
    return isinstance(error, aiohttp.ClientPayloadError)
