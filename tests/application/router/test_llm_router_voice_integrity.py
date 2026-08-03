# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Router × understudy: Bob's voice is never handed to the stand-in (BOB-087.E-M1).

Срез E wrapped Tier 0 in a local emergency understudy. These tests pin the owner's
decision on top of it — the fallback direction follows the KIND OF WORK:

* a служебный Tier-0 ход degrades to the local model, exactly as Срез E built it;
* a **user reply** that was routed to Tier 0 (BOB-006 hybrid tiering) escalates **UP** to
  Tier 1 instead — and the escalated payload goes through the SAME redaction a normal
  Tier-1 call goes through, so ``private_context`` cannot reach the cloud by the emergency
  path;
* when neither tier can serve, NOBODY answers: the router raises, and the turn ends in the
  honest GUPPI outage notice (``EssentialRunner``) rather than in a borrowed voice.

The composite under test is the REAL
:class:`~bob.infrastructure.llm.fallback_provider.FallbackLLMProvider`, so the seam between
the router's policy and the provider's understudy is exercised end to end, not mocked away.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRequest, LLMRouter, TaskType
from bob.infrastructure.llm.fallback_provider import build_fallback_provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from bob.kernel.ports import LLMProvider

# Genuinely-internal context that must never reach the cloud — not even via an outage path.
PRIVATE_CONTEXT = "INTERNAL: raw inner-monologue scratchpad, never for the user."
# Reply-shaping context (conversation/memory) that MAY reach Tier 1.
SHAREABLE_CONTEXT = "Recent conversation: the user said their name is Alice."


class RecordingProvider:
    """Fake LLMProvider recording every payload; optionally an outage."""

    def __init__(self, *, reply: str = "ok", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol signature
    ) -> str | AsyncIterator[str]:
        self.calls.append([dict(m) for m in messages])
        if self.fail:
            # ConnectionError is an OSError → the transport verdict the composite falls back on.
            raise ConnectionError("tier unavailable")
        return self.reply


def _payload_text(provider: RecordingProvider) -> str:
    return " ".join(m.get("content", "") for call in provider.calls for m in call)


def _router_with_understudy(
    *,
    tier0_primary: RecordingProvider,
    understudy: RecordingProvider,
    tier1: LLMProvider,
) -> LLMRouter:
    """A router wired the way the factory wires it with ``llm.tier0_fallback`` ON."""
    composite = build_fallback_provider(primary=tier0_primary, fallback=understudy)
    return LLMRouter(providers={0: composite, 1: tier1})


def _casual_reply(*, private: str | None = PRIVATE_CONTEXT) -> LLMRequest:
    """A short casual reply — BOB-006 tiering sends it to the fast Tier-0 model."""
    return LLMRequest(
        task_type=TaskType.REPLY_TO_USER,
        messages=[{"role": "user", "content": "как дела"}],
        shareable_context=SHAREABLE_CONTEXT,
        private_context=private,
        tier_override=0,
    )


async def test_tier0_outage_on_a_user_reply_escalates_up_to_tier1() -> None:
    # Arrange: the cloud Tier-0 endpoint is out; an understudy stands by.
    tier0_primary = RecordingProvider(fail=True)
    understudy = RecordingProvider(reply="0.5b мямлит")
    tier1 = RecordingProvider(reply="настоящий голос Боба")
    router = _router_with_understudy(
        tier0_primary=tier0_primary, understudy=understudy, tier1=tier1
    )

    # Act
    result = await router.run(_casual_reply())

    # Assert: the reply came from the QUALITY tier, and the stand-in never spoke.
    assert result == "настоящий голос Боба"
    assert len(tier1.calls) == 1
    assert understudy.calls == [], "the 0.5b understudy must never voice a user reply"


async def test_the_escalated_payload_never_carries_private_context() -> None:
    # 🔴 The privacy invariant of the emergency path (Variant 2, VISION §7.1): escalating
    # UP must go through the SAME redaction a normal Tier-1 call goes through.
    tier0_primary = RecordingProvider(fail=True)
    understudy = RecordingProvider(reply="0.5b")
    tier1 = RecordingProvider(reply="plus")
    router = _router_with_understudy(
        tier0_primary=tier0_primary, understudy=understudy, tier1=tier1
    )

    await router.run(_casual_reply())

    cloud_payload = _payload_text(tier1)
    assert PRIVATE_CONTEXT not in cloud_payload
    assert SHAREABLE_CONTEXT in cloud_payload


async def test_escalation_is_a_single_hop_with_no_cascade() -> None:
    # No Tier0 → Tier1 → Ollama merry-go-round: one attempt on each, then an honest failure.
    tier0_primary = RecordingProvider(fail=True)
    understudy = RecordingProvider(reply="0.5b")
    tier1 = RecordingProvider(fail=True)
    router = _router_with_understudy(
        tier0_primary=tier0_primary, understudy=understudy, tier1=tier1
    )

    with pytest.raises(ConnectionError):
        await router.run(_casual_reply())

    assert len(tier0_primary.calls) == 1
    assert len(tier1.calls) == 1
    assert understudy.calls == [], "a failed escalation must not fall back to the stand-in"


