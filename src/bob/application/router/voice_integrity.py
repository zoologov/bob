# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=router

"""Who may answer in BOB'S place when the tier serving his turn goes down (BOB-087.E-M1).

One question, one answer. Срез E gave Tier 0 a local emergency understudy
(:mod:`bob.infrastructure.llm.fallback_provider`), which is right for a **служебный**
Tier-0 ход — a classifier, a gate, the inner monologue: an outage there must not take
Bob's machinery down with the cloud. But Tier 0 also serves a **user reply**: the hybrid
reply tiering (BOB-006) sends a short casual turn to the fast Tier-0 model via
``tier_override``. Left alone, an outage would hand THAT turn to a 0.5b understudy — and
the reply would ship as Bob's own voice, land in the thread and in ``episodic_log``, and
keep shaping his tone through recall long after the cloud came back (the poisoning the
project already paid for in BOB-022 / BOB-074 / BOB-078). An emergency would outlive the
emergency.

Hence the owner's decision, and this core: **the fallback direction follows the KIND OF
WORK, not the tier.**

* служебный ход → :attr:`OutageVoice.LOCAL_UNDERSTUDY` — degrade locally, as Срез E built it;
* a turn in Bob's own voice → :attr:`OutageVoice.CLOUD_TIER1` — escalate **UP** to the
  quality cloud tier, never down to the stand-in;
* nothing better available → :attr:`OutageVoice.NOBODY` — no one speaks for Bob; the
  caller surfaces the outage honestly (``EssentialRunner`` → the GUPPI notice) instead of
  answering in a borrowed voice.

🔴 ``payload_redacted_for_cloud`` is the privacy guard on the escalation. The router
redacts by the TASK's policy before building the payload (Variant 2, VISION §7.1), so a
turn whose policy is Tier-0-local may legitimately carry ``private_context``. Escalating
such a payload upward would leak internal material into the cloud through an *emergency*
path — so it is not escalated at all: NOBODY answers. Escalation is offered only for a
payload that already went through the Tier-1 redaction it would have gone through anyway.

🔴 Placement + shape (BOB-087.E3, bob-abk.33). The core belongs to the ROUTER package —
the router is what knows the task type — and not to a domain module: ``personality`` (and
every other domain vertical) already imports the router from its adapters, so the reverse
import would close a node cycle (``no-dependency-cycles``, verified on a clean index).
Like the other pure cores living in technical layers (``reply_rhythm``, ``rich``,
``fallback_policy``), it is listed file-by-file in ``mutmut.source_paths`` so the gate is
real. For the same reason the verdicts are plain boolean predicates in the function body:
mutation does not touch module-level constants and refuses to look inside an ``isinstance``
tuple, but it does flip ``not`` and ``and`` — keep the policy expressed that way.

Pure and deterministic: no I/O, no clock, no state — just the verdict.
"""

from __future__ import annotations

from enum import Enum


class OutageVoice(Enum):
    """Who may speak for Bob when the tier that was serving this turn fails."""

    LOCAL_UNDERSTUDY = "local_understudy"
    """The local stand-in model may answer — nothing of Bob's voice is at stake."""

    CLOUD_TIER1 = "cloud_tier1"
    """Only the quality cloud tier may answer — escalate up, never down."""

    NOBODY = "nobody"
    """No one answers for Bob: the outage is surfaced honestly instead."""


def who_may_answer_for_bob(
    *,
    speaks_in_bobs_voice: bool,
    understudy_wired: bool,
    cloud_tier_wired: bool,
    payload_redacted_for_cloud: bool,
) -> OutageVoice:
    """Decide who may answer this turn once its tier is out.

    ``speaks_in_bobs_voice`` — is this «the voice that STAYS»: does the turn ship AS BOB
    (to a human, or into a lasting record) *and* survive the turn, so a borrowed voice
    would keep shaping him through recall? The caller derives it from the door's own
    properties (``speaks_as_bob and output_is_kept``, BOB-096.4) — a classifier, a gate or
    the inner monologue is neither, and the unpersisted interim one-liner is only the
    first half, so both stay on the служебный side. ``understudy_wired`` — is a local
    stand-in composed under the tier at all (the ``llm.tier0_fallback`` flag: off → nothing
    can impersonate him → nothing to intervene in, the pre-flag behaviour stands)?
    ``cloud_tier_wired`` — is there a quality tier to escalate to? ``payload_redacted_for_cloud``
    — was this payload built under the Tier-1 redaction policy (see the module docstring:
    an unredacted payload is never escalated).
    """
    if not speaks_in_bobs_voice:
        return OutageVoice.LOCAL_UNDERSTUDY
    if understudy_wired and cloud_tier_wired and payload_redacted_for_cloud:
        return OutageVoice.CLOUD_TIER1
    return OutageVoice.NOBODY
