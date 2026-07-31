# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Prompt invariant for the capability manifest preface (BOB-074 Fix 1).

The preface prepended to Bob's tool manifest was hardened into an IMPERATIVE anti-few-shot
rule to beat recall-poisoning: past «GUPPI пошёл… ждём отчёт» turns in history make Qwen
mimic the narration instead of emitting a tool call. These pin the two load-bearing halves
of that rule so a future reword cannot silently soften it back into the poisoning-friendly
«GUPPI executes for you» phrasing:

* it DEMANDS a real tool call with a real result when a tool is needed, and
* it FORBIDS narrating GUPPI's intent («пошёл/заглянет/ищет/перебирает») as an answer.
"""

from __future__ import annotations

from bob.personality.usecases.voice_composer import _CAPABILITY_PREFACE


def test_preface_demands_a_real_tool_call_with_a_real_result() -> None:
    lowered = _CAPABILITY_PREFACE.lower()
    assert "tool call" in lowered
    assert "реальный результат" in lowered


def test_preface_forbids_narrating_guppi_intent() -> None:
    # The imperative prohibition — narrating intent is explicitly NOT an answer.
    assert "никогда не описывай" in _CAPABILITY_PREFACE.lower()
    assert "запрещ" in _CAPABILITY_PREFACE.lower()


def test_preface_names_the_poisoning_intent_verbs_it_bans() -> None:
    # It must call out the exact recall-poisoning narration signature, not ban vaguely.
    lowered = _CAPABILITY_PREFACE.lower()
    assert "пошёл" in lowered
    assert "заглянет" in lowered
    assert "ищет" in lowered
