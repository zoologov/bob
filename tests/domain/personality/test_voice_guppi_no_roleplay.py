# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Боб не отыгрывает GUPPI — запрет в голосе (BOB-090.D3).

Живой симптом, породивший срез: Боб озвучивал GUPPI от своего лица — «GUPPI упрямо
твердит, что BOB-087 не существует», «GUPPI посмотрел на меня с тем самым выражением,
которое бывает у камня», «GUPPI, перенеси мой ответ в общий чат». Это двойное нарушение
канона: он приписал личность тому, у кого её нет, и подменил действие рассказом о
действии (класс BOB-074).

Директива — усиление BOB-074 / BOB-087.B2: не говорить за GUPPI, не приписывать ему
мнения, эмоции и реплики, не пересказывать его действия вместо самого дела. Пинуется
присутствие в ТОЧНОМ системном промпте, который получает модель (реальный
:class:`~bob.personality.usecases.voice_composer.VoiceComposer` через границу), и то,
что запрет НЕ убивает разрешённое каноном ворчание про буквализм GUPPI.
"""

from __future__ import annotations

import asyncio

from bob.personality.expression import Verbosity
from bob.personality.voice import (
    guppi_canon,
    guppi_no_roleplay_directive,
    guppi_voice_canon,
    operator_stance,
)
from tests.acceptance.formatting_harness import composed_prompt


def test_directive_forbids_voicing_guppi_and_attributing_inner_life() -> None:
    lowered = guppi_no_roleplay_directive().casefold()

    # Не говорить ЗА него и не приписывать ему внутреннюю жизнь…
    assert "guppi" in lowered
    assert "личност" in lowered or "мнени" in lowered
    assert "чувств" in lowered or "эмоц" in lowered
    # … и не подменять действие рассказом о действии (усиление BOB-074).
    assert "вместо" in lowered


def test_directive_shows_what_to_do_instead_not_only_the_ban() -> None:
    # Голый запрет модель обходит; нужна положительная замена — сделать и ответить собой.
    lowered = guppi_no_roleplay_directive().casefold()
    assert "своим голосом" in lowered or "от себя" in lowered


def test_directive_is_folded_into_the_composed_prompt() -> None:
    prompt = asyncio.run(composed_prompt(Verbosity.NORMAL))

    # Запрет доезжает до модели ДОСЛОВНО — вместе с каноном и операторской рамкой.
    assert guppi_no_roleplay_directive() in prompt
    assert guppi_canon() in prompt
    assert operator_stance() in prompt


def test_ban_does_not_kill_the_allowed_wry_canon() -> None:
    # Канон разрешает Бобу ворчать на буквализм GUPPI — это про характер БОБА, а не
    # приписанные чувства исполнителя. Запрет не должен затирать этот пласт.
    canon = guppi_canon().casefold()
    assert "буквал" in canon
    assert "ирони" in canon or "шутк" in canon


# --- Досягаемость канона: та же суть в форме, пригодной для двери (BOB-096.3) ---------


def test_the_prose_form_is_the_shipped_directive_itself() -> None:
    # Досягаемость — не новый запрет: прозаической двери достаётся ТОТ ЖЕ текст, который
    # уже стоит в базовой персоне. Иначе у Боба завелось бы два разных канона.
    assert guppi_voice_canon(prose_answer=True) == guppi_no_roleplay_directive()


def test_the_machine_form_bans_the_same_three_moves() -> None:
    lowered = guppi_voice_canon(prose_answer=False).casefold()

    # Речь, мнение и поступки за GUPPI — те же три запрещённых движения.
    assert "guppi" in lowered
    assert "мнени" in lowered
    assert "речи" in lowered or "слов" in lowered
    assert "поступк" in lowered or "действи" in lowered


def test_the_machine_form_does_not_drag_prose_instructions_into_a_json_door() -> None:
    # 🔴 У двери, отвечающей JSON'ом (выжимка фактов, правила-поправки), прозаические
    # указания «вызови инструмент… говори от себя, своим голосом» ломали бы контракт
    # ответа — молчаливая цена «канона везде», если не различать форму двери.
    machine = guppi_voice_canon(prose_answer=False).casefold()

    assert "вызови" not in machine
    assert "своим голосом" not in machine
    # И она заметно короче полной: это клауза для записи, а не наставление о речи.
    assert len(machine) < len(guppi_no_roleplay_directive()) / 2
