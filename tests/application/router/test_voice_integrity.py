# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the voice-integrity core: who may answer in Bob's place (BOB-087.E-M1).

Pure, deterministic, I/O-free — the mutation-gated core of the owner's fallback
decision: a служебный Tier-0 ход may degrade to the local understudy, a turn in
BOB'S OWN VOICE never may (it escalates UP to the cloud tier, or nobody answers).
"""

from __future__ import annotations

import pytest

from bob.application.router.voice_integrity import (
    OutageVoice,
    who_may_answer_for_bob,
)


def test_a_service_turn_may_degrade_to_the_local_understudy() -> None:
    # Классификатор/монолог/гейт — не голос Боба: дублёр страхует, как и задумывал Срез E.
    verdict = who_may_answer_for_bob(
        speaks_in_bobs_voice=False,
        understudy_wired=True,
        cloud_tier_wired=True,
        payload_redacted_for_cloud=False,
    )

    assert verdict is OutageVoice.LOCAL_UNDERSTUDY


def test_a_service_turn_stays_on_the_understudy_route_even_with_nothing_else_wired() -> None:
    # Служебный ход не зависит ни от облака, ни от редакции: политика голоса его не касается.
    verdict = who_may_answer_for_bob(
        speaks_in_bobs_voice=False,
        understudy_wired=False,
        cloud_tier_wired=False,
        payload_redacted_for_cloud=False,
    )

    assert verdict is OutageVoice.LOCAL_UNDERSTUDY


def test_bobs_own_voice_escalates_up_to_the_cloud_tier() -> None:
    # 🔴 Решение owner'а: реплика пользователю падает НЕ вниз на слабую модель, а ВВЕРХ.
    verdict = who_may_answer_for_bob(
        speaks_in_bobs_voice=True,
        understudy_wired=True,
        cloud_tier_wired=True,
        payload_redacted_for_cloud=True,
    )

    assert verdict is OutageVoice.CLOUD_TIER1


def test_bobs_voice_never_escalates_an_unredacted_payload() -> None:
    # 🔴 Приватная строка не уезжает в облако аварийным путём: ход, чей payload собран
    # под Tier-0-политику (может нести private_context), НЕ эскалируется вовсе.
    verdict = who_may_answer_for_bob(
        speaks_in_bobs_voice=True,
        understudy_wired=True,
        cloud_tier_wired=True,
        payload_redacted_for_cloud=False,
    )

    assert verdict is OutageVoice.NOBODY


def test_bobs_voice_without_an_understudy_keeps_the_pre_flag_behaviour() -> None:
    # Флаг OFF: дублёра нет → подменять голос нечем → и эскалации нет (путь как раньше).
    verdict = who_may_answer_for_bob(
        speaks_in_bobs_voice=True,
        understudy_wired=False,
        cloud_tier_wired=True,
        payload_redacted_for_cloud=True,
    )

    assert verdict is OutageVoice.NOBODY


def test_bobs_voice_with_no_cloud_tier_has_nobody_to_escalate_to() -> None:
    # Некуда эскалировать → честный отказ, а не «пусть скажет дублёр».
    verdict = who_may_answer_for_bob(
        speaks_in_bobs_voice=True,
        understudy_wired=True,
        cloud_tier_wired=False,
        payload_redacted_for_cloud=True,
    )

    assert verdict is OutageVoice.NOBODY


def test_total_outage_of_everything_lets_nobody_speak_for_bob() -> None:
    # Ни дублёра, ни облака: за Боба не говорит никто — это и есть честный отвал.
    verdict = who_may_answer_for_bob(
        speaks_in_bobs_voice=True,
        understudy_wired=False,
        cloud_tier_wired=False,
        payload_redacted_for_cloud=True,
    )

    assert verdict is OutageVoice.NOBODY


# ─── Полная таблица истинности: закрываем слепое пятно мутационного гейта ────────────────
# 🔴 Мутация меряет этот модуль честно, но УЗКО: mutmut порождает здесь ровно три мутанта —
# все на ОПЕРАТОРАХ условий (`not speaks_in_bobs_voice` → без `not`; `and`/`and` → `and`/`or`
# и `or`/`and`). ВОЗВРАЩАЕМЫЕ вердикты он не мутирует вовсе: члены enum — это обращения к
# атрибуту, а не литералы, поэтому подмена `NOBODY` на `LOCAL_UNDERSTUDY` в третьей ветке
# (тихая сдача голоса Боба дублёру — ровно та беда, против которой написан модуль) выжила бы
# незамеченной, и гейт бы этого НЕ показал. Урок bob-abk.33: «все мутанты убиты» ≠ «политика
# закреплена». Поэтому все 2⁴ входа перечислены явно, с ожидаемым вердиктом, выписанным из
# решения владельца, а не полученным вызовом самой функции: любая подмена вердикта в любой
# ветке (и любое изменение условия) валит строку таблицы.
_ALL_FACT_COMBINATIONS = [
    # (голос Боба, дублёр есть, облако есть, payload отредактирован) -> кто вправе ответить
    # Служебный ход — дублёр страхует ВСЕГДА, что бы ни было вокруг (8 строк).
    (False, False, False, False, OutageVoice.LOCAL_UNDERSTUDY),
    (False, False, False, True, OutageVoice.LOCAL_UNDERSTUDY),
    (False, False, True, False, OutageVoice.LOCAL_UNDERSTUDY),
    (False, False, True, True, OutageVoice.LOCAL_UNDERSTUDY),
    (False, True, False, False, OutageVoice.LOCAL_UNDERSTUDY),
    (False, True, False, True, OutageVoice.LOCAL_UNDERSTUDY),
    (False, True, True, False, OutageVoice.LOCAL_UNDERSTUDY),
    (False, True, True, True, OutageVoice.LOCAL_UNDERSTUDY),
    # Голос Боба — дублёр не отвечает НИ В ОДНОЙ строке; вверх уходит ровно один случай.
    (True, False, False, False, OutageVoice.NOBODY),
    (True, False, False, True, OutageVoice.NOBODY),
    (True, False, True, False, OutageVoice.NOBODY),
    (True, False, True, True, OutageVoice.NOBODY),
    (True, True, False, False, OutageVoice.NOBODY),
    (True, True, False, True, OutageVoice.NOBODY),
    (True, True, True, False, OutageVoice.NOBODY),  # 🔴 неотредактированный payload — не вверх
    (True, True, True, True, OutageVoice.CLOUD_TIER1),  # единственная эскалация
]


@pytest.mark.parametrize(
    ("voice", "understudy", "cloud", "redacted", "expected"), _ALL_FACT_COMBINATIONS
)
def test_the_whole_truth_table_matches_the_owners_decision(
    *,
    voice: bool,
    understudy: bool,
    cloud: bool,
    redacted: bool,
    expected: OutageVoice,
) -> None:
    verdict = who_may_answer_for_bob(
        speaks_in_bobs_voice=voice,
        understudy_wired=understudy,
        cloud_tier_wired=cloud,
        payload_redacted_for_cloud=redacted,
    )

    assert verdict is expected


def test_the_understudy_never_answers_a_turn_in_bobs_voice_in_any_situation() -> None:
    # Инвариант политики одной строкой поверх таблицы: как бы ни сложились обстоятельства,
    # вердикт «пусть скажет дублёр» для хода голосом Боба не выдаётся никогда.
    voiced = [row for row in _ALL_FACT_COMBINATIONS if row[0]]

    assert len(voiced) == 8
    assert all(row[-1] is not OutageVoice.LOCAL_UNDERSTUDY for row in voiced)
    assert all(
        who_may_answer_for_bob(
            speaks_in_bobs_voice=True,
            understudy_wired=understudy,
            cloud_tier_wired=cloud,
            payload_redacted_for_cloud=redacted,
        )
        is not OutageVoice.LOCAL_UNDERSTUDY
        for _, understudy, cloud, redacted, _ in voiced
    )
