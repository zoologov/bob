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
from bob.personality.voice import guppi_canon, guppi_no_roleplay_directive, operator_stance
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