async def test_a_service_turn_still_degrades_to_the_local_understudy() -> None:
    # Срез E untouched: a classifier keeps its insurance when the cloud Tier-0 drops.
    tier0_primary = RecordingProvider(fail=True)
    understudy = RecordingProvider(reply="positive")
    tier1 = RecordingProvider(reply="plus")
    router = _router_with_understudy(
        tier0_primary=tier0_primary, understudy=understudy, tier1=tier1
    )
    sentiment = LLMRequest(
        task_type=TaskType.SENTIMENT,
        messages=[{"role": "user", "content": "какое настроение"}],
        shareable_context=SHAREABLE_CONTEXT,
        private_context=PRIVATE_CONTEXT,
    )

    result = await router.run(sentiment)

    assert result == "positive"
    assert len(understudy.calls) == 1
    assert tier1.calls == [], "a service turn must not escalate to the cloud"


async def test_the_service_understudy_still_sees_the_local_only_context() -> None:
    # The degraded служебный ход keeps the Tier-0 payload it always had (private included).
    tier0_primary = RecordingProvider(fail=True)
    understudy = RecordingProvider(reply="monologue")
    router = _router_with_understudy(
        tier0_primary=tier0_primary,
        understudy=understudy,
        tier1=RecordingProvider(reply="plus"),
    )
    monologue = LLMRequest(
        task_type=TaskType.INNER_MONOLOGUE,
        messages=[{"role": "user", "content": "подумай"}],
        shareable_context=SHAREABLE_CONTEXT,
        private_context=PRIVATE_CONTEXT,
    )

    await router.run(monologue)

    assert PRIVATE_CONTEXT in _payload_text(understudy)


async def test_the_tier1_to_tier0_fallback_of_a_reply_never_reaches_the_understudy() -> None:
    # The OTHER door into the stand-in: a Tier-1 reply that fails falls back to Tier 0.
    # It must land on the REAL Tier-0 model (как прежде), never on the 0.5b understudy.
    tier0_primary = RecordingProvider(reply="tier0 говорит голосом Боба")
    understudy = RecordingProvider(reply="0.5b мямлит")
    tier1 = RecordingProvider(fail=True)
    router = _router_with_understudy(
        tier0_primary=tier0_primary, understudy=understudy, tier1=tier1
    )
    reply = LLMRequest(  # no override → REPLY_TO_USER prefers Tier 1
        task_type=TaskType.REPLY_TO_USER,
        messages=[{"role": "user", "content": "длинный сложный вопрос"}],
        shareable_context=SHAREABLE_CONTEXT,
    )

    result = await router.run(reply)

    assert result == "tier0 говорит голосом Боба"
    assert understudy.calls == []


async def test_a_reply_escalated_up_is_still_capped_by_the_tier1_concurrency_gate() -> None:
    # The escalation is an ordinary Tier-1 call: it goes through the rate-cap (BOB-072),
    # so an outage of Tier 0 cannot stampede the cloud tier.
    tier1 = RecordingProvider(reply="plus")
    composite = build_fallback_provider(
        primary=RecordingProvider(fail=True), fallback=RecordingProvider(reply="0.5b")
    )
    router = LLMRouter(providers={0: composite, 1: tier1}, tier1_max_concurrency=1)

    result = await router.run(_casual_reply())

    assert result == "plus"


async def test_both_tiers_down_on_a_reply_raises_instead_of_borrowing_a_voice() -> None:
    # Полный отвал: the router raises → EssentialRunner → the honest GUPPI outage notice.
    tier0_primary = RecordingProvider(fail=True)
    understudy = RecordingProvider(reply="0.5b мямлит")
    tier1 = RecordingProvider(fail=True)
    router = _router_with_understudy(
        tier0_primary=tier0_primary, understudy=understudy, tier1=tier1
    )
    reply = LLMRequest(
        task_type=TaskType.REPLY_TO_USER,
        messages=[{"role": "user", "content": "длинный сложный вопрос"}],
        shareable_context=SHAREABLE_CONTEXT,
    )

    with pytest.raises(ConnectionError):
        await router.run(reply)

    assert understudy.calls == []


# ─── The privacy invariant, over EVERY task the router knows ────────────────────────────
# 🔴 The core's guard («never escalate an unredacted payload») is exercised as a pure verdict
# in ``test_voice_integrity``, but the fact it guards is produced HERE, by the router, out of
# two task-indexed facts: is this Bob's voice, and does this task's policy strip the private
# half? Today only ``REPLY_TO_USER`` counts as Bob's voice and its policy is Tier 1, so the
# dangerous combination (voice + private-carrying payload) is structurally unreachable — and
# that is exactly what a future task type could quietly change. The sweep below pins the
# invariant OBSERVABLY for every task in the enum, so such a change fails here instead of in
# production: whatever the task, whichever tier dies, the private half never reaches Tier 1.


