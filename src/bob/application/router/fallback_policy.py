# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Fallback verdict: is THIS failure a reason to leave the preferred model for a weaker one?

One question, one answer (BOB-087.E1, BOB-Issues #34) — asked on BOTH floors of Bob's
tiering, by the two places that may degrade a turn onto a weaker model:

* the **lower** floor — :class:`~bob.infrastructure.llm.fallback_provider.FallbackLLMProvider`,
  which leaves a failing cloud Tier-0 endpoint for the local Ollama understudy. The cloud
  Tier-0 endpoint (Qwen/Aliyun) periodically drops off the network — BOB-084 observed 77
  consecutive outages — and an outage there takes the register classifier, the inner
  monologue and the coding gates down with it;
* the **upper** floor — :class:`~bob.application.router.LLMRouter`, which leaves a failing
  Tier 1 for Tier 0. Until bob-41o that fallback caught ANY Tier-1 exception, so the
  asymmetry undid one floor below what the other floor was built for: a stale key or an
  unknown model on Tier 1 was answered by the weaker tier and the broken configuration
  lived on unnoticed. Both floors now ask THIS function, so there is one policy, not two
  that drift apart.

🔴 Placement (bob-41o). The core is pure — no I/O, no clock, no state — and lived in
``infrastructure/llm/`` only because its first consumer did. With a consumer on each side
of the layer line it had to move INWARD, to the application layer: ``application-no-infra``
(severity error) forbids the router reaching outward into infrastructure, while
infrastructure importing the application layer is the legal downward direction (as
``infrastructure/telegram/gateway.py`` and ``multibot.py`` already do). It sits in the ROUTER
package beside :mod:`bob.application.router.voice_integrity` — the two halves of one
question, «this tier just failed: may anything rescue the turn, and who may answer?» —
and NOT in ``kernel``, whose rules require stdlib/typing only, while this verdict knows
aiohttp's exception shapes. The sibling classifier
:func:`bob.application.runtime.retry.is_transient` (a different question: what is worth
RETRYING) already reads those shapes from this layer.

Two answers, the second built on the first (BOB-116):

* :func:`classify_failure` names WHICH kind of failure this is — ``auth``, ``rate``,
  ``server``, ``timeout``, ``connection``, ``shape`` or ``contract``. The class is what the
  provider-health accounting counts and what the owner is told, so it must say more than
  «outage or not»: a 403 and a 503 are repaired differently (key/account vs. waiting);
* :func:`should_fall_back` is «the class is anything but ``contract``». One verdict
  derived from the other, so the two can never drift apart.

The classification is deliberately conservative about ``contract``, because a fallback
that fires too eagerly does not add resilience — it **hides defects** behind a quietly
degraded answer from a weaker model:

**Falls back (the endpoint could not or would not serve us):**

* ``timeout`` — the request never came back (``TimeoutError``, which
  ``asyncio.TimeoutError`` aliases on 3.11+, and aiohttp's ``ServerTimeoutError``);
* ``connection`` — the channel failed: ``aiohttp.ClientConnectionError`` and its kin
  (refused / reset / DNS, a ``ServerDisconnectedError`` mid-flight) and a bare ``OSError``
  (socket, ``socket.gaierror``);
* ``shape`` — the body was cut off mid-transfer (``ClientPayloadError``): the transport
  died while answering, so what arrived has no usable shape;
* ``server`` — HTTP **5xx** (broken on their side) and **408** (the endpoint gave up
  waiting);
* ``rate`` — HTTP **429**: the cloud will not serve *us* right now;
* ``auth`` — HTTP **401/403**: the key is revoked or expired, the account exhausted or
  denied. 🔴 Until BOB-116 these were «contract — a bad key must surface». It surfaced: Bob
  was mute for ten days on a 403, every turn re-raising the same error while the local
  understudy sat idle. A revoked key is not a defect a weaker model would HIDE — the cloud
  refuses to serve us, exactly as on 429 — so **for routing** it is unavailability. That
  it must still reach the owner is the job of the health signal (BOB-116), not of a turn
  that fails on purpose.

**Does NOT fall back — ``contract`` (a defect to surface, not an outage to survive):**

* HTTP **4xx** other than 401/403/408/429 (400, 404, 409, 413, 422, …) — a malformed
  request, an unknown model, an oversized payload: our own bug or misconfiguration.
  Masking it with a weaker model's answer would let a broken tier configuration live on
  undetected;
* a broken response shape on a call that otherwise succeeded (``ValueError`` from the body
  parsers, ``json.JSONDecodeError``) — the *content* is wrong, not the channel. This is NOT
  ``shape``: ``shape`` is a body the transport cut off, this is a whole body that says the
  wrong thing;
* ``aiohttp.InvalidURL`` — a config defect (it is a ``ValueError``, not a network
  event), and any other bare ``aiohttp.ClientError`` with no transport evidence;
* ``TypeError`` / ``RuntimeError`` and friends — programming errors;
* cancellation (``asyncio.CancelledError``) and process-level interrupts
  (``KeyboardInterrupt``, ``SystemExit``) — a shutdown must propagate instantly,
  never be "retried" on the local model. They carry no availability evidence, so they
  classify as ``contract`` too; a caller counting provider health must not hand them in.

A meaningful refusal by the model, or an empty-but-valid reply, never raises at all
(:mod:`bob.infrastructure.llm.openai_compat` degrades missing content to ``""``), so
it can never reach this policy — the fallback is for outages only.

What is worth RETRYING is a different question with a different answer:
:func:`bob.application.runtime.retry.is_transient` does not retry 401/403, and BOB-116
leaves it so — the same key does not heal between two attempts a second apart.

Pure and deterministic: no I/O, no clock, no state — just the verdict.

🔴 Every value this policy is made of — the 500 floor, the 408 and 429 codes, the
``{401, 403}`` auth pair, the class names, the roster of transport exception types — lives
INSIDE a function body on purpose (BOB-087.E3, bob-abk.33). Mutation testing mutates
bodies, not module-level constants: hoisted into constants, these values were invisible to
``scripts/mutation.sh``, which found only operator mutants and reported a comfortable 100%
for a gate that could not have noticed the floor moving to 400 or a transport type quietly
dropping out. For the same reason each transport shape is its own named predicate rather
than one merged ``isinstance`` tuple: mutation refuses to look inside an ``isinstance``
call, but it does mutate the class each predicate leads to. The prose above and the names
below keep the policy self-documenting; keeping the values in the bodies keeps the gate
real. Do not "tidy" them back into module-level constants or a single tuple.
"""

from __future__ import annotations

import aiohttp


def classify_failure(error: BaseException) -> str:
    """Which kind of failure is ``error``: ``auth`` / ``rate`` / ``server`` / ``timeout`` /
    ``connection`` / ``shape``, or ``contract`` when it carries no availability evidence.

    See the module docstring for the full classification and its rationale.
    """
    if isinstance(error, aiohttp.ClientResponseError):
        return _status_class(error.status)
    return _transport_class(error)


def should_fall_back(error: BaseException) -> bool:
    """Is ``error`` a reason to degrade to a weaker model?

    ``True`` for every class but ``contract``: the endpoint could not or would not serve
    us. ``False`` for a failure of the *contract* (ours or the upstream's) and for
    cancellation — see the module docstring.
    """
    return classify_failure(error) != "contract"


def _status_class(status: int) -> str:
    """The class of an HTTP error status.

    Everything from **500** up is an upstream-side failure, and so is **408** (the
    endpoint itself gave up waiting). **429** is a rate limit, **401/403** a refusal to
    serve US (revoked key, exhausted or denied account). Every other status below 500 is
    the client — us — being wrong: that is the boundary between "outage" and "our defect".
    """
    server_error_floor = 500  # 500+ — broken on their side; 499 and below — on ours
    request_timeout = 408  # the endpoint gave up waiting
    rate_limited = 429  # the cloud will not serve US right now
    auth_statuses = {401, 403}  # revoked/expired key, exhausted/denied account
    if status >= server_error_floor or status == request_timeout:
        return "server"
    if status == rate_limited:
        return "rate"
    if status in auth_statuses:
        return "auth"
    return "contract"


def _transport_class(error: BaseException) -> str:
    """The class of a failure that is not an HTTP status: did the *channel* fail?

    The order is load-bearing: ``TimeoutError`` is an ``OSError`` (PEP 3151) and
    aiohttp's ``ServerTimeoutError`` is a ``ClientConnectionError``, so the timeout shape
    is asked FIRST or every timeout would read as ``connection``. An error matching no
    shape is a contract failure and must surface.
    """
    if _is_timeout(error):
        return "timeout"
    if _is_socket_failure(error) or _is_connection_failure(error):
        return "connection"
    if _is_truncated_body(error):
        return "shape"
    return "contract"


def _is_timeout(error: BaseException) -> bool:
    """The request never came back — THE outage shape BOB-084 saw 77 times in a row.

    ``asyncio.TimeoutError`` aliases ``TimeoutError`` on 3.11+, and aiohttp's
    ``ServerTimeoutError`` subclasses it.
    """
    return isinstance(error, TimeoutError)


def _is_socket_failure(error: BaseException) -> bool:
    """The socket/DNS layer refused to carry the request (bare ``OSError``, ``gaierror``)."""
    return isinstance(error, OSError)


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
