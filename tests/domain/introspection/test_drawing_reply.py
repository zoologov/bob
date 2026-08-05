# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure answer core of a drawing request (BOB-091.6).

🔴 Why this core exists: the live smoke showed Bob CALL ``draw_architecture``, retell the
mermaid in words — and never send a picture, because "explain AND render" lived only in
the tool DESCRIPTION (an agreement with the model). The picture is now attached by the
capability itself, and THIS core owns the other half: what the model is TOLD about it —
that the image is already on its way (so it must not re-render), or that it could NOT be
made (so Bob says so out loud instead of pretending he sent one).

Pure: facts in, model-facing answer out. This is the mutation target of the slice.
"""

from __future__ import annotations

from bob.capabilities.introspection.drawing_reply import (
    FALLBACK_NOTE,
    NOT_FOUND,
    REFUSED_REF,
    drawn_reply,
    not_found_reply,
    refused_reply,
)

_MERMAID = 'graph LR\n    memory["memory"]\n    memory --> bob'


# --- the source always reaches the model (words are never traded for a picture) ---


def test_the_mermaid_source_reaches_the_model_when_the_picture_was_sent() -> None:
    # 🔴 The invariant: attaching the picture must NOT replace the source, or Bob would
    # drop a PNG with nothing to say about it (the owner's decision, BOB-091).
    reply = drawn_reply(
        mermaid=_MERMAID, drawn="overview", requested="overview", picture="sent"
    )

    assert reply["mermaid"] == _MERMAID
    assert reply["form"] == "overview"


def test_a_sent_picture_is_announced_and_re_rendering_is_discouraged() -> None:
    reply = drawn_reply(
        mermaid=_MERMAID, drawn="overview", requested="overview", picture="sent"
    )

    picture = str(reply["picture"])
    assert "картинк" in picture.lower()
    # The model must not call render_diagram for the same source (a second photo).
    assert "render_diagram" in picture


def test_an_unavailable_picture_is_admitted_honestly_to_the_model() -> None:
    # 🔴 The render can fail (no mmdc / timeout / broken mermaid). Then Bob must say the
    # picture is NOT coming — never stay silent and never imply he sent one.
    reply = drawn_reply(
        mermaid=_MERMAID, drawn="overview", requested="overview", picture="unavailable"
    )

    picture = str(reply["picture"]).lower()
    assert "не" in picture
    assert "картинк" in picture or "изображен" in picture
    # The source still comes back: a failed render never costs Bob his words.
    assert reply["mermaid"] == _MERMAID


def test_the_two_picture_outcomes_never_read_the_same() -> None:
    sent = drawn_reply(
        mermaid=_MERMAID, drawn="node", requested="node", picture="sent"
    )
    missing = drawn_reply(
        mermaid=_MERMAID, drawn="node", requested="node", picture="unavailable"
    )

    assert sent["picture"] != missing["picture"]


def test_an_unavailable_picture_never_claims_the_image_was_sent() -> None:
    reply = drawn_reply(
        mermaid=_MERMAID, drawn="node", requested="node", picture="unavailable"
    )

    sent_words = ("уже отправ", "уже отрисов", "ушла в чат", "уйдёт в чат")
    lowered = str(reply["picture"]).lower()
    for claim in sent_words:
        assert claim not in lowered


# --- which view was actually drawn (honesty about the form) --------------------


def test_a_form_the_port_had_to_downgrade_carries_the_correction_note() -> None:
    reply = drawn_reply(
        mermaid=_MERMAID, drawn="node", requested="components", picture="sent"
    )

    assert reply["note"] == FALLBACK_NOTE
    assert "внутренност" in str(reply["note"]).lower()


def test_a_matching_form_carries_no_correction_note() -> None:
    reply = drawn_reply(
        mermaid=_MERMAID, drawn="components", requested="components", picture="sent"
    )

    assert "note" not in reply


def test_the_correction_note_is_independent_of_the_picture_outcome() -> None:
    reply = drawn_reply(
        mermaid=_MERMAID, drawn="node", requested="components", picture="unavailable"
    )

    assert reply["note"] == FALLBACK_NOTE


# --- the two refusals: nothing to draw / a slot that was not a ref ------------


def test_an_empty_graph_answers_honestly_and_hands_over_no_source() -> None:
    reply = not_found_reply()

    assert reply == {"error": NOT_FOUND}
    assert "не нашёл" in NOT_FOUND.lower()
    # No mermaid: there is nothing to render OR to explain.
    assert "mermaid" not in reply
    assert "picture" not in reply


def test_a_refused_ref_explains_what_a_ref_is_and_hands_over_no_source() -> None:
    reply = refused_reply()

    assert reply == {"error": REFUSED_REF}
    assert "ref" in REFUSED_REF.lower()
    assert "mermaid" not in reply


def test_each_refusal_is_a_fresh_dict_no_shared_mutable_answer() -> None:
    # A module-level dict returned twice would let one turn's answer bleed into another.
    first = not_found_reply()
    first["mermaid"] = "tampered"

    assert "mermaid" not in not_found_reply()
    assert "mermaid" not in refused_reply()