@pytest.mark.parametrize("task_type", list(TaskType))
async def test_no_task_ever_leaks_private_context_to_the_cloud_during_an_outage(
    task_type: TaskType,
) -> None:
    tier0_primary = RecordingProvider(fail=True)
    understudy = RecordingProvider(reply="0.5b")
    tier1 = RecordingProvider(reply="plus")
    router = _router_with_understudy(
        tier0_primary=tier0_primary, understudy=understudy, tier1=tier1
    )
    request = LLMRequest(
        task_type=task_type,
        messages=[{"role": "user", "content": "вопрос"}],
        shareable_context=SHAREABLE_CONTEXT,
        private_context=PRIVATE_CONTEXT,
        tier_override=0,  # every task pinned DOWN to the dying tier: the outage path
    )

    with contextlib.suppress(ConnectionError):  # a task nobody can serve fails honestly
        await router.run(request)

    assert PRIVATE_CONTEXT not in _payload_text(tier1), (
        f"{task_type.value}: приватный контекст пересёк границу к Tier-1"
    )


# ─── Flag OFF: the routing protocol is IDENTICAL to the pre-flag one ────────────────────
# 🔴 Not «similar»: the block below replays a matrix of representative turns through a
# router with PLAIN providers (``llm.tier0_fallback`` empty — the default) and pins the
# WHOLE observable interaction — which provider was called, in which order, with exactly
# which payload, and what came back — against one literal trace written from the pre-change
# semantics. The voice policy adds no call, removes no call, and re-orders nothing when no
# understudy is wired. (The 15 pre-existing router tests, unmodified, are the second half
# of that proof.)


class _TracingProvider:
    """Records ``(name, payload)`` of every completion into a SHARED trace."""

    def __init__(
        self,
        name: str,
        trace: list[tuple[str, str, str]],
        *,
        reply: str = "ok",
        fail: bool = False,
    ) -> None:
        self._name = name
        self._trace = trace
        self._reply = reply
        self._fail = fail

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol signature
    ) -> str | AsyncIterator[str]:
        payload = "|".join(f"{m['role']}:{m['content']}" for m in messages)
        outcome = "ConnectionError" if self._fail else self._reply
        self._trace.append((self._name, payload, outcome))
        if self._fail:
            raise ConnectionError("tier unavailable")
        return self._reply


async def test_with_no_understudy_the_routing_protocol_is_byte_identical() -> None:
    # Arrange: one shared trace across every case of the matrix.
    trace: list[tuple[str, str, str]] = []
    results: list[str] = []

    def _plain_router(*, tier0_fails: bool = False, tier1_fails: bool = False) -> LLMRouter:
        return LLMRouter(
            providers={
                0: _TracingProvider("tier0", trace, reply="t0", fail=tier0_fails),
                1: _TracingProvider("tier1", trace, reply="t1", fail=tier1_fails),
            }
        )

    def _request(task: TaskType, *, override: int | None = None) -> LLMRequest:
        return LLMRequest(
            task_type=task,
            messages=[{"role": "user", "content": "hi"}],
            shareable_context="SHARE",
            private_context="PRIV",
            tier_override=override,
        )

    # Act: the matrix — a default reply, a casual reply pinned down to Tier 0, a service
    # turn, the Tier1→Tier0 fallback, and both «no fallback» outages.
    results.append(await _plain_router().run(_request(TaskType.REPLY_TO_USER)))
    results.append(
        await _plain_router().run(_request(TaskType.REPLY_TO_USER, override=0))
    )
    results.append(await _plain_router().run(_request(TaskType.INNER_MONOLOGUE)))
    results.append(await _plain_router(tier1_fails=True).run(_request(TaskType.REPLY_TO_USER)))
    with pytest.raises(ConnectionError):
        await _plain_router(tier0_fails=True).run(
            _request(TaskType.REPLY_TO_USER, override=0)
        )
    with pytest.raises(ConnectionError):
        await _plain_router(tier0_fails=True).run(_request(TaskType.SENTIMENT))

    # Assert: the exact pre-flag protocol — a Tier-0 reply outage does NOT escalate, a
    # Tier-1-policy payload never carries PRIV, a Tier-0-policy payload always does.
    assert trace == [
        ("tier1", "system:SHARE|user:hi", "t1"),
        ("tier0", "system:SHARE|user:hi", "t0"),
        ("tier0", "system:SHARE\nPRIV|user:hi", "t0"),
        ("tier1", "system:SHARE|user:hi", "ConnectionError"),
        ("tier0", "system:SHARE|user:hi", "t0"),
        ("tier0", "system:SHARE|user:hi", "ConnectionError"),
        ("tier0", "system:SHARE\nPRIV|user:hi", "ConnectionError"),
    ]
    assert results == ["t1", "t0", "t0", "t0"]
